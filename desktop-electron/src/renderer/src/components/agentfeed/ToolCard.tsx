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
  const hasArgs = item.arguments && Object.keys(item.arguments).length > 0
  const hasResult = item.result && Object.keys(item.result).length > 0
  return (
    <div className={item.done ? 'feed-tool done' : 'feed-tool'}>
      <button className="feed-tool-head" onClick={() => setOpen((v) => !v)}>
        <span className={item.done ? 'feed-tool-dot done' : 'feed-tool-dot'} />
        <span className="feed-tool-title">{item.title}</span>
        <span className="feed-tool-status">
          {item.done ? item.summary || 'Готово' : 'Выполняется…'}
        </span>
        <span className="feed-tool-chevron">{open ? '▲' : '▼'}</span>
      </button>
      {open && (hasArgs || hasResult) && (
        <div className="feed-tool-body">
          {hasArgs && (
            <div className="feed-tool-block">
              <div className="feed-tool-label">Параметры</div>
              <pre>{pretty(item.arguments)}</pre>
            </div>
          )}
          {hasResult && item.result && (
            <div className="feed-tool-block">
              <div className="feed-tool-label">Результат</div>
              <pre>{pretty(item.result)}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
