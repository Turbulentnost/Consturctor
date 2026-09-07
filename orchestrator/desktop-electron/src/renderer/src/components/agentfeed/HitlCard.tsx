import type { PendingHitl } from './types'

interface HitlCardProps {
  hitl: PendingHitl
  onRespond: (requestId: string, approved: boolean) => void
  onSkip: () => void
}

function summarizeArgs(args: Record<string, unknown>): string {
  const entries = Object.entries(args || {})
  if (!entries.length) return ''
  return entries
    .map(([key, value]) => {
      let text: string
      if (typeof value === 'string') text = value
      else {
        try {
          text = JSON.stringify(value)
        } catch {
          text = String(value)
        }
      }
      if (text.length > 200) text = `${text.slice(0, 200)}…`
      return `${key}: ${text}`
    })
    .join('\n')
}

export function HitlCard({ hitl, onRespond, onSkip }: HitlCardProps): React.JSX.Element {
  const summary = summarizeArgs(hitl.arguments)
  return (
    <div className="feed-hitl">
      <div className="feed-hitl-badge">Подтвердите действие</div>
      <div className="feed-hitl-title">{hitl.title}</div>
      {summary && <pre className="feed-hitl-args">{summary}</pre>}
      <div className="feed-hitl-actions">
        <button className="btn-primary" onClick={() => onRespond(hitl.requestId, true)}>
          Разрешить
        </button>
        <button className="btn-ghost" onClick={() => onRespond(hitl.requestId, false)}>
          Отклонить
        </button>
        <button className="btn-ghost" onClick={onSkip}>
          Пропустить инструмент
        </button>
      </div>
    </div>
  )
}
