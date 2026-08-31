import { useCallback, useEffect, useRef, useState } from 'react'
import { agentClient } from '../api/agent'
import { ApiError } from '../api/types'
import { api } from '../api/client'
import type { PositionOrchestrator, UserProfile } from '../api/types'
import { KpiTileCard } from '../components/KpiTileCard'
import { hasPositionKpi, ilchenkoOrchestratorFallback } from '../orchestrator/kpi'

interface OrchestratorPageProps {
  user: UserProfile
}

function formatScore(value: number | null): string {
  if (value == null) return 'нет данных'
  return `${value.toFixed(1)}%`.replace('.0%', '%')
}

function weightedScore(snap: PositionOrchestrator | null): number | null {
  const tiles = snap?.tiles || []
  let acc = 0
  let total = 0
  for (const tile of tiles) {
    if (tile.scorePercent == null) continue
    const raw = Number(tile.measure?.params?.weight ?? 0)
    const weight = Number.isFinite(raw) && raw > 0 ? raw : 100 / Math.max(tiles.length, 1)
    acc += tile.scorePercent * weight
    total += weight
  }
  return total > 0 ? acc / total : null
}

function statusLabel(snap: PositionOrchestrator | null, busy: string): string {
  if (busy === 'form') return 'Формируем'
  if (busy === 'calc') return 'Считаем'
  if (!snap) return 'KPI должности'
  if (snap.status === 'forming' || snap.status === 'reforming') return 'Формируем'
  if (snap.status === 'calculating') return 'Считаем'
  if (snap.status === 'empty' && !snap.tiles.length) return 'Нет агентов'
  return 'KPI должности'
}

export function OrchestratorPage({ user }: OrchestratorPageProps): React.JSX.Element {
  const [snap, setSnap] = useState<PositionOrchestrator | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const startedRef = useRef('')
  const aliveRef = useRef(true)

  const load = useCallback(async (): Promise<PositionOrchestrator | null> => {
    try {
      const next = await api.getOrchestrator()
      if (!aliveRef.current) return null
      setSnap(next)
      setError('')
      return next
    } catch (err) {
      if (!aliveRef.current) return null
      if (hasPositionKpi(user.id, user.fio)) {
        const fallback = ilchenkoOrchestratorFallback(user)
        setSnap(fallback)
        setError('')
        return fallback
      }
      const status = err instanceof ApiError ? err.status : 0
      const message =
        status === 404
          ? 'Сервер ещё не знает оркестратор. Перезапустите backend и откройте вкладку снова.'
          : err instanceof Error
            ? err.message
            : 'Не удалось загрузить оркестратор'
      setError(message)
      return null
    }
  }, [user])

  const startJob = useCallback(async (mode: 'form' | 'calc'): Promise<void> => {
    if (startedRef.current === mode) return
    startedRef.current = mode
    setBusy(mode)
    try {
      await api.ensureOrchestrator(mode)
      agentClient.start({
        kind: mode === 'form' ? 'form_orchestrator' : 'calc_orchestrator'
      })
    } catch (err) {
      startedRef.current = ''
      setBusy('')
      setError(err instanceof Error ? err.message : 'Не удалось запустить агента KPI')
    }
  }, [])

  useEffect(() => {
    aliveRef.current = true
    startedRef.current = ''
    setSnap(null)
    void load().then((next) => {
      if (!next || !aliveRef.current) return
      if (next.needsForm) {
        void startJob('form')
        return
      }
      if (next.needsCalc) void startJob('calc')
    })
    return () => {
      aliveRef.current = false
    }
  }, [user.id, load, startJob])

  useEffect(() => {
    const off = agentClient.onEvent((event) => {
      const kind = event.kind || ''
      if (kind !== 'form_orchestrator' && kind !== 'calc_orchestrator') return
      if (event.type === 'result') {
        startedRef.current = ''
        setBusy('')
        void load().then((next) => {
          if (next?.needsCalc) void startJob('calc')
        })
        return
      }
      if (event.type === 'error') {
        startedRef.current = ''
        setBusy('')
        setError(event.message || 'Агент KPI не смог завершить расчёт')
        void load()
      }
    })
    return off
  }, [load, startJob])

  useEffect(() => {
    if (!busy && snap?.status !== 'forming' && snap?.status !== 'reforming' && snap?.status !== 'calculating') {
      return
    }
    const timer = window.setInterval(() => {
      void load()
    }, 8000)
    return () => window.clearInterval(timer)
  }, [busy, snap?.status, load])

  const tiles = snap?.tiles || []
  const score = weightedScore(snap)
  const emptyAgents = snap != null && !snap.locked && !tiles.length && !snap.needsForm && !busy
  const forming = busy === 'form' || snap?.status === 'forming' || snap?.status === 'reforming'

  return (
    <div className="orch-page">
      <div className="orch-head">
        <h1 className="page-title">KPI сотрудника</h1>
        <span className="orch-badge">{statusLabel(snap, busy)}</span>
      </div>

      {tiles.length > 0 && (
        <div className="orch-kpi-score">Итого: {formatScore(score)}</div>
      )}

      {emptyAgents && (
        <p className="orch-note">
          Нет активных агентов — KPI должности появятся после публикации агентов.
        </p>
      )}

      {forming && tiles.length === 0 && (
        <p className="orch-note">Формируем KPI должности по вашим агентам. Это может занять несколько минут.</p>
      )}

      {busy === 'calc' && tiles.length > 0 && (
        <p className="orch-note">Обновляем факт по методике каждой плитки.</p>
      )}

      {tiles.length > 0 && (
        <div className="orch-kpi-grid">
          {tiles.map((tile) => (
            <KpiTileCard key={tile.id || tile.name} tile={tile} />
          ))}
        </div>
      )}

      {error ? <p className="orch-note orch-warn">{error}</p> : null}
    </div>
  )
}
