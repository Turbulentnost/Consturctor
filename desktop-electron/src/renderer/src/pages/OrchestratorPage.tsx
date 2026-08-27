import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { BoardAgent, UserProfile } from '../api/types'
import { boundWorkflowId, DEFINITIONS, isLocalWorkflow, matchBoardAgent } from '../orchestrator/agents'
import { formatPercent, hasPositionKpi, scoreRows, weightedScore } from '../orchestrator/kpi'
import { counts, loadInstances } from '../orchestrator/store'

interface OrchestratorPageProps {
  user: UserProfile
  onRun: (workflowId: string, title: string) => void
}

export function OrchestratorPage({ user, onRun }: OrchestratorPageProps): React.JSX.Element {
  const [agents, setAgents] = useState<BoardAgent[]>([])
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let alive = true
    void api
      .getWorkflowBoard()
      .then((board) => {
        if (alive) setAgents(board.agents.filter((item) => item.kind === 'workflow'))
      })
      .catch(() => {
        if (alive) setAgents([])
      })
    return () => {
      alive = false
    }
  }, [user.id])

  const instances = useMemo(() => loadInstances(user.id), [user.id])
  const today = useMemo(() => {
    if (agents.length) {
      return {
        waiting: agents.filter((item) => item.status === 'needs_attention').length,
        active: agents.filter((item) => item.status === 'active').length,
        errors: agents.filter((item) => item.lastRunStatus === 'error').length
      }
    }
    return counts(instances)
  }, [agents, instances])
  const showKpi = hasPositionKpi(user.id, user.fio)
  const kpiRows = showKpi ? scoreRows(instances) : []
  const kpiScore = showKpi ? weightedScore(kpiRows) : null

  function start(definitionId: string, title: string): void {
    const definition = DEFINITIONS.find((item) => item.id === definitionId)
    if (!definition) return
    const workflowId = boundWorkflowId(definition, agents)
    if (!workflowId || isLocalWorkflow(workflowId)) {
      setNotice('Опубликованный агент для этого процесса ещё не найден.')
      return
    }
    setNotice('')
    onRun(workflowId, title)
  }

  return (
    <div className="orch-page">
      <div className="orch-head">
        <h1 className="page-title">Оркестратор</h1>
        <span className="orch-badge">Пилот · 2 агента</span>
      </div>

      <div className="orch-section-title">Сегодня</div>
      <div className="orch-chips">
        <div className="orch-card orch-chip">
          <div className="orch-chip-name">Ждут меня</div>
          <div className="orch-chip-value">{today.waiting}</div>
        </div>
        <div className="orch-card orch-chip">
          <div className="orch-chip-name">Активные</div>
          <div className="orch-chip-value">{today.active}</div>
        </div>
        <div className="orch-card orch-chip">
          <div className="orch-chip-name">Ошибки</div>
          <div className="orch-chip-value">{today.errors}</div>
        </div>
      </div>

      <div className="orch-cards">
        {DEFINITIONS.map((definition) => {
          const agent = matchBoardAgent(definition, agents)
          let statusLabel = 'Опубликован'
          let statusCode = 'active'
          if (agent) {
            statusCode = agent.status || 'active'
            statusLabel = statusCode === 'needs_attention' ? 'Нужно внимание' : 'Активен'
            if (agent.paused) {
              statusLabel = 'Пауза'
              statusCode = 'paused'
            }
          }
          return (
            <div className="orch-card orch-process" key={definition.id}>
              <div className="orch-process-top">
                <div className="orch-process-title">{definition.title}</div>
                <button
                  type="button"
                  className="btn-primary orch-start"
                  onClick={() => start(definition.id, definition.title)}
                >
                  Запустить
                </button>
              </div>
              <div className="orch-status">
                {statusLabel} · {statusCode}
              </div>
              <div className="orch-meta">
                {agent?.description || 'Запуск откроет агента из «Мои агенты».'}
              </div>
            </div>
          )
        })}
      </div>

      {showKpi && (
        <>
          <div className="orch-section-title">KPI должности</div>
          <div className="orch-kpi-score">Итого: {formatPercent(kpiScore)}</div>
          <div className="orch-card orch-kpi-row head">
            <span>№</span>
            <span>Показатель</span>
            <span>Цель</span>
            <span>Вес</span>
            <span>Факт</span>
          </div>
          {kpiRows.map((row) => (
            <div className="orch-card orch-kpi-row" key={row.number}>
              <span>{row.number}</span>
              <span>{row.name}</span>
              <span>≥ {formatPercent(row.target)}</span>
              <span>{row.weight}%</span>
              <span style={{ color: row.color }}>{formatPercent(row.fact)}</span>
            </div>
          ))}
        </>
      )}

      <p className="orch-note">
        Запуск открывает опубликованного агента и выполняет его рабочую задачу.
      </p>
      {notice ? <p className="orch-note orch-warn">{notice}</p> : null}
    </div>
  )
}
