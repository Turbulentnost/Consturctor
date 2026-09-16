import { useEffect, useMemo, useState } from 'react'
import type { InboxNotification } from '../api/types'
import { useRuns } from '../store/runs'
import { isLiveRunState, liveRunProgress } from '../store/liveRun'
import { durationLabel } from '../workplace/runTiming'

function formatNotifyTime(value: string): string {
  const stamp = new Date(value)
  if (Number.isNaN(stamp.getTime())) return ''
  return stamp.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function isStartRunTitle(title: string): boolean {
  return /запуск начался|начат плановый запуск/i.test(title || '')
}

function liveStatusText(item: {
  title: string
  pendingHitl: boolean
  pendingQuestion: boolean
  phase: string
}): string {
  if (item.pendingHitl || item.pendingQuestion || item.phase === 'human') {
    return 'Ожидает подтверждения'
  }
  if (item.phase === 'agent') return 'Агент работает…'
  return item.title ? `Агент «${item.title}» запускается…` : 'Агент запускается…'
}

interface NotificationInboxProps {
  items: InboxNotification[]
  loading: boolean
  onClearAll: () => void
  onClearOne: (id: string) => void
  onOpen?: (item: InboxNotification) => void
  onStop?: (item: InboxNotification) => void
  canStop?: (item: InboxNotification) => boolean
}

export function NotificationInbox({
  items,
  loading,
  onClearAll,
  onClearOne,
  onOpen,
  onStop
}: NotificationInboxProps): React.JSX.Element {
  const runs = useRuns()
  const [now, setNow] = useState(() => Date.now())
  const liveItems = useMemo(() => {
    return Object.values(runs.entries)
      .filter((entry) => !entry.background && isLiveRunState(entry.state))
      .map((entry) => {
        const startedAt = entry.state.runningSinceMs || now
        const runId = entry.state.activeRunId || entry.backendRunId || entry.workflowId
        const statusText = liveStatusText({
          title: entry.title || 'ИИ-агент',
          pendingHitl: Boolean(entry.state.pendingHitl),
          pendingQuestion: Boolean(entry.state.pendingQuestion),
          phase: String(entry.state.timing?.phase || 'idle')
        })
        const progress = liveRunProgress({
          running: entry.state.running,
          pendingHitl: entry.state.pendingHitl,
          pendingQuestion: entry.state.pendingQuestion,
          timing: entry.state.timing || { phase: 'idle' },
          items: entry.state.items
        })
        const elapsed = durationLabel(Math.max(0, now - startedAt))
        return {
          id: `live:${entry.workflowId}:${runId}`,
          title: 'Запуск начался',
          body: `${statusText} · ${elapsed}`,
          unread: false,
          senderFio: '',
          createdAt: new Date(startedAt).toISOString(),
          workflowId: entry.workflowId,
          runId,
          progress,
          statusText,
          canStop: Boolean(onStop && entry.workflowId)
        }
      })
  }, [now, onStop, runs.entries])

  const visibleItems = useMemo(() => {
    const liveWorkflowIds = new Set(liveItems.map((item) => item.workflowId))
    return items.filter((item) => !(isStartRunTitle(item.title) && liveWorkflowIds.has(item.workflowId)))
  }, [items, liveItems])

  useEffect(() => {
    if (liveItems.length === 0) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [liveItems.length])
  return (
    <div className="notify-panel">
      <div className="notify-panel-head">
        <div className="notify-panel-title">Уведомления</div>
        {visibleItems.length > 0 && (
          <button className="notify-clear-all" onClick={onClearAll}>
            Очистить все
          </button>
        )}
      </div>
      <div className="notify-list">
        {loading && visibleItems.length === 0 && liveItems.length === 0 && (
          <div className="notify-empty">Загружаем...</div>
        )}
        {!loading && visibleItems.length === 0 && liveItems.length === 0 && (
          <div className="notify-empty">Пока нет уведомлений.</div>
        )}
        {liveItems.map((item) => {
          const canOpen = Boolean(onOpen && item.workflowId)
          return (
            <div
              key={item.id}
              className={`notify-card notify-card-live${canOpen ? ' notify-card-clickable' : ''}`}
            >
              <div
                className="notify-card-main"
                role={canOpen ? 'button' : undefined}
                onClick={canOpen ? () => onOpen?.(item) : undefined}
              >
                <div className="notify-card-title">{item.title}</div>
                <div className="notify-card-time">{item.statusText}</div>
                {item.body && <div className="notify-card-body">{item.body}</div>}
                <div className="notify-progress" aria-label={`Прогресс ${item.progress}%`}>
                  <div className="notify-progress-bar" style={{ width: `${item.progress}%` }} />
                </div>
                <div className="notify-progress-meta">
                  <span>{item.progress < 100 ? `${item.progress}%` : '100%'}</span>
                  <span>{item.statusText}</span>
                </div>
                {item.canStop && onStop ? (
                  <button
                    type="button"
                    className="notify-card-stop"
                    onClick={(event) => {
                      event.preventDefault()
                      event.stopPropagation()
                      onStop(item)
                    }}
                  >
                    Отменить
                  </button>
                ) : null}
              </div>
            </div>
          )
        })}
        {visibleItems.map((item) => {
          const canOpen = Boolean(onOpen && item.workflowId)
          const when = formatNotifyTime(item.createdAt)
          return (
            <div
              key={item.id}
              className={`notify-card${canOpen ? ' notify-card-clickable' : ''}${
                item.unread ? ' notify-card-unread' : ''
              }`}
            >
              <div
                className="notify-card-main"
                role={canOpen ? 'button' : undefined}
                onClick={canOpen ? () => onOpen?.(item) : undefined}
              >
                <div className="notify-card-title">{item.title}</div>
                {when ? <div className="notify-card-time">{when}</div> : null}
                {item.body && <div className="notify-card-body">{item.body}</div>}
              </div>
              <button
                className="notify-card-close"
                title="Очистить уведомление"
                onClick={() => onClearOne(item.id)}
              >
                {'\u00d7'}
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
