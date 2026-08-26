import { useCallback, useRef, useState } from 'react'
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
  const resumeAgentRef = useRef<string>('')

  const onResult = useCallback((result: AgentResult) => {
    if (result.agentId) resumeAgentRef.current = result.agentId
  }, [])

  const session = useAgentSession({ onResult })

  const submit = (): void => {
    const message = input.trim()
    if (!message || session.running) return
    setInput('')
    session.pushUserMessage(message)
    session.start({
      kind: 'run',
      workflowId,
      message,
      resumeAgentId: resumeAgentRef.current || undefined
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
            onAnswer={session.answer}
            onHitl={session.respondHitl}
            onSkip={session.skip}
          />
          <div className="agent-run-input">
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
            <button className="btn-primary" disabled={!input.trim() || session.running} onClick={submit}>
              Отправить
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
