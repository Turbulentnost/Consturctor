import { useEffect, useRef, useState, type ReactNode } from 'react'
import { agentClient } from '../api/agent'
import { api } from '../api/client'
import { ApiError, type AgentEvent, type RegulationCreationSession, type RegulationCreationTurn, type RegulationQueuedQuestion } from '../api/types'
import wallpaperUrl from '../assets/chat/wallpaper.png'
import programIcon from '../assets/logo.png'
import iconAttention from '@agent-icons/agent-attention-animated.svg?raw'
import iconCompleted from '@agent-icons/agent-completed-animated.svg?raw'
import iconWorking from '@agent-icons/agent-working-animated.svg?raw'
import { fileTypeIconSrc } from '../utils/fileTypeIcon'
import { appendThinkingText, THINKING_PLACEHOLDER } from '../components/agentfeed/thinkingText'
import {
  attachmentNamesFromContent,
  extractInterviewAnswer,
  formatRegulationMessageTime,
  isReplacementGarbage,
  visibleAssistantText,
  visibleUserText
} from '../utils/regulationChat'

interface AgentLiveEvent {
  type: string
  text: string
  tool?: string
}

function mergeLiveThinking(prev: string, event: AgentLiveEvent): string {
  const type = event.type
  const text = (event.text || '').trim()
  if (type === 'thinking') return appendThinkingText(prev, event.text || '')
  if (type === 'status' && text) return appendThinkingText(prev, `\n• ${text}`)
  if (type === 'tool_call') {
    const name = (event.tool || text || 'инструмент').trim()
    return appendThinkingText(prev, `\n→ ${name}`)
  }
  if (type === 'tool_result' && text) {
    const snippet = text.length > 240 ? `${text.slice(0, 240)}…` : text
    return appendThinkingText(prev, `\n← ${snippet}`)
  }
  if ((type === 'progress' || type === 'task') && text) {
    return appendThinkingText(prev, `\n${text}`)
  }
  return prev
}

function isMeaningfulThinking(text: string): boolean {
  const value = text.trim()
  return Boolean(value) && value !== THINKING_PLACEHOLDER
}

function RegulationThinkingBlock({
  text,
  defaultOpen = false,
  label = 'Размышления агента'
}: {
  text: string
  defaultOpen?: boolean
  label?: string
}): React.JSX.Element {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="regchat-think">
      <button type="button" className="regchat-think-head" onClick={() => setOpen((v) => !v)}>
        <span className="regchat-think-chevron">{open ? '\u25BE' : '\u25B8'}</span>
        <span>{label}</span>
      </button>
      {open && <div className="regchat-think-body">{text}</div>}
    </div>
  )
}

type AgentPhase = 'working' | 'attention' | 'completed'

interface RegulationChatPageProps {
  session: RegulationCreationSession
  onSessionChange: (session: RegulationCreationSession) => void
  onReady: (session: RegulationCreationSession) => void | Promise<void>
  onBack: () => void
  onStopped?: () => void
  onBusyChange?: (busy: boolean) => void
  banner?: ReactNode
}

interface PendingFile {
  path: string
  name: string
}

interface ProcessChoice {
  id: string
  title: string
  actor: string
}

const DEFAULT_PLACEHOLDER = 'Опишите процесс или ответьте на вопрос ИИ...'
const EDIT_PLACEHOLDER = 'Измените предложенный вариант и отправьте...'
const FORCE_CREATE_PROMPT =
  'Создай регламент принудительно по текущей информации. ' +
  'Если каких-то данных не хватает, используй разумные типовые формулировки и явно отметь, что это предположение.'
const WORKING_STATUS = 'Готовлю вопрос...'
const PREFETCH_STATUS = 'Готовлю следующие вопросы...'
const COMPOSER_MIN_HEIGHT = 74
// 15 строк по 25px line-height — дальше textarea прокручивается внутри.
const COMPOSER_MAX_HEIGHT = 399
const STARTER_HINTS = [
  'Приложите должностную инструкцию или файл с обязанностями — скрепка слева от поля ввода.',
  'Или коротко напишите должность и 2–3 основные функции сотрудника.',
  'Дальше ИИ уточнит только то, чего не нашёл в документах, и соберёт регламент по СТО-34-003.'
]

type BusyKind = 'reading' | 'question'

function busyHeadLabel(kind: BusyKind, fileCount: number): string {
  if (kind === 'reading') {
    return fileCount > 1 ? 'Читаю документы' : 'Читаю документ'
  }
  return 'Готовит вопрос'
}

function busyStatusLabel(kind: BusyKind, fileCount: number, prefetching: boolean): string {
  if (kind === 'reading') {
    return fileCount > 1 ? 'Читаю документы...' : 'Читаю документ...'
  }
  if (prefetching) return PREFETCH_STATUS
  return WORKING_STATUS
}

function fileCountLabel(count: number): string {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return 'файл'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'файла'
  return 'файлов'
}

function agentIcon(phase: AgentPhase): string {
  if (phase === 'working') return iconWorking
  if (phase === 'completed') return iconCompleted
  return iconAttention
}

function prepareAgentSvg(svg: string, prefix: string): string {
  const safe = prefix.replace(/[^a-zA-Z0-9_-]/g, '') || 'icon'
  return svg
    .replace(/\bid="([^"]+)"/g, `id="${safe}-$1"`)
    .replace(/url\(#([^)]+)\)/g, `url(#${safe}-$1)`)
    .replace(/\bhref="#([^"]+)"/g, `href="#${safe}-$1"`)
    .replace(/transform-origin:\s*[\d.]+px\s+[\d.]+px/g, 'transform-origin:center')
    .replace(/@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[\s\S]*?\n\s*\}/g, '')
    .replace('<style>', '<style>\n    * { transform-box: fill-box; }\n')
}

function AgentAvatar({
  phase,
  uid,
  frozen = false
}: {
  phase: AgentPhase
  uid: string
  frozen?: boolean
}): React.JSX.Element {
  if (frozen) {
    return (
      <div className="regchat-avatar program" aria-hidden>
        <img src={programIcon} alt="" />
      </div>
    )
  }
  return (
    <div
      className={`regchat-avatar ${phase}`}
      aria-hidden
      dangerouslySetInnerHTML={{ __html: prepareAgentSvg(agentIcon(phase), uid) }}
    />
  )
}

function quickAnswers(structured: Record<string, unknown>): string[] {
  const raw = structured.quickAnswers
  if (Array.isArray(raw)) return raw.map((x) => String(x)).filter(Boolean)
  return []
}

function safeDownloadName(name: string): string {
  const cleaned = name.replace(/[<>:"/\\|?*]+/g, ' ').replace(/\s+/g, ' ').trim()
  return (cleaned || 'Регламент.docx').slice(0, 120)
}

function resultFileName(session: RegulationCreationSession): string {
  const fromPath = session.resultDocumentPath.split(/[\\/]/).pop() || ''
  if (fromPath) return safeDownloadName(fromPath)
  const title = String(session.resultDocument?.title || '').trim()
  if (title) return safeDownloadName(`${title}.docx`)
  return 'Регламент.docx'
}

function attachmentsOf(structured: Record<string, unknown>): string[] {
  const raw = structured.attachments
  if (!Array.isArray(raw)) return []
  return raw
    .map((item) => {
      if (typeof item === 'string') return item
      if (item && typeof item === 'object') {
        const rec = item as Record<string, unknown>
        return String(rec.name || rec.shortName || '')
      }
      return ''
    })
    .filter(Boolean)
}

function processChoicesFromSession(session: RegulationCreationSession): ProcessChoice[] {
  const interview =
    session.interview && typeof session.interview === 'object'
      ? (session.interview as Record<string, unknown>)
      : {}
  const raw = Array.isArray(interview.processes) ? interview.processes : []
  const out: ProcessChoice[] = []
  const seen = new Set<string>()
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const row = item as Record<string, unknown>
    const id = String(row.id || row.processId || row.functionId || '').trim()
    if (!id || seen.has(id)) continue
    seen.add(id)
    out.push({
      id,
      title: String(row.title || row.name || id).trim() || id,
      actor: String(row.actor || '').trim()
    })
  }
  if (out.length > 0) return out
  const pipeline = pipelineMeta(session)
  const blocks = Array.isArray(pipeline.blocks) ? pipeline.blocks : []
  for (const item of blocks) {
    if (!item || typeof item !== 'object') continue
    const row = item as Record<string, unknown>
    const id = String(row.processId || row.id || '').trim()
    if (!id || seen.has(id)) continue
    seen.add(id)
    out.push({
      id,
      title: String(row.title || row.name || id).trim() || id,
      actor: String(row.actor || '').trim()
    })
  }
  return out
}

function selectedProcessIds(session: RegulationCreationSession): string[] {
  const pipeline =
    session.pipeline && typeof session.pipeline === 'object'
      ? (session.pipeline as Record<string, unknown>)
      : {}
  const raw = Array.isArray(pipeline.selectedProcessIds) ? pipeline.selectedProcessIds : []
  return raw.map((item) => String(item || '').trim()).filter(Boolean)
}

function effectiveQueueDepth(
  session: RegulationCreationSession,
  turn?: RegulationCreationTurn,
  extraQueueLen = 0
): number {
  return Math.max(
    turn?.queueDepth ?? 0,
    turn?.questionQueue?.length ?? 0,
    turn?.session?.queueDepth ?? 0,
    turn?.session?.questionQueue?.length ?? 0,
    session.queueDepth ?? 0,
    session.questionQueue?.length ?? 0,
    extraQueueLen
  )
}

function isAssemblePending(session: RegulationCreationSession, extraQueueLen = 0): boolean {
  const ready = Boolean(session.resultRegulation || session.resultDocumentPath)
  if (ready) return false
  if (effectiveQueueDepth(session, undefined, extraQueueLen) > 0) return false
  const pipeline = pipelineMeta(session)
  const stage = String(pipeline.stage || '').trim().toLowerCase()
  return stage === 'assemble'
}

function needsProcessSelectionForSession(session: RegulationCreationSession, ready: boolean): boolean {
  if (ready) return false
  const pipeline = pipelineMeta(session)
  const stage = String(pipeline.stage || '').trim().toLowerCase()
  if (stage === 'assemble' || stage === 'done') return false
  const processChoices = processChoicesFromSession(session)
  const pipelineSelectedIds = selectedProcessIds(session)
  return processChoices.length > 0 && pipelineSelectedIds.length === 0
}

function pipelineMeta(session: RegulationCreationSession): Record<string, unknown> {
  return session.pipeline && typeof session.pipeline === 'object'
    ? (session.pipeline as Record<string, unknown>)
    : {}
}

function stageCaption(session: RegulationCreationSession): string {
  const pipeline = pipelineMeta(session)
  const stage = String(pipeline.stage || '').trim().toLowerCase()
  const phase = String(pipeline.interviewPhase || '').trim().toLowerCase()
  if (stage === 'select') return 'Этап 1 из 3: выбор процессов'
  if (stage === 'extract') return 'Этап 1 из 3: разбор документа'
  if (stage === 'interview' && phase === 'collect') return 'Этап 2 из 3: сбор фактов по выбранным процессам'
  if (stage === 'interview') return 'Этап 3 из 3: уточняющие вопросы'
  if (stage === 'assemble') return 'Формирование регламента'
  return 'Подготовка интервью'
}

function remainingEstimateLabel(session: RegulationCreationSession, extraQueueLen = 0): string {
  const pipeline = pipelineMeta(session)
  const stage = String(pipeline.stage || '').trim().toLowerCase()
  const queueLen = effectiveQueueDepth(session, undefined, extraQueueLen)
  if (stage === 'assemble' && queueLen > 0) {
    return `В очереди: ${queueLen} вопросов — задаю следующий`
  }
  if (stage === 'assemble' && !Boolean(session.resultRegulation || session.resultDocumentPath)) {
    return 'ИИ формирует документ — новых вопросов нет'
  }
  const remaining =
    pipeline.estimatedRemainingQuestions && typeof pipeline.estimatedRemainingQuestions === 'object'
      ? (pipeline.estimatedRemainingQuestions as Record<string, unknown>)
      : {}
  const text = String(remaining.text || '').trim()
  if (text) return text
  if (stage === 'select') {
    const processCount = processChoicesFromSession(session).length
    if (processCount > 0) {
      return `Выберите процессы (${processCount} процессов × ~4 вопроса)`
    }
  }
  const min = Number(remaining.min ?? 0)
  const max = Number(remaining.max ?? min)
  if (Number.isFinite(min) && Number.isFinite(max) && min >= 0 && max >= min) {
    return min === max
      ? `Осталось примерно: ${Math.round(min)} вопросов`
      : `Осталось примерно: ${Math.round(min)}-${Math.round(max)} вопросов`
  }
  return ''
}

function visibleChatMessages(session: RegulationCreationSession): RegulationCreationSession['messages'] {
  const ready = Boolean(session.resultRegulation || session.resultDocumentPath)
  const needsSelection = needsProcessSelectionForSession(session, ready)
  return session.messages
    .filter((m) => m.role === 'assistant' || m.role === 'user')
    .filter((m) => !needsSelection || m.role === 'user')
}

function pendingUserMessageId(session: RegulationCreationSession): string {
  const relevant = session.messages.filter((m) => m.role === 'assistant' || m.role === 'user')
  const last = relevant[relevant.length - 1]
  if (!last || last.role !== 'user' || last.messageId === 'local-pending') return ''
  return last.messageId
}

function awaitingAssistantReply(session: RegulationCreationSession): boolean {
  const ready = Boolean(session.resultRegulation || session.resultDocumentPath)
  if (needsProcessSelectionForSession(session, ready)) return false
  const visible = visibleChatMessages(session)
  return visible[visible.length - 1]?.role === 'user'
}

function shouldBlockSdkAgent(
  session: RegulationCreationSession,
  turn?: RegulationCreationTurn,
  extraQueueLen = 0
): boolean {
  const pipeline = pipelineMeta(session)
  const stage = String(pipeline.stage || '').trim().toLowerCase()
  const phase = String(pipeline.interviewPhase || stage).trim().toLowerCase()
  const ready = Boolean(session.resultRegulation || session.resultDocumentPath)
  if (needsProcessSelectionForSession(session, ready)) return true
  const queueLen = effectiveQueueDepth(session, turn, extraQueueLen)
  if (isAssemblePending(session, extraQueueLen)) return queueLen > 0
  if (['upload', 'select'].includes(stage)) return true
  if (['upload', 'select'].includes(phase)) return true
  if (Boolean(turn?.prefetchedReply)) return true
  if (phase === 'extract' || stage === 'extract') return false
  if (queueLen > 0) return true
  if (stage === 'interview' && phase === 'collect') return true
  return false
}

function isCollectInterview(session: RegulationCreationSession): boolean {
  const pipeline = pipelineMeta(session)
  const stage = String(pipeline.stage || '').trim().toLowerCase()
  const phase = String(pipeline.interviewPhase || stage).trim().toLowerCase()
  return stage === 'interview' && phase === 'collect'
}

class RegulationCancelledError extends Error {
  constructor() {
    super('cancelled')
    this.name = 'RegulationCancelledError'
  }
}

function isRegulationCancelled(err: unknown): boolean {
  if (err instanceof RegulationCancelledError) return true
  if (err instanceof Error && err.name === 'RegulationCancelledError') return true
  return false
}

function waitForRegulationSdk(
  runId: string,
  onEvent: (event: AgentLiveEvent) => void,
  signal?: AbortSignal
): Promise<{ answer: string; agentId: string }> {
  return new Promise((resolve, reject) => {
    const finish = (action: () => void): void => {
      off()
      signal?.removeEventListener('abort', onAbort)
      action()
    }
    const onAbort = (): void => {
      finish(() => reject(new RegulationCancelledError()))
    }
    if (signal?.aborted) {
      reject(new RegulationCancelledError())
      return
    }
    const off = agentClient.onEvent((event: AgentEvent) => {
      if (event.runId && event.runId !== runId) return
      if (event.type === 'event' && event.payload) {
        const payload = event.payload
        const text = String(payload.text || payload.message || '')
        const kind = String(payload.type || '')
        onEvent({
          type: kind,
          text,
          tool: payload.tool ? String(payload.tool) : undefined
        })
      }
      if (event.type === 'result') {
        if (signal?.aborted) {
          finish(() => reject(new RegulationCancelledError()))
          return
        }
        finish(() =>
          resolve({
            answer: String(event.answer || ''),
            agentId: String(event.agentId || '')
          })
        )
        return
      }
      if (event.type === 'error') {
        if (signal?.aborted || String(event.code || '') === 'cancelled') {
          finish(() => reject(new RegulationCancelledError()))
          return
        }
        const recovered = extractInterviewAnswer(event.message || '')
        if (recovered) {
          finish(() => resolve({ answer: recovered, agentId: '' }))
          return
        }
        finish(() => reject(new Error(event.message || 'Ошибка локального агента')))
      }
    })
    signal?.addEventListener('abort', onAbort)
  })
}

function extractProposal(message: string): string {
  const text = (message || '').trim()
  if (!text) return ''
  const match = text.match(
    /Предлагаю\s+так\s*:\s*([\s\S]*?)(?:\n\s*\n\s*Оставить это или переделать\s*\??\s*$|$)/i
  )
  if (match) return match[1].replace(/\s+/g, ' ').trim()
  const parts = text
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean)
  if (parts.length >= 2) {
    for (const part of parts.slice(1)) {
      const lower = part.toLowerCase()
      if (lower.startsWith('оставить это или переделать')) continue
      if (lower.startsWith('вопрос')) continue
      const cleaned = part.replace(/^Предлагаю\s+так\s*:\s*/i, '').trim()
      if (cleaned) return cleaned.replace(/\s+/g, ' ').trim()
    }
  }
  return ''
}

function questionSignature(text: string): string {
  const normalized = (visibleAssistantText(text) || text || '')
    .toLowerCase()
    .replace(/«[^»]+»/g, ' ')
    .replace(/"[^"]+"/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return normalized
}

function isForceCreateShortcut(text: string): boolean {
  const t = (text || '').trim().toLowerCase()
  if (!t) return false
  return (
    t === 'создай' ||
    t === 'создать' ||
    t === 'собери' ||
    t === 'собрать' ||
    t === 'выпускай' ||
    t === 'выпустить'
  )
}

export function RegulationChatPage({
  session,
  onSessionChange,
  onReady,
  onBack,
  onStopped,
  onBusyChange,
  banner
}: RegulationChatPageProps): React.JSX.Element {
  const [input, setInput] = useState('')
  const [placeholder, setPlaceholder] = useState(DEFAULT_PLACEHOLDER)
  const [busy, setBusy] = useState(false)
  const [busyKind, setBusyKind] = useState<BusyKind>('question')
  const [readingFileCount, setReadingFileCount] = useState(0)
  const [error, setError] = useState('')
  const [savedNote, setSavedNote] = useState('')
  const [attachments, setAttachments] = useState<PendingFile[]>([])
  const [filesOpen, setFilesOpen] = useState(false)
  const [pickedProcessIds, setPickedProcessIds] = useState<string[]>([])
  const [selectingProcesses, setSelectingProcesses] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const pinnedRef = useRef(true)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const resumeKeyRef = useRef('')
  const collectRecoverKeyRef = useRef('')
  const assembleRecoverKeyRef = useRef('')
  const idleRecoverKeyRef = useRef('')
  const repeatRecoverKeyRef = useRef('')
  const runIdRef = useRef('')
  const abortRef = useRef<AbortController | null>(null)
  const stoppedRef = useRef(false)
  const queuedQuestionsRef = useRef<RegulationQueuedQuestion[]>([])
  const prefetchRunRef = useRef(false)
  const researchPrefetchRunRef = useRef(false)
  const submittingRef = useRef(false)
  const sdkRanRef = useRef(false)
  const liveThinkingRef = useRef('')
  const [optimisticQuestion, setOptimisticQuestion] = useState<RegulationQueuedQuestion | null>(null)
  const [submitLocked, setSubmitLocked] = useState(false)
  const [prefetching, setPrefetching] = useState(false)
  const [liveThinking, setLiveThinking] = useState('')
  const [savedThinkingBlocks, setSavedThinkingBlocks] = useState<Array<{ id: string; text: string }>>([])

  function resetLiveThinking(): void {
    liveThinkingRef.current = ''
    setLiveThinking('')
  }

  function pushLiveThinkingEvent(event: AgentLiveEvent): void {
    if (event.type === 'error' && event.text) {
      setError(event.text)
      return
    }
    setLiveThinking((prev) => {
      const next = mergeLiveThinking(prev, event)
      liveThinkingRef.current = next
      return next
    })
    if (event.type === 'status' && event.text && event.text !== 'reading') {
      setBusyKind('question')
    }
  }

  function saveLiveThinkingSnapshot(): void {
    const snapshot = liveThinkingRef.current.trim()
    if (!isMeaningfulThinking(snapshot)) return
    setSavedThinkingBlocks([{ id: `${Date.now()}`, text: snapshot }])
    resetLiveThinking()
  }

  function syncQueueFromSession(next: RegulationCreationSession | RegulationCreationTurn): void {
    const isTurn = 'session' in next
    const sessionData = isTurn ? next.session : next
    const queue = (isTurn ? next.questionQueue : undefined) ?? sessionData.questionQueue
    const depth = (isTurn ? next.queueDepth : undefined) ?? sessionData.queueDepth ?? queue?.length ?? 0
    const inProgress =
      (isTurn ? next.prefetchInProgress : undefined) ?? sessionData.prefetchInProgress
    if (queue?.length) {
      queuedQuestionsRef.current = queue
    } else if ((depth ?? 0) === 0) {
      queuedQuestionsRef.current = []
    }
    setPrefetching(Boolean(inProgress) && (depth ?? 0) === 0)
  }

  async function prefetchQueue(): Promise<void> {
    if (ready || needsProcessSelection || stoppedRef.current || busy) return
    try {
      const turn = await api.peekRegulationCreationTurn(session.draftId)
      syncQueueFromSession(turn)
      const lastIsAssistant = session.messages[session.messages.length - 1]?.role === 'assistant'
      if (
        !turn.prefetchPrompt?.trim() ||
        !lastIsAssistant ||
        prefetchRunRef.current ||
        typeof window.agent?.start !== 'function'
      ) {
        return
      }
      prefetchRunRef.current = true
      setPrefetching(true)
      const runId = agentClient.start({
        kind: 'regulation_creation',
        draftId: session.draftId,
        prompt: turn.prefetchPrompt,
        rules: turn.sdkRules,
        interview: turn.interview,
        resumeAgentId: turn.sdkAgentId || session.sdkAgentId
      })
      try {
        const sdk = await waitForRegulationSdk(runId, () => undefined)
        if (stoppedRef.current) return
        const answer = extractInterviewAnswer(sdk.answer) || sdk.answer
        if (!answer?.trim()) return
        const updated = await api.applyRegulationCreationReply(session.draftId, answer, {
          sdkAgentId: sdk.agentId || turn.sdkAgentId,
          prefetchOnly: true
        })
        syncQueueFromSession(updated)
        onSessionChange(updated)
      } finally {
        prefetchRunRef.current = false
        setPrefetching(false)
      }
    } catch {
      prefetchRunRef.current = false
      setPrefetching(false)
    }
  }

  async function prefetchResearch(): Promise<void> {
    if (ready || needsProcessSelection || stoppedRef.current || busy) return
    if (!session.dualWorkflow) return
    try {
      const turn = await api.peekRegulationCreationTurn(session.draftId)
      if (!turn.researchPrompt?.trim() || researchPrefetchRunRef.current || typeof window.agent?.start !== 'function') {
        return
      }
      researchPrefetchRunRef.current = true
      const runId = agentClient.start({
        kind: 'regulation_creation',
        draftId: session.draftId,
        prompt: turn.researchPrompt,
        rules: turn.sdkRules,
        interview: turn.interview,
        resumeAgentId: turn.researchAgentId || '',
        agentRole: 'research'
      })
      try {
        const sdk = await waitForRegulationSdk(runId, () => undefined)
        if (stoppedRef.current) return
        const answer = extractInterviewAnswer(sdk.answer) || sdk.answer
        if (!answer?.trim()) return
        const updated = await api.applyRegulationCreationReply(session.draftId, answer, {
          sdkAgentId: sdk.agentId || turn.researchAgentId,
          researchOnly: true
        })
        syncQueueFromSession(updated)
        onSessionChange(updated)
        void ensureCollectQuestionPosted(updated)
      } finally {
        researchPrefetchRunRef.current = false
      }
    } catch {
      researchPrefetchRunRef.current = false
    }
  }

  useEffect(() => {
    setSavedThinkingBlocks([])
    resetLiveThinking()
  }, [session.messages.length, session.draftId])

  useEffect(() => {
    setError('')
    setSavedNote('')
    setAttachments([])
    setFilesOpen(false)
    setPickedProcessIds([])
    setSelectingProcesses(false)
    setInput('')
    setPlaceholder(DEFAULT_PLACEHOLDER)
    setBusyKind('question')
    setReadingFileCount(0)
    stoppedRef.current = false
    abortRef.current = null
    runIdRef.current = ''
    queuedQuestionsRef.current = session.questionQueue ?? []
    setOptimisticQuestion(null)
    setPrefetching(Boolean(session.prefetchInProgress) && (session.queueDepth ?? 0) === 0)
    setSavedThinkingBlocks([])
    resetLiveThinking()
    resumeKeyRef.current = ''
    collectRecoverKeyRef.current = ''
    assembleRecoverKeyRef.current = ''
    setSubmitLocked(false)
    submittingRef.current = false
  }, [session.draftId])

  useEffect(() => {
    if (session.questionQueue?.length) {
      queuedQuestionsRef.current = session.questionQueue
    }
    setPrefetching(Boolean(session.prefetchInProgress) && (session.queueDepth ?? 0) === 0)
  }, [session.questionQueue, session.prefetchInProgress, session.queueDepth])

  useEffect(() => {
    onBusyChange?.(busy)
  }, [busy, onBusyChange])

  useEffect(() => {
    if (!pinnedRef.current) return
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [session.messages.length, busy])

  useEffect(() => {
    const node = textareaRef.current
    if (!node) return
    node.style.height = '0px'
    node.style.overflowY = 'hidden'
    const content = node.scrollHeight
    node.style.height = `${Math.min(Math.max(content, COMPOSER_MIN_HEIGHT), COMPOSER_MAX_HEIGHT)}px`
    node.style.overflowY = content > COMPOSER_MAX_HEIGHT ? 'auto' : 'hidden'
  }, [input])

  const ready = Boolean(session.resultRegulation || session.resultDocumentPath)
  const processChoices = processChoicesFromSession(session)
  const pipelineSelectedIds = selectedProcessIds(session)
  const needsProcessSelection = needsProcessSelectionForSession(session, ready)
  const hasUserMessage = session.messages.some((m) => m.role === 'user')
  useEffect(() => {
    if (!needsProcessSelection) return
    setPickedProcessIds((prev) => {
      if (prev.length > 0) return prev
      return pipelineSelectedIds
    })
  }, [needsProcessSelection, pipelineSelectedIds])

  const resultName = resultFileName(session)
  const phase: AgentPhase = ready ? 'completed' : busy ? 'working' : 'attention'
  const stageLabel = stageCaption(session)
  const queueDepthLabel =
    !ready && !needsProcessSelection
      ? effectiveQueueDepth(session, undefined, queuedQuestionsRef.current.length)
      : 0
  const remainingLabel = remainingEstimateLabel(session, queuedQuestionsRef.current.length)

  useEffect(() => {
    if (ready || needsProcessSelection || stoppedRef.current || busy) return
    const depth = session.queueDepth ?? session.questionQueue?.length ?? queuedQuestionsRef.current.length
    if (depth >= 3) return
    void prefetchQueue()
    void prefetchResearch()
  }, [
    session.draftId,
    ready,
    needsProcessSelection,
    busy,
    session.queueDepth,
    session.questionQueue?.length,
    session.messages.length,
    session.dualWorkflow
  ])

  async function downloadResult(): Promise<void> {
    if (!ready) return
    setError('')
    setSavedNote('')
    try {
      const res = await window.api.download({
        url: `/api/v1/regulation-creation/sessions/${session.draftId}/document`,
        defaultName: resultName,
        token: api.getToken()
      })
      if (res.canceled) return
      if (!res.ok) {
        setError(res.error || 'Не удалось скачать файл регламента')
        return
      }
      setSavedNote(res.path ? `Файл сохранён: ${res.path}` : 'Файл сохранён')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось скачать файл регламента')
    }
  }

  async function continueReady(): Promise<void> {
    setError('')
    try {
      await onReady(session)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Не удалось открыть регламент')
    }
  }

  function onScroll(): void {
    const el = scrollRef.current
    if (!el) return
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight
    pinnedRef.current = distance < 80
  }

  async function stopGeneration(): Promise<void> {
    if (!busy) return
    stoppedRef.current = true
    abortRef.current?.abort()
    if (runIdRef.current) {
      agentClient.cancel(runIdRef.current)
      runIdRef.current = ''
    }
    setBusy(false)
    setError('')
    await api.terminateRegulationCreationSessions()
    onStopped?.()
  }

  async function send(text: string, files: PendingFile[]): Promise<void> {
    const rawMessage = text.trim()
    const message = isForceCreateShortcut(rawMessage) ? FORCE_CREATE_PROMPT : rawMessage
    if (
      (!message && files.length === 0) ||
      busy ||
      needsProcessSelection ||
      submittingRef.current ||
      submitLocked ||
      awaitingAssistantReply(session)
    ) {
      return
    }
    submittingRef.current = true
    setSubmitLocked(true)
    stoppedRef.current = false
    setInput('')
    setPlaceholder(DEFAULT_PLACEHOLDER)
    setError('')
    const cachedNext = queuedQuestionsRef.current[0]
    const hasCachedNext = Boolean(cachedNext?.text)
    if (hasCachedNext) {
      setOptimisticQuestion(cachedNext)
      queuedQuestionsRef.current = queuedQuestionsRef.current.slice(1)
    }
    setBusy(true)
    setBusyKind(files.length > 0 ? 'reading' : 'question')
    setReadingFileCount(files.length)
    resetLiveThinking()
    pinnedRef.current = true
    const optimistic: RegulationCreationSession = {
      ...session,
      status: 'generating',
      messages: [
        ...session.messages,
        {
          messageId: 'local-pending',
          draftId: session.draftId,
          role: 'user',
          content: message,
          structured: files.length ? { attachments: files.map((f) => ({ name: f.name })) } : {},
          createdAt: new Date().toISOString()
        }
      ]
    }
    onSessionChange(optimistic)
    let persisted = false
    sdkRanRef.current = false
    try {
      const filePaths = files.map((f) => f.path)
      const onStreamEvent = (type: string, text: string, tool?: string): void => {
        pushLiveThinkingEvent({ type, text, tool })
      }
      if (typeof window.agent.start === 'function') {
        let turn: RegulationCreationTurn
        try {
          turn = await api.persistRegulationCreationTurn(session.draftId, message, filePaths)
        } catch (err) {
          if (!(err instanceof ApiError) || (err.status !== 404 && err.status !== 405)) {
            throw err
          }
          const updated = await api.streamRegulationCreationMessage(
            session.draftId,
            message,
            filePaths,
            (event) => onStreamEvent(event.type, event.text || event.message || '', event.tool)
          )
          persisted = true
          if (stoppedRef.current) throw new RegulationCancelledError()
          setAttachments([])
          setFilesOpen(false)
          onSessionChange(updated)
          return
        }
        persisted = true
        if (stoppedRef.current) throw new RegulationCancelledError()
        setAttachments([])
        setFilesOpen(false)
        setBusyKind('question')
        syncQueueFromSession(turn)
        onSessionChange(turn.session)
        setOptimisticQuestion(null)
        if (shouldBlockSdkAgent(turn.session, turn)) {
          resetLiveThinking()
          const depth = Math.max(
            turn.queueDepth ?? 0,
            turn.questionQueue?.length ?? 0,
            turn.session.queueDepth ?? 0,
            turn.session.questionQueue?.length ?? 0
          )
          if (depth > 0) {
            await ensureCollectQuestionPosted(turn.session)
          } else {
            void prefetchQueue()
            void prefetchResearch()
          }
          return
        }
        sdkRanRef.current = true
        await runSdkAndApply(turn)
        await tryUnstickCollectTurn(turn.session)
      } else {
        const updated = await api.streamRegulationCreationMessage(
          session.draftId,
          message,
          filePaths,
          (event) => onStreamEvent(event.type, event.text || event.message || '', event.tool)
        )
        persisted = true
        if (stoppedRef.current) throw new RegulationCancelledError()
        setAttachments([])
        setFilesOpen(false)
        onSessionChange(updated)
      }
    } catch (err) {
      if (isRegulationCancelled(err) || stoppedRef.current) {
        return
      }
      setError(err instanceof ApiError ? err.message : 'Ошибка отправки сообщения')
      setInput(text)
      setAttachments(files)
      setFilesOpen(files.length > 0)
      let next: RegulationCreationSession = { ...optimistic, status: 'idle' }
      if (persisted) {
        try {
          const latest = await api.getRegulationCreationSession(session.draftId)
          const hasUser = latest.messages.some((item) => item.role === 'user')
          next = hasUser ? latest : { ...latest, messages: optimistic.messages, status: 'idle' }
        } catch {
          /* keep the optimistic session with the user text and files */
        }
      }
      onSessionChange(next)
    } finally {
      if (sdkRanRef.current) {
        saveLiveThinkingSnapshot()
      } else {
        resetLiveThinking()
        setSavedThinkingBlocks([])
      }
      setBusy(false)
      submittingRef.current = false
      setSubmitLocked(false)
    }
  }

  async function ensureCollectQuestionPosted(freshSession?: RegulationCreationSession): Promise<void> {
    const base = freshSession ?? session
    const queueLen = Math.max(base.queueDepth ?? 0, base.questionQueue?.length ?? 0)
    if (queueLen <= 0) return
    const drainQueueUntilPosted = async (seed: RegulationCreationSession): Promise<RegulationCreationSession> => {
      let current = seed
      for (let i = 0; i < 4; i += 1) {
        const depth = Math.max(current.queueDepth ?? 0, current.questionQueue?.length ?? 0)
        if (depth <= 0) return current
        const lastAssistant = [...current.messages].reverse().find((item) => item.role === 'assistant')
        if (lastAssistant && quickAnswers(lastAssistant.structured).length > 0) return current
        const advanced = await api.advanceRegulationCreationQuestion(current.draftId)
        syncQueueFromSession(advanced)
        onSessionChange(advanced)
        current = advanced
      }
      return current
    }
    const pipeline = pipelineMeta(base)
    const stage = String(pipeline.stage || '').trim().toLowerCase()
    const phase = String(pipeline.interviewPhase || '').trim().toLowerCase()
    const interviewStage = stage === 'interview' || (stage === 'assemble' && queueLen > 0)
    if (!interviewStage && !isCollectInterview(base)) return
    if (stage === 'assemble' || phase === 'rounds' || isCollectInterview(base)) {
      try {
        const advanced = await drainQueueUntilPosted(base)
        syncQueueFromSession(advanced)
        onSessionChange(advanced)
        void prefetchQueue()
        void prefetchResearch()
        return
      } catch {
        /* fall through to heuristics below */
      }
    }
    const lastAssistant = [...base.messages].reverse().find((item) => item.role === 'assistant')
    const hasQuick = Boolean(lastAssistant && quickAnswers(lastAssistant.structured).length > 0)
    const visible = visibleChatMessages(base)
    const lastVisible = visible[visible.length - 1]
    if (lastVisible?.role === 'user' || !hasQuick) {
      try {
        const advanced = await drainQueueUntilPosted(base)
        syncQueueFromSession(advanced)
        onSessionChange(advanced)
        void prefetchQueue()
        void prefetchResearch()
      } catch {
        /* best effort when queue is waiting but chat is idle */
      }
    }
  }

  async function advanceCollectTurn(freshSession?: RegulationCreationSession): Promise<boolean> {
    const base = freshSession ?? session
    const turn = await api.peekRegulationCreationTurn(base.draftId)
    syncQueueFromSession(turn)
    if (turn.prefetchedReply?.trim()) {
      const updated = await api.applyRegulationCreationReply(base.draftId, turn.prefetchedReply, {
        sdkAgentId: turn.sdkAgentId,
        forceCreate: turn.forceCreate
      })
      syncQueueFromSession(updated)
      setOptimisticQuestion(null)
      onSessionChange(updated)
      void prefetchQueue()
      void prefetchResearch()
      await tryUnstickCollectTurn(updated)
      return true
    }
    const advanced = await api.advanceRegulationCreationQuestion(base.draftId)
    syncQueueFromSession(advanced)
    setOptimisticQuestion(null)
    onSessionChange(advanced)
    const lastAssistant = [...advanced.messages].reverse().find((item) => item.role === 'assistant')
    const served = Boolean(lastAssistant && quickAnswers(lastAssistant.structured).length > 0)
    if (served) {
      void prefetchQueue()
      void prefetchResearch()
    }
    return served
  }

  async function tryAdvanceAfterReply(freshSession?: RegulationCreationSession): Promise<void> {
    const base = freshSession ?? session
    if (Boolean(base.resultRegulation || base.resultDocumentPath)) return
    const visible = visibleChatMessages(base)
    const last = visible[visible.length - 1]
    if (last?.role !== 'user') return
    try {
      const advanced = await api.advanceRegulationCreationQuestion(base.draftId)
      syncQueueFromSession(advanced)
      onSessionChange(advanced)
      void prefetchQueue()
      void prefetchResearch()
    } catch {
      /* advance is best-effort when duplicate reply was skipped */
    }
  }

  async function tryUnstickCollectTurn(freshSession?: RegulationCreationSession): Promise<void> {
    const base = freshSession ?? session
    if (!isCollectInterview(base)) return
    const queueLen = Math.max(base.queueDepth ?? 0, base.questionQueue?.length ?? 0)
    if (queueLen <= 0) return
    const visible = visibleChatMessages(base)
    const last = visible[visible.length - 1]
    if (last?.role !== 'user') return
    try {
      await advanceCollectTurn(base)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось получить следующий вопрос')
    }
  }

  async function submitProcessSelection(): Promise<void> {
    if (busy || selectingProcesses) return
    const ids = Array.from(new Set(pickedProcessIds.map((item) => item.trim()).filter(Boolean)))
    if (ids.length === 0) {
      setError('Выберите хотя бы один процесс перед продолжением.')
      return
    }
    setError('')
    setSelectingProcesses(true)
    abortRef.current?.abort()
    abortRef.current = null
    if (runIdRef.current) {
      agentClient.cancel(runIdRef.current)
      runIdRef.current = ''
    }
    resumeKeyRef.current = ''
    resetLiveThinking()
    try {
      const updated = await api.selectRegulationCreationProcesses(session.draftId, ids)
      onSessionChange(updated)
      resumeKeyRef.current = `${updated.draftId}:selected`
      const lastAssistant = [...updated.messages].reverse().find((item) => item.role === 'assistant')
      const hasCollectQuestion = Boolean(
        lastAssistant && quickAnswers(lastAssistant.structured).length > 0
      )
      const queueLen = Math.max(updated.queueDepth ?? 0, updated.questionQueue?.length ?? 0)
      if (!hasCollectQuestion && queueLen > 0) {
        await advanceCollectTurn(updated)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось сохранить выбранные процессы')
    } finally {
      setSelectingProcesses(false)
    }
  }

  function handleQuick(answer: string, sourceText: string): void {
    if (busy || submitLocked || submittingRef.current || awaitingAssistantReply(session)) return
    if (/^передел/i.test(answer.trim())) {
      const proposal = extractProposal(sourceText)
      setInput(proposal)
      setPlaceholder(EDIT_PLACEHOLDER)
      requestAnimationFrame(() => {
        const el = textareaRef.current
        if (el) {
          el.focus()
          el.setSelectionRange(el.value.length, el.value.length)
        }
      })
      return
    }
    void send(answer, [])
  }

  async function pickFiles(): Promise<void> {
    if (busy) return
    const paths = await window.api.openFile({
      title: 'Выберите файлы для регламента',
      filters: [{ name: 'Документы', extensions: ['docx', 'pdf', 'md', 'txt'] }],
      properties: ['openFile', 'multiSelections']
    })
    if (!paths.length) return
    setAttachments((prev) => {
      const seen = new Set(prev.map((f) => f.path))
      const next = [...prev]
      for (const p of paths) {
        if (seen.has(p)) continue
        next.push({ path: p, name: p.split(/[\\/]/).pop() || p })
      }
      return next
    })
    setFilesOpen(true)
  }

  function removeAttachment(path: string): void {
    setAttachments((prev) => {
      const next = prev.filter((f) => f.path !== path)
      if (next.length === 0) setFilesOpen(false)
      return next
    })
  }

  const visible = visibleChatMessages(session)
  const lastAssistantId = [...visible].reverse().find((item) => item.role === 'assistant')?.messageId || ''
  const lastVisible = visible[visible.length - 1]
  const waitingForAssistant = awaitingAssistantReply(session)
  const pendingUserId = pendingUserMessageId(session)

  async function runSdkAndApply(turn: RegulationCreationTurn): Promise<void> {
    if (stoppedRef.current) throw new RegulationCancelledError()
    syncQueueFromSession(turn)
    if (shouldBlockSdkAgent(turn.session, turn)) {
      if (turn.prefetchedReply && !needsProcessSelectionForSession(turn.session, ready)) {
        const updated = await api.applyRegulationCreationReply(session.draftId, turn.prefetchedReply, {
          sdkAgentId: turn.sdkAgentId,
          forceCreate: turn.forceCreate
        })
        if (stoppedRef.current) throw new RegulationCancelledError()
        syncQueueFromSession(updated)
        setOptimisticQuestion(null)
        onSessionChange(updated)
        void prefetchQueue()
        void prefetchResearch()
        await tryAdvanceAfterReply(updated)
      } else {
        const queueLen = Math.max(
          turn.queueDepth ?? 0,
          turn.questionQueue?.length ?? 0,
          turn.session.queueDepth ?? 0,
          turn.session.questionQueue?.length ?? 0
        )
        if (queueLen > 0 && !turn.prefetchedReply) {
          const retry = await api.peekRegulationCreationTurn(session.draftId)
          if (retry.prefetchedReply) {
            const updated = await api.applyRegulationCreationReply(session.draftId, retry.prefetchedReply, {
              sdkAgentId: retry.sdkAgentId,
              forceCreate: retry.forceCreate
            })
            if (stoppedRef.current) throw new RegulationCancelledError()
            syncQueueFromSession(updated)
            setOptimisticQuestion(null)
            onSessionChange(updated)
            void prefetchQueue()
            void prefetchResearch()
            await ensureCollectQuestionPosted(updated)
          } else {
            await ensureCollectQuestionPosted(retry.session)
          }
        } else {
          onSessionChange(turn.session)
          if (queueLen > 0) {
            await ensureCollectQuestionPosted(turn.session)
          }
        }
      }
      return
    }
    if (turn.prefetchedReply) {
      const updated = await api.applyRegulationCreationReply(session.draftId, turn.prefetchedReply, {
        sdkAgentId: turn.sdkAgentId,
        forceCreate: turn.forceCreate
      })
      if (stoppedRef.current) throw new RegulationCancelledError()
      syncQueueFromSession(updated)
      setOptimisticQuestion(null)
      onSessionChange(updated)
      void prefetchQueue()
      void prefetchResearch()
      await tryAdvanceAfterReply(updated)
      await tryUnstickCollectTurn(updated)
      await ensureCollectQuestionPosted(updated)
      return
    }
    if (!turn.sdkPrompt?.trim()) {
      syncQueueFromSession(turn)
      onSessionChange(turn.session)
      await tryUnstickCollectTurn(turn.session)
      return
    }
    resetLiveThinking()
    const abort = new AbortController()
    abortRef.current = abort
    const runId = agentClient.start({
      kind: 'regulation_creation',
      draftId: session.draftId,
      prompt: turn.sdkPrompt,
      rules: turn.sdkRules,
      interview: turn.interview,
      resumeAgentId: turn.sdkAgentId || session.sdkAgentId
    })
    runIdRef.current = runId
    try {
      const sdk = await waitForRegulationSdk(runId, pushLiveThinkingEvent, abort.signal)
      if (abort.signal.aborted || stoppedRef.current) {
        throw new RegulationCancelledError()
      }
      const answer = extractInterviewAnswer(sdk.answer) || sdk.answer
      const visibleText = visibleAssistantText(answer) || answer
      if (!answer || answer.trim() === '{}' || isReplacementGarbage(visibleText)) {
        if (isCollectInterview(session)) {
          await ensureCollectQuestionPosted(session)
          return
        }
        throw new Error('Агент вернул нечитаемый ответ. Попробуйте ещё раз.')
      }
      const updated = await api.applyRegulationCreationReply(session.draftId, answer, {
        sdkAgentId: sdk.agentId || turn.sdkAgentId,
        forceCreate: turn.forceCreate
      })
      if (abort.signal.aborted || stoppedRef.current) {
        throw new RegulationCancelledError()
      }
      syncQueueFromSession(updated)
      setOptimisticQuestion(null)
      onSessionChange(updated)
      void prefetchQueue()
      void prefetchResearch()
      await tryAdvanceAfterReply(updated)
      await tryUnstickCollectTurn(updated)
      await ensureCollectQuestionPosted(updated)
    } finally {
      if (abortRef.current === abort) abortRef.current = null
      if (runIdRef.current === runId) runIdRef.current = ''
    }
  }

  async function continuePendingTurn(): Promise<void> {
    if (busy || ready || stoppedRef.current || needsProcessSelection || selectingProcesses) return
    setError('')
    setBusy(true)
    setBusyKind('question')
    resetLiveThinking()
    sdkRanRef.current = false
    pinnedRef.current = true
    try {
      const turn = await api.peekRegulationCreationTurn(session.draftId)
      if (stoppedRef.current) throw new RegulationCancelledError()
      if (shouldBlockSdkAgent(turn.session, turn)) {
        syncQueueFromSession(turn)
        onSessionChange(turn.session)
        setOptimisticQuestion(null)
        const queueLen = Math.max(
          turn.queueDepth ?? 0,
          turn.questionQueue?.length ?? 0,
          turn.session.queueDepth ?? 0,
          turn.session.questionQueue?.length ?? 0
        )
        if (queueLen > 0) {
          await ensureCollectQuestionPosted(turn.session)
        } else {
          void prefetchQueue()
        void prefetchResearch()
        }
        return
      }
      sdkRanRef.current = true
      await runSdkAndApply(turn)
    } catch (err) {
      if (isRegulationCancelled(err) || stoppedRef.current) return
      setError(err instanceof ApiError ? err.message : 'Не удалось получить вопрос ИИ')
    } finally {
      if (sdkRanRef.current) {
        saveLiveThinkingSnapshot()
      } else {
        resetLiveThinking()
        setSavedThinkingBlocks([])
      }
      setBusy(false)
    }
  }

  useEffect(() => {
    if (!needsProcessSelection) return
    stoppedRef.current = false
    abortRef.current?.abort()
    abortRef.current = null
    if (runIdRef.current) {
      agentClient.cancel(runIdRef.current)
      runIdRef.current = ''
    }
    setBusy(false)
    setSubmitLocked(false)
    submittingRef.current = false
    setOptimisticQuestion(null)
    resumeKeyRef.current = ''
  }, [needsProcessSelection, session.draftId])

  useEffect(() => {
    if (busy || ready || stoppedRef.current || needsProcessSelection) return
    if (!waitingForAssistant || !isCollectInterview(session)) return
    const queueLen = Math.max(
      session.queueDepth ?? 0,
      session.questionQueue?.length ?? 0,
      queuedQuestionsRef.current.length
    )
    if (queueLen <= 0) return
    const key = `collect:${session.draftId}:${pendingUserId || 'user'}`
    if (collectRecoverKeyRef.current === key) return
    collectRecoverKeyRef.current = key
    void tryUnstickCollectTurn(session)
  }, [
    session.draftId,
    pendingUserId,
    waitingForAssistant,
    busy,
    ready,
    needsProcessSelection,
    session.queueDepth,
    session.questionQueue?.length
  ])

  useEffect(() => {
    if (busy || ready || stoppedRef.current || needsProcessSelection || selectingProcesses) return
    const queueLen = Math.max(
      session.queueDepth ?? 0,
      session.questionQueue?.length ?? 0,
      queuedQuestionsRef.current.length
    )
    if (queueLen <= 0) return
    const pipeline = pipelineMeta(session)
    const stage = String(pipeline.stage || '').trim().toLowerCase()
    if (stage !== 'interview' && stage !== 'assemble') return
    const key = `idle:${session.draftId}:${queueLen}:${session.messages.length}`
    if (idleRecoverKeyRef.current === key) return
    idleRecoverKeyRef.current = key
    void ensureCollectQuestionPosted(session)
  }, [
    busy,
    ready,
    needsProcessSelection,
    selectingProcesses,
    session.draftId,
    session.queueDepth,
    session.questionQueue?.length,
    session.messages.length,
    session.pipeline
  ])

  // Retry queue draining periodically: one failed advance call should not stall
  // the interview for minutes while questionQueue is still non-empty.
  useEffect(() => {
    if (busy || ready || stoppedRef.current || needsProcessSelection || selectingProcesses) return
    const queueLen = Math.max(
      session.queueDepth ?? 0,
      session.questionQueue?.length ?? 0,
      queuedQuestionsRef.current.length
    )
    if (queueLen <= 0) return
    const timer = window.setInterval(() => {
      if (busy || stoppedRef.current) return
      void ensureCollectQuestionPosted(session)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [
    session.draftId,
    session.queueDepth,
    session.questionQueue?.length,
    session.messages.length,
    busy,
    ready,
    needsProcessSelection,
    selectingProcesses,
  ])

  useEffect(() => {
    if (busy || ready || stoppedRef.current || needsProcessSelection || selectingProcesses) return
    const queueLen = Math.max(session.queueDepth ?? 0, session.questionQueue?.length ?? 0)
    if (queueLen <= 0) return
    const visible = visibleChatMessages(session)
    const last = visible[visible.length - 1]
    const prev = visible[visible.length - 2]
    if (!last || !prev || last.role !== 'assistant' || prev.role !== 'assistant') return
    const lastSig = questionSignature(last.content)
    const prevSig = questionSignature(prev.content)
    if (!lastSig || lastSig !== prevSig) return
    const key = `${session.draftId}:${lastSig}:${visible.length}`
    if (repeatRecoverKeyRef.current === key) return
    repeatRecoverKeyRef.current = key
    void advanceCollectTurn(session)
  }, [
    session.draftId,
    session.messages.length,
    session.queueDepth,
    session.questionQueue?.length,
    busy,
    ready,
    needsProcessSelection,
    selectingProcesses,
  ])

  useEffect(() => {
    if (busy || ready || stoppedRef.current || !window.agent?.start) return
    if (needsProcessSelection) return
    const queueLen = effectiveQueueDepth(session, undefined, queuedQuestionsRef.current.length)
    if (queueLen > 0) {
      assembleRecoverKeyRef.current = ''
      void ensureCollectQuestionPosted(session)
      return
    }
    if (!isAssemblePending(session, queueLen)) return
    const key = `assemble:${session.draftId}`
    if (assembleRecoverKeyRef.current === key) return
    assembleRecoverKeyRef.current = key
    void continuePendingTurn()
  }, [
    session.draftId,
    session.pipeline,
    session.resultRegulation,
    session.resultDocumentPath,
    session.queueDepth,
    session.questionQueue?.length,
    busy,
    ready,
    needsProcessSelection
  ])

  useEffect(() => {
    if (busy || ready || stoppedRef.current || !pendingUserId || !window.agent?.start) return
    if (needsProcessSelection || selectingProcesses) return
    if (isAssemblePending(session)) return
    const key = `${session.draftId}:${pendingUserId}`
    if (resumeKeyRef.current === key) return
    resumeKeyRef.current = key
    void continuePendingTurn()
  }, [session.draftId, pendingUserId, busy, ready, needsProcessSelection, selectingProcesses, session.pipeline])

  return (
    <div className="regchat-page">
      <div className="regchat-head">
        <div className="regchat-head-top">
          <button className="btn-ghost" onClick={onBack}>
            {'\u2039'} Назад
          </button>
          <h1 className="page-title" style={{ fontSize: 24 }}>
            Создание регламента
          </h1>
          <button
            className="regchat-force"
            onClick={() => void send(FORCE_CREATE_PROMPT, [])}
            disabled={!hasUserMessage || busy || needsProcessSelection}
          >
            Создать принудительно
          </button>
        </div>
        <div className="regchat-subtitle">
          Ответьте на вопросы, и ИИ подготовит регламент в стиле ваших документов
        </div>
        {!ready && (
          <div className="regchat-stage-hint">
            <span>{stageLabel}</span>
            {remainingLabel ? <span className="regchat-remaining">{remainingLabel}</span> : null}
            {queueDepthLabel > 0 && !remainingLabel.includes('В очереди') ? (
              <span className="regchat-remaining">В очереди: {queueDepthLabel} вопросов</span>
            ) : null}
          </div>
        )}
      </div>
        {session.spawnedAgents && session.spawnedAgents.length > 0 ? (
          <div className="regchat-banner">
            Новые агенты в «Мои агенты»:{' '}
            {session.spawnedAgents.map((item) => String(item.title || item.processId || '')).filter(Boolean).join(', ')}
          </div>
        ) : null}
      {banner ? <div className="regchat-banner">{banner}</div> : null}

      <div className="regchat-stage">
        <div
          className="regchat-page-bg"
          style={{ backgroundImage: `url(${wallpaperUrl})` }}
          aria-hidden
        />
        <div className="regchat-feed-wrap">
            <div className="regchat-scroll" ref={scrollRef} onScroll={onScroll}>
              <div className="regchat-column">
              {!hasUserMessage && !ready && !needsProcessSelection && (
                <div className="regchat-row ai">
                  <AgentAvatar phase="attention" uid="starter" frozen={visible.length > 0} />
                  <div className="regchat-bubble-col">
                    <div className="regchat-starter">
                      <h3>С чего начать</h3>
                      <ul>
                        {STARTER_HINTS.map((hint) => (
                          <li key={hint}>{hint}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </div>
              )}
              {needsProcessSelection && (
                <div className="regchat-row ai">
                  <AgentAvatar phase="attention" uid="process-select" frozen={false} />
                  <div className="regchat-bubble-col">
                    <div className="regchat-select-card">
                      <h3>Выберите процессы для интервью</h3>
                      <p>ИИ продолжит только по отмеченным процессам.</p>
                      <div className="regchat-select-list">
                        {processChoices.map((process) => {
                          const checked = pickedProcessIds.includes(process.id)
                          return (
                            <label key={process.id} className="regchat-select-item">
                              <input
                                type="checkbox"
                                checked={checked}
                                disabled={selectingProcesses}
                                onChange={(e) =>
                                  setPickedProcessIds((prev) =>
                                    e.target.checked
                                      ? [...prev, process.id]
                                      : prev.filter((id) => id !== process.id)
                                  )
                                }
                              />
                              <span className="regchat-select-title">{process.title}</span>
                              {process.actor ? (
                                <span className="regchat-select-actor">{process.actor}</span>
                              ) : null}
                            </label>
                          )
                        })}
                      </div>
                      <button
                        type="button"
                        className="regchat-select-submit"
                        disabled={selectingProcesses || pickedProcessIds.length === 0}
                        onClick={() => void submitProcessSelection()}
                      >
                        {selectingProcesses ? 'Сохраняю выбор...' : 'Продолжить по выбранным процессам'}
                      </button>
                    </div>
                  </div>
                </div>
              )}
              {visible.map((m, index) => {
                const isUser = m.role === 'user'
                const structuredNames = attachmentsOf(m.structured)
                const names = structuredNames.length
                  ? structuredNames
                  : isUser
                    ? attachmentNamesFromContent(m.content)
                    : []
                const text = isUser ? visibleUserText(m.content) : visibleAssistantText(m.content)
                const timeLabel = formatRegulationMessageTime(m.createdAt)
                const quicks = quickAnswers(m.structured)
                const isCurrentStage =
                  !isUser &&
                  !busy &&
                  !ready &&
                  !waitingForAssistant &&
                  !submitLocked &&
                  Boolean(lastAssistantId) &&
                  m.messageId === lastAssistantId
                return (
                  <div key={m.messageId || index} className={isUser ? 'regchat-row user' : 'regchat-row ai'}>
                    {!isUser && (
                      <AgentAvatar
                        phase={phase}
                        uid={`msg-${m.messageId || index}`}
                        frozen={!isCurrentStage}
                      />
                    )}
                    <div className="regchat-bubble-col">
                      <div className={isUser ? 'regchat-bubble user' : 'regchat-bubble ai'}>
                        {text ? <div className="regchat-bubble-text">{text}</div> : null}
                        {names.length > 0 && (
                          <div className="regchat-attach-list">
                            {names.map((n, i) => (
                              <span key={i} className="regchat-file-row">
                                <img className="regchat-file-icon" src={fileTypeIconSrc(n)} alt="" />
                                <span className="regchat-file-name" title={n}>
                                  {n}
                                </span>
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                      {timeLabel ? (
                        <div className={isUser ? 'regchat-time user' : 'regchat-time'}>{timeLabel}</div>
                      ) : null}
                      {!isUser && isCurrentStage && quicks.length > 0 && !needsProcessSelection && (
                        <div className="regchat-quick-row">
                          {quicks.map((qa) => (
                            <button
                              key={qa}
                              className="regchat-quick-chip"
                              onClick={() => handleQuick(qa, m.content)}
                            disabled={busy || submitLocked || waitingForAssistant}
                            >
                              {qa}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
              {optimisticQuestion && (
                <div className="regchat-row ai">
                  <AgentAvatar phase="attention" uid="queued-next" frozen={false} />
                  <div className="regchat-bubble-col">
                    <div className="regchat-bubble ai">
                      <div className="regchat-bubble-text">{optimisticQuestion.text}</div>
                    </div>
                    {optimisticQuestion.options &&
                      optimisticQuestion.options.length > 0 &&
                      !waitingForAssistant &&
                      !submitLocked && (
                      <div className="regchat-quick-row">
                        {optimisticQuestion.options.map((qa) => (
                          <button
                            key={qa}
                            className="regchat-quick-chip"
                            onClick={() => handleQuick(qa, optimisticQuestion.text)}
                            disabled={busy || submitLocked || waitingForAssistant}
                          >
                            {qa}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
              {savedThinkingBlocks.map((block) => (
                <div key={block.id} className="regchat-row ai">
                  <AgentAvatar phase="completed" uid={`think-${block.id}`} frozen />
                  <div className="regchat-bubble-col">
                    <RegulationThinkingBlock text={block.text} />
                  </div>
                </div>
              ))}
              {busy && !optimisticQuestion && (
                <div className="regchat-row ai">
                  <AgentAvatar phase="working" uid="working" />
                  <div className="regchat-bubble-col">
                    {isMeaningfulThinking(liveThinking) ? (
                      <RegulationThinkingBlock
                        text={liveThinking}
                        defaultOpen
                        label={busyHeadLabel(busyKind, readingFileCount)}
                      />
                    ) : (
                      <div className="regchat-think">
                        <div className="regchat-think-head regchat-think-head-static">
                          <span>{busyHeadLabel(busyKind, readingFileCount)}</span>
                        </div>
                      </div>
                    )}
                    <div className="regchat-status">
                      {busyStatusLabel(busyKind, readingFileCount, prefetching)}
                    </div>
                  </div>
                </div>
              )}
              {busy && optimisticQuestion && prefetching && (
                <div className="regchat-row ai">
                  <div className="regchat-bubble-col">
                    <div className="regchat-status">{PREFETCH_STATUS}</div>
                  </div>
                </div>
              )}
              {ready && (
                <div className="regchat-row ai">
                  <AgentAvatar phase="completed" uid="completed" />
                  <div className="regchat-bubble-col">
                    <div className="regchat-doc-card">
                      <div className="regchat-file-row">
                        <img className="regchat-file-icon" src={fileTypeIconSrc(resultName)} alt="" />
                        <span className="regchat-file-name" title={resultName}>
                          {resultName}
                        </span>
                      </div>
                      <button
                        type="button"
                        className="regchat-doc-download"
                        onClick={() => void downloadResult()}
                      >
                        Скачать
                      </button>
                    </div>
                  </div>
                </div>
              )}
              </div>
            </div>
          </div>

          {error && (
            <div className="status-line" style={{ color: 'var(--error)' }}>
              {error}
            </div>
          )}
          {savedNote && !error && (
            <div className="status-line">{savedNote}</div>
          )}

          {ready && (
            <div className="chat-ready">
              <div>Регламент готов. Файл можно скачать в чате или перейти к проверке.</div>
              <button
                className="btn-primary"
                style={{ maxWidth: 260 }}
                onClick={() => void continueReady()}
              >
                Продолжить
              </button>
            </div>
          )}

          {!ready && (
            <div className="regchat-composer">
              <div className="regchat-composer-box">
                {attachments.length > 0 && (
                  <div className="regchat-files">
                    <button
                      type="button"
                      className="regchat-files-toggle"
                      onClick={() => setFilesOpen((open) => !open)}
                    >
                      <span>{filesOpen ? '\u25BE' : '\u25B8'}</span>
                      <span>
                        {attachments.length} {fileCountLabel(attachments.length)}
                      </span>
                    </button>
                    {filesOpen ? (
                      <div className="regchat-pending">
                        {attachments.map((f) => (
                          <span key={f.path} className="regchat-file-row pending">
                            <img className="regchat-file-icon" src={fileTypeIconSrc(f.name)} alt="" />
                            <span className="regchat-file-name" title={f.name}>
                              {f.name}
                            </span>
                            <button
                              className="regchat-pending-remove"
                              onClick={() => removeAttachment(f.path)}
                              disabled={busy}
                              aria-label="Убрать файл"
                            >
                              {'\u00D7'}
                            </button>
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                )}
            <div className="regchat-composer-input">
              <textarea
                ref={textareaRef}
                value={input}
                placeholder={placeholder}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    void send(input, attachments)
                  }
                }}
                disabled={busy || needsProcessSelection}
                rows={1}
              />
              <div className="regchat-composer-tools">
                <button
                  className="regchat-tool-btn"
                  onClick={() => void pickFiles()}
                  disabled={busy || needsProcessSelection}
                  title="Приложить файлы"
                  aria-label="Приложить файлы"
                  type="button"
                >
                  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden>
                    <path
                      d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
                {busy ? (
                  <button
                    className="regchat-send-btn stop"
                    onClick={() => void stopGeneration()}
                    title="Остановить"
                    aria-label="Остановить"
                    type="button"
                  >
                    <span className="regchat-stop-icon" />
                  </button>
                ) : (
                  <button
                    className="regchat-send-btn"
                    onClick={() => void send(input, attachments)}
                    disabled={needsProcessSelection || (!input.trim() && attachments.length === 0)}
                    title="Отправить"
                    aria-label="Отправить"
                    type="button"
                  >
                    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden>
                      <path d="M12 19V5M5 12l7-7 7 7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                )}
              </div>
            </div>
              </div>
              <div className="regchat-composer-hint">
                Enter — отправить {'\u2022'} Shift + Enter — новая строка
              </div>
            </div>
          )}
      </div>
    </div>
  )
}
