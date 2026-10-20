import { useEffect, useMemo, useState } from 'react'
import { AgentFeed } from '../../components/agentfeed/AgentFeed'
import type { ToolItem } from '../../components/agentfeed/types'
import { useRuns } from '../../store/runs'
import type { KpiDailyRun } from './useKpiDailyRun'

type StepState = 'todo' | 'active' | 'done' | 'error'

interface Step {
  id: string
  label: string
  state: StepState
}

function toolText(item: ToolItem): string {
  try {
    return JSON.stringify(item.arguments || {})
  } catch {
    return ''
  }
}

function buildSteps(items: ToolItem[], running: boolean): Step[] {
  const holders = items.filter((item) => item.tool === 'onec.position_holders')
  const reports = items.filter((item) => /report_[\w-]+\.py/.test(toolText(item)))
  const modules = items.filter((item) => {
    const text = toolText(item)
    return text.includes('--fio') && !/report_[\w-]+\.py/.test(text)
  })
  const publish = items.filter((item) => item.tool === 'kpi.publish_position_result')
  const stateOf = (list: ToolItem[], next: ToolItem[]): StepState => {
    if (!list.length) return 'todo'
    if (list.some((item) => item.error) && !list.some((item) => item.done && !item.error)) return 'error'
    if (list.some((item) => !item.done) || (running && !next.length)) return 'active'
    return 'done'
  }
  const modulesDone = modules.filter((item) => item.done && !item.error).length
  return [
    { id: 'holders', label: 'Кто на должности', state: stateOf(holders, modules) },
    {
      id: 'modules',
      label: modules.length ? `Модули: ${modulesDone} из ${modules.length}` : 'Модули',
      state: stateOf(modules, reports)
    },
    { id: 'report', label: 'Отчёт ИЦПП', state: stateOf(reports, publish) },
    { id: 'publish', label: 'Выгрузка', state: stateOf(publish, []) }
  ]
}

function elapsed(sinceMs: number | null, now: number): string {
  if (!sinceMs) return ''
  const sec = Math.max(0, Math.round((now - sinceMs) / 1000))
  const min = Math.floor(sec / 60)
  return min ? `${min} мин ${sec % 60} с` : `${sec} с`
}

function formatDay(iso: string): string {
  const [year, month, day] = iso.split('-')
  return year && month && day ? `${day}.${month}.${year}` : iso
}

export function KpiDailyWaitingTile({ day }: { day: string }): React.JSX.Element {
  return (
    <article className="kpi-employee-tile kpi-daily-run-tile" role="status">
      <span className="kpi-employee-tile-title">Расчёт за {day} уже идёт</span>
      <p>Должность считается на другом компьютере. Плитки обновятся, когда расчёт выгрузят.</p>
    </article>
  )
}

export function KpiDailyRunPanel({
  daily,
  onDownloadReport,
  onOpenChat
}: {
  daily: KpiDailyRun
  onDownloadReport: () => void
  onOpenChat?: () => void
}): React.JSX.Element | null {
  const runs = useRuns()
  const [now, setNow] = useState(() => Date.now())
  const [showFeed, setShowFeed] = useState(false)
  const state = daily.run?.state
  const running = daily.phase === 'running' && Boolean(state?.running)

  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [running])

  const steps = useMemo(() => {
    const tools = (state?.items || []).filter((item): item is ToolItem => item.kind === 'tool')
    return buildSteps(tools, Boolean(state?.running))
  }, [state?.items, state?.running])

  if (daily.phase === 'unavailable' || daily.phase === 'checking') return null
  const position = daily.today?.profile?.position || ''
  const day = daily.today?.day ? formatDay(daily.today.day) : ''

  if (daily.phase === 'ready') {
    return (
      <div className="kpi-daily-run is-ready" role="status">
        <div>
          <strong>Расчёт KPI за {day} готов</strong>
          <p>{position ? `Должность «${position}». ` : ''}Плитки и отчёт ИЦПП взяты из сегодняшнего кэша.</p>
        </div>
        <button type="button" className="spec-btn-outline" onClick={onDownloadReport}>
          Скачать отчёт ИЦПП
        </button>
      </div>
    )
  }

  if (daily.phase === 'waiting') return null

  if (daily.phase === 'failed') {
    return (
      <div className="kpi-daily-run is-error" role="alert">
        <div>
          <strong>Расчёт KPI за {day || 'сегодня'} не готов</strong>
          <p className="is-error">{daily.error || 'Агент не выгрузил расчёт.'}</p>
        </div>
        <div className="kpi-daily-run-actions">
          {onOpenChat && daily.workflowId ? (
            <button type="button" className="spec-btn-outline" onClick={onOpenChat}>
              Открыть чат
            </button>
          ) : null}
          <button type="button" className="btn-primary" onClick={daily.retry}>
            Пересчитать
          </button>
        </div>
      </div>
    )
  }

  const question = state?.pendingQuestion
  return (
    <div className="kpi-daily-run is-running" role="status" aria-live="polite">
      <div>
        <strong>
          Считаем KPI{position ? ` должности «${position}»` : ''}
          {state?.runningSinceMs ? <span className="kpi-daily-run-time"> · {elapsed(state.runningSinceMs, now)}</span> : null}
        </strong>
        <ol className="kpi-daily-run-steps">
          {steps.map((step) => (
            <li key={step.id} className={`is-${step.state}`}>
              {step.label}
            </li>
          ))}
        </ol>
        {question ? (
          <div className="kpi-daily-run-question">
            <p>{question.question}</p>
            <div>
              {question.options.map((option) => (
                <button
                  key={option}
                  type="button"
                  className="spec-btn-outline"
                  onClick={() => runs.answer(daily.workflowId, question.requestId, option)}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <p>{state?.status || 'Агент запускается…'}</p>
        )}
        {showFeed && state ? (
          <div className="kpi-daily-run-feed">
            <AgentFeed
              items={state.items}
              status={state.status}
              running={state.running}
              pendingQuestion={null}
              pendingHitl={state.pendingHitl}
              hideRunningStatus
              emptyHint="Агент запускается. Шаги появятся здесь по мере выполнения."
              onAnswer={(requestId, value, filePaths) =>
                runs.answer(daily.workflowId, requestId, value, filePaths)
              }
              onHitl={(requestId, approved) => runs.respondHitl(daily.workflowId, requestId, approved)}
              onSkip={() => runs.skip(daily.workflowId)}
            />
          </div>
        ) : null}
      </div>
      <div className="kpi-daily-run-actions">
        {onOpenChat && daily.workflowId ? (
          <button type="button" className="spec-btn-outline" onClick={onOpenChat}>
            Открыть чат
          </button>
        ) : null}
        {state ? (
          <button type="button" className="spec-btn-outline" onClick={() => setShowFeed((value) => !value)}>
            {showFeed ? 'Свернуть' : 'Подробнее'}
          </button>
        ) : null}
      </div>
    </div>
  )
}
