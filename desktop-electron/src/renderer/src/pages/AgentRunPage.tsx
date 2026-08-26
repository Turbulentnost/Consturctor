import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type { WorkflowFileItem } from '../api/types'
import { AgentFeed } from '../components/agentfeed'
import { useRuns } from '../store/runs'
import { fileTypeIconSrc } from '../utils/fileTypeIcon'
import { formatSize } from './filesGrouping'

interface AgentRunPageProps {
  workflowId: string
  title: string
  onBack: () => void
  onOpenHistory?: (workflowId: string, title: string) => void
}

function isAgentFile(file: WorkflowFileItem): boolean {
  return (file.source || '').toLowerCase() === 'agent'
}

function RunFileCard({ file }: { file: WorkflowFileItem }): React.JSX.Element {
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
          <RunFileCard key={file.id || file.name} file={file} />
        ))}
      </ul>
    </section>
  )
}

export function AgentRunPage({
  workflowId,
  title,
  onBack,
  onOpenHistory
}: AgentRunPageProps): React.JSX.Element {
  const runs = useRuns()
  const entry = runs.entries[workflowId]
  const state = entry?.state
  const running = Boolean(state?.running)
  const awaiting = Boolean(state?.pendingQuestion || state?.pendingHitl)

  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<string[]>([])
  const [files, setFiles] = useState<WorkflowFileItem[]>([])
  const resumeAgentRef = useRef<string>(entry?.resumeAgentId || '')

  const refreshFiles = useCallback(async () => {
    try {
      const list = await api.listPlatformFiles()
      setFiles(list.filter((f) => !f.workflowId || f.workflowId === workflowId))
    } catch {
      setFiles([])
    }
  }, [workflowId])

  useEffect(() => {
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
  }, [workflowId, refreshFiles])

  // Refresh the files panel whenever a run finishes.
  useEffect(() => {
    if (running) return
    void refreshFiles()
  }, [running, refreshFiles])

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
    const message = input.trim()
    if ((!message && attachments.length === 0) || running) return
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
      resumeAgentId: resumeAgentRef.current || undefined
    })
  }

  const attachedFiles = useMemo(() => files.filter((file) => !isAgentFile(file)), [files])
  const generatedFiles = useMemo(() => files.filter(isAgentFile), [files])

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
        {onOpenHistory && (
          <button className="btn-ghost" onClick={() => onOpenHistory(workflowId, title)}>
            История
          </button>
        )}
      </div>

      <div className="wf-body">
        <div className="wf-left">
          <div className="wf-left-head">Локальный запуск на реальных инструментах этого компьютера</div>
          <div className="wf-feed-wrap">
            <AgentFeed
              items={state?.items ?? []}
              status={state?.status ?? ''}
              running={running}
              pendingQuestion={state?.pendingQuestion ?? null}
              pendingHitl={state?.pendingHitl ?? null}
              emptyHint="Опишите задачу для агента и нажмите отправить. Записи требуют подтверждения."
              allowQuestionFiles
              onAnswer={(requestId, value, filePaths) =>
                runs.answer(workflowId, requestId, value, filePaths)
              }
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
                disabled={running}
                onClick={() => void pickFiles()}
              >
                📎
              </button>
              <textarea
                className="wf-composer-input"
                placeholder="Что должен сделать агент?"
                value={input}
                disabled={running}
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
                disabled={(!input.trim() && attachments.length === 0) || running}
                onClick={submit}
                title="Отправить"
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
            <button className="wf-tab active">Файлы {files.length}</button>
          </div>
          <div className="wf-right-body">
            {files.length === 0 ? (
              <div className="wf-files-empty">Файлы не прикреплены</div>
            ) : (
              <div className="wf-file-groups">
                <FileSection title="Прикрепили мы" items={attachedFiles} />
                <FileSection title="Создано агентом" items={generatedFiles} />
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
