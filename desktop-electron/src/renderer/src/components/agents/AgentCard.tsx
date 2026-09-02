import type { BoardAgent } from '../../api/types'
import { runLine } from '../../utils/calendar'
import { CardMenu, type MenuItem } from './CardMenu'

const STATUS: Record<string, { label: string; color: string }> = {
  active: { label: 'Активен', color: '#08745F' },
  paused: { label: 'Приостановлен', color: '#8A9692' },
  needs_attention: { label: 'Требует внимания', color: '#D64545' },
  draft: { label: 'Черновик', color: '#C47F17' }
}

interface AgentCardProps {
  agent: BoardAgent
  selected: boolean
  onSelect: (id: string) => void
  onRun: (id: string) => void
  onOpen: (id: string, title: string) => void
  onHistory: (id: string, title: string) => void
  onSchedule: (id: string) => void
  onPause: (id: string) => void
  onResume: (id: string) => void
  onDelete: (id: string) => void
  canLaunch?: boolean
}

export function AgentCard({
  agent,
  selected,
  onSelect,
  onRun,
  onOpen,
  onHistory,
  onSchedule,
  onPause,
  onResume,
  onDelete,
  canLaunch = true
}: AgentCardProps): React.JSX.Element {
  const status = STATUS[agent.status] ?? STATUS.active
  const lastLine = runLine('Последний запуск', agent.lastRunAt)
  const nextLine = agent.nextRunLabel || runLine('Следующий', agent.nextRunAt)
  const letter = (agent.title || 'А').charAt(0).toUpperCase()

  const menuItems: MenuItem[] = [
    { label: 'Открыть агента', onClick: () => onOpen(agent.id, agent.title) },
    { label: 'Посмотреть историю', onClick: () => onHistory(agent.id, agent.title) },
    { label: 'Изменить расписание', onClick: () => onSchedule(agent.id) },
    agent.paused
      ? { label: 'Возобновить', onClick: () => onResume(agent.id) }
      : { label: 'Приостановить', onClick: () => onPause(agent.id) },
    { label: 'Удалить', onClick: () => onDelete(agent.id), danger: true, separatorBefore: true }
  ]

  return (
    <div
      className={selected ? 'agent-card selected' : 'agent-card'}
      onClick={() => onSelect(agent.id)}
    >
      <div className="agent-card-avatar">{letter}</div>
      <div className="agent-card-body">
        <div className="agent-card-title">{agent.title || 'ИИ-агент'}</div>
        {agent.description.trim() && <div className="agent-card-desc">{agent.description}</div>}
        <div className="agent-card-status" style={{ color: status.color }}>
          &#9679;&nbsp;&nbsp;{status.label}
        </div>
        <div className="agent-card-meta">
          {lastLine}
          <br />
          {nextLine}
        </div>
      </div>
      {canLaunch ? (
        <button
          className="agent-card-run"
          onClick={(e) => {
            e.stopPropagation()
            onRun(agent.id)
          }}
          aria-label="Запустить"
        >
          &#9654;
        </button>
      ) : null}
      <CardMenu items={menuItems} />
    </div>
  )
}
