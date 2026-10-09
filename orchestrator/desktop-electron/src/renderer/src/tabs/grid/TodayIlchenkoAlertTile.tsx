import type { UserProfile } from '../../api/types'
import { isDueWithinDays } from '../../workplace/assignmentRegistryMappers'
import { useAssignmentRegistry } from '../../workplace/useAssignmentRegistry'

function isoDay(day: Date): string {
  const month = String(day.getMonth() + 1).padStart(2, '0')
  const date = String(day.getDate()).padStart(2, '0')
  return `${day.getFullYear()}-${month}-${date}`
}

/**
 * Одна плитка для аккаунта Ильченко: просроченные и подходящие ко сроку поручения.
 * Период тот же, что по умолчанию в реестре поручений (с начала года), поэтому данные общие.
 */
export function TodayIlchenkoAlertTile({ user }: { user: UserProfile }): React.JSX.Element {
  const today = new Date()
  const from = `${today.getFullYear()}-01-01`
  const to = isoDay(today)
  const { rows, loading, error } = useAssignmentRegistry(user.id || '', from, to)
  const overdue = rows.filter((row) => row.open && row.overdue).length
  const dueSoon = rows.filter((row) => isDueWithinDays(row, 3)).length
  const pending = loading && !rows.length

  return (
    <div className="today-ilchenko-alert" role="group" aria-label="Просроченные и подходящие ко сроку поручения">
      <div className="today-ilchenko-alert-item">
        <span className="today-ilchenko-alert-label">Просроченные</span>
        <strong className="today-ilchenko-alert-value">{pending ? '…' : overdue}</strong>
      </div>
      <div className="today-ilchenko-alert-item">
        <span className="today-ilchenko-alert-label">Подходит срок</span>
        <strong className="today-ilchenko-alert-value">{pending ? '…' : dueSoon}</strong>
      </div>
      {error && !rows.length ? <p className="today-ilchenko-alert-error">{error}</p> : null}
    </div>
  )
}
