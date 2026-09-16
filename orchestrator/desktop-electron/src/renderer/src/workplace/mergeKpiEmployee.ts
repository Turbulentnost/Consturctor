import type { MeetingEvent } from '../utils/outlookMeetings'
import { parseMeetingTime } from '../utils/outlookMeetings'
import type { SpecTaskRow } from './specV04DemoData'
import type { WorkflowBoard } from '../api/types'
import {
  boardRunTotalsInPeriod,
  buildKpiAgentsFromBoard,
  buildWorkloadCompareFromSources
} from './buildKpiWorkplaceLive'
import type {
  WorkplaceKpiAgentRow,
  WorkplaceKpiCard,
  WorkplaceKpiDashboard,
  WorkplaceKpiDynamics,
  WorkplaceKpiEmployeeMetric,
  WorkplaceKpiProblemZone
} from './workplaceKpiTypes'

export type KpiPeriodSources = {
  erpTasks: SpecTaskRow[]
  meetings: MeetingEvent[]
  regDone: number
  regTotal: number
  mailCount?: number
}

export type KpiEmployeeSnapshot = {
  hasData: boolean
  completionPct: number
  slaPct: number
  quality: number
  loadPct: number
  done: number
  total: number
  slaDone: number
  slaTotal: number
  tasksPerWeek: number
  meetPerWeek: number
  remainingWeekHours: number
  hoursPerWorkDay: number
  sparkTasks: number[]
  sparkSla: number[]
  sparkQuality: number[]
  sparkLoad: number[]
  xLabels: string[]
}

function parseDayBound(iso: string, end: boolean): Date {
  const d = new Date(`${iso.trim()}T${end ? '23:59:59' : '00:00:00'}`)
  return d
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

export function eachDay(from: string, to: string): Date[] {
  const lo = parseDayBound(from, false)
  const hi = parseDayBound(to, true)
  const start = lo <= hi ? lo : hi
  const end = lo <= hi ? hi : lo
  const out: Date[] = []
  const cursor = new Date(start)
  cursor.setHours(12, 0, 0, 0)
  while (cursor <= end) {
    out.push(new Date(cursor))
    cursor.setDate(cursor.getDate() + 1)
  }
  return out
}

function formatDayLabel(d: Date): string {
  return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}`
}

export function toIsoDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export type KpiDailyMetricSyncRow = { day: string; tasksPct: number; slaPct: number }

export function buildKpiDailySyncPayload(from: string, to: string, snap: KpiEmployeeSnapshot): KpiDailyMetricSyncRow[] {
  const days = eachDay(from, to)
  return days.map((d, i) => ({
    day: toIsoDate(d),
    tasksPct: snap.sparkTasks[i] ?? 0,
    slaPct: snap.sparkSla[i] ?? 0
  }))
}

export function taskInPeriod(task: SpecTaskRow, from: string, to: string): boolean {
  const due = parseTaskDue(task.deadline)
  if (!due) return true
  const lo = parseDayBound(from, false)
  const hi = parseDayBound(to, true)
  return due >= lo && due <= hi
}

export function meetingHoursInPeriod(meetings: MeetingEvent[], from: string, to: string): number {
  const lo = parseDayBound(from, false).getTime()
  const hi = parseDayBound(to, true).getTime()
  let hours = 0
  for (const m of meetings) {
    const start = parseMeetingTime(m.start)
    const end = parseMeetingTime(m.end)
    if (!start) continue
    const t = start.getTime()
    if (t < lo || t > hi) continue
    if (end && end > start) {
      hours += (end.getTime() - start.getTime()) / 3_600_000
    } else {
      hours += 1
    }
  }
  return hours
}

function workWeekHours(): number {
  const raw = String(import.meta.env.VITE_KPI_WORK_WEEK_HOURS ?? '40').trim()
  const n = Number(raw)
  return Number.isFinite(n) && n > 0 ? n : 40
}

function hoursPerWorkDay(): number {
  return workWeekHours() / 5
}

/** Оставшиеся рабочие часы от refDay (вкл.) до пятницы той же недели (пн–пт). */
export function remainingWorkWeekHours(refDay: Date = new Date()): number {
  const day = new Date(refDay)
  day.setHours(12, 0, 0, 0)
  const dow = day.getDay()
  if (dow === 0 || dow === 6) return 0
  const daysLeft = 6 - dow
  return Math.round(daysLeft * hoursPerWorkDay())
}

function pct(done: number, total: number): number {
  if (total <= 0) return 0
  return Math.round((done / total) * 100)
}

export function qualityFromPct(p: number): number {
  return Math.round((1 + 4 * (Math.max(0, Math.min(100, p)) / 100)) * 10) / 10
}

export function workloadPct(tasksPerWeek: number, meetingHoursPerWeek: number, remainingHours: number): number {
  const a = tasksPerWeek
  const b = meetingHoursPerWeek
  const c = Math.max(1, remainingHours)
  return Math.min(100, Math.max(0, Math.round((a * 0.9 * b * 40) / c)))
}

function cutoffThroughDay(day: Date): Date {
  const dayEnd = new Date(day)
  dayEnd.setHours(23, 59, 59, 999)
  const now = new Date()
  return dayEnd > now ? now : dayEnd
}

/** Кумулятивное выполнение за период (те же числитель/знаменатель, что и KPI «2 из 9»). */
function cumulativeCompletionSeries(
  periodTasks: SpecTaskRow[],
  regDone: number,
  regTotal: number,
  days: Date[]
): number[] {
  const total = periodTasks.length + regTotal
  if (total <= 0) return days.map(() => 0)
  return days.map((day) => {
    const cutoff = cutoffThroughDay(day)
    let erpDone = 0
    for (const task of periodTasks) {
      if (task.status !== 'Выполнена') continue
      const due = parseTaskDue(task.deadline)
      if (!due || due <= cutoff) erpDone += 1
    }
    return pct(erpDone + regDone, total)
  })
}

/** Кумулятивное SLA — только задачи с дедлайном (как snap.slaPct). */
function cumulativeSlaSeries(periodTasks: SpecTaskRow[], days: Date[], fallbackPct: number): number[] {
  const withDue = periodTasks.filter((t) => parseTaskDue(t.deadline))
  if (!withDue.length) return days.map(() => fallbackPct)
  return days.map((day) => {
    const cutoff = cutoffThroughDay(day)
    let ok = 0
    for (const task of withDue) {
      const due = parseTaskDue(task.deadline)
      if (!due || due > cutoff) continue
      if (task.status === 'Выполнена' && !task.urgent) ok += 1
    }
    return pct(ok, withDue.length)
  })
}

function syncLastPoint(points: number[], value: number): number[] {
  if (!points.length) return [value]
  const next = [...points]
  next[next.length - 1] = value
  return next
}

function trendFromSparkline(points: number[], isQuality: boolean): { delta: string; up: boolean } {
  if (points.length < 2) return { delta: '', up: true }
  const first = points[0]
  const last = points[points.length - 1]
  const diff = last - first
  if (isQuality) {
    return { delta: `${diff >= 0 ? '+' : ''}${Math.round(diff * 10) / 10}`, up: diff >= 0 }
  }
  return { delta: `${diff >= 0 ? '+' : ''}${Math.round(diff)}%`, up: diff >= 0 }
}

function emptyKpiEmployeeSnapshot(from: string, to: string): KpiEmployeeSnapshot {
  const days = eachDay(from, to)
  const zeroLine = days.map(() => 0)
  const q0 = qualityFromPct(0)
  return {
    hasData: false,
    completionPct: 0,
    slaPct: 0,
    quality: q0,
    loadPct: 0,
    done: 0,
    total: 0,
    slaDone: 0,
    slaTotal: 0,
    tasksPerWeek: 0,
    meetPerWeek: meetingHoursInPeriod([], from, to) / Math.max(1, days.length / 7),
    remainingWeekHours: remainingWorkWeekHours(new Date()),
    hoursPerWorkDay: hoursPerWorkDay(),
    sparkTasks: [...zeroLine],
    sparkSla: [...zeroLine],
    sparkQuality: days.map(() => q0),
    sparkLoad: [...zeroLine],
    xLabels: days.map(formatDayLabel)
  }
}

export function computeKpiEmployeeSnapshot(
  sources: KpiPeriodSources,
  from: string,
  to: string
): KpiEmployeeSnapshot | null {
  const periodTasks = sources.erpTasks.filter((t) => taskInPeriod(t, from, to))
  const erpDone = periodTasks.filter((t) => t.status === 'Выполнена').length
  const erpTotal = periodTasks.length
  const total = erpTotal + sources.regTotal
  const done = erpDone + sources.regDone
  if (total <= 0) return null

  const completion = pct(done, total)
  const withDue = periodTasks.filter((t) => parseTaskDue(t.deadline))
  const slaDone = withDue.filter((t) => t.status === 'Выполнена' && !t.urgent).length
  const slaPct = withDue.length ? pct(slaDone, withDue.length) : completion
  const quality = qualityFromPct(completion)

  const days = eachDay(from, to)
  const dayCount = Math.max(1, days.length)
  const weeks = dayCount / 7
  const tasksPerWeek = Math.round(total / weeks)
  const meetHours = meetingHoursInPeriod(sources.meetings, from, to)
  const meetPerWeek = meetHours / weeks
  const remaining = remainingWorkWeekHours(new Date())
  const load = workloadPct(tasksPerWeek, meetPerWeek, remaining)

  let sparkTasks = cumulativeCompletionSeries(periodTasks, sources.regDone, sources.regTotal, days)
  sparkTasks = syncLastPoint(sparkTasks, completion)
  let sparkSla = cumulativeSlaSeries(periodTasks, days, completion)
  sparkSla = syncLastPoint(sparkSla, slaPct)
  const sparkQuality = sparkTasks.map((p) => qualityFromPct(p))
  let sparkLoad = days.map((day) =>
    workloadPct(tasksPerWeek, meetPerWeek, remainingWorkWeekHours(day))
  )
  sparkLoad = syncLastPoint(sparkLoad, load)

  return {
    hasData: true,
    completionPct: completion,
    slaPct,
    quality,
    loadPct: load,
    done,
    total,
    slaDone,
    slaTotal: withDue.length || total,
    tasksPerWeek,
    meetPerWeek,
    remainingWeekHours: remaining,
    hoursPerWorkDay: hoursPerWorkDay(),
    sparkTasks,
    sparkSla,
    sparkQuality,
    sparkLoad,
    xLabels: days.map(formatDayLabel)
  }
}

const TITLE_BY_ID: Record<string, string> = {
  tasks: 'Выполнение задач',
  sla: 'Соблюдение сроков',
  quality: 'Качество результатов',
  load: 'Загрузка'
}

const COLOR_BY_ID: Record<string, string> = {
  tasks: '#1565c0',
  sla: '#08745f',
  quality: '#7b1fa2',
  load: '#e8943a'
}

function buildEmployeeMetricsFromSnapshot(
  base: WorkplaceKpiEmployeeMetric[],
  snap: KpiEmployeeSnapshot
): WorkplaceKpiEmployeeMetric[] {
  const byId = Object.fromEntries(base.map((m) => [m.id, m])) as Record<string, WorkplaceKpiEmployeeMetric>

  const patch = (id: string, fields: Partial<WorkplaceKpiEmployeeMetric>): WorkplaceKpiEmployeeMetric => {
    const ref =
      byId[id] ??
      base[0] ?? {
        id,
        title: TITLE_BY_ID[id] ?? id,
        displayValue: '—',
        trendDelta: '',
        trendUp: true,
        trendPositive: true,
        footerText: '',
        sparklinePoints: [],
        sparklineColor: COLOR_BY_ID[id] ?? '#1565c0',
        source: 'reference' as const
      }
    return {
      ...ref,
      title: ref.title || TITLE_BY_ID[id] || id,
      sparklineColor: ref.sparklineColor || COLOR_BY_ID[id] || '#1565c0',
      ...fields,
      source: 'computed'
    }
  }

  const tTrend = trendFromSparkline(snap.sparkTasks, false)
  const slaTrend = trendFromSparkline(snap.sparkSla, false)
  const qTrend = trendFromSparkline(snap.sparkQuality, true)
  const loadTrend = trendFromSparkline(snap.sparkLoad, false)
  const remain = snap.remainingWeekHours

  return [
    patch('tasks', {
      displayValue: `${snap.completionPct}%`,
      footerText: `${snap.done} из ${snap.total} задач`,
      sparklinePoints: snap.sparkTasks,
      trendDelta: tTrend.delta,
      trendUp: tTrend.up,
      trendPositive: tTrend.up
    }),
    patch('sla', {
      displayValue: `${snap.slaPct}%`,
      footerText:
        snap.slaTotal !== snap.total
          ? `${snap.slaDone} из ${snap.slaTotal} задач`
          : `${snap.done} из ${snap.total} задач`,
      sparklinePoints: snap.sparkSla,
      trendDelta: slaTrend.delta,
      trendUp: slaTrend.up,
      trendPositive: slaTrend.up
    }),
    patch('quality', {
      displayValue: String(snap.quality),
      footerText: 'из 5.0 (по оценкам)',
      sparklinePoints: snap.sparkQuality,
      trendDelta: qTrend.delta,
      trendUp: qTrend.up,
      trendPositive: qTrend.up
    }),
    patch('load', {
      displayValue: `${snap.loadPct}%`,
      footerText:
        remain > 0
          ? `остаток ${remain} ч/нед (пн–пт)`
          : `неделя закрыта (пн–пт)`,
      sparklinePoints: snap.sparkLoad,
      trendDelta: loadTrend.delta,
      trendUp: loadTrend.up,
      trendPositive: false
    })
  ]
}

function dynamicsHasComputedSeries(dynamics: WorkplaceKpiDynamics | undefined): boolean {
  if (!dynamics || dynamics.source !== 'computed') return false
  return dynamics.series.some((s) => s.points.length > 0)
}

export function buildPeriodDynamics(
  snap: KpiEmployeeSnapshot,
  fallback: WorkplaceKpiDynamics
): WorkplaceKpiDynamics {
  return {
    title: fallback.title || 'Динамика показателей',
    xLabels: snap.xLabels.length ? snap.xLabels : fallback.xLabels,
    yMax: 100,
    series: [
      {
        id: 'tasks',
        label: 'Выполнение задач',
        color: '#e8943a',
        points: snap.sparkTasks
      },
      {
        id: 'sla',
        label: 'Соблюдение сроков',
        color: '#08745f',
        points: snap.sparkSla
      }
    ],
    source: 'computed'
  }
}

function avgAgentMetric(agents: WorkplaceKpiDashboard['agents'], key: 'completionPct' | 'automationPct'): number | null {
  const computed = agents.filter((a) => a.source === 'computed')
  const list = computed.length ? computed : agents
  if (!list.length) return null
  const sum = list.reduce((acc, row) => acc + row[key], 0)
  return Math.round(sum / list.length)
}

export type KpiTopSummary = {
  completionPct: number
  slaPct: number
  loadPct: number
  quality: number
  aiPct: number
  autoPct: number
  trendTasks: string
  trendSla: string
  trendLoad: string
  combinedTotal: number
  slaDenom: number
  agentCount: number
  aiRunUnits: number
}

/** Общие верхние KPI: 1C/регламенты + запуски ИИ за период (не копия панели «сотрудник»). */
export function computeKpiTopSummary(
  snap: KpiEmployeeSnapshot | null,
  agents: WorkplaceKpiAgentRow[],
  board: WorkflowBoard | null,
  from: string,
  to: string
): KpiTopSummary {
  const boardTotals = boardRunTotalsInPeriod(board, from, to)
  const aiUnits = boardTotals.finished || boardTotals.events
  const aiOk = boardTotals.ok

  const empDone = snap?.done ?? 0
  const empTotal = snap?.total ?? 0
  const empSlaDone = snap?.slaDone ?? 0
  const empSlaTotal = snap?.slaTotal ?? 0

  const combinedTotal = empTotal + aiUnits
  const combinedDone = empDone + aiOk
  const completionPct = pct(combinedDone, combinedTotal)

  const slaDenom = empSlaTotal + aiUnits
  const slaNum = empSlaDone + aiOk
  const slaPct = pct(slaNum, slaDenom)

  const aiPct =
    avgAgentMetric(agents, 'completionPct') ?? (aiUnits > 0 ? pct(aiOk, aiUnits) : combinedTotal ? completionPct : 0)
  const autoPct = avgAgentMetric(agents, 'automationPct') ?? 0

  const empLoad = snap?.loadPct ?? 0
  const agentLoadAvg = agents.length
    ? Math.round(agents.reduce((acc, row) => acc + row.loadPct, 0) / agents.length)
    : 0
  const loadParts: number[] = []
  if (empTotal > 0 || (snap?.meetPerWeek ?? 0) > 0) loadParts.push(empLoad)
  if (agents.length) loadParts.push(agentLoadAvg)
  const loadPct = loadParts.length
    ? Math.round(loadParts.reduce((a, b) => a + b, 0) / loadParts.length)
    : 0

  const quality = qualityFromPct(completionPct)

  const trendTasks =
    combinedTotal > 0
      ? `${combinedDone} из ${combinedTotal} · 1C ${empDone}/${empTotal} · ИИ ${aiOk}/${aiUnits}`
      : 'нет задач и запусков'

  const trendSla =
    slaDenom > 0 ? `${slaNum} из ${slaDenom} в срок` : trendTasks === 'нет задач и запусков' ? '—' : trendTasks

  const remain = snap?.remainingWeekHours ?? remainingWorkWeekHours(new Date())
  let trendLoad = ''
  if (loadParts.length > 1) trendLoad = `сотр. ${empLoad}% · ИИ ${agentLoadAvg}%`
  else if (empTotal > 0) trendLoad = remain > 0 ? `остаток ${remain} ч` : 'пн–пт закрыта'
  else if (agents.length) trendLoad = `сред. загрузка агентов ${agentLoadAvg}%`
  else trendLoad = '—'

  return {
    completionPct,
    slaPct,
    loadPct,
    quality,
    aiPct,
    autoPct,
    trendTasks,
    trendSla,
    trendLoad,
    combinedTotal,
    slaDenom,
    agentCount: agents.length,
    aiRunUnits: aiUnits
  }
}

function applyTopSummaryToCards(cards: WorkplaceKpiCard[], summary: KpiTopSummary): WorkplaceKpiCard[] {
  return cards.map((card) => {
    switch (card.id) {
      case 'tasks':
        return {
          ...card,
          displayValue: `${summary.completionPct}%`,
          progress: summary.completionPct,
          trend: summary.trendTasks,
          source: 'computed'
        }
      case 'sla':
        return {
          ...card,
          displayValue: `${summary.slaPct}%`,
          progress: summary.slaPct,
          trend: summary.trendSla,
          source: 'computed'
        }
      case 'load':
        return {
          ...card,
          displayValue: `${summary.loadPct}%`,
          progress: summary.loadPct,
          trend: summary.trendLoad,
          source: 'computed'
        }
      case 'quality':
        return {
          ...card,
          displayValue: String(summary.quality),
          trend: 'из 5 · сводно',
          ring: false,
          source: 'computed'
        }
      case 'ai':
        return {
          ...card,
          displayValue: `${summary.aiPct}%`,
          progress: summary.aiPct,
          trend: agentsTrendLabel(summary.aiPct, 'эффективность'),
          source: 'computed'
        }
      case 'auto':
        return {
          ...card,
          displayValue: `${summary.autoPct}%`,
          progress: summary.autoPct,
          trend: agentsTrendLabel(summary.autoPct, 'автоматизация'),
          source: 'computed'
        }
      default:
        return card
    }
  })
}

function agentsTrendLabel(pctValue: number, kind: string): string {
  if (pctValue <= 0) return `нет данных по ${kind}`
  return `сред. по агентам`
}

const ZONE_REC: Record<string, string> = {
  low_completion: 'Ускорить закрытие задач, перераспределить нагрузку',
  low_sla: 'Сократить время ответа, перераспределить задачи',
  high_load: 'Пик нагрузки ср–чт, перенести встречи',
  low_ai: 'Проверить сценарии агентов, упростить процесс',
  low_automation: 'Добавить шаблоны и сценарии',
  quality_drop: 'Проверить данные, добавить контроль ИИ'
}

const KPI_TILE_TARGETS = {
  tasksMin: 90,
  slaMin: 90,
  loadMax: 50,
  aiMin: 90,
  autoMin: 60,
  qualityMin: 4.5
} as const

function fmtDevPct(delta: number): string {
  return `${delta >= 0 ? '+' : ''}${Math.round(delta)}%`
}

function fmtDevQuality(delta: number): string {
  return `${delta >= 0 ? '+' : ''}${Math.round(delta * 10) / 10}`
}

/** Только сводные KPI с верхних плиток, если показатель вне целевого коридора. */
function buildProblemZonesFromTopSummary(
  summary: KpiTopSummary,
  cards: WorkplaceKpiCard[]
): WorkplaceKpiProblemZone[] {
  const label = (id: string, fallback: string): string =>
    cards.find((c) => c.id === id)?.label?.trim() || fallback

  const zones: WorkplaceKpiProblemZone[] = []
  let seq = 0

  const push = ({ idPrefix, ...zone }: Omit<WorkplaceKpiProblemZone, 'id'> & { idPrefix: string }): void => {
    seq += 1
    zones.push({
      ...zone,
      id: `${idPrefix}-${seq}`,
      process: 'Сводно',
      zone: 'Сводно',
      status: 'Требует внимания',
      statusTone: 'orange',
      source: 'computed'
    })
  }

  if (summary.combinedTotal > 0 && summary.completionPct < KPI_TILE_TARGETS.tasksMin) {
    const dev = summary.completionPct - KPI_TILE_TARGETS.tasksMin
    const title = label('tasks', 'Выполнение задач')
    push({
      idPrefix: 'tile-tasks',
      typeId: 'low_completion',
      typeLabel: title,
      description: summary.trendTasks,
      indicator: title,
      currentValue: `${summary.completionPct}%`,
      targetValue: `≥ ${KPI_TILE_TARGETS.tasksMin}%`,
      deviation: fmtDevPct(dev),
      metric: title,
      value: `${summary.completionPct}%`,
      severity: summary.completionPct < 75 ? 'red' : 'orange',
      recommendation: ZONE_REC.low_completion
    })
  }

  if (summary.slaDenom > 0 && summary.slaPct < KPI_TILE_TARGETS.slaMin) {
    const dev = summary.slaPct - KPI_TILE_TARGETS.slaMin
    const title = label('sla', 'SLA')
    push({
      idPrefix: 'tile-sla',
      typeId: 'low_sla',
      typeLabel: title,
      description: summary.trendSla,
      indicator: title,
      currentValue: `${summary.slaPct}%`,
      targetValue: `≥ ${KPI_TILE_TARGETS.slaMin}%`,
      deviation: fmtDevPct(dev),
      metric: title,
      value: `${summary.slaPct}%`,
      severity: summary.slaPct < 80 ? 'red' : 'orange',
      recommendation: ZONE_REC.low_sla
    })
  }

  const loadHasBasis = summary.combinedTotal > 0 || summary.agentCount > 0
  if (loadHasBasis && summary.loadPct > KPI_TILE_TARGETS.loadMax) {
    const dev = summary.loadPct - KPI_TILE_TARGETS.loadMax
    const title = label('load', 'Загрузка')
    push({
      idPrefix: 'tile-load',
      typeId: 'high_load',
      typeLabel: title,
      description: summary.trendLoad,
      indicator: title,
      currentValue: `${summary.loadPct}%`,
      targetValue: `≤ ${KPI_TILE_TARGETS.loadMax}%`,
      deviation: fmtDevPct(dev),
      metric: title,
      value: `${summary.loadPct}%`,
      severity: summary.loadPct > 70 ? 'red' : 'orange',
      recommendation: ZONE_REC.high_load
    })
  }

  if ((summary.agentCount > 0 || summary.aiRunUnits > 0) && summary.aiPct < KPI_TILE_TARGETS.aiMin) {
    const dev = summary.aiPct - KPI_TILE_TARGETS.aiMin
    const title = label('ai', 'Эффективность ИИ')
    push({
      idPrefix: 'tile-ai',
      typeId: 'low_ai',
      typeLabel: title,
      description: `${title}: ${summary.aiPct}%`,
      indicator: title,
      currentValue: `${summary.aiPct}%`,
      targetValue: `≥ ${KPI_TILE_TARGETS.aiMin}%`,
      deviation: fmtDevPct(dev),
      metric: title,
      value: `${summary.aiPct}%`,
      severity: summary.aiPct < 75 ? 'red' : 'orange',
      recommendation: ZONE_REC.low_ai
    })
  }

  if (summary.agentCount > 0 && summary.autoPct < KPI_TILE_TARGETS.autoMin) {
    const dev = summary.autoPct - KPI_TILE_TARGETS.autoMin
    const title = label('auto', 'Доля автоматизации')
    push({
      idPrefix: 'tile-auto',
      typeId: 'low_automation',
      typeLabel: title,
      description: `${title}: ${summary.autoPct}%`,
      indicator: title,
      currentValue: `${summary.autoPct}%`,
      targetValue: `≥ ${KPI_TILE_TARGETS.autoMin}%`,
      deviation: fmtDevPct(dev),
      metric: title,
      value: `${summary.autoPct}%`,
      severity: summary.autoPct < 45 ? 'red' : 'orange',
      recommendation: ZONE_REC.low_automation
    })
  }

  if (summary.combinedTotal > 0 && summary.quality < KPI_TILE_TARGETS.qualityMin) {
    const dev = summary.quality - KPI_TILE_TARGETS.qualityMin
    const title = label('quality', 'Качество')
    push({
      idPrefix: 'tile-quality',
      typeId: 'quality_drop',
      typeLabel: title,
      description: `${title}: ${summary.quality}`,
      indicator: title,
      currentValue: String(summary.quality),
      targetValue: `≥ ${KPI_TILE_TARGETS.qualityMin}`,
      deviation: fmtDevQuality(dev),
      metric: title,
      value: String(summary.quality),
      severity: 'orange',
      recommendation: ZONE_REC.quality_drop
    })
  }

  return zones
}

export function mergeEmployeeKpiAndZones(
  dashboard: WorkplaceKpiDashboard | null,
  sources: KpiPeriodSources | null,
  from: string,
  to: string,
  board: WorkflowBoard | null = null
): WorkplaceKpiDashboard | null {
  if (!dashboard) return null

  const liveAgents = board ? buildKpiAgentsFromBoard(board, from, to) : []
  const agentsFromBoard = liveAgents.length > 0
  const agentsFromApi = dashboard.agents.filter((a) => a.source === 'computed')
  const agents = agentsFromBoard ? liveAgents : agentsFromApi.length ? agentsFromApi : []

  const workloadCompare = sources
    ? buildWorkloadCompareFromSources(sources, board, from, to)
    : dashboard.workloadCompare

  if (!sources) {
    return { ...dashboard, agents, workloadCompare }
  }

  const snap = computeKpiEmployeeSnapshot(sources, from, to)

  const topSummary = computeKpiTopSummary(snap, agents, board, from, to)
  const cards = applyTopSummaryToCards(dashboard.cards, topSummary)
  const problemZones = buildProblemZonesFromTopSummary(topSummary, cards)

  if (!snap) {
    const emptySnap = emptyKpiEmployeeSnapshot(from, to)
    const employeeKpi = dashboard.employeeKpi.some((m) => m.source === 'computed')
      ? dashboard.employeeKpi
      : buildEmployeeMetricsFromSnapshot(dashboard.employeeKpi, emptySnap)
    const dynamics = dynamicsHasComputedSeries(dashboard.dynamics)
      ? dashboard.dynamics
      : buildPeriodDynamics(emptySnap, dashboard.dynamics)
    return {
      ...dashboard,
      agents,
      cards,
      employeeKpi,
      dynamics,
      problemZones,
      workloadCompare
    }
  }

  const employeeKpi = buildEmployeeMetricsFromSnapshot(dashboard.employeeKpi, snap)
  const dynamics = dynamicsHasComputedSeries(dashboard.dynamics)
    ? dashboard.dynamics
    : buildPeriodDynamics(snap, dashboard.dynamics)

  return {
    ...dashboard,
    agents,
    cards,
    employeeKpi,
    dynamics,
    problemZones,
    workloadCompare
  }
}
