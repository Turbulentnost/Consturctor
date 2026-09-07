import { useState } from 'react'
import { MiniCalendar, meetingsFromToolItem } from './MiniCalendar'
import type { ToolItem } from './types'

interface ToolCardProps {
  item: ToolItem
  liftMeetings?: boolean
}

function pretty(value: Record<string, unknown>): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function ToolCard({ item, liftMeetings = false }: ToolCardProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const meetings = item.tool === 'calendar.show_meetings' ? meetingsFromToolItem(item) : []
  if (meetings.length > 0 && liftMeetings) {
    const status = item.error ? item.summary || 'Ошибка' : 'В результате'
    return (
      <div className={['feed-tool', 'done', item.error ? 'error' : ''].filter(Boolean).join(' ')}>
        <div className="feed-tool-head static">
          <span className={`feed-tool-dot${item.error ? ' error' : ' done'}`} />
          <span className="feed-tool-copy">
            <span className="feed-tool-title">{item.title}</span>
            <span className={`feed-tool-status${item.error ? ' error' : ''}`}>{status}</span>
          </span>
        </div>
      </div>
    )
  }
  if (meetings.length > 0) {
    const status = item.error ? item.summary || 'Ошибка' : ''
    return (
      <div className={['feed-tool', 'done', item.error ? 'error' : ''].filter(Boolean).join(' ')}>
        <div className="feed-tool-head static">
          <span className={`feed-tool-dot${item.error ? ' error' : ' done'}`} />
          <span className="feed-tool-copy">
            <span className="feed-tool-title">{item.title}</span>
            {status && <span className="feed-tool-status error">{status}</span>}
          </span>
        </div>
        <div className="feed-tool-body">
          <MiniCalendar meetings={meetings} />
        </div>
      </div>
    )
  }
  const hasResult = Boolean(item.result && Object.keys(item.result).length > 0)
  const classes = ['feed-tool']
  if (item.done) classes.push('done')
  if (item.error) classes.push('error')
  if (!item.done) classes.push('live')
  const status = item.statusText || (item.done ? item.summary || 'Готово' : 'Выполняется…')

  const Head = hasResult ? 'button' : 'div'
  return (
    <div className={classes.join(' ')}>
      <Head
        className="feed-tool-head"
        {...(hasResult ? { onClick: () => setOpen((v) => !v) } : {})}
      >
        <span className={`feed-tool-dot${item.error ? ' error' : item.done ? ' done' : ' run'}`} />
        <span className="feed-tool-copy">
          <span className="feed-tool-title">{item.title}</span>
          <span className={`feed-tool-status${item.done ? '' : ' live'}${item.error ? ' error' : ''}`}>
            {status}
          </span>
        </span>
        {hasResult && <span className="feed-tool-chevron">{open ? '\u25B2' : '\u25BC'}</span>}
      </Head>
      {open && hasResult && item.result && (
        <div className="feed-tool-body">
          <div className="feed-tool-block">
            <div className="feed-tool-label">Результат</div>
            <pre>{pretty(item.result)}</pre>
          </div>
        </div>
      )}
    </div>
  )
}
