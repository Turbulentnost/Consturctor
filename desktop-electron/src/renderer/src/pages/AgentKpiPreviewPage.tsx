import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { ScheduleSpec } from './AgentSchedulePage'

interface AgentKpiPreviewPageProps {
  workflowId: string
  title: string
  schedule: ScheduleSpec
  onBack: () => void
  onPublished: (workflowId: string, title: string) => void
}

const SCHEDULE_LABELS: Record<ScheduleSpec['mode'], string> = {
  once: 'Разовый запуск',
  interval: 'Периодический запуск',
  event: 'Запуск по событию',
  manual: 'Ручной запуск'
}

function describeSchedule(spec: ScheduleSpec): string {
  if (spec.mode === 'once' && spec.at) {
    try {
      return `Разово: ${new Date(spec.at).toLocaleString('ru-RU')}`
    } catch {
      return 'Разовый запуск'
    }
  }
  if (spec.mode === 'interval' && spec.intervalSeconds) {
    return `Каждые ${Math.round(spec.intervalSeconds / 60)} мин`
  }
  if (spec.mode === 'event' && spec.condition) {
    return `По событию: ${spec.condition}`
  }
  return SCHEDULE_LABELS[spec.mode]
}

export function AgentKpiPreviewPage({
  workflowId,
  title,
  schedule,
  onBack,
  onPublished
}: AgentKpiPreviewPageProps): React.JSX.Element {
  const [kpi, setKpi] = useState('')
  const [loadingKpi, setLoadingKpi] = useState(true)
  const [publishing, setPublishing] = useState(false)
  const [error, setError] = useState('')
  const kpiStartedRef = useRef(false)

  useEffect(() => {
    if (kpiStartedRef.current) return
    kpiStartedRef.current = true
    let alive = true
    void api
      .streamGenerateWorkflowKpi(workflowId, () => undefined)
      .then((record) => {
        if (!alive) return
        setKpi(record.lastResult || record.plan?.goal || 'KPI сформированы.')
      })
      .catch(() => {
        if (alive) setKpi('')
      })
      .finally(() => {
        if (alive) setLoadingKpi(false)
      })
    return () => {
      alive = false
    }
  }, [workflowId])

  const publish = async (): Promise<void> => {
    setPublishing(true)
    setError('')
    try {
      await api.confirmWorkflowKpi(workflowId)
      if (schedule.mode !== 'manual') {
        await api.createTrigger({
          workflowId,
          message: schedule.message,
          once: schedule.mode === 'once',
          at: schedule.at,
          intervalSeconds: schedule.intervalSeconds,
          condition: schedule.condition
        })
      }
      onPublished(workflowId, title)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось опубликовать агента')
    } finally {
      setPublishing(false)
    }
  }

  return (
    <div className="agent-studio">
      <div className="agent-studio-head">
        <button className="btn-ghost" onClick={onBack}>
          Назад
        </button>
        <div className="studio-titles">
          <h2>Публикация агента</h2>
          <p>{title}</p>
        </div>
      </div>

      <div className="agent-studio-body">
        <div className="agent-studio-main" style={{ padding: 20, overflowY: 'auto' }}>
          <div className="agent-side-card" style={{ marginBottom: 14 }}>
            <h4>Расписание</h4>
            <p>{describeSchedule(schedule)}</p>
          </div>

          <div className="agent-side-card" style={{ marginBottom: 14 }}>
            <h4>KPI и ожидаемый результат</h4>
            {loadingKpi ? (
              <p>Формируем KPI…</p>
            ) : (
              <p style={{ whiteSpace: 'pre-wrap' }}>{kpi || 'KPI будут уточнены после первых запусков.'}</p>
            )}
          </div>

          {error && <div className="feed-system error" style={{ marginBottom: 14 }}>{error}</div>}

          <div className="feed-clarify-actions">
            <button className="btn-primary" disabled={publishing} onClick={publish}>
              {publishing ? 'Публикуем…' : 'Опубликовать агента'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
