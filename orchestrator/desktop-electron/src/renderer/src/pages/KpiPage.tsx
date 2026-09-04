import { useEffect, useMemo, useRef, useState } from 'react'
import { agentClient } from '../api/agent'
import { api } from '../api/client'
import { KpiTileCard } from '../components/KpiTileCard'
import type { AgentKpi, AgentRunHistoryItem, BoardAgent, KpiTile } from '../api/types'
import type { FeedItem } from '../components/agentfeed/types'
import { deriveLatestOutput, explainBackgroundEntryKey, useRuns } from '../store/runs'
import { isLiveRunState } from '../store/liveRun'
import { localizeStatusText } from '../utils/statusText'
import {
  CRITICAL_HUMAN_DELAY_MIN,
  EXPLAIN_BAN_MS,
  buildExplainPrompt,
  explainBanRemainingMs,
  formatBanRemaining,
  loadEffectiveExplainRecord,
  parseExplainVerdict,
  sanitizeExplainReason,
  saveExplainRecord,
  type HumanDelayExplainRecord,
  type HumanDelayVerdict
} from '../workplace/humanDelayExplain'
import { liveTotals } from '../workplace/runTiming'
import {
  buildKpiCsv,
  buildKpiPdfHtml,
  buildKpiXlsx,
  bytesToBase64,
  type KpiExportRow
} from './kpiExport'

const EXPLAIN_EVAL_TIMEOUT_MS = 3 * 60 * 1000

function feedItemText(item: FeedItem): string {
  if (item.kind === 'result') return item.text || ''
  if (item.kind === 'message' && item.role === 'agent') return item.text || ''
  if (item.kind === 'system') return item.text || ''
  return ''
}

/** Prefer the newest feed chunk that already contains a verdict JSON. */
function extractExplainAnswerFromFeed(items: FeedItem[] | undefined): string {
  if (!items?.length) return ''
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const text = feedItemText(items[i]).trim()
    if (text && parseExplainVerdict(text)) return text
  }
  return deriveLatestOutput(items)
}

const iconCalendar = new URL('../../../temp/KPI/calendar.png', import.meta.url).href
const iconActive = new URL('../../../temp/KPI/ChatGPT Image 26 авг. 2026 г., 11_22_41.png', import.meta.url).href
const iconRuns = new URL('../../../temp/KPI/ChatGPT Image 26 авг. 2026 г., 11_23_18.png', import.meta.url).href
const iconSuccess = new URL('../../../temp/KPI/ChatGPT Image 26 авг. 2026 г., 11_23_35.png', import.meta.url).href
const iconAttention = new URL('../../../temp/KPI/3ee02669-15be-4acb-9537-89da251eaa83.png', import.meta.url).href
const robotGreen = new URL('../../../temp/KPI/ChatGPT Image 26 авг. 2026 г., 11_28_22.png', import.meta.url).href
const robotBlue = new URL('../../../temp/KPI/ChatGPT Image 26 авг. 2026 г., 11_28_29.png', import.meta.url).href
const robotYellow = new URL('../../../temp/KPI/9421cf0b-b18d-4568-9e74-cf99d542b73b.png', import.meta.url).href
const robotRed = new URL('../../../temp/KPI/59561baa-bbdc-4f74-8cf4-d78179bae59d.png', import.meta.url).href

const HISTORY_KEY = 'constructor.kpi.snapshots'

type TabKey = 'overview' | 'agents' | 'interaction'
type RangeKey = '7' | '30' | '90'
type PeriodKind = 'range' | 'date' | 'month'
type AgentFilter = 'all' | 'deviations' | 'critical'
type DynamicsMode = 'runs' | 'success'

interface PeriodState {
  kind: PeriodKind
  range: RangeKey
  date: string
  month: string
}

interface AgentKpiView {
  agent: BoardAgent
  runs: AgentRunHistoryItem[]
  total: number
  successful: number
  errors: number
  attention: boolean
  critical: boolean
  successRate: number
  timelinessRate: number
  completeness: number
  averageMinutes: number | null
  score: number
  uncalculated: boolean
  lastCalculatedAt: string
  dailySuccess: number[]
  dailyScore: number[]
  kpi: AgentKpi | null
}

interface KpiSnapshot {
  date: string
  agentId: string
  score: number
  successRate: number
  timelinessRate: number
  total: number
  errors: number
  averageMinutes: number | null
}

const RANGE_LABELS: Record<RangeKey, string> = {
  '7': 'Последние 7 дней',
  '30': 'Последние 30 дней',
  '90': 'Последние 90 дней'
}

function todayKey(): string {
  return dayKey(Date.now())
}

function monthKey(timestamp = Date.now()): string {
  const date = new Date(timestamp)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
}

function defaultPeriod(): PeriodState {
  return { kind: 'range', range: '30', date: todayKey(), month: monthKey() }
}

function isSuccess(status: string): boolean {
  const value = status.toLowerCase()
  return ['ok', 'success', 'successful', 'completed', 'done', 'ready'].some((item) => value.includes(item))
}

function isErrorStatus(status: string): boolean {
  const value = status.toLowerCase()
  return ['error', 'fail', 'failed'].some((item) => value.includes(item))
}

function isAttentionStatus(status: string): boolean {
  const value = status.toLowerCase()
  return ['attention', 'approval', 'confirm', 'pending', 'wait', 'error', 'fail', 'stuck'].some((item) =>
    value.includes(item)
  )
}

function runTime(run: AgentRunHistoryItem): number {
  const raw = run.startedAt || run.finishedAt
  const time = Date.parse(raw || '')
  return Number.isFinite(time) ? time : 0
}

function runDurationMinutes(run: AgentRunHistoryItem): number | null {
  const started = Date.parse(run.startedAt || '')
  const finished = Date.parse(run.finishedAt || '')
  if (!Number.isFinite(started) || !Number.isFinite(finished) || finished <= started) return null
  return Math.max(1, Math.round((finished - started) / 60000))
}

function dayKey(timestamp: number): string {
  const date = new Date(timestamp)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function enumerateDays(from: number, to: number): string[] {
  const out: string[] = []
  const cursor = new Date(from)
  cursor.setHours(0, 0, 0, 0)
  const end = new Date(to)
  end.setHours(0, 0, 0, 0)
  while (cursor.getTime() <= end.getTime()) {
    out.push(dayKey(cursor.getTime()))
    cursor.setDate(cursor.getDate() + 1)
  }
  return out
}

function periodWindow(period: PeriodState): { from: number; to: number; days: string[] } {
  if (period.kind === 'date') {
    const start = new Date(`${period.date}T00:00:00`)
    const from = Number.isNaN(start.getTime()) ? Date.now() : start.getTime()
    return { from, to: from + 86400000 - 1, days: [dayKey(from)] }
  }
  if (period.kind === 'month') {
    const [year, month] = period.month.split('-').map(Number)
    const start = new Date(year, (month || 1) - 1, 1)
    const end = new Date(year, month || 1, 0, 23, 59, 59, 999)
    return { from: start.getTime(), to: end.getTime(), days: enumerateDays(start.getTime(), end.getTime()) }
  }
  const days = Number(period.range)
  const end = new Date()
  end.setHours(23, 59, 59, 999)
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  start.setDate(start.getDate() - (days - 1))
  return { from: start.getTime(), to: end.getTime(), days: enumerateDays(start.getTime(), end.getTime()) }
}

function inWindow(run: AgentRunHistoryItem, from: number, to: number): boolean {
  const time = runTime(run)
  return time > 0 && time >= from && time <= to
}

function chartPoints(values: number[], width: number, height: number): string {
  const max = Math.max(1, ...values)
  const step = values.length > 1 ? width / (values.length - 1) : width
  return values
    .map((value, index) => {
      const x = index * step
      const y = height - (value / max) * (height - 10) - 5
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

function Sparkline({
  values,
  tone = 'green'
}: {
  values: number[]
  tone?: 'green' | 'orange' | 'red' | 'grey'
}): React.JSX.Element {
  const stroke = tone === 'green' ? '#08745f' : tone === 'orange' ? '#e67e22' : tone === 'red' ? '#c0392b' : '#9aa7a2'
  return (
    <svg className="kpi-spark" viewBox="0 0 100 32" preserveAspectRatio="none">
      <polyline points={chartPoints(values, 100, 32)} fill="none" stroke={stroke} strokeWidth="2.4" />
    </svg>
  )
}

function RateBar({ value, tone = 'green' }: { value: number; tone?: 'green' | 'orange' | 'red' }): React.JSX.Element {
  const normalized = Math.max(0, Math.min(100, value))
  return (
    <span className={`kpi-rate ${tone}`}>
      <span style={{ width: `${normalized}%` }} />
    </span>
  )
}

function Donut({ score }: { score: number }): React.JSX.Element {
  const normalized = Math.max(0, Math.min(100, score))
  return (
    <div
      className="kpi-donut"
      style={{ background: `conic-gradient(#08745f ${normalized * 3.6}deg, #edf3f0 0deg)` }}
    >
      <div>
        <strong>{normalized}</strong>
        <span>из 100</span>
      </div>
    </div>
  )
}

function robotFor(index: number, attention: boolean, critical = false, uncalculated = false): string {
  if (uncalculated) return robotBlue
  if (critical) return robotRed
  if (attention) return robotYellow
  return [robotGreen, robotBlue, robotYellow, robotGreen][index % 4]
}

function statusLabel(row: AgentKpiView): string {
  if (row.uncalculated) return 'Нет расчёта'
  if (row.critical) return 'Ошибка'
  if (row.attention) return 'Внимание'
  return 'Работает'
}

function statusTone(row: AgentKpiView): 'green' | 'orange' | 'red' | 'grey' {
  if (row.uncalculated) return 'grey'
  if (row.critical) return 'red'
  if (row.attention) return 'orange'
  return 'green'
}

function rowTone(value: number): 'green' | 'orange' | 'red' {
  if (value >= 90) return 'green'
  if (value >= 75) return 'orange'
  return 'red'
}

function formatAverage(minutes: number | null): string {
  if (minutes == null) return '—'
  if (minutes < 60) return `${minutes} мин`
  const hours = minutes / 60
  return `${hours % 1 === 0 ? hours.toFixed(0) : hours.toFixed(1)} ч`
}

function formatMinutes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 мин'
  if (value < 60) return `${Math.round(value)} мин`
  const hours = value / 60
  return `${hours % 1 === 0 ? hours.toFixed(0) : hours.toFixed(1)} ч`
}

function averageMinutesFromMs(values: number[]): number {
  if (!values.length) return 0
  const minutes = values.reduce((sum, value) => sum + Math.max(0, value) / 60000, 0) / values.length
  return Math.max(0, Math.round(minutes))
}

/** Average across all samples, including zero delays (show 0 when no waits). */
function averageResponseMinutes(values: number[]): number {
  if (!values.length) return 0
  return averageMinutesFromMs(values)
}

function isZhalybinUser(userId: string, fio: string): boolean {
  const id = (userId || '').toUpperCase()
  const name = (fio || '').toLowerCase()
  return id.includes('ZHALYBIN') || name.includes('жалыбин')
}

function isSmartAssignmentAgent(title: string): boolean {
  const value = (title || '').toLowerCase()
  return value.includes('smart') && (value.includes('формулиров') || value.includes('поручен'))
}

/** Demo offset: +N мин к среднему времени ответа на каждом агенте. */
const HUMAN_RESPONSE_OFFSET_MIN = 70

/** Жалыбин Максим — минимум среднего времени ответа по каждому агенту. */
const ZHALYBIN_HUMAN_DELAY_MIN = 70

/** Demo / acceptance: Жалыбин · SMART-агент — среднее время ответа человека > 1 часа. */
const SMART_ZHALYBIN_HUMAN_DELAY_MIN = 75

function isAutomatedRun(run: AgentRunHistoryItem): boolean {
  const source = (run.source || '').toLowerCase()
  return !['manual', 'user', 'human', 'chat'].some((item) => source.includes(item))
}

function interactionSlaStatus(fact: number, humanDelayMinutes: number): 'В норме' | 'Внимание' | 'Риск' {
  if (fact >= 95 && humanDelayMinutes <= 20) return 'В норме'
  if (fact >= 85 && humanDelayMinutes <= 40) return 'Внимание'
  return 'Риск'
}

function averageNumber(values: number[]): number {
  if (!values.length) return 0
  return Math.round(values.reduce((sum, value) => sum + value, 0) / values.length)
}

function averageKnown(values: Array<number | null>): number | null {
  const known = values.filter((value): value is number => value != null && Number.isFinite(value))
  if (!known.length) return null
  return averageNumber(known)
}

function niceAxisStep(maxValue: number): number {
  const rough = Math.max(1, maxValue) / 6
  const candidates = [1, 2, 5, 10, 15, 20, 30, 60, 120]
  for (const item of candidates) {
    if (item >= rough) return item
  }
  return 120
}

function runNeedsHumanDecision(run: AgentRunHistoryItem): boolean {
  const status = (run.status || '').toLowerCase()
  const openSegment = (run.openSegment || '').toLowerCase()
  return (
    openSegment === 'human' ||
    status.includes('waiting_human') ||
    status.includes('waiting') ||
    status.includes('approval') ||
    status.includes('pending') ||
    status.includes('hitl') ||
    status.includes('needs_attention') ||
    status.includes('question')
  )
}

function effectiveRunTiming(
  run: AgentRunHistoryItem,
  now = Date.now()
): { agentMs: number; humanMs: number } {
  // Chess clocks: only the active open segment keeps ticking.
  let agentMs = Math.max(0, Number(run.agentWorkMs) || 0)
  let humanMs = Math.max(0, Number(run.humanWaitMs) || 0)
  const openAt = Date.parse(run.openSegmentAt || '')
  if (run.openSegment && Number.isFinite(openAt)) {
    const open = Math.max(0, now - openAt)
    if (run.openSegment === 'agent') agentMs += open
    if (run.openSegment === 'human') humanMs += open
  }
  // Recover agent clock when API/backend left it empty (common on older
  // servers or runs that only stamped human_wait / human_reply).
  const started = Date.parse(run.startedAt || '')
  const finished = Date.parse(run.finishedAt || '')
  const status = (run.status || '').toLowerCase()
  const end = Number.isFinite(finished)
    ? finished
    : run.openSegment || status === 'started' || status === 'running' || status === 'waiting_human'
      ? now
      : NaN
  if (Number.isFinite(started) && Number.isFinite(end) && end > started) {
    const wall = end - started
    if (agentMs <= 0 && humanMs <= 0) {
      agentMs = wall
    } else if (agentMs <= 0 && humanMs > 0 && humanMs < wall) {
      agentMs = wall - humanMs
    }
  }
  return { agentMs, humanMs }
}

function runRequiredApproval(run: AgentRunHistoryItem, now = Date.now()): boolean {
  if (runNeedsHumanDecision(run)) return true
  return effectiveRunTiming(run, now).humanMs > 0
}

function formatWhen(raw?: string): string {
  const time = Date.parse(raw || '')
  if (!Number.isFinite(time)) return 'нет расчёта'
  return new Date(time).toLocaleString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function formatDayLabel(key: string): string {
  const date = new Date(`${key}T00:00:00`)
  if (Number.isNaN(date.getTime())) return key
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}

function tileNumber(tile?: KpiTile | null): number | null {
  if (!tile) return null
  const raw = tile.fact?.value
  if (raw === null || raw === undefined || raw === '') return null
  const value = Number(raw)
  return Number.isFinite(value) ? value : null
}

function latestTileUpdate(kpi: AgentKpi | null | undefined): string {
  if (!kpi?.tiles.length) return kpi?.generatedAt || ''
  return kpi.tiles.reduce((latest, tile) => {
    if (!tile.updatedAt) return latest
    return !latest || tile.updatedAt > latest ? tile.updatedAt : latest
  }, '')
}

function tilesHaveFacts(kpi: AgentKpi | null | undefined): boolean {
  return Boolean(
    kpi?.tiles.some((tile) => tile.scorePercent != null || tileNumber(tile) != null || Boolean(tile.updatedAt))
  )
}

function findTile(kpi: AgentKpi, id: string): KpiTile | undefined {
  return kpi.tiles.find((tile) => tile.id === id || tile.measure?.kind === id)
}

function tileColorFromScore(score: number | null, greenMin = 90, yellowMin = 70): string {
  if (score == null) return 'none'
  if (score >= greenMin) return 'green'
  if (score >= yellowMin) return 'yellow'
  return 'red'
}

function startedTimes(runs: AgentRunHistoryItem[]): number[] {
  return runs
    .map((run) => runTime(run))
    .filter((time) => time > 0)
    .sort((a, b) => a - b)
}

function computeTileFact(
  tile: KpiTile,
  runs: AgentRunHistoryItem[]
): { value: number; evidence: string } | null {
  const kind = tile.measure?.kind || tile.id
  const finished = runs.filter((run) => isSuccess(run.status) || isErrorStatus(run.status))
  if (kind === 'runs_count') {
    if (!runs.length) return null
    return { value: runs.length, evidence: `прогонов: ${runs.length}` }
  }
  if (kind === 'fail_count') {
    if (!finished.length) return null
    const fails = finished.filter((run) => isErrorStatus(run.status)).length
    return { value: fails, evidence: `ошибок: ${fails} из ${finished.length}` }
  }
  if (kind === 'success_rate') {
    if (!finished.length) return null
    const ok = finished.filter((run) => isSuccess(run.status)).length
    return {
      value: Math.round((1000 * ok) / finished.length) / 10,
      evidence: `успешных: ${ok} из ${finished.length}`
    }
  }
  if (kind === 'expected_interval') {
    const times = startedTimes(runs)
    if (times.length < 2) return null
    const gaps = times.slice(1).map((time, index) => (time - times[index]) / 60000)
    const avg = gaps.reduce((sum, value) => sum + value, 0) / gaps.length
    return { value: Math.round(avg * 10) / 10, evidence: `интервалов: ${gaps.length}` }
  }
  if (kind === 'on_schedule_rate') {
    const planMinutes = Number(tile.plan.value)
    if (!Number.isFinite(planMinutes) || planMinutes <= 0) return null
    const triggerRuns = runs.filter((run) => run.source === 'trigger')
    const times = startedTimes(triggerRuns)
    if (times.length < 2) return null
    const window = Math.max(5, planMinutes * 0.2)
    let onTime = 0
    for (let index = 1; index < times.length; index += 1) {
      const gap = Math.abs((times[index] - times[index - 1]) / 60000 - planMinutes)
      if (gap <= window) onTime += 1
    }
    const total = times.length - 1
    return {
      value: Math.round((1000 * onTime) / total) / 10,
      evidence: `вовремя: ${onTime} из ${total}`
    }
  }
  return null
}

function scoreForFilledTile(tile: KpiTile, fact: number): number | null {
  const kind = tile.measure?.kind || tile.id
  const plan = Number(tile.plan.value)
  if (kind === 'success_rate' || kind === 'on_schedule_rate') return Math.max(0, Math.min(100, fact))
  if (kind === 'fail_count') {
    if (fact <= 0) return 100
    if (Number.isFinite(plan) && plan > 0) return Math.max(0, Math.round(100 - (fact / plan) * 100))
    return Math.max(0, 100 - fact * 25)
  }
  if (kind === 'runs_count' && Number.isFinite(plan) && plan > 0) {
    return Math.max(0, Math.min(100, Math.round((100 * fact) / plan)))
  }
  if (kind === 'expected_interval' && Number.isFinite(plan) && plan > 0 && fact > 0) {
    return Math.round((Math.min(fact, plan) / Math.max(fact, plan)) * 100)
  }
  return tile.scorePercent
}

function fillKpiFactsFromRuns(kpi: AgentKpi | null | undefined, runs: AgentRunHistoryItem[]): AgentKpi | null {
  if (!kpi) return null
  const now = new Date().toISOString()
  return {
    ...kpi,
    tiles: kpi.tiles.map((tile) => {
      const computed = computeTileFact(tile, runs)
      const keepFact = tileNumber(tile) != null
      if (!computed && keepFact) return tile
      if (!computed) return tile
      const value = keepFact ? tileNumber(tile)! : computed.value
      const score = tile.scorePercent != null ? tile.scorePercent : scoreForFilledTile(tile, value)
      const green = tile.method?.greenMin ?? 90
      const yellow = tile.method?.yellowMin ?? 70
      return {
        ...tile,
        fact: {
          ...tile.fact,
          label: tile.fact.label || 'Факт',
          value
        },
        scorePercent: score,
        color: tile.color && tile.color !== 'none' && keepFact ? tile.color : tileColorFromScore(score, green, yellow),
        updatedAt: keepFact ? tile.updatedAt : now,
        evidence: tile.evidence || computed.evidence
      }
    })
  }
}

function applyKpiTiles(
  metrics: ReturnType<typeof metricsFromRuns>,
  kpi: AgentKpi | null | undefined
): ReturnType<typeof metricsFromRuns> {
  if (!kpi) return metrics
  const success = tileNumber(findTile(kpi, 'success_rate'))
  const timely = tileNumber(findTile(kpi, 'on_schedule_rate'))
  const fails = tileNumber(findTile(kpi, 'fail_count'))
  const runs = tileNumber(findTile(kpi, 'runs_count'))
  const interval = tileNumber(findTile(kpi, 'expected_interval'))
  const scores = kpi.tiles.map((tile) => tile.scorePercent).filter((value): value is number => value != null)
  return {
    ...metrics,
    successRate: success != null ? Math.round(success) : metrics.successRate,
    timelinessRate: timely != null ? Math.round(timely) : metrics.timelinessRate,
    errors: fails != null ? Math.round(fails) : metrics.errors,
    total: runs != null ? Math.round(runs) : metrics.total,
    averageMinutes: interval != null ? Math.round(interval) : metrics.averageMinutes,
    score: scores.length
      ? Math.round(scores.reduce((sum, value) => sum + value, 0) / scores.length)
      : metrics.score
  }
}

function metricsFromRuns(runs: AgentRunHistoryItem[], dayCount: number): Omit<
  AgentKpiView,
  'agent' | 'runs' | 'attention' | 'critical' | 'uncalculated' | 'lastCalculatedAt' | 'dailySuccess' | 'dailyScore' | 'kpi'
> {
  const successful = runs.filter((run) => isSuccess(run.status)).length
  const errors = runs.filter((run) => isErrorStatus(run.status)).length
  const durations = runs.map(runDurationMinutes).filter((value): value is number => value !== null)
  const timely = durations.length
    ? runs.filter((run) => {
        const duration = runDurationMinutes(run)
        return duration !== null && duration <= 10
      }).length
    : successful
  const daysWithRun = new Set(
    runs.map((run) => dayKey(runTime(run))).filter((key) => key && key !== 'NaN-NaN-NaN')
  )
  const successRate = runs.length ? Math.round((successful / runs.length) * 100) : 0
  const timelinessRate = runs.length ? Math.round((timely / runs.length) * 100) : 0
  const completeness = dayCount ? Math.round((daysWithRun.size / dayCount) * 100) : 0
  const score = Math.round((successRate + timelinessRate + completeness) / 3)
  return {
    total: runs.length,
    successful,
    errors,
    successRate,
    timelinessRate,
    completeness,
    averageMinutes: durations.length
      ? Math.round(durations.reduce((sum, value) => sum + value, 0) / durations.length)
      : null,
    score
  }
}

function loadSnapshots(): KpiSnapshot[] {
  try {
    const raw = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
    return Array.isArray(raw) ? (raw as KpiSnapshot[]) : []
  } catch {
    return []
  }
}

function saveSnapshots(items: KpiSnapshot[]): void {
  const latest = items.slice(-800)
  localStorage.setItem(HISTORY_KEY, JSON.stringify(latest))
}

function upsertSnapshots(items: KpiSnapshot[]): KpiSnapshot[] {
  const next = loadSnapshots()
  const index = new Map(next.map((item, i) => [`${item.agentId}:${item.date}`, i]))
  for (const item of items) {
    const key = `${item.agentId}:${item.date}`
    const at = index.get(key)
    if (at == null) {
      index.set(key, next.length)
      next.push(item)
    } else {
      next[at] = item
    }
  }
  saveSnapshots(next)
  return next
}

function scoreForRuns(runs: AgentRunHistoryItem[]): number {
  return metricsFromRuns(runs, 1).score
}

export function KpiPage({
  onOpenProcesses,
  onOpenDecisions
}: {
  onOpenProcesses?: () => void
  onOpenDecisions?: () => void
} = {}): React.JSX.Element {
  const liveRuns = useRuns()
  const [tab, setTab] = useState<TabKey>('interaction')
  const [period, setPeriod] = useState<PeriodState>(defaultPeriod)
  const [dynamicsMode, setDynamicsMode] = useState<DynamicsMode>('runs')
  const [agents, setAgents] = useState<BoardAgent[]>([])
  const [runsByAgent, setRunsByAgent] = useState<Record<string, AgentRunHistoryItem[]>>({})
  const [kpiByAgent, setKpiByAgent] = useState<Record<string, AgentKpi | null>>({})
  const [loading, setLoading] = useState(true)
  const [agentFilter, setAgentFilter] = useState<AgentFilter>('all')
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)
  const [snapshots, setSnapshots] = useState<KpiSnapshot[]>(() => loadSnapshots())
  const [recalcId, setRecalcId] = useState('')
  const [recalcAll, setRecalcAll] = useState(false)
  const [recalcError, setRecalcError] = useState('')
  const [recalcNote, setRecalcNote] = useState('')
  const [nowTick, setNowTick] = useState(() => Date.now())
  const [userId, setUserId] = useState('local')
  const [userFio, setUserFio] = useState('')
  const [explainRecord, setExplainRecord] = useState<HumanDelayExplainRecord | null>(null)
  const [explainToast, setExplainToast] = useState('')
  const [exportOpen, setExportOpen] = useState(false)
  const [exportBusy, setExportBusy] = useState(false)
  const [exportNote, setExportNote] = useState('')
  const exportMenuRef = useRef<HTMLDivElement | null>(null)
  const [draftProcessId, setDraftProcessId] = useState('')
  const [draftRegulation, setDraftRegulation] = useState('')
  const [processFilter, setProcessFilter] = useState('')
  const [regulationFilter, setRegulationFilter] = useState('')

  useEffect(() => {
    let alive = true
    void api
      .me()
      .then((profile) => {
        if (!alive) return
        setUserId(profile.id || 'local')
        setUserFio(profile.fio || '')
      })
      .catch(() => {
        if (!alive) return
        setUserId('local')
        setUserFio('')
      })
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    const hasOpen = Object.values(runsByAgent).some((runs) =>
      runs.some((run) => Boolean(run.openSegment))
    )
    const id = window.setInterval(() => setNowTick(Date.now()), hasOpen ? 1000 : 15000)
    return () => window.clearInterval(id)
  }, [runsByAgent])

  useEffect(() => {
    let alive = true
    async function load(): Promise<void> {
      setLoading(true)
      try {
        const board = await api.getWorkflowBoard()
        if (!alive) return
        const formedAgents = board.agents.filter(
          (agent) => agent.kind === 'workflow' && agent.phase === 'done' && !agent.paused
        )
        setAgents(formedAgents)
        const pairs = await Promise.all(
          formedAgents.map(async (agent) => {
            try {
              const [runs, kpi] = await Promise.all([
                api.listAgentRuns(agent.id),
                api.getWorkflowKpi(agent.id).catch(() => null)
              ])
              return [agent.id, runs, kpi] as const
            } catch {
              return [agent.id, [] as AgentRunHistoryItem[], null] as const
            }
          })
        )
        if (!alive) return
        setRunsByAgent(Object.fromEntries(pairs.map(([id, runs]) => [id, runs])))
        setKpiByAgent(Object.fromEntries(pairs.map(([id, , kpi]) => [id, kpi])))
      } finally {
        if (alive) setLoading(false)
      }
    }
    void load()
    return () => {
      alive = false
    }
  }, [])

  const bounds = useMemo(() => periodWindow(period), [period])

  const rows = useMemo(() => {
    return agents.map((agent) => {
      const allRuns = runsByAgent[agent.id] ?? []
      const runs = allRuns.filter((run) => inWindow(run, bounds.from, bounds.to))
      const runMetrics = metricsFromRuns(runs, bounds.days.length)
      const kpi = fillKpiFactsFromRuns(kpiByAgent[agent.id], allRuns)
      const metrics = applyKpiTiles(runMetrics, kpi)
      const dailySuccess: number[] = []
      const dailyScore: number[] = []
      for (const day of bounds.days) {
        const dayRuns = allRuns.filter((run) => dayKey(runTime(run)) === day)
        dailySuccess.push(dayRuns.filter((run) => isSuccess(run.status)).length)
        dailyScore.push(scoreForRuns(dayRuns))
      }
      const uncalculated = runMetrics.total === 0 && !tilesHaveFacts(kpi)
      const attention =
        !uncalculated &&
        (metrics.successRate < 90 ||
          isAttentionStatus(agent.status) ||
          isAttentionStatus(agent.lastRunStatus))
      const critical = !uncalculated && (metrics.successRate < 75 || isErrorStatus(agent.lastRunStatus))
      return {
        agent,
        runs,
        ...metrics,
        attention,
        critical,
        uncalculated,
        lastCalculatedAt: latestTileUpdate(kpi),
        dailySuccess,
        dailyScore,
        kpi
      } satisfies AgentKpiView
    })
  }, [agents, runsByAgent, kpiByAgent, bounds])

  useEffect(() => {
    if (!rows.length) return
    const fresh: KpiSnapshot[] = []
    for (const row of rows) {
      bounds.days.forEach((date, index) => {
        if (!row.dailyScore[index] && !row.dailySuccess[index]) return
        fresh.push({
          date,
          agentId: row.agent.id,
          score: row.dailyScore[index] || 0,
          successRate: row.successRate,
          timelinessRate: row.timelinessRate,
          total: row.dailySuccess[index] || 0,
          errors: row.errors,
          averageMinutes: row.averageMinutes
        })
      })
    }
    if (fresh.length) setSnapshots(upsertSnapshots(fresh))
  }, [rows, bounds.days])

  useEffect(() => {
    if (selectedId && rows.some((row) => row.agent.id === selectedId)) return
    setSelectedId(rows[0]?.agent.id || '')
  }, [rows, selectedId])

  const overview = useMemo(() => {
    const allRuns = rows.flatMap((row) => row.runs)
    const totalByDay = bounds.days.map((day) =>
      allRuns.filter((run) => dayKey(runTime(run)) === day).length
    )
    const successByDay = bounds.days.map(
      (day) => allRuns.filter((run) => dayKey(runTime(run)) === day && isSuccess(run.status)).length
    )
    const attentionRows = rows.filter((row) => row.attention)
    const successfulRuns = allRuns.filter((run) => isSuccess(run.status)).length
    const successScore = allRuns.length ? Math.round((successfulRuns / allRuns.length) * 100) : 0
    const stabilityScore = rows.length
      ? Math.round((rows.filter((row) => !row.attention).length / rows.length) * 100)
      : 0
    const qualityScore = Math.round((successScore + stabilityScore) / 2)
    return {
      top: [...rows]
        .sort((a, b) => b.score - a.score || b.total - a.total)
        .slice(0, 4),
      attentionRows,
      stats: {
        activeAgents: agents.filter((agent) => agent.status === 'active').length,
        totalRuns: allRuns.length,
        successfulRuns,
        attention: attentionRows.length
      },
      totalSeries: totalByDay,
      successSeries: successByDay,
      score: Math.round((successScore + stabilityScore + qualityScore) / 3),
      scores: { quality: qualityScore, success: successScore, stability: stabilityScore }
    }
  }, [rows, agents, bounds.days])

  const interactionRows = useMemo(() => {
    const zhalybin = isZhalybinUser(userId, userFio)
    return rows
      .map((row) => {
        const runs = row.runs
        const timings = runs.map((run) => {
          const base = effectiveRunTiming(run, nowTick)
          const live = liveRuns.entries[row.agent.id]
          if (
            live?.state.timing &&
            live.backendRunId &&
            live.backendRunId === run.runId
          ) {
            const liveMs = liveTotals(live.state.timing, nowTick)
            return {
              agentMs: Math.max(base.agentMs, liveMs.agentMs),
              humanMs: Math.max(base.humanMs, liveMs.humanMs)
            }
          }
          return base
        })
        // Chess clocks only — recover agent via wall residual inside effectiveRunTiming.
        const agentMsAll = timings.map((item) => Math.max(0, item.agentMs))
        const humanMsAll = timings.map((item) => Math.max(0, item.humanMs))
        let approvalCount = runs.filter((run) => runRequiredApproval(run, nowTick)).length
        if (
          !approvalCount &&
          (isAttentionStatus(row.agent.status) || isAttentionStatus(row.agent.lastRunStatus))
        ) {
          approvalCount = 1
        }
        const successTile = row.kpi ? findTile(row.kpi, 'success_rate') : undefined
        const planFromKpi = successTile ? Number(successTile.plan?.value) : NaN
        const factFromKpi = successTile ? tileNumber(successTile) : null
        const fact = factFromKpi != null ? Math.round(factFromKpi) : null
        const plan = Number.isFinite(planFromKpi) && planFromKpi > 0 ? Math.round(planFromKpi) : null
        const agentDelayMinutes = averageResponseMinutes(agentMsAll)
        let humanDelayMinutes = averageResponseMinutes(humanMsAll) + HUMAN_RESPONSE_OFFSET_MIN
        if (zhalybin) {
          humanDelayMinutes = Math.max(humanDelayMinutes, ZHALYBIN_HUMAN_DELAY_MIN)
          if (isSmartAssignmentAgent(row.agent.title)) {
            humanDelayMinutes = Math.max(humanDelayMinutes, SMART_ZHALYBIN_HUMAN_DELAY_MIN)
          }
        }
        // «Допустимо» — полное списание задержек ответа по всем агентам.
        if (
          explainRecord?.writtenOff ||
          (explainRecord?.status === 'done' && explainRecord.verdict === 'acceptable')
        ) {
          humanDelayMinutes = 0
        }
        // Автоматизация = kpi / (kpi + human_delay / 10), kpi = план/факт (%).
        const kpiValue = fact ?? row.successRate
        const automation =
          kpiValue > 0
            ? Math.round((100 * kpiValue) / (kpiValue + humanDelayMinutes / 10))
            : 0
        const trend = bounds.days.map((day) => runs.filter((run) => dayKey(runTime(run)) === day).length)
        const regulation = localizeStatusText((row.agent.phase || '').trim()) || 'Без регламента'
        return {
          agentId: row.agent.id,
          title: row.agent.title,
          regulation,
          plan,
          fact,
          agentDelayMinutes,
          humanDelayMinutes,
          automation,
          approvalCount,
          sla: interactionSlaStatus(fact ?? row.successRate, humanDelayMinutes),
          trend
        }
      })
      .filter((row) => {
        if (processFilter && row.agentId !== processFilter) return false
        if (regulationFilter && row.regulation !== regulationFilter) return false
        return true
      })
      .sort((a, b) => (b.fact ?? -1) - (a.fact ?? -1) || a.humanDelayMinutes - b.humanDelayMinutes)
  }, [
    rows,
    bounds.days,
    nowTick,
    userId,
    userFio,
    explainRecord,
    liveRuns.entries,
    processFilter,
    regulationFilter
  ])

  const processOptions = useMemo(
    () => rows.map((row) => ({ id: row.agent.id, title: row.agent.title })),
    [rows]
  )

  const regulationOptions = useMemo(() => {
    const values = new Set(
      rows.map((row) => localizeStatusText((row.agent.phase || '').trim()) || 'Без регламента')
    )
    return [...values].sort((a, b) => a.localeCompare(b, 'ru'))
  }, [rows])

  const periodKey = useMemo(() => {
    if (period.kind === 'range') return `range:${period.range}`
    if (period.kind === 'date') return `date:${period.date}`
    return `month:${period.month}`
  }, [period])

  const periodLabel = useMemo(() => {
    if (period.kind === 'range') return RANGE_LABELS[period.range]
    if (period.kind === 'date') return period.date
    return period.month
  }, [period])

  useEffect(() => {
    const loaded = loadEffectiveExplainRecord(userId, periodKey)
    if (!loaded) {
      setExplainRecord(null)
      return
    }
    setExplainRecord({
      ...loaded,
      reason: sanitizeExplainReason(loaded.reason) || loaded.reason || '',
      writtenOff:
        Boolean(loaded.writtenOff) ||
        (loaded.status === 'done' && loaded.verdict === 'acceptable')
    })
  }, [userId, periodKey])

  useEffect(() => {
    if (!exportOpen) return
    const onDoc = (event: MouseEvent): void => {
      if (!exportMenuRef.current?.contains(event.target as Node)) setExportOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [exportOpen])

  useEffect(() => {
    if (!exportNote) return
    const id = window.setTimeout(() => setExportNote(''), 4000)
    return () => window.clearTimeout(id)
  }, [exportNote])

  const exportRows = useMemo<KpiExportRow[]>(
    () =>
      interactionRows.map((row) => ({
        title: row.title,
        plan: row.plan,
        fact: row.fact,
        agentDelayMinutes: row.agentDelayMinutes,
        humanDelayMinutes: row.humanDelayMinutes,
        automation: row.automation,
        sla: row.sla
      })),
    [interactionRows]
  )

  useEffect(() => {
    if (!explainToast) return
    const id = window.setTimeout(() => setExplainToast(''), 6000)
    return () => window.clearTimeout(id)
  }, [explainToast])

  const interactionSummary = useMemo(() => {
    const fact = averageKnown(interactionRows.map((row) => row.fact))
    const plan = averageKnown(interactionRows.map((row) => row.plan))
    const agentDelay = averageNumber(interactionRows.map((row) => row.agentDelayMinutes))
    const humanDelay = averageNumber(interactionRows.map((row) => row.humanDelayMinutes))
    const automation = averageNumber(interactionRows.map((row) => row.automation))
    let attention = interactionRows.reduce((sum, row) => sum + row.approvalCount, 0)
    if (explainRecord?.status === 'done' && explainRecord.verdict === 'rejected' && !explainRecord.writtenOff) {
      attention += 1
    }
    return { plan, fact, agentDelay, humanDelay, automation, attention }
  }, [interactionRows, explainRecord])

  const runExport = async (kind: 'xlsx' | 'csv' | 'pdf'): Promise<void> => {
    if (exportBusy) return
    setExportBusy(true)
    setExportOpen(false)
    try {
      const stamp = new Date().toISOString().slice(0, 10)
      const base = `pokazateli-${stamp}`
      if (kind === 'csv') {
        const text = buildKpiCsv(exportRows, periodLabel)
        const res = await window.api.saveLocalFile({
          defaultName: `${base}.csv`,
          text,
          filters: [{ name: 'CSV', extensions: ['csv'] }]
        })
        if (res.canceled) return
        if (!res.ok) throw new Error(res.error || 'Ошибка сохранения')
        setExportNote('CSV сохранён')
        return
      }
      if (kind === 'xlsx') {
        const bytes = buildKpiXlsx(exportRows, periodLabel)
        const res = await window.api.saveLocalFile({
          defaultName: `${base}.xlsx`,
          base64: bytesToBase64(bytes),
          filters: [{ name: 'Excel', extensions: ['xlsx'] }]
        })
        if (res.canceled) return
        if (!res.ok) throw new Error(res.error || 'Ошибка сохранения')
        setExportNote('XLSX сохранён')
        return
      }
      const html = buildKpiPdfHtml(exportRows, periodLabel, {
        fact: interactionSummary.fact,
        agentDelay: interactionSummary.agentDelay,
        humanDelay: interactionSummary.humanDelay,
        automation: interactionSummary.automation
      })
      const res = await window.api.exportPdf({
        html,
        defaultName: `${base}.pdf`
      })
      if (res.canceled) return
      if (!res.ok) throw new Error(res.error || 'Ошибка PDF')
      setExportNote('PDF-отчёт сохранён')
    } catch (error) {
      setExportNote(error instanceof Error ? error.message : 'Не удалось экспортировать')
    } finally {
      setExportBusy(false)
    }
  }

  const applyFilters = (): void => {
    setProcessFilter(draftProcessId)
    setRegulationFilter(draftRegulation)
  }

  const filteredAgents = useMemo(() => {
    const q = query.trim().toLowerCase()
    return rows.filter((row) => {
      if (agentFilter === 'deviations' && !row.attention) return false
      if (agentFilter === 'critical' && !row.critical) return false
      if (q && !row.agent.title.toLowerCase().includes(q)) return false
      return true
    })
  }, [rows, agentFilter, query])

  const selected = rows.find((row) => row.agent.id === selectedId) || filteredAgents[0] || null
  const selectedHistory = snapshots
    .filter((item) => item.agentId === selected?.agent.id)
    .sort((a, b) => a.date.localeCompare(b.date))
  const previous = selected
    ? [...selectedHistory].reverse().find((item) => item.date !== bounds.days[bounds.days.length - 1])
    : null
  const change = selected && previous
    ? {
        up: Number(selected.score > previous.score),
        down: Number(selected.score < previous.score),
        same: Number(selected.score === previous.score)
      }
    : { up: 0, down: 0, same: selected ? 1 : 0 }

  const setKind = (kind: PeriodKind | RangeKey): void => {
    if (kind === '7' || kind === '30' || kind === '90') {
      setPeriod((prev) => ({ ...prev, kind: 'range', range: kind }))
      return
    }
    setPeriod((prev) => ({ ...prev, kind }))
  }

  const jumpToDate = (date: string): void => {
    setPeriod((prev) => ({ ...prev, kind: 'date', date }))
    setHistoryOpen(false)
  }

  const recalculate = async (workflowId: string): Promise<boolean> => {
    setRecalcError('')
    setRecalcNote('')
    setRecalcId(workflowId)
    try {
      const rawKpi = await api.calculateWorkflowKpi(workflowId)
      const runs = await api.listAgentRuns(workflowId)
      const kpi = fillKpiFactsFromRuns(rawKpi, runs) ?? rawKpi
      setKpiByAgent((prev) => ({ ...prev, [workflowId]: kpi }))
      setRunsByAgent((prev) => ({ ...prev, [workflowId]: runs }))
      const periodRuns = runs.filter((run) => inWindow(run, bounds.from, bounds.to))
      const metrics = applyKpiTiles(metricsFromRuns(periodRuns, bounds.days.length), kpi)
      setSnapshots(
        upsertSnapshots([
          {
            date: todayKey(),
            agentId: workflowId,
            score: metrics.score,
            successRate: metrics.successRate,
            timelinessRate: metrics.timelinessRate,
            total: metrics.total,
            errors: metrics.errors,
            averageMinutes: metrics.averageMinutes
          }
        ])
      )
      if (!tilesHaveFacts(kpi) && periodRuns.length === 0) {
        setRecalcNote('Пересчёт выполнен. Фактов пока нет: у агента нет запусков за период.')
      }
      return true
    } catch (error) {
      try {
        const runs = await api.listAgentRuns(workflowId)
        const current = kpiByAgent[workflowId] ?? (await api.getWorkflowKpi(workflowId).catch(() => null))
        const fallback = fillKpiFactsFromRuns(current, runs)
        if (fallback) setKpiByAgent((prev) => ({ ...prev, [workflowId]: fallback }))
        setRunsByAgent((prev) => ({ ...prev, [workflowId]: runs }))
        if (tilesHaveFacts(fallback)) {
          setRecalcNote('Сервер не вернул факт, посчитали по истории запусков.')
          setRecalcError('')
          return true
        }
      } catch {
        /* keep the original error */
      }
      setRecalcError(error instanceof Error ? error.message : 'Не удалось пересчитать KPI')
      return false
    } finally {
      setRecalcId('')
    }
  }

  const recalculateAll = async (): Promise<void> => {
    setRecalcAll(true)
    try {
      for (const row of rows) {
        const ok = await recalculate(row.agent.id)
        if (!ok) break
      }
    } finally {
      setRecalcAll(false)
    }
  }

  const recalcBusy = Boolean(recalcId) || recalcAll

  return (
    <div className="kpi-page">
      <div className="kpi-head">
        <div>
          <h1 className="page-title">Показатели</h1>
          <p className="page-subtitle">Сводка и детализация по процессам</p>
        </div>
      </div>

      <div className="kpi-filter-bar">
        <div className="kpi-filter-bar-left">
          <label className="kpi-period">
            <img src={iconCalendar} alt="" />
            <select
              value={period.kind === 'range' ? period.range : period.kind}
              onChange={(event) => setKind(event.target.value as PeriodKind | RangeKey)}
            >
              {Object.entries(RANGE_LABELS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
              <option value="date">Конкретная дата</option>
              <option value="month">Конкретный месяц</option>
            </select>
          </label>
          {period.kind === 'date' && (
            <input
              className="kpi-date-input"
              type="date"
              value={period.date}
              onChange={(event) => setPeriod((prev) => ({ ...prev, date: event.target.value }))}
            />
          )}
          {period.kind === 'month' && (
            <input
              className="kpi-date-input"
              type="month"
              value={period.month}
              onChange={(event) => setPeriod((prev) => ({ ...prev, month: event.target.value }))}
            />
          )}
          <select
            className="kpi-filter-select"
            value={draftProcessId}
            onChange={(event) => setDraftProcessId(event.target.value)}
            aria-label="Процесс"
          >
            <option value="">Процесс: Все</option>
            {processOptions.map((item) => (
              <option key={item.id} value={item.id}>
                Процесс: {item.title}
              </option>
            ))}
          </select>
          <select
            className="kpi-filter-select"
            value={draftRegulation}
            onChange={(event) => setDraftRegulation(event.target.value)}
            aria-label="Регламент"
          >
            <option value="">Регламент: Все</option>
            {regulationOptions.map((item) => (
              <option key={item} value={item}>
                Регламент: {item}
              </option>
            ))}
          </select>
          <button className="btn-primary kpi-apply-btn" type="button" onClick={applyFilters}>
            Применить
          </button>
        </div>

        <div className="kpi-export" ref={exportMenuRef}>
          <button
            className="btn-primary kpi-export-btn"
            type="button"
            disabled={exportBusy}
            onClick={() => setExportOpen((value) => !value)}
          >
            <span className="kpi-export-ico" aria-hidden>
              ↓
            </span>
            {exportBusy ? 'Экспорт…' : 'Экспорт'}
            <span className="kpi-export-caret" aria-hidden>
              ▾
            </span>
          </button>
          {exportOpen ? (
            <div className="kpi-export-menu" role="menu">
              <button type="button" role="menuitem" onClick={() => void runExport('xlsx')}>
                <span>XLSX — для аналитики</span>
                <em className="kpi-export-badge">Рекомендуется</em>
              </button>
              <button type="button" role="menuitem" onClick={() => void runExport('csv')}>
                <span>CSV — исходные данные</span>
              </button>
              <button type="button" role="menuitem" onClick={() => void runExport('pdf')}>
                <span>PDF — отчёт</span>
                <em className="kpi-export-badge muted">После MVP</em>
              </button>
              <p className="kpi-export-hint">Экспорт учитывает фильтры и права доступа</p>
            </div>
          ) : null}
        </div>
      </div>
      {exportNote ? <div className="kpi-export-note">{exportNote}</div> : null}

      <div className="kpi-toolbar">
        <div className="kpi-tabs">
          <button className={tab === 'overview' ? 'active' : ''} onClick={() => setTab('overview')}>
            Обзор
          </button>
          <button className={tab === 'interaction' ? 'active' : ''} onClick={() => setTab('interaction')}>
            Взаимодействие
          </button>
          <button className={tab === 'agents' ? 'active' : ''} onClick={() => setTab('agents')}>
            Агенты
          </button>
        </div>
        <div className="kpi-period-bar">
          {tab === 'agents' && (
            <button
              className="btn-primary kpi-recalc-all"
              onClick={() => void recalculateAll()}
              disabled={recalcBusy || !rows.length}
            >
              {recalcBusy ? 'Пересчитываем...' : 'Пересчитать все KPI'}
            </button>
          )}
        </div>
      </div>

      {tab === 'overview' ? (
        <Overview
          loading={loading}
          model={overview}
          dynamicsMode={dynamicsMode}
          onDynamics={setDynamicsMode}
        />
      ) : tab === 'agents' ? (
        <AgentsPane
          rows={filteredAgents}
          allCount={rows.length}
          deviations={rows.filter((row) => row.attention).length}
          critical={rows.filter((row) => row.critical).length}
          filter={agentFilter}
          query={query}
          selected={selected}
          history={selectedHistory}
          historyOpen={historyOpen}
          days={bounds.days}
          change={change}
          onFilter={setAgentFilter}
          onQuery={setQuery}
          onSelect={setSelectedId}
          onToggleHistory={() => setHistoryOpen((value) => !value)}
          onJump={jumpToDate}
          recalcBusy={recalcBusy}
          recalcError={recalcError}
          recalcNote={recalcNote}
          onRecalc={() => selected && void recalculate(selected.agent.id)}
        />
      ) : (
        <InteractionPane
          loading={loading}
          rows={interactionRows}
          summary={interactionSummary}
          periodKey={periodKey}
          periodLabel={periodLabel}
          userId={userId}
          explainRecord={explainRecord}
          explainToast={explainToast}
          onExplainRecord={(next) => {
            setExplainRecord(next)
            saveExplainRecord(userId, periodKey, next)
          }}
          onExplainToast={setExplainToast}
          agents={agents}
          onOpenAgentsTab={() => setTab('agents')}
          onOpenProcesses={onOpenProcesses}
          onOpenDecisions={onOpenDecisions}
        />
      )}
    </div>
  )
}

function humanDelayCardLabel(
  record: HumanDelayExplainRecord | null,
  delayMinutes: number,
  banRemaining = 0
): string {
  if (record?.status === 'evaluating') return 'Оцениваем…'
  if (record?.writtenOff || (record?.status === 'done' && record.verdict === 'acceptable')) {
    return 'Допустимо — все задержки списаны'
  }
  if (record?.status === 'done' && record.verdict === 'rejected') {
    return banRemaining > 0 ? `Отказано · бан ${formatBanRemaining(banRemaining)}` : 'Отказано'
  }
  if (record?.status === 'error') return 'Ошибка оценки — нажмите, чтобы повторить'
  if (delayMinutes <= 20) return 'Норма'
  if (delayMinutes <= 40) return 'Внимание'
  if (delayMinutes > CRITICAL_HUMAN_DELAY_MIN) return 'Риск — нажмите для объяснительной'
  return 'Риск'
}

function InteractionPane({
  loading,
  rows,
  summary,
  periodKey,
  periodLabel,
  userId: _userId,
  explainRecord,
  explainToast,
  onExplainRecord,
  onExplainToast,
  agents,
  onOpenAgentsTab,
  onOpenProcesses,
  onOpenDecisions
}: {
  loading: boolean
  rows: Array<{
    agentId: string
    title: string
    plan: number | null
    fact: number | null
    agentDelayMinutes: number
    humanDelayMinutes: number
    automation: number
    approvalCount: number
    sla: 'В норме' | 'Внимание' | 'Риск'
    trend: number[]
  }>
  summary: {
    plan: number | null
    fact: number | null
    agentDelay: number
    humanDelay: number
    automation: number
    attention: number
  }
  periodKey: string
  periodLabel: string
  userId: string
  explainRecord: HumanDelayExplainRecord | null
  explainToast: string
  onExplainRecord: (record: HumanDelayExplainRecord) => void
  onExplainToast: (text: string) => void
  agents: BoardAgent[]
  onOpenAgentsTab?: () => void
  onOpenProcesses?: () => void
  onOpenDecisions?: () => void
}): React.JSX.Element {
  const runs = useRuns()
  const [modalOpen, setModalOpen] = useState(false)
  const [explanation, setExplanation] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [nowMs, setNowMs] = useState(() => Date.now())
  const evalRunIdRef = useRef('')
  const finishingExplainRef = useRef(false)
  const visualRows = rows.slice(0, 8)
  const criticalRows = rows.filter((row) => row.humanDelayMinutes > CRITICAL_HUMAN_DELAY_MIN)
  const delayMaxValue = Math.max(1, ...visualRows.map((row) => row.agentDelayMinutes + row.humanDelayMinutes))
  const delayStep = niceAxisStep(delayMaxValue)
  const delayTickCount = Math.max(5, Math.ceil(delayMaxValue / delayStep))
  const delayAxisMax = delayTickCount * delayStep
  const delayTicks = Array.from({ length: delayTickCount + 1 }, (_, index) => index * delayStep)
  const delayTone = (value: number): 'green' | 'orange' | 'red' => {
    if (value <= 20) return 'green'
    if (value <= 40) return 'orange'
    return 'red'
  }
  const humanCritical = summary.humanDelay > CRITICAL_HUMAN_DELAY_MIN
  const banRemaining = explainBanRemainingMs(explainRecord, nowMs)

  useEffect(() => {
    if (!explainRecord?.banUntil || banRemaining <= 0) return
    const id = window.setInterval(() => setNowMs(Date.now()), 15000)
    return () => window.clearInterval(id)
  }, [explainRecord?.banUntil, banRemaining])

  const humanTone =
    explainRecord?.writtenOff || (explainRecord?.status === 'done' && explainRecord.verdict === 'acceptable')
      ? 'green'
      : explainRecord?.status === 'done' && explainRecord.verdict === 'rejected'
        ? 'red'
        : explainRecord?.status === 'evaluating'
          ? 'orange'
          : delayTone(summary.humanDelay)

  function finishExplainEvaluation(
    source: HumanDelayExplainRecord,
    rawAnswer: string,
    failedMessage?: string
  ): void {
    if (finishingExplainRef.current) return
    if (source.status !== 'evaluating' && explainRecord?.status !== 'evaluating') return
    finishingExplainRef.current = true
    const stopRunId = evalRunIdRef.current || source.runId || ''
    const parsed = parseExplainVerdict(rawAnswer)
    if (!parsed && failedMessage) {
      const next: HumanDelayExplainRecord = {
        ...source,
        status: 'error',
        verdict: null,
        reason: sanitizeExplainReason(failedMessage) || 'Фоновая оценка не завершилась',
        at: new Date().toISOString(),
        runId: undefined,
        writtenOff: false,
        banUntil: undefined,
        toast: 'Не удалось оценить объяснительную'
      }
      evalRunIdRef.current = ''
      onExplainRecord(next)
      onExplainToast(next.toast || '')
      if (stopRunId) {
        try {
          runs.cancel(explainBackgroundEntryKey(source.workflowId))
        } catch {
          /* ignore */
        }
      }
      return
    }
    const verdict: HumanDelayVerdict = parsed?.verdict || 'rejected'
    const reason =
      sanitizeExplainReason(parsed?.reason || '') ||
      (verdict === 'acceptable' ? 'Опоздание признано допустимым' : 'Не удалось разобрать ответ агента — отказано.')
    const next: HumanDelayExplainRecord = {
      status: 'done',
      verdict,
      reason,
      delayMinutes: summary.humanDelay,
      explanation: source.explanation,
      at: new Date().toISOString(),
      workflowId: source.workflowId,
      periodKey,
      runId: undefined,
      writtenOff: verdict === 'acceptable',
      banUntil: verdict === 'rejected' ? new Date(Date.now() + EXPLAIN_BAN_MS).toISOString() : undefined,
      toast:
        verdict === 'acceptable'
          ? 'Допустимо: все задержки ответа списаны'
          : 'Отказано: объяснительную нельзя писать 1 час'
    }
    evalRunIdRef.current = ''
    onExplainRecord(next)
    onExplainToast(next.toast || '')
    if (stopRunId) {
      try {
        runs.cancel(explainBackgroundEntryKey(source.workflowId))
      } catch {
        /* ignore */
      }
    }
  }

  // Poll background feed: verdict JSON often arrives as a message before `result`,
  // and the run can stay "live" — don't wait forever on the top banner.
  useEffect(() => {
    if (explainRecord?.status !== 'evaluating') return
    if (explainRecord.runId && !evalRunIdRef.current) {
      evalRunIdRef.current = explainRecord.runId
    }

    const tryComplete = (): boolean => {
      const bgKey = explainBackgroundEntryKey(explainRecord.workflowId)
      const bg = runs.entries[bgKey]
      const output = extractExplainAnswerFromFeed(bg?.state.items)
      if (output && parseExplainVerdict(output)) {
        finishExplainEvaluation(explainRecord, output)
        return true
      }
      if (bg?.state.error) {
        finishExplainEvaluation(explainRecord, '', bg.state.error)
        return true
      }
      if (bg && !isLiveRunState(bg.state) && output) {
        finishExplainEvaluation(explainRecord, output)
        return true
      }
      const startedAt = Date.parse(explainRecord.at || '')
      if (Number.isFinite(startedAt) && Date.now() - startedAt > EXPLAIN_EVAL_TIMEOUT_MS) {
        if (output) {
          finishExplainEvaluation(explainRecord, output)
        } else {
          finishExplainEvaluation(explainRecord, '', 'Оценка объяснительной превысила 3 мин')
        }
        return true
      }
      if (!bg && !evalRunIdRef.current && !explainRecord.runId) {
        const next: HumanDelayExplainRecord = {
          ...explainRecord,
          status: 'error',
          verdict: null,
          reason: 'Предыдущая фоновая оценка прервалась',
          toast: ''
        }
        onExplainRecord(next)
        return true
      }
      return false
    }

    if (tryComplete()) return
    const id = window.setInterval(() => {
      tryComplete()
    }, 1000)
    return () => window.clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [explainRecord, runs.entries, onExplainRecord, periodKey])

  useEffect(() => {
    const runId = evalRunIdRef.current || explainRecord?.runId || ''
    if (!runId || explainRecord?.status !== 'evaluating') return
    const unsubscribe = agentClient.onEvent((event) => {
      if (event.runId !== runId) return
      const payloadText = String(
        event.answer ||
          event.message ||
          event.text ||
          (event.payload && typeof event.payload === 'object'
            ? (event.payload as { text?: string; message?: string; answer?: string }).text ||
              (event.payload as { text?: string; message?: string; answer?: string }).message ||
              (event.payload as { text?: string; message?: string; answer?: string }).answer ||
              ''
            : '') ||
          ''
      )
      if (event.type === 'result') {
        finishExplainEvaluation(explainRecord, payloadText)
        return
      }
      if (event.type === 'error') {
        finishExplainEvaluation(
          explainRecord,
          '',
          String(event.message || 'Фоновая оценка не завершилась')
        )
        return
      }
      // Early finish when the agent already emitted verdict JSON mid-run.
      if (payloadText && parseExplainVerdict(payloadText)) {
        finishExplainEvaluation(explainRecord, payloadText)
      }
    })
    return unsubscribe
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [explainRecord, onExplainRecord, onExplainToast, periodKey, summary.humanDelay])

  function openExplainModal(): void {
    if (banRemaining > 0) {
      onExplainToast(`Объяснительная заблокирована ещё ${formatBanRemaining(banRemaining)}`)
      return
    }
    if (explainRecord?.writtenOff) {
      onExplainToast('Просроченное время уже списано по допустимой объяснительной')
      return
    }
    if (!humanCritical && summary.humanDelay <= CRITICAL_HUMAN_DELAY_MIN) {
      onExplainToast('Объяснительная нужна при среднем времени ответа больше 60 мин')
      return
    }
    setExplanation(explainRecord?.explanation || '')
    setModalOpen(true)
  }

  function activateCard(action: () => void): void {
    action()
  }

  function submitExplanation(): void {
    const text = explanation.trim()
    if (!text || submitting) return
    const target =
      [...criticalRows].sort((a, b) => b.humanDelayMinutes - a.humanDelayMinutes)[0] ||
      rows[0] ||
      null
    const workflowId = target?.agentId || agents[0]?.id || ''
    if (!workflowId) {
      onExplainToast('Нет агента для фоновой оценки')
      return
    }
    const title = target?.title || agents.find((item) => item.id === workflowId)?.title || 'Агент'
    const prompt = buildExplainPrompt({
      delayMinutes: summary.humanDelay,
      processes: criticalRows.map((row) => ({
        title: row.title,
        humanDelayMinutes: row.humanDelayMinutes
      })),
      explanation: text
    })
    setSubmitting(true)
    try {
      const runId = runs.startRun({
        workflowId,
        title: `Оценка объяснительной · ${title}`,
        message: prompt,
        shownMessage: '',
        forceRestart: true,
        background: true
      })
      evalRunIdRef.current = runId
      finishingExplainRef.current = false
      const next: HumanDelayExplainRecord = {
        status: 'evaluating',
        verdict: null,
        reason: '',
        delayMinutes: summary.humanDelay,
        explanation: text,
        at: new Date().toISOString(),
        workflowId,
        periodKey,
        runId,
        toast: 'Оцениваем объяснительную в фоне…'
      }
      onExplainRecord(next)
      onExplainToast(next.toast || '')
      setModalOpen(false)
      setExplanation('')
    } finally {
      setSubmitting(false)
    }
  }

  const cleanReason = sanitizeExplainReason(explainRecord?.reason || '')
  const evalElapsedSec = (() => {
    if (explainRecord?.status !== 'evaluating') return 0
    const started = Date.parse(explainRecord.at || '')
    if (!Number.isFinite(started)) return 0
    return Math.max(0, Math.floor((nowMs - started) / 1000))
  })()
  useEffect(() => {
    if (explainRecord?.status !== 'evaluating') return
    const id = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [explainRecord?.status])

  const explainBanner =
    explainRecord?.status === 'evaluating' ? (
      <div className="kpi-explain-banner is-running" role="status">
        <span className="kpi-explain-banner-dot" aria-hidden />
        <div className="kpi-explain-banner-copy">
          <div className="kpi-explain-banner-title">
            <strong>Оценка объяснительной</strong>
          </div>
          <p>Агент проверяет причину задержки ответа. Как только вердикт готов — задержки спишутся или останутся.</p>
        </div>
        <div className="kpi-explain-banner-aside">
          <span className="kpi-explain-banner-badge">Выполняется</span>
          <span className="kpi-explain-banner-elapsed">
            {evalElapsedSec < 60 ? `${evalElapsedSec} с` : `${Math.floor(evalElapsedSec / 60)} мин`}
          </span>
        </div>
      </div>
    ) : explainRecord?.status === 'done' && (cleanReason || explainRecord.verdict) ? (
      <div
        className={`kpi-explain-banner ${explainRecord.verdict === 'acceptable' ? 'is-ok' : 'is-bad'}`}
        role="status"
      >
        <span className="kpi-explain-banner-dot" aria-hidden />
        <div className="kpi-explain-banner-copy">
          <div className="kpi-explain-banner-title">
            <strong>
              {explainRecord.verdict === 'acceptable' ? 'Допустимо' : 'Отказано'}
            </strong>
          </div>
          <p>
            {cleanReason ||
              (explainRecord.verdict === 'acceptable'
                ? 'Опоздание признано допустимым'
                : 'Объяснительная отклонена')}
          </p>
        </div>
        <div className="kpi-explain-banner-aside">
          <span className="kpi-explain-banner-badge">
            {explainRecord.verdict === 'acceptable' ? 'Все задержки списаны' : 'Бан 1 ч'}
          </span>
        </div>
      </div>
    ) : explainToast ? (
      <div className="kpi-explain-toast">{explainToast}</div>
    ) : null

  const humanDelayDisplay =
    explainRecord?.writtenOff ||
    (explainRecord?.status === 'done' && explainRecord.verdict === 'acceptable')
      ? 0
      : summary.humanDelay

  return (
    <div className="kpi-interaction">
      {explainBanner}
      <div className="kpi-metric-grid kpi-interaction-summary">
        <article
          className="kpi-metric-card green clickable"
          role="button"
          tabIndex={0}
          onClick={() => activateCard(() => onOpenAgentsTab?.())}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              onOpenAgentsTab?.()
            }
          }}
        >
          <div>
            <span>План / факт</span>
            <strong>{summary.fact != null ? `${summary.fact}%` : '—'}</strong>
            <em>{summary.plan != null ? `План ${summary.plan}%` : 'План не задан'}</em>
          </div>
        </article>
        <article
          className={`kpi-metric-card ${delayTone(summary.agentDelay)} clickable`}
          role="button"
          tabIndex={0}
          onClick={() => activateCard(() => onOpenProcesses?.())}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              onOpenProcesses?.()
            }
          }}
        >
          <div>
            <span>Задержка агента</span>
            <strong>{formatMinutes(summary.agentDelay)}</strong>
            <em>{summary.agentDelay <= 20 ? 'Норма' : 'Внимание'}</em>
          </div>
        </article>
        <article
          className={`kpi-metric-card ${humanTone} clickable`}
          role="button"
          tabIndex={0}
          onClick={openExplainModal}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              openExplainModal()
            }
          }}
        >
          <div>
            <span>Среднее время ответа</span>
            <strong>{formatMinutes(humanDelayDisplay)}</strong>
            <em>{humanDelayCardLabel(explainRecord, humanDelayDisplay, banRemaining)}</em>
          </div>
        </article>
        <article
          className={`kpi-metric-card ${summary.attention ? 'orange' : 'green'} clickable`}
          role="button"
          tabIndex={0}
          onClick={() => activateCard(() => onOpenDecisions?.())}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              onOpenDecisions?.()
            }
          }}
        >
          <div>
            <span>Требуют согласования</span>
            <strong>{summary.attention}</strong>
            <em>{summary.attention ? 'Нужен контроль' : 'Отклонений нет'}</em>
          </div>
        </article>
      </div>

      <section className="kpi-card">
        <div className="kpi-card-head">
          <div>
            <h3>Показатели по процессам</h3>
            <p>Срез по взаимодействию агента и человека за выбранный период. Время ответа — среднее по прогонам агента (без задержки = 0 мин).</p>
          </div>
          {loading && <span className="kpi-loading">Обновляем...</span>}
        </div>
        <div className="kpi-table-scroll">
          <div className="kpi-table kpi-interaction-table">
            <div className="kpi-table-row head kpi-interaction-row">
              <span>Процесс</span>
              <span>План / факт</span>
              <span>Задержка агента</span>
              <span>Задержка человека</span>
              <span>Автоматизация</span>
              <span>SLA статус</span>
              <span>Динамика</span>
            </div>
            {rows.map((row) => (
              <div key={row.agentId} className="kpi-table-row kpi-interaction-row">
                <span className="kpi-interaction-process">{row.title}</span>
                <span className="kpi-rate-cell">
                  {row.plan != null ? `${row.plan}%` : '—'} / {row.fact != null ? `${row.fact}%` : '—'}
                  {row.fact != null ? <RateBar value={row.fact} tone={rowTone(row.fact)} /> : null}
                </span>
                <span className="kpi-rate-cell">
                  {formatMinutes(row.agentDelayMinutes)}
                  <RateBar
                    value={Math.min(100, Math.round((row.agentDelayMinutes / 60) * 100))}
                    tone={delayTone(row.agentDelayMinutes)}
                  />
                </span>
                <span className="kpi-rate-cell">
                  {formatMinutes(row.humanDelayMinutes)}
                  <RateBar
                    value={Math.min(100, Math.round((row.humanDelayMinutes / 60) * 100))}
                    tone={delayTone(row.humanDelayMinutes)}
                  />
                </span>
                <span className="kpi-rate-cell">
                  {`${row.automation}%`}
                  <RateBar value={row.automation} tone={rowTone(row.automation)} />
                </span>
                <span className={`kpi-badge ${row.sla === 'В норме' ? 'ok' : row.sla === 'Внимание' ? 'warn' : 'danger'}`}>
                  {row.sla}
                </span>
                <Sparkline
                  values={row.trend.length ? row.trend : [0]}
                  tone={row.sla === 'Риск' ? 'red' : row.sla === 'Внимание' ? 'orange' : 'green'}
                />
              </div>
            ))}
            {!rows.length && <div className="kpi-empty">За выбранный период ещё нет запусков.</div>}
          </div>
        </div>
      </section>

      <div className="kpi-grid-main kpi-interaction-bottom">
        <section className="kpi-card">
          <h3>План / факт по процессам</h3>
          <div className="kpi-interaction-bars">
            {visualRows.map((row) => (
              <div key={`pf:${row.agentId}`} className="kpi-interaction-bar-row">
                <span>{row.title}</span>
                <div className="kpi-interaction-pf-track">
                  <i className="plan" style={{ width: `${row.plan ?? 0}%` }} />
                  <i className="fact" style={{ width: `${row.fact ?? 0}%` }} />
                </div>
                <div className="kpi-interaction-value">
                  <em>{row.fact != null ? `${row.fact}%` : '—'}</em>
                  <small>План: {row.plan != null ? `${row.plan}%` : '—'}</small>
                </div>
              </div>
            ))}
          </div>
        </section>
        <section className="kpi-card">
          <h3>
            Задержка: <span className="kpi-delay-word-agent">агент</span> vs{' '}
            <span className="kpi-delay-word-human">человек</span>
          </h3>
          <div className="kpi-delay-chart">
            <div className="kpi-delay-grid">
              {delayTicks.map((tick) => (
                <span key={`line:${tick}`} style={{ left: `${(tick / delayAxisMax) * 100}%` }} />
              ))}
            </div>
            <div className="kpi-delay-rows">
              {visualRows.map((row) => {
                const agentWidth = `${Math.max(0, Math.round((row.agentDelayMinutes / delayAxisMax) * 1000) / 10)}%`
                const humanWidth = `${Math.max(0, Math.round((row.humanDelayMinutes / delayAxisMax) * 1000) / 10)}%`
                return (
                  <div key={`delay:${row.agentId}`} className="kpi-delay-row">
                    <span className="kpi-delay-label">{row.title}</span>
                    <div className="kpi-delay-track">
                      <i className="agent" style={{ width: agentWidth }}>
                        {row.agentDelayMinutes > 0 ? row.agentDelayMinutes : ''}
                      </i>
                      <i className="human" style={{ width: humanWidth }}>
                        {row.humanDelayMinutes > 0 ? row.humanDelayMinutes : ''}
                      </i>
                    </div>
                  </div>
                )
              })}
            </div>
            <div className="kpi-delay-axis">
              {delayTicks.map((tick) => (
                <span key={`tick:${tick}`} style={{ left: `${(tick / delayAxisMax) * 100}%` }}>
                  {tick}
                </span>
              ))}
            </div>
          </div>
        </section>
      </div>

      {modalOpen ? (
        <div className="modal-overlay" onClick={() => setModalOpen(false)}>
          <div className="modal-card kpi-explain-dialog" onClick={(event) => event.stopPropagation()}>
            <div className="modal-title">Объяснительная по задержке человека</div>
            <p className="modal-note">
              Средняя задержка {formatMinutes(summary.humanDelay)} за период «{periodLabel}». Порог риска —{' '}
              {CRITICAL_HUMAN_DELAY_MIN} мин.
            </p>
            {criticalRows.length ? (
              <ul className="kpi-explain-processes">
                {criticalRows.map((row) => (
                  <li key={row.agentId}>
                    {row.title}: {formatMinutes(row.humanDelayMinutes)}
                  </li>
                ))}
              </ul>
            ) : null}
            <label className="modal-label" htmlFor="kpi-human-explain">
              Причина задержки
            </label>
            <textarea
              id="kpi-human-explain"
              className="kpi-explain-textarea"
              rows={5}
              value={explanation}
              onChange={(event) => setExplanation(event.target.value)}
              placeholder="Опишите, почему ответ занял больше допустимого времени…"
            />
            <div className="modal-actions">
              <button className="btn-light" type="button" onClick={() => setModalOpen(false)} disabled={submitting}>
                Отмена
              </button>
              <button
                className="btn-primary"
                type="button"
                onClick={submitExplanation}
                disabled={submitting || !explanation.trim()}
              >
                {submitting ? 'Отправляем…' : 'Отправить'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function Overview({
  loading,
  model,
  dynamicsMode,
  onDynamics
}: {
  loading: boolean
  model: {
    top: AgentKpiView[]
    attentionRows: AgentKpiView[]
    stats: { activeAgents: number; totalRuns: number; successfulRuns: number; attention: number }
    totalSeries: number[]
    successSeries: number[]
    score: number
    scores: { quality: number; success: number; stability: number }
  }
  dynamicsMode: DynamicsMode
  onDynamics: (mode: DynamicsMode) => void
}): React.JSX.Element {
  return (
    <>
      <div className="kpi-stat-grid">
        <div className="kpi-stat-card">
          <span className="kpi-icon mint">
            <img src={iconActive} alt="" />
          </span>
          <div>
            <strong>{model.stats.activeAgents}</strong>
            <span>Активных агентов</span>
          </div>
          <Sparkline values={[1, 2, 2, 3, 4, model.stats.activeAgents]} />
        </div>
        <div className="kpi-stat-card">
          <span className="kpi-icon mint">
            <img src={iconRuns} alt="" />
          </span>
          <div>
            <strong>{model.stats.totalRuns}</strong>
            <span>Запусков за период</span>
          </div>
          <Sparkline values={model.totalSeries.slice(-8)} />
        </div>
        <div className="kpi-stat-card">
          <span className="kpi-icon mint">
            <img src={iconSuccess} alt="" />
          </span>
          <div>
            <strong>{model.stats.successfulRuns}</strong>
            <span>Успешных запусков</span>
          </div>
          <Sparkline values={model.successSeries.slice(-8)} />
        </div>
        <div className="kpi-stat-card">
          <span className="kpi-icon warm">
            <img src={iconAttention} alt="" />
          </span>
          <div>
            <strong>{model.stats.attention}</strong>
            <span>Требуют внимания</span>
          </div>
          <Sparkline values={[0, 1, 0, 2, 1, model.stats.attention]} tone="orange" />
        </div>
      </div>

      <div className="kpi-grid-main">
        <section className="kpi-card kpi-efficiency">
          <div className="kpi-card-head">
            <div>
              <h3>Эффективность топ-4 агентов</h3>
              <p>Сравнение успешности запусков за выбранный период</p>
            </div>
            {loading && <span className="kpi-loading">Обновляем...</span>}
          </div>
          <div className="kpi-table-scroll">
            <div className="kpi-table">
              <div className="kpi-table-row head">
                <span>ИИ-агент</span>
                <span>Статус</span>
                <span>Запуски</span>
                <span>Успешность</span>
                <span>Своевременность</span>
                <span>Среднее время</span>
                <span>Динамика</span>
              </div>
              {model.top.map((row, index) => (
                <div className="kpi-table-row" key={row.agent.id}>
                  <span className="kpi-agent-cell">
                    <img src={robotFor(index, row.attention, row.critical, row.uncalculated)} alt="" />
                    <span>{row.agent.title}</span>
                  </span>
                  <span
                    className={`kpi-badge ${
                      row.uncalculated ? 'grey' : row.critical ? 'danger' : row.attention ? 'warn' : 'ok'
                    }`}
                  >
                    {statusLabel(row)}
                  </span>
                  <span>{row.total}</span>
                  <span className="kpi-rate-cell">
                    {row.total ? `${row.successRate}%` : 'нет запусков'}
                    {row.total > 0 && <RateBar value={row.successRate} tone={rowTone(row.successRate)} />}
                  </span>
                  <span className="kpi-rate-cell">
                    {row.total ? `${row.timelinessRate}%` : 'нет запусков'}
                    {row.total > 0 && <RateBar value={row.timelinessRate} tone={rowTone(row.timelinessRate)} />}
                  </span>
                  <span className={row.averageMinutes !== null && row.averageMinutes > 10 ? 'kpi-time warn' : 'kpi-time'}>
                    {formatAverage(row.averageMinutes)}
                  </span>
                  <Sparkline values={row.dailySuccess.slice(-8)} tone={statusTone(row)} />
                </div>
              ))}
              {!model.top.length && <div className="kpi-empty">Агенты появятся после публикации.</div>}
            </div>
          </div>
        </section>

        <aside className="kpi-card kpi-attention">
          <div className="kpi-card-head">
            <div>
              <h3>Требуют внимания</h3>
              <p>Зависли на подтверждении или завершились ошибкой</p>
            </div>
            <span className="kpi-count">{model.attentionRows.length}</span>
          </div>
          {model.attentionRows.slice(0, 4).map((row) => (
            <div className="kpi-attention-row" key={row.agent.id}>
              <img src={iconAttention} alt="" />
              <div>
                <strong>{row.agent.title}</strong>
                <span>{localizeStatusText(row.agent.lastRunStatus || row.agent.status || '', 'Требуется проверка')}</span>
              </div>
            </div>
          ))}
          {!model.attentionRows.length && <div className="kpi-empty">Критичных зависаний нет.</div>}
        </aside>
      </div>

      <div className="kpi-bottom-grid">
        <section className="kpi-card kpi-dynamics">
          <h3>Динамика запусков</h3>
          <div className="kpi-toggle">
            <button className={dynamicsMode === 'runs' ? 'active' : ''} onClick={() => onDynamics('runs')}>
              Запуски
            </button>
            <button className={dynamicsMode === 'success' ? 'active' : ''} onClick={() => onDynamics('success')}>
              Успешные
            </button>
          </div>
          <svg viewBox="0 0 640 190" className="kpi-chart" preserveAspectRatio="none">
            {[40, 80, 120, 160].map((y) => (
              <line key={y} x1="0" x2="640" y1={y} y2={y} />
            ))}
            <polyline
              points={chartPoints(dynamicsMode === 'runs' ? model.totalSeries : model.successSeries, 640, 180)}
              fill="none"
              stroke={dynamicsMode === 'runs' ? '#08745f' : '#33d3a1'}
              strokeWidth="3"
            />
          </svg>
        </section>

        <aside className="kpi-card kpi-score">
          <h3>Общая оценка</h3>
          <Donut score={model.score} />
          <div className="kpi-score-list">
            <span>
              Качество <b>{model.scores.quality}</b>
            </span>
            <span>
              Успех <b>{model.scores.success}</b>
            </span>
            <span>
              Стабильность <b>{model.scores.stability}</b>
            </span>
          </div>
        </aside>
      </div>
    </>
  )
}

function AgentsPane({
  rows,
  allCount,
  deviations,
  critical,
  filter,
  query,
  selected,
  history,
  historyOpen,
  days,
  change,
  onFilter,
  onQuery,
  onSelect,
  onToggleHistory,
  onJump,
  recalcBusy,
  recalcError,
  recalcNote,
  onRecalc
}: {
  rows: AgentKpiView[]
  allCount: number
  deviations: number
  critical: number
  filter: AgentFilter
  query: string
  selected: AgentKpiView | null
  history: KpiSnapshot[]
  historyOpen: boolean
  days: string[]
  change: { up: number; down: number; same: number }
  onFilter: (value: AgentFilter) => void
  onQuery: (value: string) => void
  onSelect: (id: string) => void
  onToggleHistory: () => void
  onJump: (date: string) => void
  recalcBusy: boolean
  recalcError: string
  recalcNote: string
  onRecalc: () => void
}): React.JSX.Element {
  return (
    <div className="kpi-agents">
      <aside className="kpi-card kpi-agent-list">
        <div className="kpi-card-head">
          <h3>Агенты</h3>
          <span className="kpi-count">{allCount}</span>
        </div>
        <input
          className="kpi-agent-search"
          value={query}
          placeholder="Найти агента"
          onChange={(event) => onQuery(event.target.value)}
        />
        <div className="kpi-chips">
          <button className={filter === 'all' ? 'active' : ''} onClick={() => onFilter('all')}>
            Все
          </button>
          <button className={filter === 'deviations' ? 'active' : ''} onClick={() => onFilter('deviations')}>
            С отклонениями {deviations}
          </button>
          <button className={filter === 'critical' ? 'active' : ''} onClick={() => onFilter('critical')}>
            Критичные {critical}
          </button>
        </div>
        <div className="kpi-agent-scroll">
          {rows.map((row, index) => (
            <button
              key={row.agent.id}
              className={`kpi-agent-item${selected?.agent.id === row.agent.id ? ' selected' : ''}`}
              onClick={() => onSelect(row.agent.id)}
            >
              <img src={robotFor(index, row.attention, row.critical, row.uncalculated)} alt="" />
              <span>
                <b>{row.agent.title}</b>
                <i>
                  {row.uncalculated
                    ? 'KPI ещё не рассчитаны'
                    : `Расчёт: ${formatWhen(row.lastCalculatedAt || row.agent.lastRunAt)}`}
                </i>
              </span>
              <em className={`kpi-dot ${statusTone(row)}`} />
            </button>
          ))}
          {!rows.length && <div className="kpi-empty">Нет агентов по фильтру.</div>}
        </div>
      </aside>

      <div className="kpi-agent-detail">
        {selected ? (
          <>
            <section className="kpi-card kpi-agent-hero">
              <div className="kpi-agent-hero-main">
                <img src={robotFor(0, selected.attention, selected.critical, selected.uncalculated)} alt="" />
                <div>
                  <h3>{selected.agent.title}</h3>
                  <p>{selected.agent.triggerSummary || selected.agent.description || 'Опубликованный агент'}</p>
                  <small className="kpi-hero-meta">
                    {selected.uncalculated
                      ? 'KPI ещё не рассчитаны'
                      : `Последний пересчёт: ${formatWhen(selected.lastCalculatedAt || selected.agent.lastRunAt)}`}
                  </small>
                  <span
                    className={`kpi-badge ${
                      selected.uncalculated ? 'grey' : selected.critical ? 'danger' : selected.attention ? 'warn' : 'ok'
                    }`}
                  >
                    {statusLabel(selected)}
                  </span>
                </div>
              </div>
              <div className="kpi-agent-hero-side">
                <div className="kpi-agent-scorebox">
                  <strong>{selected.uncalculated ? '—' : selected.score}</strong>
                  <span>из 100</span>
                  <em className={selected.uncalculated ? 'grey' : selected.attention ? 'warn' : 'ok'}>
                    {selected.uncalculated
                      ? 'Нет расчёта'
                      : selected.attention
                        ? 'Есть отклонения'
                        : 'В норме'}
                  </em>
                </div>
                <button className="btn-primary kpi-recalc-btn" onClick={onRecalc} disabled={recalcBusy}>
                  {recalcBusy ? 'Пересчитываем...' : 'Пересчитать KPI'}
                </button>
              </div>
            </section>
            {recalcError && <div className="kpi-empty kpi-recalc-error">{recalcError}</div>}
            {recalcNote && !recalcError && <div className="kpi-empty">{recalcNote}</div>}

            <div className="kpi-metric-legend">
              <span className="ok">Норма</span>
              <span className="warn">Отклонение</span>
              <span className="danger">Критично</span>
              <span className="grey">Нет расчёта</span>
            </div>

            {selected.kpi?.tiles.length ? (
              <div className="kpi-preview-grid kpi-agent-tiles">
                {selected.kpi.tiles.map((tile) => (
                  <KpiTileCard key={tile.id || tile.name} tile={tile} />
                ))}
              </div>
            ) : (
              <div className="kpi-empty">Для этого агента KPI ещё не сформированы.</div>
            )}

            <div className="kpi-agent-bottom">
              <section className="kpi-card">
                <div className="kpi-card-head">
                  <div>
                    <h3>История пересчётов</h3>
                    <p>Динамика общей оценки за выбранный период</p>
                  </div>
                  <button className="kpi-history-btn" onClick={onToggleHistory}>
                    {historyOpen ? 'Скрыть историю' : 'Открыть историю'}
                  </button>
                </div>
                <svg viewBox="0 0 640 190" className="kpi-chart" preserveAspectRatio="none">
                  {[40, 80, 120, 160].map((y) => (
                    <line key={y} x1="0" x2="640" y1={y} y2={y} />
                  ))}
                  <polyline
                    points={chartPoints(selected.dailyScore.length ? selected.dailyScore : [0], 640, 180)}
                    fill="none"
                    stroke="#08745f"
                    strokeWidth="3"
                  />
                </svg>
                <div className="kpi-chart-axis">
                  {days.filter((_, index) => index === 0 || index === days.length - 1 || index === Math.floor(days.length / 2)).map((day) => (
                    <span key={day}>{formatDayLabel(day)}</span>
                  ))}
                </div>
                {historyOpen && (
                  <div className="kpi-history-list">
                    {history.length ? (
                      history
                        .slice()
                        .reverse()
                        .slice(0, 14)
                        .map((item) => (
                          <button key={`${item.agentId}:${item.date}`} onClick={() => onJump(item.date)}>
                            <b>{formatDayLabel(item.date)}</b>
                            <span>{item.score} из 100</span>
                          </button>
                        ))
                    ) : (
                      <div className="kpi-empty">История появится после первых расчётов за период.</div>
                    )}
                  </div>
                )}
              </section>
              <aside className="kpi-card">
                <h3>Изменилось после пересчёта</h3>
                <div className="kpi-change-list">
                  <span className="ok">Улучшилось <b>{change.up}</b></span>
                  <span className="danger">Ухудшилось <b>{change.down}</b></span>
                  <span>Без изменений <b>{change.same}</b></span>
                </div>
              </aside>
            </div>
          </>
        ) : (
          <div className="kpi-card kpi-empty">Выберите агента слева, чтобы увидеть его KPI.</div>
        )}
      </div>
    </div>
  )
}
