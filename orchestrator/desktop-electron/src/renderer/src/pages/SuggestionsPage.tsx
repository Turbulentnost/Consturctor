import type { AgentSuggestion } from '../api/types'

interface SuggestionsPageProps {
  suggestions: AgentSuggestion[]
  busy?: boolean
  onBack: () => void
  onCreate: (suggestion: AgentSuggestion) => void
}

export function SuggestionsPage({
  suggestions,
  busy,
  onBack,
  onCreate
}: SuggestionsPageProps): React.JSX.Element {
  return (
    <div>
      <div className="chat-head">
        <button className="btn-ghost" onClick={onBack}>
          {'\u2039'} Назад
        </button>
        <h1 className="page-title" style={{ fontSize: 28 }}>
          ИИ-агенты для реализации
        </h1>
        <p className="page-subtitle">
          Выберите ИИ-агента из найденных функций. Все варианты сохранены в черновиках.
        </p>
      </div>

      <div className="card-list">
        {suggestions.length === 0 && (
          <div className="placeholder-card">ИИ-агенты для реализации пока не найдены.</div>
        )}
        {suggestions.map((item) => (
          <div key={item.agentId} className="option-card" style={{ alignItems: 'stretch' }}>
            <h3 style={{ textAlign: 'left' }}>{item.title}</h3>
            <p style={{ textAlign: 'left' }}>{item.description || 'Без описания'}</p>
            <button
              className="btn-primary"
              style={{ maxWidth: 240, marginTop: 8 }}
              onClick={() => onCreate(item)}
              disabled={busy}
            >
              {busy ? 'Открываем паспорт...' : 'Создать агента'}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
