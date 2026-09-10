import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import { AgentFeed, useAgentSession, type AgentResult, type FeedItem, type PendingQuestion } from '../components/agentfeed'
import type { AgentDraft, AgentSuggestion } from '../api/types'

interface ReadinessPageProps {
  draft: AgentDraft
  busy?: boolean
  onBack: () => void
  onComplete: (draft: AgentDraft) => void
}

function foldText(text: string): string {
  return text.toLowerCase().replace(/ё/g, 'е')
}

function matchSuggestion(text: string, suggestions: AgentSuggestion[]): AgentSuggestion | null {
  const blob = foldText(text)
  let best: AgentSuggestion | null = null
  for (const item of suggestions) {
    const title = item.title.trim()
    if (title.length < 3 || !blob.includes(foldText(title))) continue
    if (!best || title.length > best.title.length) best = item
  }
  if (best) return best
  for (const item of suggestions) {
    const id = item.functionId.trim()
    if (id.length >= 3 && blob.includes(foldText(id))) return item
  }
  return null
}

function stripAgentPrefix(question: string, title: string): string {
  const trimmed = question.trim()
  if (!title) return trimmed
  const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return trimmed.replace(new RegExp(`^по агенту\\s*[«"']${escaped}[»"']\\s*:\\s*`, 'i'), '')
}

function labelQuestion(question: string, title: string): string {
  const trimmed = question.trim()
  if (!title || foldText(trimmed).includes(foldText(title))) return trimmed
  const rest = trimmed ? trimmed[0].toLowerCase() + trimmed.slice(1) : trimmed
  return `По агенту «${title}»: ${rest}`
}

function currentReadinessBlock(
  question: PendingQuestion | null,
  items: FeedItem[],
  suggestions: AgentSuggestion[]
): AgentSuggestion | null {
  if (!suggestions.length) return null
  const named = question?.blockTitle?.trim()
  if (named) {
    const exact = suggestions.find((item) => foldText(item.title) === foldText(named))
    if (exact) return exact
  }
  if (question?.question) {
    const fromQuestion = matchSuggestion(question.question, suggestions)
    if (fromQuestion) return fromQuestion
  }
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index]
    const text = item.kind === 'message' ? item.text : ''
    if (!text) continue
    const found = matchSuggestion(text, suggestions)
    if (found) return found
  }
  return question ? suggestions[0] : null
}

function enrichReadinessQuestion(
  question: PendingQuestion | null,
  suggestions: AgentSuggestion[],
  current: AgentSuggestion | null
): PendingQuestion | null {
  if (!question || !current) return question
  const index = suggestions.findIndex(
    (item) => item.functionId === current.functionId || item.title === current.title
  )
  const position = index >= 0 ? index + 1 : 1
  return {
    ...question,
    blockTitle: current.title,
    context: `Агент ${position} из ${suggestions.length}`,
    question: stripAgentPrefix(labelQuestion(question.question, current.title), current.title)
  }
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
  const [suggestions, setSuggestions] = useState(draft.agentSuggestions)
  const [progress, setProgress] = useState(draft.progress ?? 0)

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
      if (!cancelled) {
        setSuggestions(fresh.agentSuggestions)
        setProgress(fresh.progress ?? 0)
      }
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
      setSuggestions(fresh.agentSuggestions)
      setProgress(fresh.progress ?? 0)
    }).catch(() => {})
    start({ kind: 'readiness', draftId: draft.draftId })
  }

  useEffect(() => {
    if (!session.running || session.pendingQuestion) return
    const starting = /запускается/i.test(session.status)
    const deadSidecar = session.items.every(
      (item) => item.kind === 'system' && item.text.includes('завершился')
    )
    const stuck = starting && (session.items.length === 0 || deadSidecar)
    if (!stuck || watchdogRef.current >= 2) return
    const timer = window.setTimeout(() => {
      watchdogRef.current += 1
      restartAgent()
    }, 20000)
    return () => window.clearTimeout(timer)
  }, [session.running, session.pendingQuestion, session.items, session.status, draft.draftId])

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
    const refresh = (): void => {
      void api.getAgentDraft(draft.draftId).then((fresh) => {
        setSuggestions(fresh.agentSuggestions)
        setProgress(fresh.progress ?? 0)
      }).catch(() => {})
    }
    window.setTimeout(refresh, 800)
    window.setTimeout(refresh, 2000)
  }

  const currentBlock = useMemo(
    () => currentReadinessBlock(session.pendingQuestion, session.items, suggestions),
    [session.pendingQuestion, session.items, suggestions]
  )
  const pendingQuestion = useMemo(
    () => enrichReadinessQuestion(session.pendingQuestion, suggestions, currentBlock),
    [session.pendingQuestion, suggestions, currentBlock]
  )
  const currentIndex = currentBlock
    ? suggestions.findIndex(
        (item) => item.functionId === currentBlock.functionId || item.title === currentBlock.title
      ) + 1
    : 0
  const totalBlocks = suggestions.length
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
          <div className="stat-value">{currentIndex ? `${currentIndex}/${totalBlocks}` : totalBlocks}</div>
          <div className="stat-label">{currentIndex ? 'текущий агент' : 'блоков'}</div>
        </div>
        <div className="stat">
          <div className="stat-value">{pendingQuestion ? 1 : 0}</div>
          <div className="stat-label">нужен ответ</div>
        </div>
        <div className="stat">
          <div className="stat-value">{progress}</div>
          <div className="stat-label">готовность</div>
        </div>
      </div>

      <div className="agent-studio-body">
        <div className="agent-studio-main">
          <AgentFeed
            items={session.items}
            status={uploading ? 'Прикрепляю файл к черновику…' : session.status}
            running={session.running || locked}
            pendingQuestion={locked ? null : pendingQuestion}
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
            {currentBlock ? (
              <p className="readiness-current-agent">
                Сейчас уточняем агента: <strong>{currentBlock.title}</strong>
              </p>
            ) : null}
            <p>
              Локальный Cursor SDK проходит функциональные блоки по очереди. На вопрос можно выбрать вариант,
              написать свой ответ или прикрепить файл.
            </p>
            {suggestions.length > 0 ? (
              <ol className="readiness-block-list">
                {suggestions.map((item, index) => {
                  const active =
                    currentBlock != null &&
                    (item.functionId === currentBlock.functionId || item.title === currentBlock.title)
                  return (
                    <li
                      key={item.functionId || item.agentId || `${item.title}-${index}`}
                      className={active ? 'readiness-block-item on' : 'readiness-block-item'}
                    >
                      <span className="step-index">{index + 1}.</span>
                      <span>{item.title}</span>
                    </li>
                  )
                })}
              </ol>
            ) : null}
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
