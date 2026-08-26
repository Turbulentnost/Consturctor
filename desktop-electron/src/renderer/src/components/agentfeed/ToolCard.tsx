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

/**
 * Tool activity card. Shows ONLY the tool output (never the input/arguments),
 * like the real Cursor feed. Header shows the tool name + a short status/result
 * summary; expanding reveals the raw returned result.
 */
export function ToolCard({ item }: ToolCardProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const hasResult = item.result && Object.keys(item.result).length > 0
  const classes = ['feed-tool']
  if (item.done) classes.push('done')
  if (item.error) classes.push('error')
  return (
    <div className={classes.join(' ')}>
      <button className="feed-tool-head" onClick={() => setOpen((v) => !v)}>
        <span className={`feed-tool-dot${item.error ? ' error' : item.done ? ' done' : ''}`} />
        <span className="feed-tool-title">{item.title}</span>
        <span className="feed-tool-status">
          {item.done ? item.summary || 'Готово' : 'Выполняется…'}
        </span>
        {hasResult && <span className="feed-tool-chevron">{open ? '▲' : '▼'}</span>}
      </button>
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
