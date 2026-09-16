import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { loadOrchestratorMail, type OrchestratorMailLoad } from './mailProbe'
import {
  enrichEmptyOneCErrors,
  isOneCAuthFailure,
  isTechnicalDocflowConfigMessage,
  sessionOneCSourceLabel,
  userFacingOneCError,
  isErpMetaHintRecord,
} from './onecSessionHints'
import { hasTurboSessionCredentials, onecGatewayInvokeArgs, turboProjectInvokeArgs } from './userContext'
import {
  erpTaskToRow,
  turboProjectTaskToSpecTaskRow,
  turboProjectToRow
} from './specV04Mappers'
import { turboTaskAssignedToActor } from './turboAssigneeMatch'
import type { SpecMailRow, SpecProjectRow, SpecTaskRow } from './specV04DemoData'
import { isTechnicalTurboMessage, isTurboNoSessionError } from './turboSession'

/** Одна задача 1С — один id (повторы из SOAP/кэша или гонки refetch). */
export function dedupeSpecTaskRows(rows: SpecTaskRow[]): SpecTaskRow[] {
  const seen = new Set<string>()
  const out: SpecTaskRow[] = []
  for (const row of rows) {
    const id = row.id.trim().toLowerCase()
    const key =
      id && id !== '—'
        ? `id:${id}`
        : `sig:${row.title.trim().toLowerCase()}|${row.deadline}|${row.executor.trim().toLowerCase()}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push(row)
  }
  return out
}

/** Stable ids for grid refresh / telemetry (see GridDataRefreshProvider generation). */
export const ORCH_SOURCE_ID = {
  erpPm: 'erp_pm',
  turboProject: 'turboproject',
  outlookMail: 'outlook_mail'
} as const

/**
 * 1C grid: only HTTP SOAP документооборот (onec.docflow_tasks → /doc/ws/dm.1cws).
 * onec.erp_tasks_current / OData не вызываем.
 */
export function erpTasksSourceMode(): 'sql' | 'odata' | 'auto' {
  const flag = String(import.meta.env.VITE_ERP_TASKS_SOURCE ?? '').trim().toLowerCase()
  if (flag === 'odata') return 'odata'
  if (flag === 'sql') return 'sql'
  return 'auto'
}

export function isLocalBackendUrl(backendUrl: string): boolean {
  const url = (backendUrl || '').trim()
  if (!url) return true
  return /127\.0\.0\.1|localhost/i.test(url)
}

/** @deprecated 1C tasks use SOAP docflow only; OData is not called. */
export function preferErpTasksOdata(): boolean {
  return false
}

export function onecComTasksFallbackEnabled(): boolean {
  const flag = String(import.meta.env.VITE_ONEC_COM_TASKS_FALLBACK ?? '').trim().toLowerCase()
  return flag === '1' || flag === 'true' || flag === 'yes'
}

/** Pin Turbo file_id(s) so «Сегодня → проектные» always loads them (e.g. 363). */
export function turboPinnedProjectFileIds(): string[] {
  const raw = String(import.meta.env.VITE_TURBO_PIN_FILE_IDS ?? '363').trim()
  if (!raw) return ['363']
  return raw
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
}

export function isTurboPinPlaceholder(row: SpecProjectRow): boolean {
  if (row.role === 'pin') return true
  const pinned = turboPinnedProjectFileIds()
  if (pinned.includes(row.id) && /^TurboProject #\d+$/.test(row.name)) return true
  return false
}

/** Placeholder rows so pinned file_id loads even when user_portfolio filter is empty. */
export function mergePinnedTurboProjects(projects: SpecProjectRow[]): SpecProjectRow[] {
  const pinned = turboPinnedProjectFileIds()
  if (!pinned.length) return projects
  const byId = new Map(projects.map((row) => [row.id, row]))
  const merged = [...projects]
  for (const id of pinned) {
    if (byId.has(id)) continue
    merged.unshift({
      id,
      name: `TurboProject #${id}`,
      code: id,
      role: 'pin',
      tasks: 1,
      status: '—',
      statusTone: 'gray',
      deadline: '—',
      progress: 0,
      risk: '—',
      riskTone: 'gray'
    })
  }
  return merged
}

/** Load card fields for pin placeholders and pinned file_id (empty portfolio index). */
export async function enrichTurboProjectsFromApi(
  user: UserProfile,
  erpFio: string,
  projects: SpecProjectRow[]
): Promise<SpecProjectRow[]> {
  if (!projects.length) return projects
  const enrichIds = new Set<string>()
  for (const id of turboPinnedProjectFileIds()) enrichIds.add(id)
  for (const row of projects) {
    if (isTurboPinPlaceholder(row)) enrichIds.add(row.id)
  }
  if (!enrichIds.size) return projects

  const byId = new Map(projects.map((row) => [row.id, row]))
  await Promise.all(
    [...enrichIds].map(async (projectId) => {
      const res = await api.invokeServerTool(
        'turboproject.get_project',
        turboProjectInvokeArgs(user, {
          project_id: projectId,
          fields: ['identity', 'dates', 'data_1c', 'task_stats', 'overdue', 'resources']
        })
      )
      if (!res.ok || !res.result || typeof res.result !== 'object') return
      const payload = res.result as Record<string, unknown>
      const rawList = Array.isArray(payload.projects) ? payload.projects : []
      const raw = rawList.find((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
      if (!raw) return
      const mapped = turboProjectToRow({ ...raw, file_id: raw.file_id ?? projectId }, erpFio)
      byId.set(projectId, { ...mapped, id: projectId })
    })
  )
  const seen = new Set<string>()
  const merged: SpecProjectRow[] = []
  for (const row of projects) {
    const next = byId.get(row.id) ?? row
    if (seen.has(next.id)) continue
    seen.add(next.id)
    merged.push(next)
  }
  for (const id of enrichIds) {
    if (seen.has(id)) continue
    const row = byId.get(id)
    if (row) {
      seen.add(id)
      merged.unshift(row)
    }
  }
  return merged.length ? merged : projects
}

export function turboProjectFetchCandidates(projects: SpecProjectRow[], max = 5): SpecProjectRow[] {
  const merged = mergePinnedTurboProjects(projects)
  return pickTurboProjectsForTaskFetch(merged, max)
}

export function normalizeErpGatewaySource(source: string): string {
  const key = (source || '').trim().toLowerCase()
  if (!key || key === 'stub') return key || ''
  if (key.includes('erp_pm') && key.includes('odata')) return ORCH_SOURCE_ID.erpPm
  if (key.includes('erp_pm')) return ORCH_SOURCE_ID.erpPm
  if (key.includes('документооборот') || key.includes('docflow')) return 'docflow'
  return source
}

export function parseErpToolTasks(
  res: { ok: boolean; result?: unknown; error?: string },
  erpFio: string
): { rows: SpecTaskRow[]; source: string; warning: string; error: string } {
  if (!res.ok || !res.result || typeof res.result !== 'object') {
    return {
      rows: [],
      source: '',
      warning: '',
      error: res.error || ''
    }
  }
  const payload = res.result as Record<string, unknown>
  const source = normalizeErpGatewaySource(String(payload.source || 'документооборот'))
  const warning = userFacingOneCError(String(payload.docflow_warning || payload.warning || '').trim())
  const raw = Array.isArray(payload.tasks) ? payload.tasks : []
  const records = raw
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .filter((item) => !isErpMetaHintRecord(item))
  const rows = dedupeSpecTaskRows(records.map((item) => erpTaskToRow(item, erpFio)))
  return { rows, source, warning, error: '' }
}

function uniqueErrorJoin(...chunks: (string | undefined | null)[]): string {
  const seen = new Set<string>()
  const parts: string[] = []
  for (const chunk of chunks) {
    if (!chunk?.trim()) continue
    for (const piece of chunk.split(' · ')) {
      const text = piece.trim()
      if (!text || seen.has(text)) continue
      seen.add(text)
      parts.push(text)
    }
  }
  return parts.join(' · ')
}

export type IsolatedSource<T> = {
  rows: T[]
  error: string
  loading: boolean
}

export type OrchestratorErpLoad = {
  tasks: SpecTaskRow[]
  sourceLabel: string
  error: string
  loading: boolean
  /** Reserved; SOAP is the only 1C source, so this stays empty. */
  erpSecondaryHint: string
  oneCAuthFailure: boolean
}

export async function loadOrchestratorErpTasks(
  user: UserProfile,
  erpFio: string,
  opts?: { forceRefresh?: boolean }
): Promise<OrchestratorErpLoad> {
  const onecArgs = onecGatewayInvokeArgs(user, {
    limit: 80,
    only_open: true,
    today_and_overdue: false,
    force_refresh: Boolean(opts?.forceRefresh)
  })
  const dfRes = await api.invokeServerTool('onec.docflow_tasks', onecArgs, 90_000)
  const dfParsed = parseErpToolTasks(dfRes, erpFio)
  const tasks = dfParsed.rows
  const invokeError = userFacingOneCError(dfRes.error || '')
  const stubOrTech =
    dfParsed.source === 'stub' ||
    isTechnicalDocflowConfigMessage(dfRes.error || '') ||
    isTechnicalDocflowConfigMessage(dfParsed.warning) ||
    isTechnicalDocflowConfigMessage(dfParsed.error) ||
    (!dfRes.ok && !invokeError && !tasks.length)
  const mergedError = uniqueErrorJoin(
    invokeError,
    userFacingOneCError(dfParsed.error),
    dfParsed.warning
  )
  const erpCoreError = tasks.length
    ? ''
    : enrichEmptyOneCErrors(mergedError, {
        erpSource: dfParsed.source,
        docSource: dfParsed.source,
        mergedCount: tasks.length,
        fio: erpFio
      })
  const sourceLabel = tasks.length
    ? dfParsed.source === 'stub'
      ? 'документооборот'
      : dfParsed.source || 'документооборот'
    : sessionOneCSourceLabel(erpFio)
  const oneCAuthFailure =
    tasks.length === 0 && !stubOrTech && isOneCAuthFailure(dfRes.error, dfParsed.error, erpCoreError)

  return {
    tasks,
    sourceLabel,
    error: erpCoreError,
    loading: false,
    erpSecondaryHint: '',
    oneCAuthFailure
  }
}

export type OrchestratorTurboLoad = {
  projects: SpecProjectRow[]
  sourceLabel: string
  turboNoSession: boolean
  hint: string
  error: string
  loading: boolean
}

async function finalizeTurboPortfolioProjects(
  user: UserProfile,
  erpFio: string,
  projects: SpecProjectRow[],
  turboNoSession: boolean
): Promise<SpecProjectRow[]> {
  if (turboNoSession || !projects.length) return projects
  return enrichTurboProjectsFromApi(user, erpFio, projects)
}

export async function loadOrchestratorTurboPortfolio(
  user: UserProfile,
  erpFio: string
): Promise<OrchestratorTurboLoad> {
  const [turboRes, turboStatus] = await Promise.all([
    api.invokeServerTool(
      'turboproject.get_user_portfolio',
      turboProjectInvokeArgs(user, { limit: 40 })
    ),
    api.getToolStatus('turboproject').catch(() => null)
  ])

  const liveSession = hasTurboSessionCredentials(user)

  if (turboRes.ok && turboRes.result && typeof turboRes.result === 'object') {
    const payload = turboRes.result as Record<string, unknown>
    const source = String(payload.source || ORCH_SOURCE_ID.turboProject)
    if (source === 'stub') {
      return {
        projects: await finalizeTurboPortfolioProjects(
          user,
          erpFio,
          mergePinnedTurboProjects([]),
          !liveSession
        ),
        sourceLabel: liveSession ? ORCH_SOURCE_ID.turboProject : '',
        turboNoSession: !liveSession,
        hint: '',
        error: '',
        loading: false
      }
    }
    const raw = Array.isArray(payload.projects) ? payload.projects : []
    const projects = await finalizeTurboPortfolioProjects(
      user,
      erpFio,
      mergePinnedTurboProjects(
        raw
          .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
          .map((item) => turboProjectToRow(item, erpFio))
      ),
      false
    )
    const portfolioHint = String(payload.portfolio_empty_hint || '').trim()
    const pinnedNote =
      !raw.length && projects.length
        ? `Портфель пуст — загружаем pin file_id (${turboPinnedProjectFileIds().join(', ')})`
        : ''
    return {
      projects,
      sourceLabel: ORCH_SOURCE_ID.turboProject,
      turboNoSession: false,
      hint: uniqueErrorJoin(portfolioHint, pinnedNote),
      error: '',
      loading: false
    }
  }

  if (turboStatus && !turboStatus.configured) {
    return {
      projects: await finalizeTurboPortfolioProjects(
        user,
        erpFio,
        mergePinnedTurboProjects([]),
        !liveSession
      ),
      sourceLabel: liveSession ? ORCH_SOURCE_ID.turboProject : '',
      turboNoSession: !liveSession,
      hint: '',
      error: '',
      loading: false
    }
  }

  const turboErr = turboRes.error || 'недоступно'
  const noSession = !liveSession && isTurboNoSessionError(turboErr)
  const tech = isTechnicalTurboMessage(turboErr)
  return {
    projects: await finalizeTurboPortfolioProjects(
      user,
      erpFio,
      noSession ? [] : mergePinnedTurboProjects([]),
      noSession
    ),
    sourceLabel: liveSession ? ORCH_SOURCE_ID.turboProject : '',
    turboNoSession: noSession,
    hint: '',
    error: liveSession && !tech ? turboErr : '',
    loading: false
  }
}

export type { OrchestratorMailLoad }

export async function loadOrchestratorOutlookMailWeek(
  outlookMailbox: string
): Promise<OrchestratorMailLoad> {
  return loadOrchestratorMail(outlookMailbox)
}

/** Projects to fetch for «Сегодня → проектные задачи» (pinned file_id first, then by open task count). */
export function pickTurboProjectsForTaskFetch(projects: SpecProjectRow[], max = 5): SpecProjectRow[] {
  const pinned = new Set(turboPinnedProjectFileIds())
  const byId = new Map(projects.map((row) => [row.id, row]))
  const selected: SpecProjectRow[] = []
  for (const id of pinned) {
    const row = byId.get(id)
    if (row) selected.push(row)
  }
  const rest = [...projects]
    .filter((row) => !pinned.has(row.id))
    .sort((left, right) => {
      if (right.tasks !== left.tasks) return right.tasks - left.tasks
      return left.name.localeCompare(right.name, 'ru')
    })
  const cap = max > 0 ? max : projects.length
  for (const row of rest) {
    if (cap > 0 && selected.length >= cap) break
    if (!selected.some((item) => item.id === row.id)) selected.push(row)
  }
  return selected
}

export type OrchestratorTurboTasksLoad = {
  tasks: SpecTaskRow[]
  error: string
  loading: boolean
}

function isOpenTurboTask(task: Record<string, unknown>): boolean {
  const percent = Number(task.percent_complete ?? 0)
  return !Number.isFinite(percent) || percent < 1
}

/** Open TurboProject tasks for current user (assignee filter), across portfolio projects. */
export async function loadOrchestratorTurboTaskRows(
  user: UserProfile,
  erpFio: string,
  projects: SpecProjectRow[],
  _turboNoSession: boolean
): Promise<OrchestratorTurboTasksLoad> {
  const pool = projects.length ? projects : mergePinnedTurboProjects([])
  const candidates = turboProjectFetchCandidates(pool, pool.length || 200)
  if (!candidates.length) return { tasks: [], error: '', loading: false }

  const byId = new Map(pool.map((row) => [row.id, row]))
  let fetchError = ''
  const batches = await Promise.all(
    candidates.map(async (project) => {
      const res = await api.invokeServerTool(
        'turboproject.get_project_tasks',
        turboProjectInvokeArgs(user, {
          project_id: project.id,
          status: 'open',
          limit: 60
        })
      )
      if (!res.ok || !res.result || typeof res.result !== 'object') {
        const hint = (res.error || '').trim()
        if (hint && !fetchError && !isTechnicalTurboMessage(hint) && !isTurboNoSessionError(hint)) {
          fetchError = hint
        }
        return [] as SpecTaskRow[]
      }
      const payload = res.result as Record<string, unknown>
      const raw = Array.isArray(payload.tasks) ? payload.tasks : []
      const meta = byId.get(project.id)
      const projectName = meta?.name || `TurboProject #${project.id}`
      return raw
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
        .filter((task) => turboTaskAssignedToActor(task, erpFio))
        .filter(isOpenTurboTask)
        .map((task) => turboProjectTaskToSpecTaskRow(task, project.id, projectName, erpFio))
    })
  )
  const seen = new Set<string>()
  const tasks: SpecTaskRow[] = []
  for (const row of batches.flat()) {
    if (seen.has(row.id)) continue
    seen.add(row.id)
    tasks.push(row)
  }
  tasks.sort((left, right) => {
    if (left.urgent !== right.urgent) return left.urgent ? -1 : 1
    return left.deadline.localeCompare(right.deadline, 'ru')
  })
  return { tasks, error: fetchError, loading: false }
}

export type OrchestratorTaskSourcesBundle = {
  erp: OrchestratorErpLoad
  turbo: OrchestratorTurboLoad
  turboTasks: OrchestratorTurboTasksLoad
  mail: OrchestratorMailLoad
  sources: {
    erp: IsolatedSource<SpecTaskRow>
    turbo: IsolatedSource<SpecTaskRow>
    mail: IsolatedSource<SpecMailRow>
  }
}

/** Single fetch entry for SpecV04SourcesProvider (order: SOAP ДО → Turbo portfolio → Outlook week). */
export async function fetchOrchestratorTaskSources(
  user: UserProfile,
  erpFio: string,
  outlookMailbox: string,
  opts?: { forceRefresh?: boolean }
): Promise<OrchestratorTaskSourcesBundle> {
  const mailPromise = loadOrchestratorMail(outlookMailbox)
  const [erp, turbo] = await Promise.all([
    loadOrchestratorErpTasks(user, erpFio, opts),
    loadOrchestratorTurboPortfolio(user, erpFio)
  ])
  const turboTasks = await loadOrchestratorTurboTaskRows(
    user,
    erpFio,
    turbo.projects,
    turbo.turboNoSession
  )
  const mail = await mailPromise
  const turboError = turbo.error || turboTasks.error || ''
  return {
    erp,
    turbo,
    turboTasks,
    mail,
    sources: {
      erp: { rows: erp.tasks, error: erp.error, loading: false },
      turbo: { rows: turboTasks.tasks, error: turboError, loading: false },
      mail: {
        rows: mail.rows,
        error: [mail.comError, mail.imapError].filter(Boolean).join(' · '),
        loading: false
      }
    }
  }
}
