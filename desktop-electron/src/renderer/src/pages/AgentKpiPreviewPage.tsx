import { useEffect, useRef, useState } from 'react'
import { api, kpiFromRecord } from '../api/client'
import { KpiTileCard } from '../components/KpiTileCard'
import type { AgentKpi, ScheduleDraft } from '../api/types'
import { triggerChipLabel } from './AgentSchedulePage'

interface AgentKpiPreviewPageProps {
  workflowId: string
  title: string
  draft: ScheduleDraft
  onBack: () => void
  onPublished: (workflowId: string, title: string) => void
}

export function AgentKpiPreviewPage({
  workflowId,
  title,
  draft,
  onBack,
  onPublished
}: AgentKpiPreviewPageProps): React.JSX.Element {
  const [kpi, setKpi] = useState<AgentKpi | null>(null)
  const [loadingKpi, setLoadingKpi] = useState(true)
  const [statusText, setStatusText] = useState('Куратор собирает KPI…')
  const [publishing, setPublishing] = useState(false)
  const [error, setError] = useState('')
  const kpiStartedRef = useRef(false)

  useEffect(() => {
    if (kpiStartedRef.current) return
    kpiStartedRef.current = true
    let alive = true
    void (async () => {
      try {
        const existing = await api.getWorkflowKpi(workflowId)
        if (alive && existing && existing.tiles.length > 0) {
          setKpi(existing)
          setLoadingKpi(false)
          return
        }
      } catch {
        /* generate below */
      }
      try {
        // Never let a stalled stream trap the publish button: race the KPI
        // generation against a timeout, then fall back to whatever KPI exists.
        const streamPromise = api.streamGenerateWorkflowKpi(workflowId, (event) => {
          if (!alive) return
          const text = event.text || event.message || ''
          if (
            text &&
            (event.type === 'assistant' ||
              event.type === 'thinking' ||
              event.type === 'status' ||
              event.type === 'decision')
          ) {
            setStatusText(text.slice(0, 120))
          }
        })
        const timeout = new Promise<'timeout'>((resolve) =>
          window.setTimeout(() => resolve('timeout'), 60_000)
        )
        const outcome = await Promise.race([streamPromise, timeout])
        if (!alive) return
        let parsed =
          outcome === 'timeout' ? null : kpiFromRecord(outcome as Awaited<typeof streamPromise>)
        if (!parsed || parsed.tiles.length === 0) {
          try {
            parsed = await api.getWorkflowKpi(workflowId)
          } catch {
            /* ignore */
          }
        }
        if (alive) setKpi(parsed)
      } catch {
        if (alive) setError('Не удалось сформировать KPI, можно опубликовать без него.')
      } finally {
        if (alive) setLoadingKpi(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [workflowId])

  const publish = async (): Promise<void> => {
    setPublishing(true)
    setError('')
    try {
      await api.confirmWorkflowKpi(workflowId)
      for (const spec of draft.triggers) {
        await api.createTriggerFromSpec(workflowId, spec)
      }
      onPublished(workflowId, draft.name || title)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось опубликовать агента')
    } finally {
      setPublishing(false)
    }
  }

  const triggerText =
    draft.triggers.length === 0
      ? 'Только вручную из чата'
      : draft.triggers.map((t) => triggerChipLabel(t)).join(', ')

  return (
    <div className="agent-studio">
      <div className="agent-studio-head">
        <button className="btn-ghost" onClick={onBack}>
          Назад
        </button>
        <div className="studio-titles">
          <h2>KPI агента</h2>
          <p>План — как агент должен работать. Факт — что произошло после запусков.</p>
        </div>
      </div>

      <div className="agent-studio-body">
        <div className="agent-studio-main" style={{ padding: 20, overflowY: 'auto' }}>
          <div className="passport-card" style={{ marginBottom: 14 }}>
            <div className="kpi-agent-name">{draft.name || title}</div>
            {draft.goal && <div className="kpi-agent-goal">{draft.goal}</div>}
            <div className="kpi-agent-schedule">
              <span className="kpi-agent-schedule-label">Расписание:</span> {triggerText}
            </div>
          </div>

          <h4 className="kpi-section-title">KPI и ожидаемый результат</h4>

          {loadingKpi && (
            <div className="feed-system" style={{ marginBottom: 14 }}>
              <span className="kpi-busy-dot" /> {statusText}
            </div>
          )}

          {kpi?.summary && <p className="kpi-summary">{kpi.summary}</p>}

          {kpi && kpi.tiles.length > 0 ? (
            <div className="kpi-preview-grid">
              {kpi.tiles.map((tile) => (
                <KpiTileCard key={tile.id || tile.name} tile={tile} />
              ))}
            </div>
          ) : (
            !loadingKpi && (
              <p className="kpi-empty-note">
                KPI будут уточнены после первых запусков. Агента можно опубликовать сейчас.
              </p>
            )
          )}

          {error && (
            <div className="feed-system error" style={{ margin: '14px 0' }}>
              {error}
            </div>
          )}

          <div className="feed-clarify-actions" style={{ marginTop: 16 }}>
            <button className="btn-primary" disabled={publishing} onClick={publish}>
              {publishing ? 'Публикуем…' : 'Опубликовать агента'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
