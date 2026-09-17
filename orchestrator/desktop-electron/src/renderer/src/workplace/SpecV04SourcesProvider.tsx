import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode
} from 'react'
import type { UserProfile } from '../api/types'
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
import { fetchOrchestratorTaskSources, ORCH_SOURCE_ID } from './orchestratorTaskSources'
import type { SpecV04SourcesState } from './useSpecV04Data'

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
  erpSecondaryHint: '',
  sources: { erp: '—', turbo: '—', mail: '—' },
  turboNoSession: false,
  comPasswordInSession: false,
  oneCAuthFailure: false,
  user: null
}

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
  const [meetings, setMeetings] = useState<MeetingEvent[]>([])
  const [meetingsLoading, setMeetingsLoading] = useState(true)
  const [oneCAuthFailure, setOneCAuthFailure] = useState(false)
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
        const bundle = await fetchOrchestratorTaskSources(user, erpFio, outlookMailbox, {
          forceRefresh: takeHardRefresh()
        })
        if (!alive) return

        setErpTasks(bundle.erp.tasks)
        setErpSource(bundle.erp.tasks.length ? bundle.erp.sourceLabel : bundle.erp.sourceLabel)
        setErpError(bundle.erp.error)
        setErpSecondaryHint(bundle.erp.erpSecondaryHint || '')
        setOneCAuthFailure(bundle.erp.oneCAuthFailure)
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
          setError((prev) => (prev ? `${prev} · ${bundle.turbo.hint}` : bundle.turbo.hint))
        }
        if (bundle.turboTasks.error?.trim() && bundle.turboTasks.tasks.length) {
          setErpSecondaryHint((prev) =>
            prev ? `${prev} · Turbo: ${bundle.turboTasks.error}` : `Turbo: ${bundle.turboTasks.error}`
          )
        }

        setMailRows(bundle.mail.rows)
        setMailSource(bundle.mail.sourceLabel)
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
    if (!user.id) {
      setMeetingsLoading(false)
      return
    }
    let alive = true
    setMeetingsLoading(true)
    const today = new Date()
    void ensureOutlookMeetings('week', today, { owner: erpFio })
      .then((cal) => {
        if (!alive) return
        setMeetings(dedupeMeetingEvents(cal.meetings || []))
      })
      .catch(() => {
        if (alive) setMeetings([])
      })
      .finally(() => {
        if (alive) setMeetingsLoading(false)
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
      erpSecondaryHint,
      erpTasks,
      erpTaskCount: erpTasks.length,
      turboTasks,
      turboTaskCount: turboTasks.length,
      turboLoading: sourcesLoading,
      turboError: turboTasksError,
      allTaskCount,
      projects,
      projectCount: projects.length,
      mailRows,
      mailCount: mailRows.length,
      processRows: regRows,
      todayProcessRows,
      boardEvents: board.events,
      boardAgents: board.agents,
      allProcessRows,
      meetingCount: meetings.length,
      meetingCountToday,
      meetings,
      meetingsLoading,
      sources: {
        erp: erpSource || ORCH_SOURCE_ID.erpPm,
        turbo: turboSource || ORCH_SOURCE_ID.turboProject,
        mail: mailSource
      },
      turboNoSession,
      comPasswordInSession: hasComPassword(),
      oneCAuthFailure,
      user
    }),
    [
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
      regRows,
      todayProcessRows,
      board.events,
      board.agents,
      allProcessRows,
      meetings,
      meetingsLoading,
      meetingCountToday,
      erpSource,
      turboSource,
      mailSource,
      turboNoSession,
      comCredsRevision,
      oneCAuthFailure,
      user
    ]
  )

  return <SpecV04SourcesContext.Provider value={value}>{children}</SpecV04SourcesContext.Provider>
}

export function useSpecV04SourcesContext(): SpecV04SourcesState {
  return useContext(SpecV04SourcesContext)
}
