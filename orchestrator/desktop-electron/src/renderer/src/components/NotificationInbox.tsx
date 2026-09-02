import type { InboxNotification } from '../api/types'

interface NotificationInboxProps {
  items: InboxNotification[]
  loading: boolean
  onClearAll: () => void
  onClearOne: (id: string) => void
  onOpen?: (item: InboxNotification) => void
}

export function NotificationInbox({
  items,
  loading,
  onClearAll,
  onClearOne,
  onOpen
}: NotificationInboxProps): React.JSX.Element {
  return (
    <div className="notify-panel">
      <div className="notify-panel-head">
        <div className="notify-panel-title">Уведомления</div>
        {items.length > 0 && (
          <button className="notify-clear-all" onClick={onClearAll}>
            Очистить все
          </button>
        )}
      </div>
      <div className="notify-list">
        {loading && items.length === 0 && <div className="notify-empty">Загружаем...</div>}
        {!loading && items.length === 0 && <div className="notify-empty">Пока нет уведомлений.</div>}
        {items.map((item) => {
          const canOpen = Boolean(onOpen && item.workflowId)
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
