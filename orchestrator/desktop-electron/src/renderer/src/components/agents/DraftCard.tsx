import type { AgentSuggestion, BoardAgent } from '../../api/types'
import { CardMenu, type MenuItem } from './CardMenu'

function normalizeTitle(value: string): string {
  return (value || '')
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .join(' ')
}

interface DraftCardProps {
  agent: BoardAgent
  suggestions: AgentSuggestion[]
  createdTitles: Set<string>
  onContinue: (draftId: string) => void
  onFormSuggestion: (draftId: string, agentId: string) => void
  onDelete: (draftId: string) => void
}

export function DraftCard({
  agent,
  suggestions,
  createdTitles,
  onContinue,
  onFormSuggestion,
  onDelete
}: DraftCardProps): React.JSX.Element {
  const draftId = agent.draftId || agent.id
  const letter = (agent.title || 'Ч').charAt(0).toUpperCase()
  const menuItems: MenuItem[] = [
    { label: 'Продолжить', onClick: () => onContinue(draftId) },
    { label: 'Удалить', onClick: () => onDelete(draftId), danger: true }
  ]

  return (
    <div className="draft-card">
      <div className="draft-card-header">
        <div className="agent-card-avatar">{letter}</div>
        <div className="draft-card-head-text">
          <div className="agent-card-title">{agent.title || 'Черновик агента'}</div>
          <div className="draft-card-status">&#9679;&nbsp;&nbsp;Черновик</div>
        </div>
        <CardMenu items={menuItems} />
      </div>

      {suggestions.length > 0 ? (
        <>
          <div className="draft-card-label">ИИ-агенты в черновике</div>
          {suggestions.map((item) => {
            const created = createdTitles.has(normalizeTitle(item.title))
            return (
              <div className="suggestion-row" key={item.agentId}>
                <div className="suggestion-name">{item.title || 'ИИ-агент'}</div>
                <div className="suggestion-desc">
                  {item.description || 'Функция из регламента'}
                </div>
                <button
                  className="btn-primary suggestion-btn"
                  disabled={created}
                  onClick={() => onFormSuggestion(draftId, item.agentId)}
                >
                  {created ? 'Сформирован' : 'Сформировать'}
                </button>
              </div>
            )
          })}
        </>
      ) : (
        <>
          <div className="draft-card-empty">
            ИИ-агенты ещё не выделены. Продолжите формирование черновика.
          </div>
          <button className="btn-primary suggestion-btn" onClick={() => onContinue(draftId)}>
            Сформировать
          </button>
        </>
      )}
    </div>
  )
}
