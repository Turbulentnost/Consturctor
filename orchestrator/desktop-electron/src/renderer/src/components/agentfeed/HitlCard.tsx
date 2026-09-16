import { agentWantsText, explainTool } from './explainTool'
import type { PendingHitl } from './types'

interface HitlCardProps {
  hitl: PendingHitl
  onRespond: (requestId: string, approved: boolean) => void
  onSkip: () => void
}

export function HitlCard({ hitl, onRespond, onSkip }: HitlCardProps): React.JSX.Element {
  const explained = explainTool(hitl.tool, hitl.arguments)
  const title = hitl.title?.startsWith('Агент хочет') ? hitl.title : agentWantsText(hitl.tool, hitl.arguments)
  const detail = (hitl.intent || explained.detail).trim()
  const facts = detail ? [] : explained.facts
  return (
    <div className="feed-hitl">
      <div className="feed-hitl-badge">Нужно ваше решение</div>
      <div className="feed-hitl-title">{title}</div>
      {detail && <div className="feed-hitl-intent">{detail}</div>}
      {facts.length > 0 && (
        <ul className="feed-hitl-facts">
          {facts.map((fact) => (
            <li key={fact}>{fact}</li>
          ))}
        </ul>
      )}
      <div className="feed-hitl-actions">
        <button className="btn-primary" onClick={() => onRespond(hitl.requestId, true)}>
          Разрешить
        </button>
        <button className="btn-ghost" onClick={() => onRespond(hitl.requestId, false)}>
          Отклонить
        </button>
        <button className="btn-ghost" onClick={onSkip}>
          Пропустить
        </button>
      </div>
    </div>
  )
}
