import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import type { KpiRunProfile, KpiTodayRun, UserProfile } from '../../api/types'
import { hiddenEntryKey, useRuns, type RunEntry } from '../../store/runs'

export const KPI_LAUNCH_PLATFORM_ID = '80d85957-2002-480d-b058-caa7a8198711'
export const KPI_LAUNCH_TITLE = 'запуск модулей kpi'
const KPI_LAUNCH_DEFAULT_TITLE = 'Запуск модулей KPI'
const ELSEWHERE_POLL_MS = 15_000

export type KpiDailyPhase =
  | 'checking'
  | 'running'
  | 'waiting'
  | 'ready'
  | 'failed'
  | 'unavailable'

export function sameAgentTitle(title: string, expected: string): boolean {
  return title.trim().toLowerCase().replace(/ё/g, 'е') === expected
}

function launchAgentTitle(title: string): boolean {
  return title.trim().toLowerCase().replace(/ё/g, 'е').includes(KPI_LAUNCH_TITLE)
}

let launchAgentCache: { workflowId: string; title: string } | null = null
/** Days this session already handed the other positions to a hidden run. */
const othersStartedFor = new Set<string>()

function rememberLaunchAgent(workflowId: string, title: string): { workflowId: string; title: string } {
  launchAgentCache = { workflowId, title: title.trim() || KPI_LAUNCH_DEFAULT_TITLE }
  return launchAgentCache
}

async function resolveLaunchAgent(force = false): Promise<{ workflowId: string; title: string } | null> {
  if (!force && launchAgentCache) return launchAgentCache
  launchAgentCache = null
  const rows = await api.listWorkflows()
  const candidates = rows
    .filter((item) => launchAgentTitle(item.title))
    .sort((a, b) => Number(b.phase === 'done') - Number(a.phase === 'done'))
  let fallback: { workflowId: string; title: string } | null = null
  for (const item of candidates) {
    const record = await api.getWorkflow(item.id).catch(() => null)
    const title = record?.title || item.title
    const notes = record?.notes || ''
    if (notes.includes(KPI_LAUNCH_PLATFORM_ID)) {
      return rememberLaunchAgent(record?.id || item.id, title)
    }
    if (!fallback && launchAgentTitle(title)) {
      fallback = { workflowId: record?.id || item.id, title }
    }
  }
  if (fallback) return rememberLaunchAgent(fallback.workflowId, fallback.title)
  return null
}

function stepsText(day: string, month: string): string {
  return (
    `1) onec.position_holders: position, department, as_of=${day}. ФИО бери из people[].fio. ` +
    '2) Для каждого ФИО запусти уже готовые модули этой должности ' +
    `(python <module>.py --fio "<ФИО>" --month ${month}). stdout модуля — кэш: положи его в metrics[].output, ` +
    'файлы в Documents/kpi/cache не пиши. ' +
    `3) Собери отчёт существующим report_<profile_id>.py --position --fio --month ${month}. ` +
    '4) Один вызов kpi.publish_position_result на должность: profile_id, ' +
    `month=${month}, status=done, people=[{fio, status, report_path — абсолютный путь к xlsx, ` +
    'metrics: [{metric_code, output — JSON вывода модуля}]}]. ' +
    'Если status=empty или not_found — сразу kpi.publish_position_result со status=done и people=[]. ' +
    'Если должность посчитать не удалось — kpi.publish_position_result со status=failed и error. ' +
    'Новый модуль, новую методику и код отчёта не пиши, в базу только SELECT.'
  )
}

export function kpiOwnTask(profile: KpiRunProfile, day: string): string {
  const month = day.slice(0, 7)
  const place = profile.department ? `, подразделение «${profile.department}»` : ''
  return (
    `Ежедневный расчёт KPI за ${day} (Europe/Moscow), месяц ${month}. ` +
    `Считай только должность «${profile.position}»${place}, profile_id ${profile.profileId}. ` +
    'Другие должности не трогай, даже если журнал прошлого запуска их перечисляет. ' +
    stepsText(day, month) +
    ' Если onec.position_holders вернул ambiguous — уточни подразделение через ask_user.'
  )
}

export function kpiOthersTask(profiles: KpiRunProfile[], day: string): string {
  const month = day.slice(0, 7)
  const list = profiles
    .map(
      (item, index) =>
        `${index + 1}. «${item.position}», подразделение «${item.department || '—'}», profile_id ${item.profileId}`
    )
    .join('\n')
  return (
    `Фоновый ежедневный расчёт KPI за ${day} (Europe/Moscow), месяц ${month}. ` +
    'Посчитай по очереди только эти должности:\n' +
    `${list}\n` +
    'Для каждой должности: ' +
    stepsText(day, month) +
    ' Публикуй результат сразу после каждой должности, потом переходи к следующей. ' +
    'Вопросов не задавай, ask_user не вызывай: никто не ответит. ' +
    'Если onec.position_holders вернул ambiguous или у должности нет подразделения — ' +
    'kpi.publish_position_result со status=failed, в error причина и варианты, и иди дальше.'
  )
}

export interface KpiDailyRun {
  phase: KpiDailyPhase
  today: KpiTodayRun | null
  run: RunEntry | undefined
  workflowId: string
  title: string
  error: string
  retry: () => void
  refresh: () => void
}

export function useKpiDailyRun(user: UserProfile | undefined, onDone: () => void): KpiDailyRun {
  const runs = useRuns()
  const [phase, setPhase] = useState<KpiDailyPhase>('checking')
  const [today, setToday] = useState<KpiTodayRun | null>(null)
  const [agent, setAgent] = useState<{ workflowId: string; title: string } | null>(launchAgentCache)
  const [error, setError] = useState('')
  const busyRef = useRef(false)
  const queuedRef = useRef<{ autoStart: boolean; retryFailed?: boolean } | null>(null)
  const forceResolveRef = useRef(false)
  const ownStartedRef = useRef(false)
  const sawRunningRef = useRef(false)
  const autoRetriedRef = useRef(false)
  const onDoneRef = useRef(onDone)
  onDoneRef.current = onDone
  const userId = user?.id || ''

  const startOthers = useCallback(
    async (day: string) => {
      if (!day || othersStartedFor.has(day)) return
      othersStartedFor.add(day)
      try {
        const found = agent || (await resolveLaunchAgent())
        if (!found) return
        const claim = await api.claimKpiTodayRun('others')
        if (!claim.profiles.length) return
        runs.startRun({
          workflowId: found.workflowId,
          title: found.title,
          message: kpiOthersTask(claim.profiles, claim.day || day),
          hidden: true
        })
      } catch {
        othersStartedFor.delete(day)
      }
    },
    [agent, runs]
  )

  const startOwn = useCallback(
    async (retryFailed: boolean) => {
      const force = forceResolveRef.current
      forceResolveRef.current = false
      setError('')
      setPhase('running')
      const found = (!force && agent) || (await resolveLaunchAgent(force))
      if (!found) {
        setPhase('failed')
        setError('В «Моих агентах» нет карточки «Запуск модулей KPI».')
        return
      }
      setAgent(found)
      const live = runs.getRun(found.workflowId)
      if (live?.state.running) {
        ownStartedRef.current = true
        sawRunningRef.current = true
        setPhase('running')
        return
      }
      // A visible start cancels every sidecar run of this agent, the hidden one included.
      if (runs.getRun(hiddenEntryKey(found.workflowId))?.state.running) {
        setPhase('waiting')
        return
      }
      const claim = await api.claimKpiTodayRun('own', retryFailed)
      if (!claim.granted || !claim.profiles[0]) {
        if (claim.reason === 'no_modules') {
          setPhase('unavailable')
          void startOthers(claim.day)
          return
        }
        setPhase('waiting')
        return
      }
      ownStartedRef.current = true
      sawRunningRef.current = false
      setError('')
      setPhase('running')
      runs.startRun({
        workflowId: found.workflowId,
        title: found.title,
        message: kpiOwnTask(claim.profiles[0], claim.day)
      })
    },
    [agent, runs, startOthers]
  )

  const check = useCallback(
    async (opts: { autoStart: boolean; retryFailed?: boolean } = { autoStart: true }) => {
      if (busyRef.current) {
        if (opts.retryFailed) queuedRef.current = opts
        return
      }
      busyRef.current = true
      try {
        const status = await api.getKpiTodayRun()
        setToday(status)
        const restart = Boolean(opts.autoStart || opts.retryFailed)
        switch (status.status) {
          case 'ready':
            setPhase('ready')
            setError('')
            onDoneRef.current()
            void startOthers(status.day)
            break
          case 'missing':
          case 'running_here':
            if (restart) await startOwn(Boolean(opts.retryFailed))
            else setPhase(status.status === 'missing' ? 'failed' : 'running')
            break
          case 'failed':
            if (restart) {
              await startOwn(true)
            } else {
              setPhase('failed')
              setError(status.run?.error || 'Расчёт KPI сегодня не удался.')
              void startOthers(status.day)
            }
            break
          case 'running_elsewhere':
            setPhase('waiting')
            void startOthers(status.day)
            break
          default:
            setPhase('unavailable')
            void startOthers(status.day)
        }
      } catch (err) {
        setPhase('failed')
        setError(err instanceof Error ? err.message : 'Не удалось проверить расчёт KPI')
      } finally {
        busyRef.current = false
        const queued = queuedRef.current
        queuedRef.current = null
        if (queued) void check(queued)
      }
    },
    [startOthers, startOwn]
  )

  useEffect(() => {
    if (!userId) return
    void check({ autoStart: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  useEffect(() => {
    if (phase !== 'waiting') return
    const timer = window.setInterval(() => void check({ autoStart: true }), ELSEWHERE_POLL_MS)
    return () => window.clearInterval(timer)
  }, [phase, check])

  const run = agent ? runs.entries[agent.workflowId] : undefined
  const running = Boolean(run?.state.running)

  useEffect(() => {
    if (!ownStartedRef.current) return
    if (running) {
      sawRunningRef.current = true
      return
    }
    if (!sawRunningRef.current) return
    ownStartedRef.current = false
    sawRunningRef.current = false
    void (async () => {
      try {
        const status = await api.getKpiTodayRun()
        setToday(status)
        if (status.status === 'ready') {
          setPhase('ready')
          setError('')
          onDoneRef.current()
          void startOthers(status.day)
        } else if (!autoRetriedRef.current) {
          autoRetriedRef.current = true
          await startOwn(true)
        } else {
          setPhase('failed')
          setError(
            status.run?.error ||
              run?.state.error ||
              'Агент закончил работу, но не выгрузил расчёт на сервер.'
          )
          onDoneRef.current()
          void startOthers(status.day)
        }
      } catch (err) {
        setPhase('failed')
        setError(err instanceof Error ? err.message : 'Не удалось проверить расчёт KPI')
      }
    })()
  }, [running, run?.state.error, startOthers, startOwn])

  const retry = useCallback(() => {
    forceResolveRef.current = true
    autoRetriedRef.current = false
    launchAgentCache = null
    setAgent(null)
    setError('')
    setPhase('running')
    void check({ autoStart: true, retryFailed: true })
  }, [check])
  const refresh = useCallback(() => void check({ autoStart: false }), [check])

  return {
    phase,
    today,
    run,
    workflowId: agent?.workflowId || '',
    title: agent?.title || KPI_LAUNCH_DEFAULT_TITLE,
    error,
    retry,
    refresh
  }
}
