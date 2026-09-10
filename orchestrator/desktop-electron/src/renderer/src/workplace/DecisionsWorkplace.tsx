import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type { AgentRunHistoryItem, AgentRunnerEvent, WorkflowFileItem } from '../api/types'
import { FilterBar } from './FilterBar'
import { useWorkplaceData } from './WorkplaceBoard'
import { humanWhen, parseIso } from '../utils/calendar'
import { MiniCalendar, meetingsFromEvents, type MiniMeeting } from '../components/agentfeed/MiniCalendar'
import { cleanRunResult } from '../utils/cleanRunResult'
import { useRuns } from '../store/runs'
import { fileTypeIconSrc } from '../utils/fileTypeIcon'
import { fileExt, formatSize } from '../pages/filesGrouping'
import { isUserFacingResultFile } from './preparedDecisions'
import {
  extractToolDecisions,
  feedItemsToRunnerEvents,
  isDecisionTool,
  toolIntent,
  type ToolDecisionItem
} from './decisionTools'

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

function dayKey(stamp: Date): string {
  return `${stamp.getFullYear()}-${pad(stamp.getMonth() + 1)}-${pad(stamp.getDate())}`
}

function todayKey(): string {
  return dayKey(new Date())
}

function inRange(stamp: Date | null, fromDay: string, toDay: string): boolean {
  if (!stamp) return false
  const key = dayKey(stamp)
  const start = fromDay <= toDay ? fromDay : toDay
  const end = fromDay <= toDay ? toDay : fromDay
  return key >= start && key <= end
}

function runStamp(run: AgentRunHistoryItem): Date | null {
  return parseIso(run.finishedAt || run.startedAt || '')
}

function formatRange(fromDay: string, toDay: string): string {
  if (fromDay === toDay) {
    if (fromDay === todayKey()) return 'сегодня'
    return fromDay
  }
  return `${fromDay} — ${toDay}`
}

function isOpenRun(status: string): boolean {
  const key = (status || '').trim().toLowerCase()
  return key === 'started' || key === 'running'
}

function toolStatusLabel(item: ToolDecisionItem): string {
  if (item.status === 'pending') return 'Ждёт подтверждения'
  if (item.status === 'rejected') return 'Возвращено'
  if (item.status === 'confirmed') return 'Подтверждено'
  if (!item.result || /не был выполнен|не сохранился/i.test(item.result)) return 'Не выполнен'
  return 'Выполнено'
}

function runStatusLabel(status: string): string {
  const key = (status || '').trim().toLowerCase()
  if (key === 'ok' || key === 'done' || key === 'completed') return 'готово'
  if (key === 'error' || key === 'failed') return 'ошибка'
  if (key === 'canceled' || key === 'cancelled') return 'отменён'
  if (key === 'started' || key === 'running') return 'выполняется'
  return status || 'готово'
}

function shiftDay(base: string, delta: number): string {
  const stamp = parseIso(`${base}T12:00:00`) || new Date()
  stamp.setDate(stamp.getDate() + delta)
  return dayKey(stamp)
}

type DecisionStatusFilter = '' | 'pending' | 'review' | 'confirmed' | 'returned'
type DueFilter = 'all' | 'today' | 'overdue' | 'period'
type PriorityFilter = '' | 'high' | 'medium' | 'low'
type DecisionSort = 'due_asc' | 'due_desc' | 'name' | 'status'

const STATUS_FILTER_LABEL: Record<Exclude<DecisionStatusFilter, ''>, string> = {
  pending: 'Ожидают меня',
  review: 'На рассмотрении',
  confirmed: 'Подтверждено',
  returned: 'Возвращено'
}

const DUE_FILTER_LABEL: Record<DueFilter, string> = {
  all: 'Все',
  today: 'Сегодня',
  overdue: 'Просрочено',
  period: 'Период'
}

const PRIORITY_FILTER_LABEL: Record<Exclude<PriorityFilter, ''>, string> = {
  high: 'Высокий',
  medium: 'Средний',
  low: 'Низкий'
}

const SORT_LABEL: Record<DecisionSort, string> = {
  due_asc: 'Срок: сначала ближайшие',
  due_desc: 'Срок: сначала дальние',
  name: 'По названию',
  status: 'По статусу'
}

function itemPriority(item: ToolDecisionItem): PriorityFilter {
  if (item.status === 'pending' && item.live) return 'high'
  if (item.status === 'pending') return 'medium'
  if (item.status === 'rejected') return 'high'
  return 'low'
}

const DECISION_SLA_MS = 60 * 60 * 1000
const NOTIFY_BEFORE_MS = 10 * 60 * 1000
const NOTIFY_STORAGE = 'orchestrator.decisionNotify.v1'

function itemHasAttachment(item: ToolDecisionItem): boolean {
  if ((item.files || []).length > 0) return true
  const blob = `${item.tool} ${item.title} ${item.intent} ${item.result}`.toLowerCase()
  return /attach|влож|файл|file|document|xlsx|docx|pdf/.test(blob) || attachmentNames(item).length > 0
}

function mentionedFileNames(item: ToolDecisionItem): Set<string> {
  return new Set(attachmentNames(item).map((name) => name.toLowerCase()))
}

function uniqueFiles(items: WorkflowFileItem[]): WorkflowFileItem[] {
  const seen = new Set<string>()
  const out: WorkflowFileItem[] = []
  for (const file of items) {
    const key = file.id || `${file.runId || ''}:${file.name}`
    if (!key || seen.has(key)) continue
    seen.add(key)
    out.push(file)
  }
  return out
}

function pickFilesForDecision(item: ToolDecisionItem, pool: WorkflowFileItem[]): WorkflowFileItem[] {
  const facing = pool.filter(isUserFacingResultFile)
  const mentioned = mentionedFileNames(item)
  const byName = facing.filter((file) => mentioned.has((file.name || '').toLowerCase()))
  const byRun = facing.filter((file) => {
    const rid = (file.runId || '').trim()
    return Boolean(item.runId) && Boolean(rid) && (rid === item.runId || rid === 'local')
  })
  const runAttach = facing.filter(
    (file) => file.scope === 'run_attachment' && (!file.runId || file.runId === item.runId)
  )
  const picked = uniqueFiles([...byName, ...byRun, ...runAttach])
  if (picked.length) return picked
  return facing
    .slice()
    .sort((left, right) => String(right.createdAt || '').localeCompare(String(left.createdAt || '')))
    .slice(0, 8)
}

function fileTypeLabel(name: string): string {
  return (fileExt(name) || '').toUpperCase()
}

async function downloadDecisionFiles(files: WorkflowFileItem[]): Promise<void> {
  for (const file of files) {
    if (!file.downloadUrl) continue
    await api.download(file.downloadUrl, file.name || 'file')
  }
}

function clockLabel(stamp: Date): string {
  return `${pad(stamp.getHours())}:${pad(stamp.getMinutes())}`
}

function createdLabel(stamp: Date | null): string {
  if (!stamp) return ''
  const prefix = dayKey(stamp) === todayKey() ? 'сегодня' : humanWhen(stamp)
  return `${prefix}, ${clockLabel(stamp)}`
}

function dueStamp(item: ToolDecisionItem): number {
  const start = parseIso(item.at) || new Date(item.at)
  return start.getTime() + DECISION_SLA_MS
}

function priorityLabel(item: ToolDecisionItem): string {
  const key = itemPriority(item)
  return key ? PRIORITY_FILTER_LABEL[key] : 'Средний'
}

function recommendedText(item: ToolDecisionItem): string {
  if (item.status === 'rejected') return 'Вернуть на доработку — решение уже отклонено.'
  if (item.status === 'confirmed' || item.status === 'done') {
    return item.result || item.title
  }
  return item.title
}

const FIRST_SEEN_STORAGE = 'orchestrator.decisionFirstSeen.v1'

function readFirstSeen(): Record<string, string> {
  try {
    const raw = localStorage.getItem(FIRST_SEEN_STORAGE)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, string>) : {}
  } catch {
    return {}
  }
}

function stampFirstSeen(store: Record<string, string>, key: string, fallback?: string): string {
  if (store[key]) return store[key]
  const value = fallback || new Date().toISOString()
  store[key] = value
  try {
    localStorage.setItem(FIRST_SEEN_STORAGE, JSON.stringify(store))
  } catch {
    /* ignore */
  }
  return value
}

function remainingLabel(ms: number): string {
  if (ms <= 0) {
    const late = Math.max(1, Math.round(-ms / 60_000))
    return `Просрочено на ${late} мин`
  }
  const minutes = Math.max(1, Math.round(ms / 60_000))
  if (minutes < 60) return `До срока ${minutes} мин`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `До срока ${hours} ч ${rest} мин` : `До срока ${hours} ч`
}

function deadlineInfo(item: ToolDecisionItem, now: number): {
  due: Date
  remainingMs: number
  ratio: number
  critical: boolean
  overdue: boolean
  label: string
  dueClock: string
} {
  const start = parseIso(item.at) || new Date(item.at)
  const due = new Date(start.getTime() + DECISION_SLA_MS)
  const remainingMs = due.getTime() - now
  const ratio = Math.max(0, Math.min(1, remainingMs / DECISION_SLA_MS))
  return {
    due,
    remainingMs,
    ratio,
    critical: remainingMs <= DECISION_SLA_MS,
    overdue: remainingMs <= 0,
    label: remainingLabel(remainingMs),
    dueClock: clockLabel(due)
  }
}

function attachmentNames(item: ToolDecisionItem): string[] {
  const names: string[] = []
  const visit = (value: unknown): void => {
    if (typeof value === 'string') {
      const base = value.split(/[\\/]/).pop() || value
      if (/\.(xlsx|xls|xlsm|docx|pdf|pptx|csv|png|jpe?g|zip)$/i.test(base)) names.push(base)
      return
    }
    if (Array.isArray(value)) {
      value.forEach(visit)
      return
    }
    if (value && typeof value === 'object') {
      Object.values(value as Record<string, unknown>).forEach(visit)
    }
  }
  visit(item.arguments || {})
  return Array.from(new Set(names))
}

function sourceChips(item: ToolDecisionItem): string[] {
  const chips = [item.tool, item.agentName].filter(Boolean)
  const args = item.arguments || {}
  for (const key of ['subject', 'path', 'file', 'filename', 'query', 'entity', 'number', 'title']) {
    const value = args[key]
    if (typeof value === 'string' && value.trim()) chips.push(value.trim())
  }
  return Array.from(new Set(chips)).slice(0, 6)
}

function readNotifyPrefs(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(NOTIFY_STORAGE)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, boolean>) : {}
  } catch {
    return {}
  }
}

function writeNotifyPref(id: string, on: boolean): void {
  const next = { ...readNotifyPrefs(), [id]: on }
  try {
    localStorage.setItem(NOTIFY_STORAGE, JSON.stringify(next))
  } catch {
    /* ignore */
  }
}

function decisionStatusBucket(item: ToolDecisionItem): Exclude<DecisionStatusFilter, ''> {
  if (item.status === 'pending') return item.live ? 'pending' : 'review'
  if (item.status === 'rejected') return 'returned'
  return 'confirmed'
}

function DecisionDetail({
  item,
  now,
  process,
  files,
  notify,
  onNotify,
  onConfirm,
  onReturn,
  onOpen
}: {
  item: ToolDecisionItem
  now: number
  process: { name: string; code: string }
  files: WorkflowFileItem[]
  notify: boolean
  onNotify: (on: boolean) => void
  onConfirm: () => void
  onReturn: () => void
  onOpen: () => void
}): React.JSX.Element {
  const due = deadlineInfo(item, now)
  const created = createdLabel(parseIso(item.at) || new Date(item.at))
  const sources = sourceChips(item)
  const pending = item.status === 'pending'
  const dueTone = !pending ? 'ok' : due.overdue ? 'overdue' : 'warn'
  const barWidth = pending ? `${Math.round(due.ratio * 100)}%` : '100%'

  return (
    <>
      <div className="wp-decision-detail-head">
        <div>
          <h2>{item.title}</h2>
          <p className="wp-decision-detail-meta">
            Подготовлено агентом {process.code}
            {' · '}
            Процесс: {process.name}
            {created ? ` · Создано: ${created}` : ''}
          </p>
        </div>
        <span className={`wp-decision-state ${pending ? 'wait' : item.status === 'rejected' ? 'warn' : 'ok'}`}>
          {toolStatusLabel(item)}
        </span>
      </div>
      <div className={`wp-decision-due ${dueTone}`}>
        <div className="wp-decision-due-row">
          <strong>{pending ? due.label : item.status === 'rejected' ? 'Возвращено на доработку' : 'Срок соблюдён'}</strong>
          <span>Срок {due.dueClock}</span>
        </div>
        <div className="wp-decision-due-bar" aria-hidden>
          <i style={{ width: barWidth }} />
        </div>
        <p className="wp-decision-due-hint">Критическое окно подтверждения — 60 минут.</p>
      </div>
      <div className="wp-decision-block">
        <strong>Краткое описание</strong>
        <p>{item.intent}</p>
      </div>
      <div className="wp-decision-block wp-decision-recommend">
        <strong>Рекомендуемое решение</strong>
        <p>{recommendedText(item)}</p>
      </div>
      <div className="wp-decision-block">
        <strong>Основания и источники</strong>
        <div className="wp-chip-row">
          {sources.map((chip) => (
            <span key={chip} className="wp-decision-chip">
              <span>{chip}</span>
            </span>
          ))}
        </div>
        {item.result ? <p className="wp-decisions-result">{item.result}</p> : null}
      </div>
      <div className="wp-decision-block">
        <div className="wp-decision-attach-head">
          <strong>Вложения{files.length ? ` (${files.length})` : ''}</strong>
          {files.length > 1 ? (
            <button
              className="btn-ghost wp-decision-download-all"
              type="button"
              onClick={() => void downloadDecisionFiles(files)}
            >
              Скачать все
            </button>
          ) : null}
        </div>
        {files.length ? (
          <div className="wp-decision-files">
            {files.map((file) => {
              const name = file.name || 'file'
              const type = fileTypeLabel(name)
              const size = formatSize(file.sizeBytes)
              return (
                <button
                  key={file.id || name}
                  type="button"
                  className="wp-decision-file"
                  disabled={!file.downloadUrl}
                  onClick={() => {
                    if (file.downloadUrl) void api.download(file.downloadUrl, name)
                  }}
                >
                  <img className="files-type-icon" src={fileTypeIconSrc(name)} alt="" />
                  <span>
                    <b>{name}</b>
                    <i>{[type, size].filter(Boolean).join(' · ')}</i>
                  </span>
                </button>
              )
            })}
          </div>
        ) : (
          <p className="wp-decision-time">Файлы в запросе не указаны.</p>
        )}
      </div>
      <label className="wp-decision-notify">
        <input
          type="checkbox"
          checked={notify}
          disabled={!pending}
          onChange={(e) => onNotify(e.target.checked)}
        />
        <span>Уведомить за 10 минут до срока</span>
      </label>
      <div className="wp-actions wp-decision-actions">
        {item.live && item.requestId && pending ? (
          <>
            <button className="btn-primary" type="button" onClick={onConfirm}>
              Подтвердить
            </button>
            <button className="btn-ghost wp-decision-return" type="button" onClick={onReturn}>
              Вернуть на доработку
            </button>
          </>
        ) : null}
        <button className="btn-ghost" type="button" onClick={onOpen}>
          Открыть материалы
        </button>
      </div>
    </>
  )
}

export function DecisionsTab({
  onOpenRun
}: {
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
}): React.JSX.Element {
  const today = todayKey()
  const [query, setQuery] = useState('')
  const [processId, setProcessId] = useState('')
  const [status, setStatus] = useState<DecisionStatusFilter>('')
  const [due, setDue] = useState<DueFilter>('all')
  const [priority, setPriority] = useState<PriorityFilter>('')
  const [attachmentsOnly, setAttachmentsOnly] = useState(false)
  const [sort, setSort] = useState<DecisionSort>('due_asc')
  const [fromDay, setFromDay] = useState(() => shiftDay(today, -90))
  const [toDay, setToDay] = useState(() => shiftDay(today, 30))
  const [duePanelOpen, setDuePanelOpen] = useState(false)
  const [dueAnchor, setDueAnchor] = useState(() => {
    const now = new Date()
    return new Date(now.getFullYear(), now.getMonth(), 1)
  })
  const [loadingDetails, setLoadingDetails] = useState(false)
  const [filesByWorkflow, setFilesByWorkflow] = useState<Record<string, WorkflowFileItem[]>>({})
  const [tools, setTools] = useState<ToolDecisionItem[]>([])
  const [results, setResults] = useState<
    Array<{
      workflowId: string
      agentName: string
      runId: string
      at: string
      text: string
      status: string
      meetings: MiniMeeting[]
    }>
  >([])
  const { agents, loading, error } = useWorkplaceData()
  const runs = useRuns()
  const agentsRef = useRef(agents)
  agentsRef.current = agents
  const firstSeenRef = useRef<Record<string, string>>(readFirstSeen())
  const notifiedRef = useRef<Set<string>>(new Set())
  const pickListRef = useRef<HTMLDivElement>(null)
  const loadingFilesRef = useRef<Set<string>>(new Set())
  const [selectedId, setSelectedId] = useState('')
  const [now, setNow] = useState(() => Date.now())
  const [notifyPrefs, setNotifyPrefs] = useState<Record<string, boolean>>(readNotifyPrefs)

  const agentKey = useMemo(() => agents.map((item) => item.workflowId).join('|'), [agents])
  const [pollTick, setPollTick] = useState(0)

  const runActivityKey = useMemo(
    () =>
      Object.entries(runs.entries)
        .map(([wid, entry]) => {
          const state = entry.state
          return [
            wid,
            entry.backendRunId,
            state.activeRunId,
            state.running,
            state.items.length,
            state.status,
            state.pendingHitl?.requestId || ''
          ].join(':')
        })
        .join('|'),
    [runs.entries]
  )

  useEffect(() => {
    const timer = window.setInterval(() => setPollTick((value) => value + 1), 30000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!agentKey) {
      setLoadingDetails(false)
      return
    }
    let alive = true
    setLoadingDetails(true)
    void (async () => {
      const collectedTools: ToolDecisionItem[] = []
      const collectedResults: Array<{
        workflowId: string
        agentName: string
        runId: string
        at: string
        text: string
        status: string
        meetings: MiniMeeting[]
      }> = []
      const seenRuns = new Set<string>()
      try {
        const collectedFiles: Record<string, WorkflowFileItem[]> = {}
        const liveEntries = runs.entries
        const jobs = agentsRef.current.slice(0, 40).map(async (agent) => {
          const [history, workflowFiles] = await Promise.all([
            api.listAgentRuns(agent.workflowId).catch(() => [] as AgentRunHistoryItem[]),
            api.listWorkflowFiles(agent.workflowId).catch(() => [] as WorkflowFileItem[])
          ])
          const visibleFiles = workflowFiles.filter(isUserFacingResultFile)
          collectedFiles[agent.workflowId] = visibleFiles

          const live = liveEntries[agent.workflowId]
          if (live?.state.items.length) {
            const liveEvents = feedItemsToRunnerEvents(live.state.items)
            const liveRunId =
              live.backendRunId || live.state.activeRunId || `live:${agent.workflowId}`
            const liveAt = new Date(live.state.runningSinceMs || Date.now()).toISOString()
            if (liveEvents.length) {
              seenRuns.add(`${agent.workflowId}:${liveRunId}`)
              const extracted = extractToolDecisions(liveEvents, {
                workflowId: agent.workflowId,
                agentName: agent.name,
                runId: liveRunId,
                at: liveAt,
                runClosed: !live.state.running
              })
              for (const item of extracted) {
                item.files = pickFilesForDecision(item, visibleFiles)
              }
              collectedTools.push(...extracted)
            }
            const cleaned = cleanRunResult({
              answer: '',
              events: liveEvents,
              status: live.state.running ? 'running' : 'ok'
            })
            const meetings = meetingsFromEvents(liveEvents)
            if (cleaned.text || meetings.length) {
              collectedResults.push({
                workflowId: agent.workflowId,
                agentName: agent.name,
                runId: liveRunId,
                at: liveAt,
                text: cleaned.text,
                status: live.state.running ? 'running' : 'ok',
                meetings
              })
            }
          }

          const matched = history
            .filter((run) => inRange(runStamp(run), fromDay, toDay))
            .slice(0, 10)
          for (const run of matched) {
            const runKey = `${agent.workflowId}:${run.runId}`
            if (seenRuns.has(runKey)) continue
            seenRuns.add(runKey)
            const detail = await api.getAgentRunDetail(agent.workflowId, run.runId).catch(() => null)
            const events: AgentRunnerEvent[] = detail?.events || []
            const at = run.finishedAt || run.startedAt || ''
            const extracted = extractToolDecisions(events, {
              workflowId: agent.workflowId,
              agentName: agent.name,
              runId: run.runId,
              at,
              runClosed: !isOpenRun(run.status)
            })
            for (const item of extracted) {
              item.files = pickFilesForDecision(item, visibleFiles)
            }
            collectedTools.push(...extracted)
            const cleaned = cleanRunResult({
              answer: detail?.item.answer || run.answer,
              summary: run.summary,
              events,
              status: run.status
            })
            const meetings = meetingsFromEvents(events)
            const storedMeetings = detail?.item.calendarMeetings || []
            const plan = meetings.length ? meetings : storedMeetings
            if (cleaned.text || plan.length) {
              collectedResults.push({
                workflowId: agent.workflowId,
                agentName: agent.name,
                runId: run.runId,
                at,
                text: cleaned.text,
                status: run.status,
                meetings: plan
              })
            }
          }
        })
        await Promise.all(jobs)
        if (!alive) return
        collectedTools.sort((left, right) => String(right.at).localeCompare(String(left.at)))
        collectedResults.sort((left, right) => String(right.at).localeCompare(String(left.at)))
        setTools(collectedTools)
        setResults(collectedResults)
        setFilesByWorkflow((prev) => ({ ...prev, ...collectedFiles }))
      } finally {
        if (alive) setLoadingDetails(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [agentKey, fromDay, toDay, runActivityKey, pollTick, runs.entries])

  const livePending = useMemo(() => {
    if (!inRange(new Date(), fromDay, toDay)) return []
    const items: ToolDecisionItem[] = []
    for (const entry of Object.values(runs.entries)) {
      const hitl = entry.state.pendingHitl
      if (!hitl) continue
      const tool = String(hitl.tool || '')
      if (!isDecisionTool(tool, true)) continue
      const seenKey = `${entry.workflowId}:${hitl.requestId}`
      const item: ToolDecisionItem = {
        id: `live:${entry.workflowId}:${hitl.requestId}`,
        workflowId: entry.workflowId,
        agentName: entry.title,
        runId: entry.backendRunId || entry.state.activeRunId || '',
        tool,
        title: hitl.title || tool,
        intent: toolIntent(tool, hitl.arguments),
        result: '',
        status: 'pending',
        requestId: hitl.requestId,
        at: stampFirstSeen(firstSeenRef.current, seenKey),
        live: true,
        arguments: hitl.arguments && typeof hitl.arguments === 'object' ? hitl.arguments : {}
      }
      item.files = pickFilesForDecision(item, filesByWorkflow[entry.workflowId] || [])
      items.push(item)
    }
    return items
  }, [runs.entries, fromDay, toDay, filesByWorkflow])

  const processOptions = useMemo(
    () =>
      agents
        .filter((agent) => !agent.standalone)
        .map((agent) => ({ id: agent.workflowId, name: agent.name }))
        .sort((left, right) => left.name.localeCompare(right.name, 'ru')),
    [agents]
  )

  useEffect(() => {
    if (due === 'today') {
      setFromDay(today)
      setToDay(today)
      return
    }
    if (due === 'all' || due === 'overdue') {
      setFromDay(shiftDay(today, -90))
      setToDay(shiftDay(today, 30))
    }
  }, [due, today])

  const visibleTools = useMemo(() => {
    const q = query.trim().toLowerCase()
    const seen = new Set<string>()
    const merged: ToolDecisionItem[] = []
    for (const item of [...livePending, ...tools]) {
      const key = item.requestId
        ? `${item.workflowId}:${item.requestId}`
        : `${item.workflowId}:${item.runId}:${item.tool}:${item.status}`
      if (seen.has(key)) continue
      seen.add(key)
      if (q && !`${item.title} ${item.tool} ${item.agentName}`.toLowerCase().includes(q)) continue
      if (processId && item.workflowId !== processId) continue
      if (status && decisionStatusBucket(item) !== status) continue
      if (priority && itemPriority(item) !== priority) continue
      if (attachmentsOnly && !itemHasAttachment(item)) continue
      if (due === 'today') {
        const stamp = parseIso(item.at)
        if (!stamp || dayKey(stamp) !== today) continue
      }
      if (due === 'overdue') {
        if (item.status !== 'pending' || dueStamp(item) > Date.now()) continue
      }
      merged.push(item)
    }
    merged.sort((left, right) => {
      if (sort === 'name') return left.agentName.localeCompare(right.agentName, 'ru')
      if (sort === 'status') {
        return decisionStatusBucket(left).localeCompare(decisionStatusBucket(right), 'ru')
      }
      const leftDue = dueStamp(left)
      const rightDue = dueStamp(right)
      return sort === 'due_desc' ? rightDue - leftDue : leftDue - rightDue
    })
    return merged
  }, [livePending, tools, query, processId, status, priority, attachmentsOnly, due, sort, today])

  const pending = visibleTools.filter((item) => item.status === 'pending')
  const history = visibleTools.filter((item) => item.status !== 'pending')
  const returned = visibleTools.filter((item) => decisionStatusBucket(item) === 'returned')
  const selected = visibleTools.find((item) => item.id === selectedId) || null
  const selectedFiles = selected
    ? (() => {
        const fromPool = uniqueFiles([
          ...(selected.files || []),
          ...pickFilesForDecision(selected, filesByWorkflow[selected.workflowId] || [])
        ])
        const have = new Set(fromPool.map((file) => (file.name || '').toLowerCase()))
        const extras = attachmentNames(selected)
          .filter((name) => !have.has(name.toLowerCase()))
          .map((name) => ({ id: `name:${name}`, name, sizeBytes: 0 }))
        return [...fromPool, ...extras]
      })()
    : []

  useEffect(() => {
    const ids = new Set<string>()
    if (selected?.workflowId) ids.add(selected.workflowId)
    for (const item of livePending) ids.add(item.workflowId)
    for (const id of ids) {
      if (!id || filesByWorkflow[id] || loadingFilesRef.current.has(id)) continue
      loadingFilesRef.current.add(id)
      void api
        .listWorkflowFiles(id)
        .catch(() => [] as WorkflowFileItem[])
        .then((files) => {
          setFilesByWorkflow((prev) => ({ ...prev, [id]: files.filter(isUserFacingResultFile) }))
        })
        .finally(() => {
          loadingFilesRef.current.delete(id)
        })
    }
  }, [selected?.workflowId, livePending, filesByWorkflow])

  useEffect(() => {
    if (visibleTools.some((item) => item.id === selectedId)) return
    const first = visibleTools.find((item) => item.status === 'pending') || visibleTools[0]
    setSelectedId(first?.id || '')
  }, [visibleTools, selectedId])

  useEffect(() => {
    const node = pickListRef.current?.querySelector<HTMLElement>('.wp-decision-pick.selected')
    node?.scrollIntoView({ block: 'nearest' })
  }, [selectedId])

  useEffect(() => {
    if (!pending.length) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [pending.length])

  useEffect(() => {
    for (const item of pending) {
      if (!notifyPrefs[item.id] || notifiedRef.current.has(item.id)) continue
      const info = deadlineInfo(item, now)
      if (info.remainingMs > NOTIFY_BEFORE_MS || info.remainingMs <= 0) continue
      notifiedRef.current.add(item.id)
      if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        new Notification('Срок решения', { body: `${item.title}: осталось менее 10 минут` })
      }
    }
  }, [now, pending, notifyPrefs])

  function processFor(item: ToolDecisionItem): { name: string; code: string } {
    const agent = agents.find((entry) => entry.workflowId === item.workflowId)
    return {
      name: agent?.name || item.agentName,
      code: agent?.code || item.agentName
    }
  }

  function toggleNotify(id: string, on: boolean): void {
    setNotifyPrefs((prev) => {
      const next = { ...prev, [id]: on }
      writeNotifyPref(id, on)
      return next
    })
    if (on && typeof Notification !== 'undefined' && Notification.permission === 'default') {
      void Notification.requestPermission()
    }
  }
  const visibleResults = useMemo(() => {
    const q = query.trim().toLowerCase()
    return results
      .filter((item) => {
        if (processId && item.workflowId !== processId) return false
        if (q && !`${item.agentName} ${item.workflowId} ${item.text}`.toLowerCase().includes(q)) return false
        if (due === 'today') {
          const stamp = parseIso(item.at)
          if (!stamp || dayKey(stamp) !== today) return false
        }
        return true
      })
      .sort((left, right) => {
        if (sort === 'name') return left.agentName.localeCompare(right.agentName, 'ru')
        const leftAt = left.at || ''
        const rightAt = right.at || ''
        return sort === 'due_desc' ? rightAt.localeCompare(leftAt) : leftAt.localeCompare(rightAt)
      })
  }, [results, query, processId, due, sort, today])

  const dueMonthLabel = dueAnchor.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' })
  const dueCells = useMemo(() => {
    const first = new Date(dueAnchor.getFullYear(), dueAnchor.getMonth(), 1)
    const weekday = (first.getDay() + 6) % 7
    const start = new Date(first)
    start.setDate(first.getDate() - weekday)
    return Array.from({ length: 42 }, (_, idx) => {
      const day = new Date(start)
      day.setDate(start.getDate() + idx)
      return day
    })
  }, [dueAnchor])

  function resetFilters(): void {
    setQuery('')
    setProcessId('')
    setStatus('')
    setDue('all')
    setPriority('')
    setAttachmentsOnly(false)
    setSort('due_asc')
    setFromDay(shiftDay(today, -90))
    setToDay(shiftDay(today, 30))
    setDuePanelOpen(false)
  }

  function pickDay(key: string): void {
    setDue('period')
    setFromDay(key)
    setToDay(key)
    setDuePanelOpen(false)
  }

  const filterChips = [
    { id: 'q', label: query ? `Поиск: ${query}` : '', onClear: () => setQuery('') },
    {
      id: 'process',
      label: processId
        ? `Процесс: ${processOptions.find((item) => item.id === processId)?.name || processId}`
        : '',
      onClear: () => setProcessId('')
    },
    {
      id: 'status',
      label: status ? `Статус: ${STATUS_FILTER_LABEL[status]}` : '',
      onClear: () => setStatus('')
    },
    {
      id: 'due',
      label: due !== 'all' ? `Срок: ${DUE_FILTER_LABEL[due]}` : '',
      onClear: () => {
        setDue('all')
        setFromDay(shiftDay(today, -90))
        setToDay(shiftDay(today, 30))
        setDuePanelOpen(false)
      }
    },
    {
      id: 'priority',
      label: priority ? `Приоритет: ${PRIORITY_FILTER_LABEL[priority]}` : '',
      onClear: () => setPriority('')
    },
    {
      id: 'attach',
      label: attachmentsOnly ? 'Только с вложениями' : '',
      onClear: () => setAttachmentsOnly(false)
    },
    {
      id: 'sort',
      label: sort !== 'due_asc' ? `Сортировка: ${SORT_LABEL[sort] || sort}` : '',
      onClear: () => setSort('due_asc')
    }
  ].filter((item) => Boolean(item.label))

  return (
    <div className="wp-page">
      <div className="wp-head">
        <div>
          <h1 className="page-title">Решения</h1>
        </div>
      </div>
      <section className="wp-decisions-kpi">
        <article className="wp-decisions-kpi-card wait">
          <div className="wp-decisions-kpi-icon" aria-hidden>
            !
          </div>
          <div>
            <p>Ждут подтверждения</p>
            <strong>{pending.length}</strong>
          </div>
        </article>
        <article className="wp-decisions-kpi-card done">
          <div className="wp-decisions-kpi-icon" aria-hidden>
            ✓
          </div>
          <div>
            <p>История за период</p>
            <strong>{history.length}</strong>
          </div>
        </article>
        <article className="wp-decisions-kpi-card review">
          <div className="wp-decisions-kpi-icon" aria-hidden>
            ●
          </div>
          <div>
            <p>Результаты агентов</p>
            <strong>{visibleResults.length}</strong>
          </div>
        </article>
        <article className="wp-decisions-kpi-card returned">
          <div className="wp-decisions-kpi-icon" aria-hidden>
            ↻
          </div>
          <div>
            <p>Возвращено</p>
            <strong>{returned.length}</strong>
          </div>
        </article>
      </section>
      <FilterBar
        query={query}
        onQuery={setQuery}
        queryPlaceholder="Найти решение"
        chips={filterChips}
        onReset={resetFilters}
        className="wp-filters-decisions"
      >
        <label className="wp-filter-field">
          <span>Процесс</span>
          <select className="wp-select" value={processId} onChange={(e) => setProcessId(e.target.value)}>
            <option value="">Все</option>
            {processOptions.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="wp-filter-field">
          <span>Статус</span>
          <select
            className="wp-select"
            value={status}
            onChange={(e) => setStatus(e.target.value as DecisionStatusFilter)}
          >
            <option value="">Все</option>
            {(Object.keys(STATUS_FILTER_LABEL) as Array<Exclude<DecisionStatusFilter, ''>>).map((key) => (
              <option key={key} value={key}>
                {STATUS_FILTER_LABEL[key]}
              </option>
            ))}
          </select>
        </label>
        <label className="wp-filter-field">
          <span>Срок</span>
          <select
            className="wp-select"
            value={due}
            onChange={(e) => {
              const next = e.target.value as DueFilter
              setDue(next)
              setDuePanelOpen(next === 'period')
            }}
          >
            <option value="all">Все</option>
            <option value="today">Сегодня</option>
            <option value="overdue">Просрочено</option>
            <option value="period">Период…</option>
          </select>
        </label>
        <label className="wp-filter-field">
          <span>Приоритет</span>
          <select
            className="wp-select"
            value={priority}
            onChange={(e) => setPriority(e.target.value as PriorityFilter)}
          >
            <option value="">Все</option>
            {(Object.keys(PRIORITY_FILTER_LABEL) as Array<Exclude<PriorityFilter, ''>>).map((key) => (
              <option key={key} value={key}>
                {PRIORITY_FILTER_LABEL[key]}
              </option>
            ))}
          </select>
        </label>
        <label className="wp-switch">
          <input
            type="checkbox"
            checked={attachmentsOnly}
            onChange={(e) => setAttachmentsOnly(e.target.checked)}
          />
          <span className="wp-switch-track" aria-hidden />
          <span>Только с вложениями</span>
        </label>
        <label className="wp-filter-field wp-filter-field-sort">
          <span>Сортировка</span>
          <select className="wp-select" value={sort} onChange={(e) => setSort(e.target.value as DecisionSort)}>
            {(Object.keys(SORT_LABEL) as DecisionSort[]).map((key) => (
              <option key={key} value={key}>
                {SORT_LABEL[key]}
              </option>
            ))}
          </select>
        </label>
      </FilterBar>
      {duePanelOpen || due === 'period' ? (
        <section className="wp-card wp-deadline-panel">
          <div className="wp-deadline-head">
            <button
              className="btn-ghost"
              type="button"
              onClick={() => setDueAnchor((prev) => new Date(prev.getFullYear(), prev.getMonth() - 1, 1))}
            >
              ←
            </button>
            <strong>{dueMonthLabel}</strong>
            <button
              className="btn-ghost"
              type="button"
              onClick={() => setDueAnchor((prev) => new Date(prev.getFullYear(), prev.getMonth() + 1, 1))}
            >
              →
            </button>
          </div>
          <div className="wp-deadline-weekdays">
            {['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map((name) => (
              <span key={name}>{name}</span>
            ))}
          </div>
          <div className="wp-deadline-grid">
            {dueCells.map((day) => {
              const key = dayKey(day)
              const tone = key < today ? 'past' : key > today ? 'future' : 'today'
              const outside = day.getMonth() !== dueAnchor.getMonth()
              const start = fromDay <= toDay ? fromDay : toDay
              const end = fromDay <= toDay ? toDay : fromDay
              const selected = key === fromDay || key === toDay
              const inSel = key >= start && key <= end
              return (
                <button
                  key={key}
                  type="button"
                  className={`wp-deadline-day ${tone}${outside ? ' muted' : ''}${selected ? ' selected' : ''}${
                    inSel && !selected ? ' in-range' : ''
                  }`}
                  onClick={() => pickDay(key)}
                >
                  {day.getDate()}
                </button>
              )
            })}
          </div>
        </section>
      ) : null}
      {error ? <div className="wp-banner wp-banner-warn">{error}</div> : null}
      <div className="wp-decisions-columns wp-decisions-master">
            <section className="wp-card wp-decisions-col">
              <h2>Подтверждение инструментов</h2>
              <p>
                {loading || loadingDetails
                  ? 'Собираем подтверждения… список появится по мере загрузки.'
                  : visibleTools.length
                    ? `Решения (${visibleTools.length}). Критический срок — 60 минут с появления запроса.`
                    : `За ${formatRange(fromDay, toDay)} запросов на подтверждение нет.`}
              </p>
              <div ref={pickListRef} className="wp-decisions-col-list wp-decision-pick-list">
                {!visibleTools.length ? (
                  <article className="wp-card wp-decisions-mini">За выбранный период таких инструментов нет.</article>
                ) : null}
                {visibleTools.map((item) => {
                  const process = processFor(item)
                  const due = deadlineInfo(item, now)
                  const selectedItem = item.id === selectedId
                  const stateTone =
                    item.status === 'pending' ? 'wait' : item.status === 'rejected' ? 'warn' : 'ok'
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className={`wp-decision-pick${selectedItem ? ' selected' : ''}${due.overdue && item.status === 'pending' ? ' overdue' : ''}`}
                      onClick={() => setSelectedId(item.id)}
                    >
                      <span className={`wp-decision-pick-radio${selectedItem ? ' on' : ''}`} aria-hidden />
                      <span className="wp-decision-pick-body">
                        <span className="wp-decision-pick-head">
                          <strong>{item.title}</strong>
                          <span className={`wp-decision-state ${stateTone}`}>{toolStatusLabel(item)}</span>
                        </span>
                        <span className="wp-decision-pick-process">Процесс: {process.name}</span>
                        <span className="wp-decision-pick-foot">
                          <span>
                            {priorityLabel(item)}
                            {' · '}
                            {item.status === 'pending'
                              ? due.overdue
                                ? `Просрочено · ${Math.max(1, Math.round(-due.remainingMs / 60_000))} мин`
                                : `до ${due.dueClock} · ${Math.max(1, Math.round(due.remainingMs / 60_000))} мин`
                              : createdLabel(parseIso(item.at) || new Date(item.at))}
                          </span>
                          <span className="wp-code">{process.code}</span>
                        </span>
                      </span>
                    </button>
                  )
                })}
              </div>
            </section>
            <section className="wp-card wp-decisions-col wp-decision-detail">
              {!selected ? (
                <article className="wp-decisions-mini">
                  Выберите решение слева, чтобы увидеть срок и материалы.
                </article>
              ) : (
                <DecisionDetail
                  item={selected}
                  now={now}
                  process={processFor(selected)}
                  files={selectedFiles}
                  notify={Boolean(notifyPrefs[selected.id])}
                  onNotify={(on) => toggleNotify(selected.id, on)}
                  onConfirm={() => {
                    if (selected.live && selected.requestId) {
                      runs.respondHitl(selected.workflowId, selected.requestId, true)
                    }
                  }}
                  onReturn={() => {
                    if (selected.live && selected.requestId) {
                      runs.respondHitl(selected.workflowId, selected.requestId, false)
                    }
                  }}
                  onOpen={() => onOpenRun(selected.workflowId, selected.agentName, selected.runId)}
                />
              )}
            </section>
          </div>
          <section className="wp-card wp-decisions-col">
            <h2>Результаты агентов</h2>
            <p>Итог работы, без хода выполнения.</p>
            <div className="wp-decisions-col-list">
              {!visibleResults.length ? (
                <article className="wp-card wp-decisions-mini">За выбранный период готовых результатов нет.</article>
              ) : null}
              {visibleResults.map((item) => (
                <article key={`${item.workflowId}:${item.runId}`} className="wp-card wp-decision-rich">
                  <div className="wp-decision-rich-head">
                    <div>
                      <h3>{item.agentName}</h3>
                      <div className="wp-code">{item.workflowId}</div>
                    </div>
                    <span className="wp-decision-state ok">{runStatusLabel(item.status)}</span>
                  </div>
                  <div className="wp-decision-block">
                    <strong>Результат</strong>
                    {item.meetings.length > 0 && (
                      <div className="wf-result-calendar">
                        <MiniCalendar meetings={item.meetings} />
                      </div>
                    )}
                    {item.text ? (
                      <p className="wp-decisions-result wp-decision-summary">{item.text}</p>
                    ) : null}
                  </div>
                  <p className="wp-decision-time">{item.at ? humanWhen(parseIso(item.at) || new Date(item.at)) : ''}</p>
                  <div className="wp-actions wp-decision-actions">
                    <button
                      className="btn-ghost"
                      type="button"
                      onClick={() => onOpenRun(item.workflowId, item.agentName, item.runId)}
                    >
                      Открыть материалы
                    </button>
                  </div>
                </article>
              ))}
            </div>
          </section>
    </div>
  )
}
