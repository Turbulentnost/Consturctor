import { useCallback, useEffect, useMemo, useState } from 'react'
import { agentClient } from '../api/agent'
import { api } from '../api/client'
import type { WorkflowFileItem, WorkflowRecord } from '../api/types'
import { AgentFeed, StageStepper, type FormationController } from '../components/agentfeed'
import { ClarifyCard } from '../components/agentfeed/ClarifyCard'
import { MarkdownBody } from '../components/agentfeed/MarkdownBody'
import { presentAgentText } from '../components/agentfeed/formatAgentText'
import { fileTypeIconSrc } from '../utils/fileTypeIcon'
import { categoryOf, FILE_CATEGORY_LABELS, formatSize } from './filesGrouping'

interface AgentStudioPageProps {
  workflowId: string
  title: string
  formation: FormationController
  autoStart?: boolean
  onBack: () => void
  onGoSchedule: (workflowId: string, title: string) => void
}

type StudioTab = 'stages' | 'files'

function StudioFileCard({ file }: { file: WorkflowFileItem }): React.JSX.Element {
  const name = file.name || 'file'
  const size = formatSize(file.sizeBytes)
  return (
    <li className="wf-file-card">
      <img className="files-type-icon" src={fileTypeIconSrc(name)} alt="" />
      <div className="wf-file-copy">
        <span className="wf-file-name" title={name}>
          {name}
        </span>
        {size ? <span className="wf-file-meta">{size}</span> : null}
      </div>
    </li>
  )
}

function FileSection({
  title,
  items
}: {
  title: string
  items: WorkflowFileItem[]
}): React.JSX.Element | null {
  if (items.length === 0) return null
  return (
    <section className="wf-file-section">
      <h4>{title}</h4>
      <ul className="wf-files">
        {items.map((file) => (
          <StudioFileCard key={file.id || file.name} file={file} />
        ))}
      </ul>
    </section>
  )
}

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
  formation,
  autoStart = true,
  onBack,
  onGoSchedule
}: AgentStudioPageProps): React.JSX.Element {
  const [record, setRecord] = useState<WorkflowRecord | null>(null)
  const [tab, setTab] = useState<StudioTab>('stages')
  const [files, setFiles] = useState<WorkflowFileItem[]>([])
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<string[]>([])

  // The session and design/demo orchestration live in the shared formation
  // controller (above this page), so leaving the page does not stop the run and
  // returning does not restart the planner.
  const session = formation.session
  const { designDone, demoDone, designDraft, phase } = formation
  const busy = formation.running
  const awaiting = formation.awaiting

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
      setFiles(await api.listWorkflowFiles(workflowId))
    } catch {
      setFiles([])
    }
  }, [workflowId])

  useEffect(() => {
    void refreshRecord()
    void refreshFiles()
  }, [refreshRecord, refreshFiles])

  // Attach to (or start) the formation for this workflow. begin() is idempotent
  // per workflow, so remounts / navigation back never restart the planner.
  useEffect(() => {
    if (!autoStart) return
    formation.begin(workflowId, title)
  }, [autoStart, workflowId, title, formation.begin])

  // Refresh the workflow record + files whenever a phase completes.
  useEffect(() => {
    if (!designDone) return
    void refreshRecord()
    void refreshFiles()
  }, [designDone, refreshRecord, refreshFiles])

  useEffect(() => {
    if (!demoDone) return
    void refreshRecord()
    void refreshFiles()
  }, [demoDone, refreshRecord, refreshFiles])

  const runDemo = (): void => {
    formation.runDemo()
  }

  const basePhrase = useMemo(() => {
    if (session.pendingQuestion) return 'Агент ждёт ваш ответ'
    if (session.pendingHitl) return 'Требуется подтверждение действия'
    if (busy) {
      if (session.status) return session.status
      if (phase === 'executing') return 'Пробный прогон'
      return 'Планирование черновика'
    }
    if (demoDone) return 'Пробный прогон завершён — можно перейти к расписанию'
    if (designDone) return 'Черновик готов — запускаю пробный прогон'
    return 'Готов к работе'
  }, [session.pendingQuestion, session.pendingHitl, session.status, busy, phase, demoDone, designDone])

  const clampedPhrase = clampWords(basePhrase, 10)
  const truncated = clampedPhrase !== basePhrase.trim()
  const animatedStatus = useAnimatedStatus(clampedPhrase, busy && !awaiting && !truncated)

  const canDemo = designDone && !busy && !awaiting
  const composerDisabled = busy || awaiting
  const temporaryFiles = useMemo(
    () => files.filter((file) => categoryOf(file) === 'temporary'),
    [files]
  )
  const knowledgeFiles = useMemo(
    () => files.filter((file) => categoryOf(file) === 'knowledge'),
    [files]
  )
  const instructionFiles = useMemo(
    () => files.filter((file) => categoryOf(file) === 'instructions'),
    [files]
  )
  const generatedFiles = useMemo(
    () => files.filter((file) => categoryOf(file) === 'agent'),
    [files]
  )

  useEffect(() => {
    if (tab !== 'files') return
    void refreshFiles()
  }, [tab, refreshFiles])

  useEffect(() => {
    return agentClient.onEvent((event) => {
      if (event.type !== 'files_updated') return
      if (event.workflowId && event.workflowId !== workflowId) return
      void refreshFiles()
    })
  }, [workflowId, refreshFiles])

  const pickFiles = async (): Promise<void> => {
    const paths = await window.api.openFile({
      title: 'Прикрепить файл',
      properties: ['openFile', 'multiSelections']
    })
    if (!paths.length) return
    setAttachments((prev) => Array.from(new Set([...prev, ...paths])))
  }

  const removeAttachment = (path: string): void => {
    setAttachments((prev) => prev.filter((item) => item !== path))
  }

  const answerWithRefresh = (
    requestId: string,
    value: string,
    filePaths?: string[]
  ): void => {
    session.answer(requestId, value, filePaths)
    if (filePaths && filePaths.length > 0) {
      window.setTimeout(() => {
        void refreshFiles()
      }, 400)
    }
  }

  const submit = (): void => {
    const message = input.trim()
    if ((!message && attachments.length === 0) || composerDisabled) return
    const names = attachments.map((path) => path.split(/[\\/]/).pop()).filter(Boolean)
    const shownMessage = [message, names.length ? `Прикреплённые файлы: ${names.join(', ')}` : '']
      .filter(Boolean)
      .join('\n')
    setInput('')
    const filePaths = attachments
    setAttachments([])
    formation.sendMessage(shownMessage || message, message || shownMessage, filePaths)
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
              dockQuestion
              emptyHint="Проектировщик готовит черновик агента. Ответьте на уточняющие вопросы, если они появятся."
              onAnswer={answerWithRefresh}
              onHitl={session.respondHitl}
              onSkip={session.skip}
            />
          </div>
          <div className={session.pendingQuestion ? 'wf-dock has-clarify' : 'wf-dock'}>
            {session.pendingQuestion && (
              <div className="wf-dock-clarify">
                <ClarifyCard
                  key={`${session.pendingQuestion.requestId}:${session.pendingQuestion.question}:${session.pendingQuestion.options.join('|')}`}
                  question={session.pendingQuestion}
                  allowFiles
                  onAnswer={answerWithRefresh}
                />
              </div>
            )}
            {attachments.length > 0 && (
              <div className="wf-attachments">
                {attachments.map((path) => (
                  <span key={path} className="wf-attachment">
                    <span className="wf-attachment-name">{path.split(/[\\/]/).pop() || path}</span>
                    <button
                      className="wf-attachment-remove"
                      onClick={() => removeAttachment(path)}
                      title="Убрать файл"
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="wf-composer">
              <button
                className="wf-clip"
                title="Прикрепить файл"
                disabled={composerDisabled}
                onClick={() => void pickFiles()}
              >
                📎
              </button>
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
                disabled={(!input.trim() && attachments.length === 0) || composerDisabled}
                onClick={submit}
                title="Отправить"
              >
                ↑
              </button>
            </div>
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
              {designDraft && (
                <div className="wf-result-card">
                  <div className="wf-result-title">Черновик агента</div>
                  <MarkdownBody text={presentAgentText(designDraft)} />
                </div>
              )}
              {record?.lastResult && (
                <div className="wf-result-card">
                  <div className="wf-result-title">Результат пробного прогона</div>
                  <MarkdownBody text={presentAgentText(record.lastResult)} />
                </div>
              )}
            </div>
          ) : (
            <div className="wf-right-body">
              {files.length === 0 ? (
                <div className="wf-files-empty">Файлы не прикреплены</div>
              ) : (
                <div className="wf-file-groups">
                  <FileSection title={FILE_CATEGORY_LABELS.temporary} items={temporaryFiles} />
                  <FileSection title={FILE_CATEGORY_LABELS.knowledge} items={knowledgeFiles} />
                  <FileSection title={FILE_CATEGORY_LABELS.instructions} items={instructionFiles} />
                  <FileSection title={FILE_CATEGORY_LABELS.agent} items={generatedFiles} />
                </div>
              )}
            </div>
          )}

          {busy && (
            <button className="wf-stop" onClick={formation.cancel}>
              Остановить
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
