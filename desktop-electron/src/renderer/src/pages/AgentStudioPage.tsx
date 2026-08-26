import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { WorkflowRecord } from '../api/types'
import {
  AgentFeed,
  FORMATION_STAGES,
  StageStepper,
  useAgentSession,
  type AgentResult
} from '../components/agentfeed'

interface AgentStudioPageProps {
  workflowId: string
  title: string
  autoStart?: boolean
  onBack: () => void
  onGoSchedule: (workflowId: string, title: string) => void
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
  const [stageIndex, setStageIndex] = useState(1)
  const startedRef = useRef(false)

  const refreshRecord = useCallback(async () => {
    try {
      const fresh = await api.getWorkflow(workflowId)
      setRecord(fresh)
      return fresh
    } catch {
      return null
    }
  }, [workflowId])

  const onResult = useCallback(
    (result: AgentResult) => {
      if (result.kind === 'design') {
        setDesignDone(true)
        setStageIndex(2)
        void refreshRecord()
      } else if (result.kind === 'demo') {
        setDemoDone(true)
        setStageIndex(3)
        void refreshRecord()
      }
    },
    [refreshRecord]
  )

  const session = useAgentSession({ onResult })
  const { start } = session

  useEffect(() => {
    void refreshRecord()
  }, [refreshRecord])

  useEffect(() => {
    if (!autoStart || startedRef.current) return
    startedRef.current = true
    start({ kind: 'design', workflowId })
  }, [autoStart, start, workflowId])

  const runDemo = (): void => {
    setDemoDone(false)
    start({ kind: 'demo', workflowId })
  }

  const restartDesign = (): void => {
    setDesignDone(false)
    setStageIndex(1)
    start({ kind: 'design', workflowId })
  }

  const plan = record?.plan
  const canDemo = designDone && !session.running && !session.pendingQuestion && !session.pendingHitl

  return (
    <div className="agent-studio">
      <div className="agent-studio-head">
        <button className="btn-ghost" onClick={onBack}>
          Назад
        </button>
        <div className="studio-titles">
          <h2>{record?.title || title || 'Формирование агента'}</h2>
          <StageStepper stages={FORMATION_STAGES} currentIndex={stageIndex} />
        </div>
        <div className="agent-toolbar">
          {session.running && (
            <button className="btn-ghost" onClick={session.cancel}>
              Остановить
            </button>
          )}
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
      </div>

      <div className="agent-studio-body">
        <div className="agent-studio-main">
          <AgentFeed
            items={session.items}
            status={session.status}
            running={session.running}
            pendingQuestion={session.pendingQuestion}
            pendingHitl={session.pendingHitl}
            emptyHint="Проектировщик готовит черновик агента. Ответьте на уточняющие вопросы, если они появятся."
            onAnswer={session.answer}
            onHitl={session.respondHitl}
            onSkip={session.skip}
          />
        </div>

        <div className="agent-studio-side">
          <div className="agent-side-card">
            <h4>Статус</h4>
            <p>
              {demoDone
                ? 'Пробный прогон завершён. Можно перейти к расписанию и публикации.'
                : designDone
                  ? 'Черновик готов. Запустите пробный прогон на реальных инструментах.'
                  : 'Идёт проектирование агента через локальный Cursor SDK.'}
            </p>
            {designDone && !demoDone && !session.running && (
              <button
                className="btn-ghost"
                style={{ marginTop: 10 }}
                onClick={restartDesign}
              >
                Перепроектировать
              </button>
            )}
          </div>

          {plan && (plan.goal || plan.steps.length > 0) && (
            <div className="agent-side-card">
              <h4>{plan.title || 'План агента'}</h4>
              {plan.goal && <p style={{ marginBottom: 8 }}>{plan.goal}</p>}
              {plan.steps.map((step, index) => (
                <div key={step.id || index} className="agent-plan-step">
                  <span className="step-index">{index + 1}</span>
                  <span>{step.action || step.title}</span>
                </div>
              ))}
            </div>
          )}

          {record?.lastResult && (
            <div className="agent-side-card">
              <h4>Результат пробного прогона</h4>
              <p style={{ whiteSpace: 'pre-wrap' }}>{record.lastResult}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
