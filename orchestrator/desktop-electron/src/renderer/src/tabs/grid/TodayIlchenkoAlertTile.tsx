import type { UserProfile } from '../../api/types'
import { isDueWithinDays } from '../../workplace/assignmentRegistryMappers'
import { useAssignmentRegistry } from '../../workplace/useAssignmentRegistry'

function isoDay(day: Date): string {
  const month = String(day.getMonth() + 1).padStart(2, '0')
  const date = String(day.getDate()).padStart(2, '0')
  return `${day.getFullYear()}-${month}-${date}`
}

/** Тот же период, что открыт в реестре поручений, иначе с начала года по сегодня. */
function registryRange(userId: string): { from: string; to: string } {
  const today = new Date()
  const fallback = { from: `${today.getFullYear()}-01-01`, to: isoDay(today) }
  try {
    const raw = sessionStorage.getItem(`orch-registry:${userId || 'default'}:filters`)
    if (!raw) return fallback
    const parsed = JSON.parse(raw) as { from?: string; to?: string }
    const from = /^\d{4}-\d{2}-\d{2}$/.test(parsed.from || '') ? String(parsed.from) : fallback.from
    const to = /^\d{4}-\d{2}-\d{2}$/.test(parsed.to || '') ? String(parsed.to) : fallback.to
    return { from, to }
  } catch {
    return fallback
  }
}

/**
 * Плитка «Поручения»: те же «Просроченные» и «Подходит срок», что в реестре.
 * Числа берутся из того же журнала и того же периода.
 */
export function TodayIlchenkoAlertTile({ user }: { user: UserProfile }): React.JSX.Element {
  const range = registryRange(user.id || '')
  const { rows, loading, error } = useAssignmentRegistry(user.id || '', range.from, range.to)
  const overdue = rows.filter((row) => row.open && row.overdue).length
  const dueSoon = rows.filter((row) => isDueWithinDays(row, 3)).length
  const pending = loading && !rows.length
  const overdueText = pending ? '…' : String(overdue)
  const dueSoonText = pending ? '…' : String(dueSoon)

  return (
    <article className="spec-v04-tile today-assignments-tile" aria-label="Поручения: просроченные и подходящие ко сроку">
      <span className="today-assignments-title">Поручения</span>
      <div className="today-assignments-split">
        <div className="today-assignments-half is-overdue">
          <span>Просроченные</span>
          <strong>{overdueText}</strong>
        </div>
        <div className="today-assignments-half is-soon">
          <span>Подходит срок</span>
          <strong>{dueSoonText}</strong>
        </div>
      </div>
      {error && !rows.length ? <p className="today-assignments-error">{error}</p> : null}
    </article>
  )
}
