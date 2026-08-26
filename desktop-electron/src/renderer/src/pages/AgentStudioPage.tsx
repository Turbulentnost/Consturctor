import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type { WorkflowFileItem, WorkflowRecord } from '../api/types'
import { AgentFeed, StageStepper, useAgentSession, type AgentResult } from '../components/agentfeed'

interface AgentStudioPageProps {
  workflowId: string
  title: string
  autoStart?: boolean
  onBack: () => void
  onGoSchedule: (workflowId: string, title: string) => void
}

type StudioTab = 'stages' | 'files'

/** Keep the status hint to one short line (desktop shows a single-line phrase). */
function clampWords(text: string, max: number): string {
  const words = (text || '').trim().split(/\s+/).filter(Boolean)
  if (words.length <= max) return words.join(' ')
  return `${words.slice(0, max).join(' ')}\u2026`
}

/** Cycling dots ("Думает" -> "Думает." -> "Думает..") while busy. */
function useAnimatedStatus(base: string, active: boolean): string {
  const [dots, setDots] = useState(0)
  useEffect(() => {
    if (!active) {
      setDots(0)
      return
    }
    const timer = setInterval(() => setDots((d) => (d + 1) % 4), 420)
    return () => clearInterval(timer)
  }, [active])
  if (!active) return base
  const trimmed = base.replace(/[.\u2026]+$/, '')
  return `${trimmed}${'.'.repeat(dots)}`
}

export function AgentStudioPage({
  workflowId,
  title,
  autoStart = true,
  onBack,
  onGoSchedule
}: AgentStudioPageProps): React.JSX.Element {
  const [record, setRecord] = useState<WorkflowRecord | null>(null)
  const [designDone, setDesignDone] = useState(false)
  const [demoDone, setDemoDone] = useState(false)
  const [tab, setTab] = useState<StudioTab>('stages')
  const [files, setFiles] = useState<WorkflowFileItem[]>([])
  const [input, setInput] = useState('')
  const startedRef = useRef(false)
  const resumeAgentRef = useRef<string>('')

  const refreshRecord = useCallback(async () => {
    try {
      const fresh = await api.getWorkflow(workflowId)
      setRecord(fresh)
      return fresh
    } catch {
      return null
    }
  }, [workflowId])

  const refreshFiles = useCallback(async () => {
    try {
      const list = await api.listPlatformFiles()
      setFiles(list.filter((f) => !f.workflowId || f.workflowId === workflowId))
    } catch {
      setFiles([])
    }
  }, [workflowId])

  const onResult = useCallback(
    (result: AgentResult) => {
      if (result.agentId) resumeAgentRef.current = result.agentId
      if (result.kind === 'design') {
        setDesignDone(true)
        void refreshRecord()
      } else if (result.kind === 'demo') {
        setDemoDone(true)
        void refreshRecord()
      }
    },
    [refreshRecord]
  )

  const session = useAgentSession({ onResult })
  const { start } = session

  useEffect(() => {
    void refreshRecord()
    void refreshFiles()
  }, [refreshRecord, refreshFiles])

  useEffect(() => {
    if (!autoStart || startedRef.current) return
    startedRef.current = true
    start({ kind: 'design', workflowId })
  }, [autoStart, start, workflowId])

  const runDemo = (): void => {
    setDemoDone(false)
    start({ kind: 'demo', workflowId })
  }

  const busy = session.running
  const awaiting = Boolean(session.pendingQuestion || session.pendingHitl)

  const phase = useMemo(() => {
    if (demoDone) return 'tested'
    if (designDone && busy) return 'executing'
    if (designDone) return 'designed'
    return 'designing'
  }, [demoDone, designDone, busy])

  const basePhrase = useMemo(() => {
    if (session.pendingQuestion) return 'Агент ждёт ваш ответ'
    if (session.pendingHitl) return 'Требуется подтверждение действия'
    if (busy) {
      if (session.status) return session.status
      if (phase === 'executing') return 'Пробный прогон'
      return 'Планирование черновика'
    }
    if (demoDone) return 'Пробный прогон завершён — можно перейти к расписанию'
    if (designDone) return 'Черновик готов — запустите пробный прогон'
    return 'Готов к работе'
  }, [session.pendingQuestion, session.pendingHitl, session.status, busy, phase, demoDone, designDone])

  const clampedPhrase = clampWords(basePhrase, 10)
  const truncated = clampedPhrase !== basePhrase.trim()
  const animatedStatus = useAnimatedStatus(clampedPhrase, busy && !awaiting && !truncated)

  const canDemo = designDone && !busy && !awaiting
  const composerDisabled = busy || awaiting

  const submit = (): void => {
    const message = input.trim()
    if (!message || composerDisabled) return
    setInput('')
    session.pushUserMessage(message)
    start({
      kind: 'run',
      workflowId,
      message,
      resumeAgentId: resumeAgentRef.current || undefined
    })
  }

  return (
    <div className="wf-page">
      <div className="wf-topbar">
        <button className="btn-ghost" onClick={onBack}>
          Назад
        </button>
        <h1 className="wf-title">Конструктор workflow</h1>
        <div className="wf-topbar-spacer" />
      </div>

      <div className="wf-body">
        <div className="wf-left">
          <div className="wf-left-head">Работа агента</div>
          <div className="wf-feed-wrap">
            <AgentFeed
              items={session.items}
              status={session.status}
              running={session.running}
              pendingQuestion={session.pendingQuestion}
              pendingHitl={session.pendingHitl}
              hideRunningStatus
              emptyHint="Проектировщик готовит черновик агента. Ответьте на уточняющие вопросы, если они появятся."
              onAnswer={session.answer}
              onHitl={session.respondHitl}
              onSkip={session.skip}
            />
          </div>
          <div className="wf-composer">
            <span className="wf-clip" title="Прикрепить файл">
              📎
            </span>
            <textarea
              className="wf-composer-input"
              placeholder="Напишите сообщение агенту…"
              value={input}
              disabled={composerDisabled}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  submit()
                }
              }}
            />
            <button
              className="wf-send"
              disabled={!input.trim() || composerDisabled}
              onClick={submit}
              title="Отправить"
            >
              ↑
            </button>
          </div>
          <div className="wf-status">
            <span className={`wf-status-dot${busy ? ' busy' : awaiting ? ' wait' : ''}`} />
            <span className="wf-status-text">{animatedStatus}</span>
          </div>
        </div>

        <div className="wf-right">
          <div className="wf-tabs">
            <button
              className={`wf-tab${tab === 'stages' ? ' active' : ''}`}
              onClick={() => setTab('stages')}
            >
              Этапы
            </button>
            <button
              className={`wf-tab${tab === 'files' ? ' active' : ''}`}
              onClick={() => setTab('files')}
            >
              Файлы {files.length}
            </button>
          </div>

          {tab === 'stages' ? (
            <div className="wf-right-body">
              <StageStepper phase={phase} busy={busy} />
              <div className="wf-actions">
                {canDemo && !demoDone && (
                  <button className="btn-primary" onClick={runDemo}>
                    Пробный прогон
                  </button>
                )}
                {demoDone && (
                  <button
                    className="btn-primary"
                    onClick={() => onGoSchedule(workflowId, record?.title || title)}
                  >
                    Далее
                  </button>
                )}
              </div>
              {record?.lastResult && (
                <div className="wf-result-card">
                  <div className="wf-result-title">Результат пробного прогона</div>
                  <p>{record.lastResult}</p>
                </div>
              )}
            </div>
          ) : (
            <div className="wf-right-body">
              {files.length === 0 ? (
                <div className="wf-files-empty">Файлы не прикреплены</div>
              ) : (
                <ul className="wf-files">
                  {files.map((file) => (
                    <li key={file.id} className="wf-file">
                      <span className="wf-file-name">{file.name}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {busy && (
            <button className="wf-stop" onClick={session.cancel}>
              Остановить
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
