import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { ClarifyCard } from '../components/agentfeed/ClarifyCard'
import type { PendingQuestion } from '../components/agentfeed/types'
import type { AgentDraft, AgentReadinessResult, ReadinessQuestion } from '../api/types'

const SYSTEM_ANSWER =
  'Вся необходимая информация уже есть в корпоративных системах (1С ERP, Action Tracker, Outlook). Дополнительные файлы не требуются.'

interface ReadinessPageProps {
  draft: AgentDraft
  busy?: boolean
  onBack: () => void
  onComplete: (draft: AgentDraft) => void
}

function pendingQuestion(question: ReadinessQuestion): PendingQuestion {
  return {
    requestId: question.questionId,
    question: question.question,
    options: question.options?.length ? question.options : [SYSTEM_ANSWER],
    needsFile: false,
    accept: []
  }
}

async function acceptPendingChanges(
  regulationId: string,
  readinessRunId: string,
  readiness: AgentReadinessResult
): Promise<AgentReadinessResult> {
  let current = readiness
  for (const change of current.changes) {
    if (change.status !== 'pending') continue
    current = await api.decideReadinessChange(
      regulationId,
      readinessRunId,
      change.changeId,
      'accepted'
    )
  }
  return current
}

export function ReadinessPage({
  draft,
  busy,
  onBack,
  onComplete
}: ReadinessPageProps): React.JSX.Element {
  const bootedRef = useRef('')
  const [draftState, setDraftState] = useState(draft)
  const [readiness, setReadiness] = useState<AgentReadinessResult | null>(draft.readiness)
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')

  const blockCount = draftState.agentSuggestions.length
  const currentQuestion = readiness?.questions.find((item) => !item.answered) ?? null
  const pendingChanges = readiness?.changes.filter((item) => item.status === 'pending') ?? []
  const progress = draftState.progress ?? readiness?.score ?? 0

  const finishIfReady = useCallback(
    async (nextDraft: AgentDraft, nextReadiness: AgentReadinessResult | null): Promise<boolean> => {
      if (nextDraft.status === 'ready') {
        onComplete(nextDraft)
        return true
      }
      if (
        nextReadiness?.status === 'ready' &&
        !nextReadiness.questions.some((item) => !item.answered) &&
        !nextReadiness.changes.some((item) => item.status === 'pending')
      ) {
        const finalized = await api.updateAgentDraftStatus(nextDraft.draftId, 'ready')
        onComplete(finalized)
        return true
      }
      return false
    },
    [onComplete]
  )

  const bootstrap = useCallback(async (): Promise<void> => {
    setError('')
    setLoading(true)
    try {
      let next = await api.ensureDraftReadiness(draft.draftId)
      let nextReadiness = next.readiness
      if (nextReadiness && next.regulationId && next.readinessRunId) {
        nextReadiness = await acceptPendingChanges(
          next.regulationId,
          next.readinessRunId,
          nextReadiness
        )
        next = { ...next, readiness: nextReadiness }
      }
      setDraftState(next)
      setReadiness(nextReadiness)
      await finishIfReady(next, nextReadiness)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить уточнение регламента')
    } finally {
      setLoading(false)
    }
  }, [draft.draftId, finishIfReady])

  useEffect(() => {
    if (!draft.draftId || bootedRef.current === draft.draftId) return
    bootedRef.current = draft.draftId
    void bootstrap()
  }, [draft.draftId, bootstrap])

  const applyAnswer = async (questionId: string, answer: string): Promise<void> => {
    if (!readiness?.readinessRunId || !draftState.regulationId) return
    setWorking(true)
    setError('')
    try {
      let next = await api.answerReadinessQuestion(
        draftState.regulationId,
        readiness.readinessRunId,
        questionId,
        answer
      )
      next = await acceptPendingChanges(
        draftState.regulationId,
        readiness.readinessRunId,
        next
      )
      setReadiness(next)
      const refreshed = await api.getAgentDraft(draft.draftId)
      setDraftState(refreshed)
      if (next.status === 'ready') {
        const finalized = await api.updateAgentDraftStatus(draft.draftId, 'ready')
        onComplete(finalized)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сохранить ответ')
    } finally {
      setWorking(false)
    }
  }

  const autoFillAll = async (): Promise<void> => {
    if (!readiness?.readinessRunId || !draftState.regulationId) return
    setWorking(true)
    setError('')
    try {
      let next = readiness
      for (const question of next.questions.filter((item) => !item.answered)) {
        next = await api.answerReadinessQuestion(
          draftState.regulationId,
          readiness.readinessRunId,
          question.questionId,
          SYSTEM_ANSWER
        )
      }
      next = await acceptPendingChanges(
        draftState.regulationId,
        readiness.readinessRunId,
        next
      )
      setReadiness(next)
      const finalized = await api.updateAgentDraftStatus(draft.draftId, 'ready')
      onComplete(finalized)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось автоматически закрыть пробелы')
    } finally {
      setWorking(false)
    }
  }

  const locked = Boolean(busy || working || loading)
  const statusText = loading
    ? 'Анализирую функциональные блоки…'
    : working
      ? 'Сохраняю ответ…'
      : currentQuestion
        ? 'Нужен ваш ответ'
        : pendingChanges.length
          ? 'Подтверждаю изменения…'
          : readiness?.status === 'ready'
            ? 'Готово'
            : ''

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
          <div className="stat-value">{blockCount}</div>
          <div className="stat-label">блоков</div>
        </div>
        <div className="stat">
          <div className="stat-value">{currentQuestion ? 1 : 0}</div>
          <div className="stat-label">нужен ответ</div>
        </div>
        <div className="stat">
          <div className="stat-value">{progress}</div>
          <div className="stat-label">готовность</div>
        </div>
      </div>

      <div className="agent-studio-body">
        <div className="agent-studio-main">
          {loading && (
            <div className="chat-hint">
              <div className="spinner" style={{ marginBottom: 12 }} />
              Анализирую регламент и формирую вопросы…
            </div>
          )}
          {!loading && currentQuestion && (
            <ClarifyCard
              question={pendingQuestion(currentQuestion)}
              allowFiles
              onAnswer={(requestId, value) => void applyAnswer(requestId, value)}
            />
          )}
          {!loading && !currentQuestion && !error && readiness && (
            <div className="chat-hint">
              {readiness.status === 'ready'
                ? 'Все пробелы закрыты — переходим к списку агентов…'
                : 'Вопросов пока нет. Можно продолжить автоматически.'}
            </div>
          )}
          {error && (
            <div className="status-line" style={{ color: 'var(--error)', marginTop: 8 }}>
              {error}
            </div>
          )}
          {statusText && !loading && (
            <div className="status-line" style={{ marginTop: 8 }}>
              {statusText}
            </div>
          )}
        </div>
        <div className="agent-studio-side">
          <div className="agent-side-card">
            <h4>Уточнение регламента</h4>
            <p>
              Backend анализирует функциональные блоки и задаёт вопросы по пробелам логики. На вопрос
              можно выбрать вариант или написать свой ответ.
            </p>
            <button
              className="btn-ghost"
              style={{ marginTop: 10 }}
              disabled={locked || !readiness}
              onClick={() => void autoFillAll()}
            >
              Всё уже в системе — закрыть пробелы
            </button>
            <button
              className="btn-ghost"
              style={{ marginTop: 10 }}
              disabled={locked}
              onClick={() => void bootstrap()}
            >
              Обновить
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
