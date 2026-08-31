import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { agentClient } from '../api/agent'
import { api } from '../api/client'
import type { WorkflowFileItem } from '../api/types'
import { AgentFeed } from '../components/agentfeed'
import type { FeedItem } from '../components/agentfeed/types'
import { useRuns } from '../store/runs'
import { fileTypeIconSrc } from '../utils/fileTypeIcon'
import { categoryOf, FILE_CATEGORY_LABELS, formatSize } from './filesGrouping'
import { isPersonalAgentWorkflowId } from '../workplace/personalAgent'
import { parseIso, sameDay } from '../utils/calendar'

interface AgentRunPageProps {
  workflowId: string
  title: string
  autoStart?: boolean
  onBack: () => void
  onOpenHistory?: (workflowId: string, title: string) => void
}


function RunFileCard({ file }: { file: WorkflowFileItem }): React.JSX.Element {
  const name = file.name || 'file'
  const size = formatSize(file.sizeBytes)
  return (
    <li>
      <button
        className="wf-file-card history-file-btn"
        type="button"
        onClick={() => {
          if (file.downloadUrl) void api.download(file.downloadUrl, name)
        }}
      >
        <img className="files-type-icon" src={fileTypeIconSrc(name)} alt="" />
        <div className="wf-file-copy">
          <span className="wf-file-name" title={name}>
            {name}
          </span>
          {size ? <span className="wf-file-meta">{size}</span> : null}
        </div>
      </button>
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
          <RunFileCard key={file.id || file.name} file={file} />
        ))}
      </ul>
    </section>
  )
}

export function AgentRunPage({
  workflowId,
  title,
  autoStart = false,
  onBack,
  onOpenHistory
}: AgentRunPageProps): React.JSX.Element {
  const runs = useRuns()
  const personalAgent = isPersonalAgentWorkflowId(workflowId)
  const entry = runs.entries[workflowId]
  const state = entry?.state
  const running = Boolean(state?.running)
  const awaiting = Boolean(state?.pendingQuestion || state?.pendingHitl)

  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<string[]>([])
  const [files, setFiles] = useState<WorkflowFileItem[]>([])
  const resumeAgentRef = useRef<string>(entry?.resumeAgentId || '')
  const autoStartedRef = useRef(false)

  const isTodayFile = useCallback((item: WorkflowFileItem): boolean => {
    const stamp = parseIso(item.createdAt)
    if (!stamp) return false
    return sameDay(stamp, new Date())
  }, [])

  const refreshFiles = useCallback(async () => {
    if (personalAgent) {
      setFiles([])
      return
    }
    try {
      const rows = await api.listWorkflowFiles(workflowId)
      // Runtime panel keeps only today's files; older files stay available
      // in run history and on the global files page.
      const todayRows = rows
        .filter((item) => isTodayFile(item))
        .sort((left, right) => (right.createdAt || '').localeCompare(left.createdAt || ''))
      setFiles(todayRows)
    } catch {
      setFiles([])
    }
  }, [workflowId, personalAgent, isTodayFile])

  useEffect(() => {
    return agentClient.onEvent((event) => {
      if (event.type !== 'files_updated') return
      if (event.workflowId && event.workflowId !== workflowId) return
      void refreshFiles()
    })
  }, [workflowId, refreshFiles])

  useEffect(() => {
    if (personalAgent) return
    let cancelled = false
    async function loadResumeAgent(): Promise<void> {
      try {
        const workflow = await api.getWorkflow(workflowId)
        if (cancelled) return
        const agentId = String(workflow.localRun?.sdk_agent_id || workflow.localRun?.sdkAgentId || '')
        if (agentId && !resumeAgentRef.current) resumeAgentRef.current = agentId
      } catch {
        /* sidecar also falls back to workflow.local_run.sdk_agent_id */
      }
    }
    void loadResumeAgent()
    void refreshFiles()
    return () => {
      cancelled = true
    }
  }, [workflowId, refreshFiles, personalAgent])

  // Refresh the files panel whenever a run finishes.
  useEffect(() => {
    if (running) return
    void refreshFiles()
  }, [running, refreshFiles])

  // Scheduled runs mark the agent "working" from the board before any sidecar
  // events reach this page. Pull persisted steps so the feed is not empty.
  useEffect(() => {
    if (!running) return
    if ((state?.items?.length ?? 0) > 0) return
    void runs.attachHistoryFeed(workflowId)
  }, [running, workflowId, state?.items?.length, runs])

  // On open, restore the latest known conversation for this exact agent.
  useEffect(() => {
    if ((state?.items?.length ?? 0) > 0) return
    void runs.attachHistoryFeed(workflowId)
  }, [workflowId, runs, state?.items?.length])

  // The "Запустить" play button opens this page with autoStart, so the agent
  // starts immediately on its own playbook instead of waiting for a message.
  useEffect(() => {
    if (personalAgent) return
    if (!autoStart || autoStartedRef.current) return
    if (running || (state?.items?.length ?? 0) > 0) return
    autoStartedRef.current = true
    runs.startRun({
      workflowId,
      title,
      message: '',
      shownMessage: 'Запуск агента',
      resumeAgentId: resumeAgentRef.current || undefined
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart, workflowId])

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

  const submit = (): void => {
    if (running) return
    const message = input.trim()
    if (!message && attachments.length === 0) return
    const names = attachments.map((path) => path.split(/[\\/]/).pop()).filter(Boolean)
    const shownMessage = [message, names.length ? `Прикреплённые файлы: ${names.join(', ')}` : '']
      .filter(Boolean)
      .join('\n')
    const filePaths = attachments
    setInput('')
    setAttachments([])
    runs.startRun({
      workflowId,
      title,
      message: message || shownMessage,
      shownMessage: shownMessage || message,
      filePaths: filePaths.length ? filePaths : undefined,
      resumeAgentId: resumeAgentRef.current || undefined,
      forceRestart: running
    })
  }

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
  const feedItems = useMemo<FeedItem[]>(() => {
    const items = state?.items ?? []
    if (!personalAgent) return items
    const cleaned = items.filter((item) => {
      if (item.kind !== 'system') return true
      return !/^workflow\b/i.test((item.text || '').trim())
    })
    if (cleaned.length > 0) return cleaned
    return [
      {
        kind: 'message',
        id: 'personal-greeting',
        role: 'agent',
        text: 'Чем могу помочь?'
      }
    ]
  }, [state?.items, personalAgent])

  const statusText = running
    ? state?.status || 'Агент работает…'
    : awaiting
      ? 'Агент ждёт ваш ответ'
      : 'Готов к работе'

  return (
    <div className="wf-page">
      <div className="wf-topbar">
        <button className="btn-ghost" onClick={onBack}>
          Назад
        </button>
        <h1 className="wf-title">{title || 'Запуск агента'}</h1>
        <div className="wf-topbar-spacer" />
        {onOpenHistory && !personalAgent && (
          <button className="btn-ghost" onClick={() => onOpenHistory(workflowId, title)}>
            История
          </button>
        )}
      </div>

      <div className="wf-body">
        <div className="wf-left">
          <div className="wf-feed-wrap">
            <AgentFeed
              items={feedItems}
              status={state?.status ?? ''}
              running={running}
              pendingQuestion={state?.pendingQuestion ?? null}
              pendingHitl={state?.pendingHitl ?? null}
              emptyHint="Опишите задачу для агента и нажмите отправить. Записи требуют подтверждения."
              allowQuestionFiles
              onAnswer={(requestId, value, filePaths) => {
                runs.answer(workflowId, requestId, value, filePaths)
                if (filePaths && filePaths.length > 0) {
                  window.setTimeout(() => {
                    void refreshFiles()
                  }, 400)
                }
              }}
              onHitl={(requestId, approved) => runs.respondHitl(workflowId, requestId, approved)}
              onSkip={() => runs.skip(workflowId)}
            />
          </div>
          <div className="wf-dock">
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
                disabled={false}
                onClick={() => void pickFiles()}
              >
                📎
              </button>
              <textarea
                className="wf-composer-input"
                placeholder="Что должен сделать агент?"
                value={input}
                disabled={false}
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
                disabled={running || (!input.trim() && attachments.length === 0)}
                onClick={submit}
                title={running ? 'Агент выполняется' : 'Отправить'}
              >
                ↑
              </button>
            </div>
          </div>
          <div className="wf-status">
            <span className={`wf-status-dot${running ? ' busy' : awaiting ? ' wait' : ''}`} />
            <span className="wf-status-text">{statusText}</span>
          </div>
        </div>

        <div className="wf-right">
          <div className="wf-tabs">
            <button className="wf-tab active">Файлы за сегодня {files.length}</button>
          </div>
          <div className="wf-right-body">
            {files.length === 0 ? (
              <div className="wf-files-empty">Сегодня файлов пока нет</div>
            ) : (
              <div className="wf-file-groups">
                <FileSection title={FILE_CATEGORY_LABELS.temporary} items={temporaryFiles} />
                <FileSection title={FILE_CATEGORY_LABELS.knowledge} items={knowledgeFiles} />
                <FileSection title={FILE_CATEGORY_LABELS.instructions} items={instructionFiles} />
                <FileSection title={FILE_CATEGORY_LABELS.agent} items={generatedFiles} />
              </div>
            )}
          </div>
          {running && (
            <button className="wf-stop" onClick={() => runs.cancel(workflowId)}>
              Остановить
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
