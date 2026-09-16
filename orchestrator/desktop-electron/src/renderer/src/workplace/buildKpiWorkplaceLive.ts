import type { BoardAgent, CalendarEvent, WorkflowBoard } from '../api/types'
import { parseIso } from '../utils/calendar'
import type { MeetingEvent } from '../utils/outlookMeetings'
import { parseMeetingTime } from '../utils/outlookMeetings'
import type { SpecTaskRow } from './specV04DemoData'
import type { WorkplaceKpiAgentRow, WorkplaceKpiCompareRow } from './workplaceKpiTypes'

export type KpiLiveSources = {
  erpTasks: SpecTaskRow[]
  meetings: MeetingEvent[]
  regDone: number
  regTotal: number
  mailCount?: number
}

function parseDayBound(iso: string, end: boolean): Date {
  return new Date(`${iso.trim()}T${end ? '23:59:59' : '00:00:00'}`)
}

function parseTaskDue(deadline: string): Date | null {
  const raw = (deadline || '').trim()
  if (!raw || raw === '—') return null
  const iso = parseMeetingTime(raw)
  if (iso) return iso
  const m = raw.match(/(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?/)
  if (m) {
    const day = Number(m[1])
    const month = Number(m[2]) - 1
    const year = m[3] ? (m[3].length === 2 ? 2000 + Number(m[3]) : Number(m[3])) : new Date().getFullYear()
    return new Date(year, month, day, 12, 0, 0)
  }
  return null
}

function taskInPeriod(task: SpecTaskRow, from: string, to: string): boolean {
  const due = parseTaskDue(task.deadline)
  if (!due) return true
  const lo = parseDayBound(from, false)
  const hi = parseDayBound(to, true)
  return due >= lo && due <= hi
}

function meetingHoursInPeriod(meetings: MeetingEvent[], from: string, to: string): number {
  const lo = parseDayBound(from, false).getTime()
  const hi = parseDayBound(to, true).getTime()
  let hours = 0
  for (const m of meetings) {
    const start = parseMeetingTime(m.start)
    const end = parseMeetingTime(m.end)
    if (!start) continue
    const t = start.getTime()
    if (t < lo || t > hi) continue
    if (end && end > start) hours += (end.getTime() - start.getTime()) / 3_600_000
    else hours += 1
  }
  return hours
}

const SUCCESS = new Set(['ok', 'success', 'successful', 'completed', 'done', 'ready'])
const FAIL = new Set(['error', 'fail', 'failed'])

function isSuccessStatus(status: string): boolean {
  const v = (status || '').toLowerCase()
  return [...SUCCESS].some((token) => v.includes(token))
}

function isFinishedStatus(status: string): boolean {
  const v = (status || '').toLowerCase()
  return isSuccessStatus(v) || [...FAIL].some((token) => v.includes(token))
}

function eventsInPeriod(events: CalendarEvent[], from: string, to: string): CalendarEvent[] {
  const lo = parseDayBound(from, false).getTime()
  const hi = parseDayBound(to, true).getTime()
  return events.filter((ev) => {
    const stamp = parseIso(ev.startAt)
    if (!stamp) return false
    const t = stamp.getTime()
    return t >= lo && t <= hi
  })
}

function workflowCode(agent: BoardAgent, index: number): string {
  const title = (agent.title || '').trim()
  if (title) {
    const slug = title
      .toUpperCase()
      .replace(/[^A-ZА-Я0-9]/g, '')
      .slice(0, 6)
    if (slug.length >= 3) return slug
  }
  return `WF-${String(index + 1).padStart(2, '0')}`
}

function statusForCompletion(completion: number): { status: string; tone: string } {
  if (completion >= 90) return { status: 'В норме', tone: 'green' }
  if (completion >= 75) return { status: 'Внимание', tone: 'orange' }
  return { status: 'Риск', tone: 'red' }
}

function processLabel(agent: BoardAgent): string {
  const summary = (agent.triggerSummary || '').trim()
  if (summary && summary.length < 80) return summary
  return (agent.title || 'Процесс').trim()
}

type WorkloadCategory = 'reg' | 'report' | 'mail' | 'tasks'

function categorizeAgent(agent: BoardAgent): WorkloadCategory {
  const text = `${agent.title} ${agent.triggerSummary} ${agent.description}`.toLowerCase()
  if (/реглам|rig-|rig_/.test(text)) return 'reg'
  if (/отч[её]т|report|rep-|kpi/.test(text)) return 'report'
  if (/почт|mail|ml-|входящ/.test(text)) return 'mail'
  return 'tasks'
}

function aiHoursForEvent(_event: CalendarEvent): number {
  return 0.5
}

export type BoardRunTotals = { ok: number; finished: number; events: number }

/** Свод по запускам workflow за период (для общих KPI, не дублируя только 1C). */
export function boardRunTotalsInPeriod(
  board: WorkflowBoard | null,
  from: string,
  to: string
): BoardRunTotals {
  if (!board) return { ok: 0, finished: 0, events: 0 }
  const periodEvents = eventsInPeriod(board.events, from, to)
  const finished = periodEvents.filter((ev) => isFinishedStatus(ev.status))
  const ok = finished.filter((ev) => isSuccessStatus(ev.status)).length
  return { ok, finished: finished.length, events: periodEvents.length }
}

export function buildKpiAgentsFromBoard(board: WorkflowBoard, from: string, to: string): WorkplaceKpiAgentRow[] {
  const workflows = board.agents.filter((a) => a.kind === 'workflow' && a.id)
  const periodEvents = eventsInPeriod(board.events, from, to)
  const byWf = new Map<string, CalendarEvent[]>()
  for (const ev of periodEvents) {
    if (!ev.workflowId) continue
    const list = byWf.get(ev.workflowId) || []
    list.push(ev)
    byWf.set(ev.workflowId, list)
  }

  return workflows.slice(0, 16).map((wf, index) => {
    const wfEvents = byWf.get(wf.id) || []
    const finished = wfEvents.filter((ev) => isFinishedStatus(ev.status))
    const ok = finished.filter((ev) => isSuccessStatus(ev.status)).length
    const total = finished.length || wfEvents.length
    const completion = total ? Math.round((100 * ok) / total) : 0
    const sla = total ? completion : 0
    const load = Math.min(100, wfEvents.length * 8)
    const automation = total ? Math.min(99, Math.max(40, completion - 10)) : 40
    const { status, tone } = statusForCompletion(completion || (wf.lastRunStatus ? 75 : 50))

    return {
      id: wf.id,
      code: workflowCode(wf, index),
      name: wf.title || 'ИИ-агент',
      process: processLabel(wf),
      completionPct: completion,
      slaPct: sla,
      loadPct: load,
      automationPct: automation,
      status,
      statusTone: tone,
      source: 'computed'
    }
  })
}

export function buildWorkloadCompareFromSources(
  sources: KpiLiveSources,
  board: WorkflowBoard | null,
  from: string,
  to: string
): WorkplaceKpiCompareRow[] {
  const buckets: Record<WorkloadCategory, { employee: number; ai: number }> = {
    reg: { employee: 0, ai: 0 },
    report: { employee: 0, ai: 0 },
    mail: { employee: 0, ai: 0 },
    tasks: { employee: 0, ai: 0 }
  }

  const pendingReg = Math.max(0, sources.regTotal - sources.regDone)
  buckets.reg.employee = Math.round(pendingReg * 1.2 + sources.regDone * 0.4)

  buckets.report.employee = Math.round(meetingHoursInPeriod(sources.meetings, from, to))

  buckets.mail.employee = Math.round((sources.mailCount ?? 0) * 0.25)

  const periodTasks = sources.erpTasks.filter((t) => taskInPeriod(t, from, to))
  const openTasks = periodTasks.filter((t) => t.status !== 'Выполнена').length
  const doneTasks = periodTasks.filter((t) => t.status === 'Выполнена').length
  buckets.tasks.employee = Math.round(openTasks * 1.5 + doneTasks * 0.5)

  if (board) {
    const wfById = new Map(board.agents.map((a) => [a.id, a]))
    for (const ev of eventsInPeriod(board.events, from, to)) {
      const wf = wfById.get(ev.workflowId)
      const cat = wf ? categorizeAgent(wf) : 'tasks'
      buckets[cat].ai += aiHoursForEvent(ev)
    }
  }

  const round = (n: number): number => Math.max(0, Math.round(n))

  return [
    {
      id: 'c1',
      label: 'Регламенты',
      employee: round(buckets.reg.employee),
      ai: round(buckets.reg.ai),
      source: 'computed'
    },
    {
      id: 'c2',
      label: 'Отчётность',
      employee: round(buckets.report.employee),
      ai: round(buckets.report.ai),
      source: 'computed'
    },
    {
      id: 'c3',
      label: 'Почта',
      employee: round(buckets.mail.employee),
      ai: round(buckets.mail.ai),
      source: 'computed'
    },
    {
      id: 'c4',
      label: 'Задачи 1С',
      employee: round(buckets.tasks.employee),
      ai: round(buckets.tasks.ai),
      source: 'computed'
    }
  ]
}
