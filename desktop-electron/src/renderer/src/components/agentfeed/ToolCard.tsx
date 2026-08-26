import { useState } from 'react'
import type { ToolItem } from './types'

interface ToolCardProps {
  item: ToolItem
}

function pretty(value: Record<string, unknown>): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function ToolCard({ item }: ToolCardProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const hasResult = Boolean(item.result && Object.keys(item.result).length > 0)
  const classes = ['feed-tool']
  if (item.done) classes.push('done')
  if (item.error) classes.push('error')
  if (!item.done) classes.push('live')
  const status = item.statusText || (item.done ? item.summary || 'Готово' : 'Выполняется…')

  return (
    <div className={classes.join(' ')}>
      <button className="feed-tool-head" onClick={() => hasResult && setOpen((v) => !v)}>
        <span className={`feed-tool-dot${item.error ? ' error' : item.done ? ' done' : ' run'}`} />
        <span className="feed-tool-copy">
          <span className="feed-tool-title">{item.title}</span>
          {item.hint && item.hint !== status && <span className="feed-tool-hint">{item.hint}</span>}
        </span>
        {hasResult && <span className="feed-tool-chevron">{open ? '\u25B2' : '\u25BC'}</span>}
      </button>
      <div className={`feed-tool-status-block${item.done ? '' : ' live'}`}>{status}</div>
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
