import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { AgentFeed, useAgentSession, type AgentResult } from '../components/agentfeed'
import type { AgentDraft } from '../api/types'

interface ReadinessPageProps {
  draft: AgentDraft
  busy?: boolean
  onBack: () => void
  onComplete: (draft: AgentDraft) => void
}

export function ReadinessPage({
  draft,
  busy,
  onBack,
  onComplete
}: ReadinessPageProps): React.JSX.Element {
  const startedRef = useRef('')
  const watchdogRef = useRef(0)
  const [uploading, setUploading] = useState(false)
  const [blockCount, setBlockCount] = useState(draft.agentSuggestions.length)

  const handleResult = useCallback(
    async (result: AgentResult) => {
      if (result.kind !== 'readiness') return
      const updated = await api.getAgentDraft(draft.draftId)
      onComplete(updated)
    },
    [draft.draftId, onComplete]
  )

  const session = useAgentSession({ onResult: handleResult })
  const { start } = session

  useEffect(() => {
    let cancelled = false
    if (!draft.draftId) return
    void api.getAgentDraft(draft.draftId).then((fresh) => {
      if (!cancelled) setBlockCount(fresh.agentSuggestions.length)
    }).catch(() => {})
    return () => {
      cancelled = true
    }
  }, [draft.draftId])

  useEffect(() => {
    if (!draft.draftId || startedRef.current === draft.draftId) return
    startedRef.current = draft.draftId
    start({ kind: 'readiness', draftId: draft.draftId })
  }, [draft.draftId, start])

  const restartAgent = (): void => {
    startedRef.current = draft.draftId
    void api.getAgentDraft(draft.draftId).then((fresh) => {
      setBlockCount(fresh.agentSuggestions.length)
    }).catch(() => {})
    start({ kind: 'readiness', draftId: draft.draftId })
  }

  useEffect(() => {
    if (!session.running || session.pendingQuestion) return
    const stuck =
      session.items.length === 0 ||
      session.items.every((item) => item.kind === 'system' && item.text.includes('завершился'))
    if (!stuck || watchdogRef.current >= 2) return
    const timer = window.setTimeout(() => {
      watchdogRef.current += 1
      restartAgent()
    }, 5000)
    return () => window.clearTimeout(timer)
  }, [session.running, session.pendingQuestion, session.items, draft.draftId])

  const answer = async (requestId: string, value: string, filePaths: string[] = []): Promise<void> => {
    let finalValue = value
    if (filePaths.length > 0) {
      setUploading(true)
      try {
        const files = await api.uploadAgentDraftFiles(draft.draftId, filePaths)
        const names = files.map((file) => file.filename).filter(Boolean)
        if (names.length) {
          finalValue = `${value.trim()}\nФайлы сохранены в черновике: ${names.join(', ')}`.trim()
        }
      } catch (err) {
        session.pushSystem(err instanceof Error ? err.message : 'Не удалось прикрепить файл')
        return
      } finally {
        setUploading(false)
      }
    }
    session.answer(requestId, finalValue)
  }

  const totalBlocks = blockCount
  const locked = Boolean(busy || uploading)

  return (
    <div className="agent-studio">
      <div className="chat-head">
        <button className="btn-ghost" onClick={onBack}>
          {'\u2039'} Назад
        </button>
        <h1 className="page-title" style={{ fontSize: 28 }}>
          Уточнение регламента
        </h1>
        <p className="page-subtitle">
          Закрываем пробелы в логике, прежде чем собирать паспорт агента
        </p>
      </div>

      <div className="review-stats">
        <div className="stat">
          <div className="stat-value">{totalBlocks}</div>
          <div className="stat-label">блоков</div>
        </div>
        <div className="stat">
          <div className="stat-value">{session.pendingQuestion ? 1 : 0}</div>
          <div className="stat-label">нужен ответ</div>
        </div>
        <div className="stat">
          <div className="stat-value">{draft.progress ?? 0}</div>
          <div className="stat-label">готовность</div>
        </div>
      </div>

      <div className="agent-studio-body">
        <div className="agent-studio-main">
          <AgentFeed
            items={session.items}
            status={uploading ? 'Прикрепляю файл к черновику…' : session.status}
            running={session.running || locked}
            pendingQuestion={locked ? null : session.pendingQuestion}
            pendingHitl={session.pendingHitl}
            emptyHint="Локальный Cursor SDK анализирует функциональные блоки и задаст вопросы по пробелам логики."
            allowQuestionFiles
            onAnswer={(requestId, value, filePaths) => void answer(requestId, value, filePaths)}
            onHitl={session.respondHitl}
            onSkip={session.skip}
          />
        </div>
        <div className="agent-studio-side">
          <div className="agent-side-card">
            <h4>Уточнение регламента</h4>
            <p>
              Локальный Cursor SDK проходит функциональные блоки по очереди. На вопрос можно выбрать вариант,
              написать свой ответ или прикрепить файл.
            </p>
            {session.running ? (
              <button className="btn-ghost" style={{ marginTop: 10 }} onClick={session.cancel}>
                Остановить
              </button>
            ) : (
              <button className="btn-ghost" style={{ marginTop: 10 }} onClick={restartAgent}>
                Запустить агента
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
