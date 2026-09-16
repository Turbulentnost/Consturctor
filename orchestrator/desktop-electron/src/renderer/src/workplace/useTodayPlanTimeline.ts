import { useEffect, useMemo, useRef, useState } from 'react'
import type { CalendarEvent, WorkflowBoard } from '../api/types'
import {
  dedupeMeetingEvents,
  ensureOutlookMeetings,
  parseMeetingTime,
  type MeetingEvent
} from '../utils/outlookMeetings'
import { parseIso, sameDay } from '../utils/calendar'
import { useWorkplaceData } from './WorkplaceBoard'
import {
  TODAY_PLAN_AI_MOCKS,
  TODAY_PLAN_MEETING_MOCKS,
  TODAY_PLAN_PREFER_MOCKS,
  type TodayPlanBlock
} from '../tabs/grid/todayDemoData'
import { useGridRefreshGeneration } from './GridDataRefreshContext'
import { readGridCache, shouldRunGridFetch, writeGridCache } from './gridDataCache'

export const TODAY_PLAN_DAY_START = 9
export const TODAY_PLAN_DAY_END = 18

const MEETING_TONES: TodayPlanBlock['tone'][] = ['pink', 'purple', 'sky', 'orange', 'teal']
const AI_TONES: TodayPlanBlock['tone'][] = ['sky', 'teal', 'orange', 'blue', 'mint']

export const TODAY_LUNCH_BLOCK: TodayPlanBlock = {
  id: 'lunch',
  startHour: 12,
  endHour: 13,
  title: 'Обед',
  tone: 'mint',
  who: 'employee',
  kind: 'reg',
  lane: 'lunch',
  detail: {
    timeRange: '12:00 – 13:00',
    typeLabel: 'Перерыв',
    note: 'Обеденный перерыв'
  }
}

function decimalHour(stamp: Date): number {
  return stamp.getHours() + stamp.getMinutes() / 60 + stamp.getSeconds() / 3600
}

function formatClock(stamp: Date): string {
  return stamp.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

function formatTimeRange(start: Date, end: Date): string {
  return `${formatClock(start)} – ${formatClock(end)}`
}

function meetingFormatHint(location: string): string | undefined {
  const loc = (location || '').trim()
  if (!loc) return 'Формат не указан'
  const lower = loc.toLowerCase()
  if (
    lower.includes('teams') ||
    lower.includes('zoom') ||
    lower.includes('meet') ||
    lower.includes('онлайн') ||
    lower.includes('http')
  ) {
    return 'Онлайн'
  }
  return 'Очно / переговорная'
}

function isOnLocalDay(stamp: Date, day: Date): boolean {
  return sameDay(stamp, day)
}

function isNoiseBoardEvent(event: CalendarEvent): boolean {
  const status = (event.status || '').toLowerCase()
  if (status === 'canceled' || status === 'cancelled') return true
  const text = `${event.subtitle || ''} ${event.title || ''}`.trim().toLowerCase()
  return text.startsWith('агент уже выполняется')
}

function meetingToBlock(meeting: MeetingEvent, index: number): TodayPlanBlock | null {
  const start = parseMeetingTime(meeting.start)
  const end = parseMeetingTime(meeting.end)
  if (!start) return null
  const endStamp = end && end > start ? end : new Date(start.getTime() + 60 * 60 * 1000)
  const location = (meeting.location || '').trim()
  return {
    id: `meet:${meeting.id}:${meeting.start || index}`,
    startHour: decimalHour(start),
    endHour: decimalHour(endStamp),
    title: meeting.subject,
    subtitle: location || undefined,
    tone: MEETING_TONES[index % MEETING_TONES.length],
    who: 'employee',
    kind: 'meet',
    lane: 'meetings',
    detail: {
      timeRange: formatTimeRange(start, endStamp),
      typeLabel: 'Совещание',
      location: location || undefined,
      format: meetingFormatHint(location),
      organizer: (meeting.organizer || '').trim() || undefined,
      participants: (meeting.attendees || '').trim() || undefined
    }
  }
}

function agentEventToBlock(
  event: CalendarEvent,
  agentTitle: string,
  index: number
): TodayPlanBlock | null {
  const start = parseIso(event.startAt)
  if (!start) return null
  const end = new Date(start.getTime() + 60 * 60 * 1000)
  const title = (event.subtitle || event.title || agentTitle || 'Запуск агента').trim()
  const displayTitle = title === agentTitle ? 'Запуск агента' : title
  const status = (event.status || '').trim()
  const source = (event.source || '').trim()
  const runId = (event.runId || '').trim()
  return {
    id: `ai:${event.id || event.runId || `${event.workflowId}-${event.startAt}`}`,
    startHour: decimalHour(start),
    endHour: decimalHour(end),
    title: displayTitle,
    subtitle: agentTitle,
    tone: AI_TONES[index % AI_TONES.length],
    who: 'ai',
    kind: 'reg',
    lane: 'ai',
    detail: {
      timeRange: formatTimeRange(start, end),
      typeLabel: 'Запуск ИИ-агента',
      agentName: agentTitle,
      status: status || undefined,
      source: source || undefined,
      workflowId: event.workflowId || undefined,
      runId: runId || undefined,
      note: (event.title || '').trim() && event.title !== displayTitle ? event.title : undefined
    }
  }
}

function nextRunToBlock(
  workflowId: string,
  nextRunAt: string,
  agentTitle: string,
  index: number
): TodayPlanBlock | null {
  const start = parseIso(nextRunAt)
  if (!start) return null
  const end = new Date(start.getTime() + 60 * 60 * 1000)
  return {
    id: `ai-next:${workflowId}-${nextRunAt}`,
    startHour: decimalHour(start),
    endHour: decimalHour(end),
    title: agentTitle || 'ИИ-агент',
    subtitle: 'Плановый запуск',
    tone: AI_TONES[index % AI_TONES.length],
    who: 'ai',
    kind: 'reg',
    lane: 'ai',
    detail: {
      timeRange: formatTimeRange(start, end),
      typeLabel: 'Плановый запуск ИИ-агента',
      agentName: agentTitle || 'ИИ-агент',
      workflowId,
      note: 'Запуск по расписанию агента'
    }
  }
}

function aiBlocksForDay(board: WorkflowBoard, periodDay: Date): TodayPlanBlock[] {
  const workflows = board.agents.filter((item) => item.kind === 'workflow')
  const titleById = new Map(workflows.map((agent) => [agent.id, agent.title || 'ИИ-агент']))
  const dayEvents = board.events.filter((event) => {
    if (isNoiseBoardEvent(event)) return false
    const stamp = parseIso(event.startAt)
    return stamp ? isOnLocalDay(stamp, periodDay) : false
  })

  const blocks: TodayPlanBlock[] = []
  const seen = new Set<string>()

  dayEvents.forEach((event, index) => {
    const block = agentEventToBlock(event, titleById.get(event.workflowId) || 'ИИ-агент', index)
    if (!block) return
    const key = `${event.workflowId}:${Math.floor(block.startHour * 60)}`
    if (seen.has(key)) return
    seen.add(key)
    blocks.push(block)
  })

  let slot = dayEvents.length
  for (const agent of workflows) {
    const next = parseIso(agent.nextRunAt || '')
    if (!next || !isOnLocalDay(next, periodDay)) continue
    const key = `${agent.id}:${Math.floor(decimalHour(next) * 60)}`
    if (seen.has(key)) continue
    seen.add(key)
    const block = nextRunToBlock(agent.id, agent.nextRunAt, agent.title, slot)
    if (block) blocks.push(block)
    slot += 1
  }

  return blocks.sort((a, b) => a.startHour - b.startHour)
}

export interface TodayPlanTimelineState {
  loading: boolean
  meetingsError: string
  meetingBlocks: TodayPlanBlock[]
  aiBlocks: TodayPlanBlock[]
  lunchBlock: TodayPlanBlock
}

export function useTodayPlanTimeline(
  periodDay: Date,
  options: { userId: string; fio: string }
): TodayPlanTimelineState {
  const { userId, fio } = options
  const { board, loading: boardLoading } = useWorkplaceData(
    userId ? { userId, fio } : null
  )

  const [meetingsLoading, setMeetingsLoading] = useState(true)
  const [meetingsError, setMeetingsError] = useState('')
  const [meetings, setMeetings] = useState<MeetingEvent[]>([])

  const dayKey = `${periodDay.getFullYear()}-${periodDay.getMonth()}-${periodDay.getDate()}`
  const generation = useGridRefreshGeneration()

  useEffect(() => {
    let alive = true
    const cacheKey = `today-plan-meetings:${userId}:${dayKey}`
    if (!shouldRunGridFetch(cacheKey, generation)) {
      const cached = readGridCache<{ meetings: MeetingEvent[]; error: string }>(cacheKey)
      if (cached) {
        setMeetings(cached.meetings)
        setMeetingsError(cached.error)
        setMeetingsLoading(false)
        return
      }
    }
    const hadCache = Boolean(readGridCache<{ meetings: MeetingEvent[]; error: string }>(cacheKey))
    if (!hadCache) setMeetingsLoading(true)
    setMeetingsError('')
    void ensureOutlookMeetings('day', periodDay, { owner: fio })
      .then((res) => {
        if (!alive) return
        if (!res.ok) {
          const errText = res.error || 'Outlook недоступен'
          setMeetings([])
          setMeetingsError(errText)
          writeGridCache(cacheKey, { meetings: [], error: errText })
          return
        }
        setMeetings(res.meetings)
        writeGridCache(cacheKey, { meetings: res.meetings, error: '' })
      })
      .catch((err) => {
        if (!alive) return
        setMeetings([])
        const errText = err instanceof Error ? err.message : 'Ошибка календаря'
        setMeetingsError(errText)
        writeGridCache(cacheKey, { meetings: [], error: errText })
      })
      .finally(() => {
        if (alive) setMeetingsLoading(false)
      })
    return () => {
      alive = false
    }
  }, [dayKey, fio, generation, periodDay, userId])

  const stableMeetingsRef = useRef<TodayPlanBlock[]>([])
  const stableAiRef = useRef<TodayPlanBlock[]>([])

  return useMemo(() => {
    const loading = meetingsLoading || boardLoading
    const onDay = dedupeMeetingEvents(
      meetings.filter((item) => {
        const start = parseMeetingTime(item.start)
        return start ? isOnLocalDay(start, periodDay) : false
      })
    )

    let meetingBlocks = onDay
      .map((meeting, index) => meetingToBlock(meeting, index))
      .filter((item): item is TodayPlanBlock => item !== null)
      .sort((a, b) => a.startHour - b.startHour)

    let aiBlocks = aiBlocksForDay(board, periodDay)

    if (TODAY_PLAN_PREFER_MOCKS) {
      meetingBlocks = TODAY_PLAN_MEETING_MOCKS
      aiBlocks = TODAY_PLAN_AI_MOCKS
    } else {
      if (!meetingBlocks.length) meetingBlocks = TODAY_PLAN_MEETING_MOCKS
      if (!aiBlocks.length) aiBlocks = TODAY_PLAN_AI_MOCKS
      if (loading) {
        if (!meetingBlocks.length && stableMeetingsRef.current.length) {
          meetingBlocks = stableMeetingsRef.current
        }
        if (!aiBlocks.length && stableAiRef.current.length) {
          aiBlocks = stableAiRef.current
        }
      }
    }

    if (meetingBlocks.length) stableMeetingsRef.current = meetingBlocks
    if (aiBlocks.length) stableAiRef.current = aiBlocks

    const usingPlanMocks =
      TODAY_PLAN_PREFER_MOCKS || meetingBlocks.every((block) => block.id.startsWith('mock-'))

    return {
      loading: TODAY_PLAN_PREFER_MOCKS ? false : loading,
      meetingsError: usingPlanMocks ? '' : meetingsError,
      meetingBlocks,
      aiBlocks,
      lunchBlock: TODAY_LUNCH_BLOCK
    }
  }, [board, boardLoading, meetings, meetingsError, meetingsLoading, periodDay, dayKey])
}
