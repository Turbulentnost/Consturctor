import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAgentSession, type AgentResult, type UseAgentSessionValue } from './useAgentSession'

export type FormationPhase = 'designing' | 'designed' | 'executing' | 'tested'

export interface FormationController {
  session: UseAgentSessionValue
  workflowId: string
  title: string
  designDone: boolean
  demoDone: boolean
  designDraft: string
  phase: FormationPhase
  running: boolean
  awaiting: boolean
  /** Latest plain agent output (conclusions), excluding thinking/tool calls. */
  latestOutput: string
  /** A formation is being tracked and has not fully finished yet. */
  inProgress: boolean
  /** Attach to (or start) the formation for a workflow. Idempotent per workflow. */
  begin: (workflowId: string, title: string) => void
  /** Re-run the trial run (demo). */
  runDemo: () => void
  /** Send a follow-up message to the running agent. */
  sendMessage: (shownMessage: string, message: string, filePaths?: string[]) => void
  /** Stop the current run: cancels it and suppresses the auto trial run. */
  cancel: () => void
  /** Stop tracking this formation (does not kill the sidecar run). */
  clear: () => void
}

/**
 * Owns the agent formation session ABOVE the studio page so that navigating
 * away does not unmount the session (the run keeps going) and returning does
 * not restart the planner. This also fixes the dev HMR remount that used to
 * wipe the feed and re-trigger design.
 */
export function useFormation(): FormationController {
  const [workflowId, setWorkflowId] = useState('')
  const [title, setTitle] = useState('')
  const [designDone, setDesignDone] = useState(false)
  const [demoDone, setDemoDone] = useState(false)
  const [designDraft, setDesignDraft] = useState('')
  const [stopped, setStopped] = useState(false)

  const startedForRef = useRef('')
  const demoAutoForRef = useRef('')
  const resumeAgentRef = useRef('')

  const onResult = useCallback((result: AgentResult) => {
    if (result.agentId) resumeAgentRef.current = result.agentId
    if (result.kind === 'design') {
      setDesignDraft((result.answer || '').trim())
      setDesignDone(true)
    } else if (result.kind === 'demo') {
      setDemoDone(true)
    }
  }, [])

  const session = useAgentSession({ onResult })
  const sessionRef = useRef(session)
  sessionRef.current = session

  const begin = useCallback((wf: string, ttl: string) => {
    setWorkflowId(wf)
    setTitle(ttl)
    if (startedForRef.current === wf) return
    startedForRef.current = wf
    demoAutoForRef.current = ''
    setDesignDone(false)
    setDemoDone(false)
    setDesignDraft('')
    setStopped(false)
    sessionRef.current.start({ kind: 'design', workflowId: wf })
  }, [])

  // Auto-start the trial run once the design draft is ready (unless the user
  // stopped the run - cancelling design must not silently start the demo).
  useEffect(() => {
    if (!designDone || !workflowId || stopped) return
    if (demoAutoForRef.current === workflowId) return
    if (session.running || session.pendingQuestion || session.pendingHitl) return
    demoAutoForRef.current = workflowId
    const timer = setTimeout(
      () => sessionRef.current.start({ kind: 'demo', workflowId }),
      1200
    )
    return () => clearTimeout(timer)
  }, [designDone, workflowId, stopped, session.running, session.pendingQuestion, session.pendingHitl])

  const runDemo = useCallback(() => {
    if (!workflowId) return
    setDemoDone(false)
    setStopped(false)
    demoAutoForRef.current = workflowId
    sessionRef.current.start({ kind: 'demo', workflowId })
  }, [workflowId])

  const sendMessage = useCallback(
    (shownMessage: string, message: string, filePaths?: string[]) => {
      if (!workflowId) return
      setStopped(false)
      sessionRef.current.pushUserMessage(shownMessage)
      sessionRef.current.start({
        kind: 'run',
        workflowId,
        message,
        resumeAgentId: resumeAgentRef.current || undefined,
        filePaths: filePaths && filePaths.length ? filePaths : undefined
      })
    },
    [workflowId]
  )

  const cancel = useCallback(() => {
    // Suppress the auto trial run for this workflow and hide the banner.
    demoAutoForRef.current = workflowId
    setStopped(true)
    sessionRef.current.cancel()
  }, [workflowId])

  const clear = useCallback(() => {
    startedForRef.current = ''
    demoAutoForRef.current = ''
    resumeAgentRef.current = ''
    setWorkflowId('')
    setTitle('')
    setDesignDone(false)
    setDemoDone(false)
    setDesignDraft('')
    setStopped(false)
    sessionRef.current.reset()
  }, [])

  const running = session.running
  const awaiting = Boolean(session.pendingQuestion || session.pendingHitl)

  const phase: FormationPhase = useMemo(() => {
    if (demoDone) return 'tested'
    if (designDone && running) return 'executing'
    if (designDone) return 'designed'
    return 'designing'
  }, [demoDone, designDone, running])

  const latestOutput = useMemo(() => {
    const items = session.items
    for (let i = items.length - 1; i >= 0; i -= 1) {
      const item = items[i]
      if (item.kind === 'result') return item.text
      if (item.kind === 'message' && item.role === 'agent') return item.text
    }
    return ''
  }, [session.items])

  const inProgress = Boolean(workflowId) && !demoDone && !stopped

  return {
    session,
    workflowId,
    title,
    designDone,
    demoDone,
    designDraft,
    phase,
    running,
    awaiting,
    latestOutput,
    inProgress,
    begin,
    runDemo,
    sendMessage,
    cancel,
    clear
  }
}
