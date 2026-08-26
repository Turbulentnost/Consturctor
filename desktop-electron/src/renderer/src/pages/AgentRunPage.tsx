import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import {
  AgentFeed,
  useAgentSession,
  type AgentResult
} from '../components/agentfeed'

interface AgentRunPageProps {
  workflowId: string
  title: string
  onBack: () => void
  onOpenHistory?: (workflowId: string, title: string) => void
}

export function AgentRunPage({
  workflowId,
  title,
  onBack,
  onOpenHistory
}: AgentRunPageProps): React.JSX.Element {
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<string[]>([])
  const resumeAgentRef = useRef<string>('')

  const onResult = useCallback((result: AgentResult) => {
    if (result.agentId) resumeAgentRef.current = result.agentId
  }, [])

  const session = useAgentSession({ onResult })

  useEffect(() => {
    let cancelled = false
    async function loadResumeAgent(): Promise<void> {
      try {
        const workflow = await api.getWorkflow(workflowId)
        if (cancelled) return
        const agentId = String(workflow.localRun?.sdk_agent_id || workflow.localRun?.sdkAgentId || '')
        if (agentId) resumeAgentRef.current = agentId
      } catch {
        /* sidecar also falls back to workflow.local_run.sdk_agent_id */
      }
    }
    void loadResumeAgent()
    return () => {
      cancelled = true
    }
  }, [workflowId])

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
    if ((!message && attachments.length === 0) || session.running) return
    const names = attachments.map((path) => path.split(/[\\/]/).pop()).filter(Boolean)
    const shownMessage = [message, names.length ? `Прикреплённые файлы: ${names.join(', ')}` : '']
      .filter(Boolean)
      .join('\n')
    const filePaths = attachments
    setInput('')
    setAttachments([])
    session.pushUserMessage(shownMessage || message)
    session.start({
      kind: 'run',
      workflowId,
      message: message || shownMessage,
      resumeAgentId: resumeAgentRef.current || undefined,
      filePaths: filePaths.length ? filePaths : undefined
    })
  }

  return (
    <div className="agent-studio">
      <div className="agent-studio-head">
        <button className="btn-ghost" onClick={onBack}>
          Назад
        </button>
        <div className="studio-titles">
          <h2>{title || 'Запуск агента'}</h2>
          <p>Локальный запуск агента на реальных инструментах этого компьютера</p>
        </div>
        <div className="agent-toolbar">
          {session.running && (
            <button className="btn-ghost" onClick={session.cancel}>
              Остановить
            </button>
          )}
          {onOpenHistory && (
            <button className="btn-ghost" onClick={() => onOpenHistory(workflowId, title)}>
              История
            </button>
          )}
        </div>
      </div>

      <div className="agent-studio-body">
        <div className="agent-studio-main">
          <AgentFeed
            items={session.items}
            status={session.status}
            running={session.running}
            pendingQuestion={session.pendingQuestion}
            pendingHitl={session.pendingHitl}
            emptyHint="Опишите задачу для агента и нажмите отправить. Записи требуют подтверждения."
            allowQuestionFiles
            onAnswer={session.answer}
            onHitl={session.respondHitl}
            onSkip={session.skip}
          />
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
          <div className="agent-run-input">
            <button
              className="wf-clip"
              title="Прикрепить файл"
              disabled={session.running}
              onClick={() => void pickFiles()}
            >
              📎
            </button>
            <textarea
              placeholder="Что должен сделать агент?"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  submit()
                }
              }}
            />
            <button
              className="btn-primary"
              disabled={(!input.trim() && attachments.length === 0) || session.running}
              onClick={submit}
            >
              Отправить
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
