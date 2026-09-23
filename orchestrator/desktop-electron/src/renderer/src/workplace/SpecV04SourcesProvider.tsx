import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode
} from 'react'
import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { platformTaskToRow } from './platformTasks'
import {
  countMeetingsOnDay,
  dedupeMeetingEvents,
  ensureOutlookMeetings,
  type MeetingEvent
} from '../utils/outlookMeetings'
import { hasComPassword } from '../store/session'
import { erpActorFio, outlookMailboxAddress } from './userContext'
import {
  agentToProcessRow,
  erpTaskToProcessRow,
  mailRowToProcessRow,
  meetingToProcessRow,
  turboProjectToProcessRow
} from './specV04Mappers'
import type { SpecMailRow, SpecProcessRow, SpecProjectRow, SpecTaskRow } from './specV04DemoData'
import { useWorkplaceData } from './WorkplaceBoard'
import { summarizeDayLaunches } from './todayKpiLaunches'
import { useGridDataRefreshContext } from './GridDataRefreshContext'
import { fetchOrchestratorCoreSources, ORCH_SOURCE_ID } from './orchestratorTaskSources'
import { loadOrchestratorMail } from './mailProbe'
import { useWorkplacePeriod } from './workplacePeriod'
import type { SpecV04SourcesState } from './useSpecV04Data'
import { diffAndStoreOneCTaskSnapshot } from './onecTaskSnapshot'

const EMPTY: SpecV04SourcesState = {
  sourcesLoading: false,
  tableLoading: false,
  loading: false,
  error: '',
  outlookMailbox: '',
  erpFio: '',
  erpTasks: [],
  erpTaskCount: 0,
  turboTasks: [],
  turboTaskCount: 0,
  turboLoading: false,
  turboError: '',
  allTaskCount: 0,
  projects: [],
  projectCount: 0,
  mailRows: [],
  mailCount: 0,
  mailLoading: false,
  mailImapPrimary: false,
  mailComError: '',
  mailImapError: '',
  mailImapStatus: '',
  processRows: [],
  todayProcessRows: [],
  boardEvents: [],
  boardAgents: [],
  allProcessRows: [],
  meetingCount: 0,
  meetingCountToday: 0,
  meetings: [],
  meetingsLoading: false,
  erpError: '',
  erpLoading: false,
  erpSecondaryHint: '',
  sources: { erp: '—', turbo: '—', mail: '—' },
  turboNoSession: false,
  comPasswordInSession: false,
  oneCAuthFailure: false,
  newOneCTaskKeys: new Set(),
  platformTasks: [],
  platformTaskCount: 0,
  platformLoading: false,
  platformError: '',
  user: null
}

const PLATFORM_POLL_MS = 60_000
/** Исполненные и отклонённые задачи платформы видны ещё неделю — чтобы постановщик увидел итог. */
const PLATFORM_CLOSED_KEEP_MS = 7 * 24 * 3600 * 1000

export const SpecV04SourcesContext = createContext<SpecV04SourcesState>(EMPTY)

export function SpecV04SourcesProvider({
  user,
  comCredsRevision = 0,
  children
}: {
  user: UserProfile
  /** From getComCredentialsRevision() — refetch 1C after password re-entry. */
  comCredsRevision?: number
  children: ReactNode
}): React.JSX.Element {
  const erpFio = erpActorFio(user)
  const outlookMailbox = outlookMailboxAddress(user)
  const { from: mailPeriodFrom, to: mailPeriodTo } = useWorkplacePeriod()
  const mailPeriodKey = `${mailPeriodFrom}:${mailPeriodTo}`
  const mailPeriodKeyRef = useRef('')
  const { generation, takeHardRefresh } = useGridDataRefreshContext()
  const { agents, board, loading: agentsLoading } = useWorkplaceData({
    userId: user.id || '',
    fio: erpFio
  })

  const [sourcesLoading, setSourcesLoading] = useState(true)
  const [turboNoSession, setTurboNoSession] = useState(false)
  const [error, setError] = useState('')
  const [erpTasks, setErpTasks] = useState<SpecTaskRow[]>([])
  const [turboTasks, setTurboTasks] = useState<SpecTaskRow[]>([])
  const [turboTasksError, setTurboTasksError] = useState('')
  const [erpSource, setErpSource] = useState('—')
  const [erpError, setErpError] = useState('')
  const [erpSecondaryHint, setErpSecondaryHint] = useState('')
  const [projects, setProjects] = useState<SpecProjectRow[]>([])
  const [turboSource, setTurboSource] = useState('—')
  const [mailRows, setMailRows] = useState<SpecMailRow[]>([])
  const [mailSource, setMailSource] = useState('—')
  const [mailComError, setMailComError] = useState('')
  const [mailImapError, setMailImapError] = useState('')
  const [mailImapPrimary, setMailImapPrimary] = useState(false)
  const [mailImapStatus, setMailImapStatus] = useState('')
  const [meetings, setMeetings] = useState<MeetingEvent[]>([])
  const [oneCAuthFailure, setOneCAuthFailure] = useState(false)
  const [newOneCTaskKeys, setNewOneCTaskKeys] = useState<ReadonlySet<string>>(() => new Set())
  const snapshotUserRef = useRef('')
  const hasLoadedSourcesRef = useRef(false)

  useEffect(() => {
    if (!user.id) {
      setSourcesLoading(false)
      setTurboNoSession(false)
      return
    }
    let alive = true
    ;(async () => {
      if (!hasLoadedSourcesRef.current) setSourcesLoading(true)
      setError('')
      setTurboTasksError('')
      setOneCAuthFailure(false)
      try {
        const bundle = await fetchOrchestratorCoreSources(user, erpFio, {
          forceRefresh: takeHardRefresh()
        })
        if (!alive) return

        setErpTasks(bundle.erp.tasks)
        setErpSource(bundle.erp.tasks.length ? bundle.erp.sourceLabel : bundle.erp.sourceLabel)
        setErpError(bundle.erp.error)
        setErpSecondaryHint(bundle.erp.erpSecondaryHint || '')
        setOneCAuthFailure(bundle.erp.oneCAuthFailure)
        const erpLoaded =
          !bundle.erp.oneCAuthFailure &&
          bundle.erp.sourceLabel !== 'stub' &&
          (bundle.erp.tasks.length > 0 || !bundle.erp.error?.trim())
        if (erpLoaded && snapshotUserRef.current !== user.id) {
          snapshotUserRef.current = user.id
          setNewOneCTaskKeys(diffAndStoreOneCTaskSnapshot(user.id, bundle.erp.tasks))
        }
        const blockingErp = bundle.erp.error?.trim() || ''
        if (blockingErp) {
          setError((prev) => (prev && prev.includes(blockingErp) ? prev : blockingErp))
        }

        setProjects(bundle.turbo.projects)
        setTurboSource(bundle.turbo.sourceLabel)
        setTurboNoSession(bundle.turbo.turboNoSession)
        setTurboTasks(bundle.turboTasks.tasks)
        setTurboTasksError(bundle.turboTasks.error || '')
        if (bundle.turbo.hint?.trim() && !bundle.turbo.projects.length) {
          setTurboTasksError((prev) =>
            prev ? `${prev} · ${bundle.turbo.hint}` : bundle.turbo.hint
          )
        }
        if (bundle.turboTasks.error?.trim() && bundle.turboTasks.tasks.length) {
          setErpSecondaryHint((prev) =>
            prev ? `${prev} · Turbo: ${bundle.turboTasks.error}` : `Turbo: ${bundle.turboTasks.error}`
          )
        }

      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : 'Не удалось загрузить данные')
      } finally {
        if (alive) {
          hasLoadedSourcesRef.current = true
          setSourcesLoading(false)
        }
      }
    })()
    return () => {
      alive = false
    }
  }, [user.id, erpFio, outlookMailbox, generation, comCredsRevision])

  useEffect(() => {
    if (!user.id) return
    let alive = true
    void loadOrchestratorMail(
      outlookMailbox,
      { dateFrom: mailPeriodFrom, dateTo: mailPeriodTo },
      { forceOutlook: takeHardRefresh() }
    ).then((mail) => {
      if (!alive) return
      setMailRows(mail.rows)
      setMailSource(mail.sourceLabel)
      setMailComError(mail.comError || '')
      setMailImapError(mail.imapError || '')
      setMailImapPrimary(Boolean(mail.imapPrimary))
      setMailImapStatus(mail.imapStatus || '')
      mailPeriodKeyRef.current = mailPeriodKey
    })
    return () => {
      alive = false
    }
  }, [user.id, outlookMailbox, mailPeriodFrom, mailPeriodTo, mailPeriodKey, generation])

  useEffect(() => {
    if (!user.id) return
    let alive = true
    const today = new Date()
    void ensureOutlookMeetings('week', today, { owner: erpFio })
      .then((cal) => {
        if (alive) setMeetings(dedupeMeetingEvents(cal.meetings || []))
      })
      .catch(() => {
        if (alive) setMeetings([])
      })
    return () => {
      alive = false
    }
  }, [user.id, erpFio, generation])

  const regRows = useMemo(() => {
    return agents.filter((a) => !a.standalone).map(agentToProcessRow)
  }, [agents])

  const todayLaunch = useMemo(
    () => summarizeDayLaunches(board.events, board.agents, new Date()),
    [board.agents, board.events]
  )

  const todayProcessRows = useMemo(() => {
    const due = new Set(todayLaunch.agentIds)
    const done = new Set(todayLaunch.agentDoneIds)
    return agents
      .filter((agent) => !agent.standalone && due.has(agent.workflowId))
      .map((agent) => {
        const row = agentToProcessRow(agent)
        if (done.has(agent.workflowId)) {
          return { ...row, status: 'Выполнен', statusTone: 'green' as const, progress: 100 }
        }
        return { ...row, status: 'В работе', statusTone: 'blue' as const }
      })
  }, [agents, todayLaunch.agentDoneIds, todayLaunch.agentIds])

  const allTaskCount = useMemo(
    () => erpTasks.length + turboTasks.length + regRows.length,
    [erpTasks.length, turboTasks.length, regRows.length]
  )

  const [platformTasks, setPlatformTasks] = useState<SpecTaskRow[]>([])
  const [platformLoading, setPlatformLoading] = useState(true)
  const [platformError, setPlatformError] = useState('')

  // Задачи от коллег приходят без действий пользователя, поэтому список ещё и опрашиваем.
  useEffect(() => {
    if (!user.id) return
    let alive = true
    const load = (): void => {
      void api
        .listPlatformTasks()
        .then((items) => {
          if (!alive) return
          const keepSince = Date.now() - PLATFORM_CLOSED_KEEP_MS
          setPlatformTasks(
            items
              .filter((task) => task.status === 'open' || new Date(task.statusAt || 0).getTime() >= keepSince)
              .map(platformTaskToRow)
          )
          setPlatformError('')
        })
        .catch((err: unknown) => {
          if (alive) setPlatformError(err instanceof Error ? err.message : 'Задачи платформы не загрузились')
        })
        .finally(() => {
          if (alive) setPlatformLoading(false)
        })
    }
    load()
    const timer = window.setInterval(load, PLATFORM_POLL_MS)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [user.id, generation])

  const allProcessRows = useMemo(() => {
    const erpRows = erpTasks.map(erpTaskToProcessRow)
    const projRows = projects.map(turboProjectToProcessRow)
    const mailProcessRows = mailRows.map((m, index) => mailRowToProcessRow(m, index))
    const meetRows = meetings.map(meetingToProcessRow)
    return [...regRows, ...erpRows, ...projRows, ...mailProcessRows, ...meetRows]
  }, [regRows, erpTasks, projects, mailRows, meetings])

  const meetingCountToday = useMemo(() => countMeetingsOnDay(meetings), [meetings])

  const tableLoading = agentsLoading
  const value = useMemo(
    (): SpecV04SourcesState => ({
      sourcesLoading,
      tableLoading,
      loading: sourcesLoading || tableLoading,
      error,
      outlookMailbox,
      erpFio,
      erpError,
      erpLoading: sourcesLoading,
      erpSecondaryHint,
      erpTasks,
      erpTaskCount: erpTasks.length,
      turboTasks,
      turboTaskCount: turboTasks.length,
      turboLoading: sourcesLoading,
      turboError: turboTasksError,
      allTaskCount: allTaskCount + platformTasks.length,
      projects,
      projectCount: projects.length,
      mailRows,
      mailCount: mailRows.length,
      mailLoading: sourcesLoading,
      mailImapPrimary,
      mailComError,
      mailImapError,
      mailImapStatus,
      processRows: regRows,
      todayProcessRows,
      boardEvents: board.events,
      boardAgents: board.agents,
      allProcessRows,
      meetingCount: meetings.length,
      meetingCountToday,
      meetings,
      meetingsLoading: false,
      sources: {
        erp: erpSource || ORCH_SOURCE_ID.erpPm,
        turbo: turboSource || ORCH_SOURCE_ID.turboProject,
        mail: mailSource
      },
      turboNoSession,
      comPasswordInSession: hasComPassword(),
      oneCAuthFailure,
      newOneCTaskKeys,
      platformTasks,
      platformTaskCount: platformTasks.length,
      platformLoading,
      platformError,
      user
    }),
    [
      platformTasks,
      platformLoading,
      platformError,
      sourcesLoading,
      tableLoading,
      error,
      outlookMailbox,
      erpFio,
      erpError,
      erpSecondaryHint,
      erpTasks,
      turboTasks,
      allTaskCount,
      turboTasksError,
      projects,
      mailRows,
      mailComError,
      mailImapError,
      mailImapPrimary,
      mailImapStatus,
      regRows,
      todayProcessRows,
      board.events,
      board.agents,
      allProcessRows,
      meetings,
      meetingCountToday,
      erpSource,
      turboSource,
      mailSource,
      turboNoSession,
      comCredsRevision,
      oneCAuthFailure,
      newOneCTaskKeys,
      user
    ]
  )

  return <SpecV04SourcesContext.Provider value={value}>{children}</SpecV04SourcesContext.Provider>
}

export function useSpecV04SourcesContext(): SpecV04SourcesState {
  return useContext(SpecV04SourcesContext)
}
