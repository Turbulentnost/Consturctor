import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import {
  enrichEmptyOneCErrors,
  isOneCAuthFailure,
  stubSourceMessage,
  isErpMetaHintRecord
} from './onecSessionHints'
import { hasTurboSessionCredentials, onecGatewayInvokeArgs, turboProjectInvokeArgs } from './userContext'
import {
  erpTaskToRow,
  isRawTurboTodayOrOverdue,
  isTurboProjectManager,
  turboProjectTaskToSpecTaskRow,
  turboProjectToRow
} from './specV04Mappers'
import { filterTurboTasksByActor } from './turboAssigneeMatch'
import type { SpecProjectRow, SpecTaskRow } from './specV04DemoData'
import { loadOrchestratorMail, type OrchestratorMailLoad } from './mailProbe'
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

export function turboProjectFetchCandidates(
  projects: SpecProjectRow[],
  max = 5,
  actorFio = ''
): SpecProjectRow[] {
  const merged = mergePinnedTurboProjects(projects)
  return pickTurboProjectsForTaskFetch(merged, max, actorFio)
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
  const warning = String(payload.docflow_warning || payload.warning || '').trim()
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

export type OrchestratorErpLoad = {
  tasks: SpecTaskRow[]
  sourceLabel: string
  error: string
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
  const dfRes = await api.invokeServerTool('onec.docflow_tasks', onecArgs, 300_000)
  const dfParsed = parseErpToolTasks(dfRes, erpFio)
  const tasks = dfParsed.rows
  const sourceLabel = tasks.length ? dfParsed.source || 'документооборот' : dfParsed.source || '—'

  let mergedError = uniqueErrorJoin(
    dfRes.error || '',
    dfParsed.error,
    dfParsed.warning,
    !dfRes.ok && !tasks.length && !dfRes.error ? 'onec.docflow_tasks недоступен' : '',
    dfParsed.source === 'stub' ? 'Документооборот: stub (нет DOK_HTTP_* на backend)' : ''
  )
  const erpCoreError =
    !tasks.length && dfParsed.source === 'stub'
      ? enrichEmptyOneCErrors(mergedError, {
          erpSource: dfParsed.source,
          docSource: dfParsed.source,
          mergedCount: 0
        })
      : mergedError

  const oneCAuthFailure =
    tasks.length === 0 && isOneCAuthFailure(dfRes.error, dfParsed.error, erpCoreError)

  return {
    tasks,
    sourceLabel,
    error: erpCoreError,
    erpSecondaryHint: '',
    oneCAuthFailure
  }
}

export type OrchestratorTurboLoad = {
  projects: SpecProjectRow[]
  sourceLabel: string
  turboNoSession: boolean
  hint: string
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
  const liveSession = hasTurboSessionCredentials(user)
  const [turboRes, turboStatus] = await Promise.all([
    api.invokeServerTool(
      'turboproject.get_user_portfolio',
      turboProjectInvokeArgs(user, { limit: 40 })
    ),
    api.getToolStatus('turboproject').catch(() => null)
  ])

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
        hint: liveSession ? stubSourceMessage('stub') : ''
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
      hint: uniqueErrorJoin(portfolioHint, pinnedNote)
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
      hint: ''
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
    sourceLabel: liveSession && tech ? ORCH_SOURCE_ID.turboProject : turboErr,
    turboNoSession: noSession,
    hint: tech ? '' : turboErr
  }
}

export type { OrchestratorMailLoad } from './mailProbe'

/** Неделя писем: IMAP (primary) + Outlook COM + probe today. */
export async function loadOrchestratorOutlookMailWeek(
  outlookMailbox: string
): Promise<OrchestratorMailLoad> {
  return loadOrchestratorMail(outlookMailbox)
}

/** Projects to fetch for «Сегодня → проектные задачи»: pin, все где я руководитель, затем по числу открытых. */
export function pickTurboProjectsForTaskFetch(
  projects: SpecProjectRow[],
  max = 5,
  actorFio = ''
): SpecProjectRow[] {
  const pinned = new Set(turboPinnedProjectFileIds())
  const byId = new Map(projects.map((row) => [row.id, row]))
  const selected: SpecProjectRow[] = []
  const push = (row?: SpecProjectRow): void => {
    if (!row || selected.some((item) => item.id === row.id)) return
    selected.push(row)
  }
  for (const id of pinned) {
    push(byId.get(id))
  }
  if (actorFio.trim()) {
    for (const row of projects) {
      if (isTurboProjectManager(row, actorFio)) push(row)
    }
  }
  const rest = [...projects]
    .filter((row) => !pinned.has(row.id) && !selected.some((item) => item.id === row.id))
    .sort((left, right) => {
      if (right.tasks !== left.tasks) return right.tasks - left.tasks
      return left.name.localeCompare(right.name, 'ru')
    })
  for (const row of rest) {
    if (selected.length >= max) break
    push(row)
  }
  return selected
}

export type OrchestratorTurboTasksLoad = {
  tasks: SpecTaskRow[]
  error: string
}

function isOpenTurboTask(task: Record<string, unknown>): boolean {
  const percent = Number(task.percent_complete ?? 0)
  return !Number.isFinite(percent) || percent < 1
}

/** Open Turbo tasks assigned to me + today/overdue from projects I manage. */
export async function loadOrchestratorTurboTaskRows(
  user: UserProfile,
  erpFio: string,
  projects: SpecProjectRow[],
  turboNoSession: boolean
): Promise<OrchestratorTurboTasksLoad> {
  if (turboNoSession || !projects.length) {
    return { tasks: [], error: '' }
  }
  const candidates = turboProjectFetchCandidates(projects, 8, erpFio)
  if (!candidates.length) return { tasks: [], error: '' }

  const byId = new Map(projects.map((row) => [row.id, row]))
  const today = new Date()
  let fetchError = ''
  const batches = await Promise.all(
    candidates.map(async (project) => {
      const managed = isTurboProjectManager(project, erpFio)
      const res = await api.invokeServerTool(
        'turboproject.get_project_tasks',
        turboProjectInvokeArgs(user, {
          project_id: project.id,
          status: 'open',
          limit: 80,
          ...(managed ? { all_assignees: true } : {})
        })
      )
      if (!res.ok || !res.result || typeof res.result !== 'object') {
        const hint = (res.error || '').trim()
        if (hint && !fetchError) fetchError = hint
        return [] as SpecTaskRow[]
      }
      const payload = res.result as Record<string, unknown>
      const raw = Array.isArray(payload.tasks) ? payload.tasks : []
      const records = raw.filter(
        (item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object'
      )
      const meta = byId.get(project.id)
      const projectName = meta?.name || `TurboProject #${project.id}`
      const mine = filterTurboTasksByActor(records, erpFio).filter(isOpenTurboTask)
      const extras = managed
        ? records.filter((task) => !mine.includes(task) && isRawTurboTodayOrOverdue(task, today))
        : []
      return [
        ...mine.map((task) =>
          turboProjectTaskToSpecTaskRow(
            task,
            project.id,
            projectName,
            erpFio,
            managed ? 'both' : 'mine'
          )
        ),
        ...extras.map((task) =>
          turboProjectTaskToSpecTaskRow(task, project.id, projectName, erpFio, 'managed')
        )
      ]
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
  return { tasks, error: fetchError }
}

export type OrchestratorCoreSourcesBundle = {
  erp: OrchestratorErpLoad
  turbo: OrchestratorTurboLoad
  turboTasks: OrchestratorTurboTasksLoad
}

export type OrchestratorTaskSourcesBundle = OrchestratorCoreSourcesBundle & {
  mail: OrchestratorMailLoad
}

/** 1C / Turbo — без Outlook COM (не дергать почту при смене пароля 1С). */
export async function fetchOrchestratorCoreSources(
  user: UserProfile,
  erpFio: string,
  opts?: { forceRefresh?: boolean }
): Promise<OrchestratorCoreSourcesBundle> {
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
  return { erp, turbo, turboTasks }
}

/** Single fetch entry for SpecV04SourcesProvider (order: SOAP ДО → Turbo portfolio → Outlook week). */
export async function fetchOrchestratorTaskSources(
  user: UserProfile,
  erpFio: string,
  outlookMailbox: string,
  opts?: { forceRefresh?: boolean; mailPeriod?: { dateFrom: string; dateTo: string } }
): Promise<OrchestratorTaskSourcesBundle> {
  const core = await fetchOrchestratorCoreSources(user, erpFio, opts)
  const mail = await loadOrchestratorMail(outlookMailbox, opts?.mailPeriod, {
    forceOutlook: opts?.forceRefresh
  })
  return { ...core, mail }
}
