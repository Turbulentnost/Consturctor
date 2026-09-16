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
import { devGatewayCredentials, hasComPassword, gatewaySessionPassword } from '../store/session'
import { isOneCAuthFailure, userFacingOneCError } from './onecSessionHints'
import { isTechnicalTurboMessage } from './turboSession'
import { useRuns } from '../store/runs'
import { erpActorFio, outlookMailboxAddress } from './userContext'
import {
  agentToProcessRow,
  erpTaskToProcessRow,
  mailRowToProcessRow,
  meetingToProcessRow,
  turboProjectToProcessRow
} from './specV04Mappers'
import type { SpecMailRow, SpecProcessRow, SpecProjectRow, SpecTaskRow } from './specV04DemoData'
import { agentLaunchesToday, useWorkplaceData } from './WorkplaceBoard'
import { useGridDataRefreshContext } from './GridDataRefreshContext'
import {
  dedupeSpecTaskRows,
  loadOrchestratorErpTasks,
  loadOrchestratorOutlookMailWeek,
  loadOrchestratorTurboPortfolio,
  loadOrchestratorTurboTaskRows,
  ORCH_SOURCE_ID
} from './orchestratorTaskSources'
import { isLiveRunState, liveRunProgress } from '../store/liveRun'
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
  allProcessRows: [],
  meetingCount: 0,
  meetingCountToday: 0,
  meetings: [],
  meetingsLoading: false,
  erpError: '',
  erpLoading: false,
  turboError: '',
  turboLoading: false,
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
  const liveRuns = useRuns()
  const { agents, loading: agentsLoading } = useWorkplaceData({
    userId: user.id || '',
    fio: erpFio
  })

  const [turboNoSession, setTurboNoSession] = useState(false)
  const [error, setError] = useState('')
  const [erpTasks, setErpTasks] = useState<SpecTaskRow[]>([])
  const [turboTasks, setTurboTasks] = useState<SpecTaskRow[]>([])
  const [erpSource, setErpSource] = useState('—')
  const [erpError, setErpError] = useState('')
  const [erpLoading, setErpLoading] = useState(true)
  const [erpSecondaryHint, setErpSecondaryHint] = useState('')
  const [projects, setProjects] = useState<SpecProjectRow[]>([])
  const [turboSource, setTurboSource] = useState('—')
  const [turboError, setTurboError] = useState('')
  const [turboLoading, setTurboLoading] = useState(true)
  const [mailRows, setMailRows] = useState<SpecMailRow[]>([])
  const [mailSource, setMailSource] = useState('—')
  const [mailLoading, setMailLoading] = useState(true)
  const [mailImapPrimary, setMailImapPrimary] = useState(false)
  const [mailComError, setMailComError] = useState('')
  const [mailImapError, setMailImapError] = useState('')
  const [mailImapStatus, setMailImapStatus] = useState('')
  const [meetings, setMeetings] = useState<MeetingEvent[]>([])
  const [meetingsLoading, setMeetingsLoading] = useState(true)
  const [oneCAuthFailure, setOneCAuthFailure] = useState(false)
  const erpFetchSeqRef = useRef(0)
  const turboFetchSeqRef = useRef(0)
  const takeHardRefreshRef = useRef(takeHardRefresh)
  takeHardRefreshRef.current = takeHardRefresh

  useEffect(() => {
    if (!user.id) {
      setErpLoading(false)
      return
    }
    const has1cPassword = hasComPassword() || Boolean(gatewaySessionPassword() || devGatewayCredentials().password)
    if (!has1cPassword) {
      setErpLoading(false)
      setErpTasks([])
      setErpError('')
      setOneCAuthFailure(true)
      setErpSource('—')
      return
    }
    let alive = true
    const fetchSeq = ++erpFetchSeqRef.current
    const forceRefresh = takeHardRefreshRef.current()
    setErpLoading(true)
    setErpTasks([])
    setError('')
    // #region agent log
    const _erpT0 = Date.now()
    fetch('http://127.0.0.1:7847/ingest/b2a622e9-6027-4fae-9a68-3d036eb3c49e',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'d8a6bb'},body:JSON.stringify({sessionId:'d8a6bb',runId:'pre-fix',hypothesisId:'H4',location:'SpecV04SourcesProvider.tsx:erp-start',message:'erp fetch start',data:{generation,forceRefresh,comCredsRevision},timestamp:Date.now()})}).catch(()=>{})
    // #endregion
    void loadOrchestratorErpTasks(user, erpFio, { forceRefresh })
      .then((erp) => {
        if (!alive || fetchSeq !== erpFetchSeqRef.current) return
        setErpTasks(dedupeSpecTaskRows(erp.tasks))
        setErpSource(erp.sourceLabel)
        setErpError(userFacingOneCError(erp.error))
        setErpSecondaryHint(erp.erpSecondaryHint || '')
        setOneCAuthFailure(erp.oneCAuthFailure)
      })
      .catch((err: unknown) => {
        if (!alive || fetchSeq !== erpFetchSeqRef.current) return
        setErpTasks([])
        setErpError(userFacingOneCError(err instanceof Error ? err.message : ''))
        setOneCAuthFailure(isOneCAuthFailure(err instanceof Error ? err.message : ''))
      })
      .finally(() => {
        if (alive && fetchSeq === erpFetchSeqRef.current) setErpLoading(false)
        // #region agent log
        fetch('http://127.0.0.1:7847/ingest/b2a622e9-6027-4fae-9a68-3d036eb3c49e',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'d8a6bb'},body:JSON.stringify({sessionId:'d8a6bb',runId:'pre-fix',hypothesisId:'H4',location:'SpecV04SourcesProvider.tsx:erp-end',message:'erp fetch end',data:{ms:Date.now()-_erpT0,alive},timestamp:Date.now()})}).catch(()=>{})
        // #endregion
      })
    return () => {
      alive = false
    }
  }, [user.id, erpFio, generation, comCredsRevision])

  useEffect(() => {
    if (!user.id) {
      setTurboLoading(false)
      setTurboNoSession(false)
      return
    }
    let alive = true
    const fetchSeq = ++turboFetchSeqRef.current
    setTurboLoading(true)
    setTurboTasks([])
    setProjects([])
    // #region agent log
    const _turboT0 = Date.now()
    fetch('http://127.0.0.1:7847/ingest/b2a622e9-6027-4fae-9a68-3d036eb3c49e',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'d8a6bb'},body:JSON.stringify({sessionId:'d8a6bb',runId:'pre-fix',hypothesisId:'H3',location:'SpecV04SourcesProvider.tsx:turbo-start',message:'turbo fetch start',data:{generation,comCredsRevision},timestamp:Date.now()})}).catch(()=>{})
    // #endregion
    void (async () => {
      try {
        const turbo = await loadOrchestratorTurboPortfolio(user, erpFio)
        if (!alive || fetchSeq !== turboFetchSeqRef.current) return
        setProjects(turbo.projects)
        setTurboSource(turbo.sourceLabel)
        setTurboNoSession(turbo.turboNoSession)
        const turboTasksLoad = await loadOrchestratorTurboTaskRows(
          user,
          erpFio,
          turbo.projects,
          turbo.turboNoSession
        )
        if (!alive || fetchSeq !== turboFetchSeqRef.current) return
        setTurboTasks(dedupeSpecTaskRows(turboTasksLoad.tasks))
        const turboErr = userFacingOneCError(turbo.error || turboTasksLoad.error || '')
        setTurboError(isTechnicalTurboMessage(turboErr) ? '' : turboErr)
      } catch (err) {
        if (!alive || fetchSeq !== turboFetchSeqRef.current) return
        setTurboTasks([])
        setTurboError(
          userFacingOneCError(err instanceof Error ? err.message : '') ||
            'Не удалось загрузить TurboProject'
        )
      } finally {
        if (alive && fetchSeq === turboFetchSeqRef.current) setTurboLoading(false)
        // #region agent log
        fetch('http://127.0.0.1:7847/ingest/b2a622e9-6027-4fae-9a68-3d036eb3c49e',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'d8a6bb'},body:JSON.stringify({sessionId:'d8a6bb',runId:'pre-fix',hypothesisId:'H3',location:'SpecV04SourcesProvider.tsx:turbo-end',message:'turbo fetch end',data:{ms:Date.now()-_turboT0,alive},timestamp:Date.now()})}).catch(()=>{})
        // #endregion
      }
    })()
    return () => {
      alive = false
    }
  }, [user.id, erpFio, generation, comCredsRevision])

  useEffect(() => {
    if (!user.id) {
      setMailLoading(false)
      return
    }
    let alive = true
    setMailLoading(true)
    void loadOrchestratorOutlookMailWeek(outlookMailbox)
      .then((mail) => {
        if (!alive) return
        setMailRows(mail.rows)
        setMailSource(mail.sourceLabel)
        setMailImapPrimary(mail.imapPrimary)
        setMailComError(mail.comError)
        setMailImapError(mail.imapError)
        setMailImapStatus(mail.imapStatus)
      })
      .catch((err: unknown) => {
        if (!alive) return
        setMailComError(err instanceof Error ? err.message : 'Не удалось загрузить почту')
        setMailImapPrimary(false)
      })
      .finally(() => {
        if (alive) setMailLoading(false)
      })
    return () => {
      alive = false
    }
  }, [user.id, outlookMailbox, generation])

  useEffect(() => {
    if (!user.id) {
      setMeetingsLoading(false)
      return
    }
    let alive = true
    setMeetingsLoading(true)
    void ensureOutlookMeetings('week', new Date(), { owner: erpFio })
      .then((cal) => {
        if (alive) setMeetings(dedupeMeetingEvents(cal.meetings || []))
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
    return agents.map((agent) => {
      const row = agentToProcessRow(agent)
      const live = liveRuns.entries[agent.workflowId]
      if (!live || !isLiveRunState(live.state)) return row
      return {
        ...row,
        progress: liveRunProgress({
          running: live.state.running,
          pendingQuestion: live.state.pendingQuestion,
          pendingHitl: live.state.pendingHitl,
          timing: live.state.timing,
          items: live.state.items
        })
      }
    })
  }, [agents, liveRuns.entries])

  const todayProcessRows = useMemo(() => {
    const today = new Date()
    return agents
      .filter((agent) => agentLaunchesToday(agent, today))
      .map(agentToProcessRow)
  }, [agents])

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
  const sourcesLoading = erpLoading || turboLoading
  const value = useMemo(
    (): SpecV04SourcesState => ({
      sourcesLoading,
      tableLoading,
      loading: sourcesLoading || tableLoading,
      error,
      outlookMailbox,
      erpFio,
      erpError,
      erpLoading,
      turboError,
      turboLoading,
      erpSecondaryHint,
      erpTasks,
      erpTaskCount: erpTasks.length,
      turboTasks,
      turboTaskCount: turboTasks.length,
      allTaskCount,
      projects,
      projectCount: projects.length,
      mailRows,
      mailCount: mailRows.length,
      mailLoading,
      mailImapPrimary,
      mailComError,
      mailImapError,
      mailImapStatus,
      todayProcessRows,
      processRows: regRows,
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
      erpLoading,
      turboError,
      turboLoading,
      erpSecondaryHint,
      erpTasks,
      turboTasks,
      allTaskCount,
      projects,
      mailRows,
      mailLoading,
      mailImapPrimary,
      mailComError,
      mailImapError,
      mailImapStatus,
      regRows,
      todayProcessRows,
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
