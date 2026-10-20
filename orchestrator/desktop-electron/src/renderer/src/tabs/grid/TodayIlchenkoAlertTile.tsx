import type { UserProfile } from '../../api/types'
import { isDueWithinDays } from '../../workplace/assignmentRegistryMappers'
import type { AssignmentRegistryTileId } from '../../workplace/assignmentRegistryTypes'
import { useAssignmentRegistry } from '../../workplace/useAssignmentRegistry'
import { openWorkplaceTab } from '../../workplace/workplaceNav'

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

  const openRegistry = (tile: AssignmentRegistryTileId | 'all'): void => {
    try {
      const key = `orch-registry:${user.id || 'default'}:filters`
      const raw = sessionStorage.getItem(key)
      const parsed = raw ? (JSON.parse(raw) as { columns?: unknown }) : {}
      sessionStorage.setItem(
        key,
        JSON.stringify({ from: range.from, to: range.to, tile, columns: parsed.columns ?? {} })
      )
    } catch {
      /* ignore */
    }
    openWorkplaceTab('assignments_registry', { registryTile: tile })
  }

  const problem = error && !rows.length ? assignmentErrorText(error) : ''

  return (
    <section className="ht-card ht-assignments" aria-label="Поручения: просроченные и подходящие ко сроку">
      <div className="ht-card-h">
        <h2>Поручения</h2>
        <button className="ht-text" type="button" onClick={() => openRegistry('all')}>
          Журнал
        </button>
      </div>
      {problem ? <p className="ht-note">{problem}</p> : null}
      <div className="ht-rows">
        <button type="button" className="ht-task" onClick={() => openRegistry('overdue')}>
          <span className="ht-main">
            <span className="ht-title">Просрочено</span>
            <span className="ht-preview">срок уже прошёл, поручение открыто</span>
          </span>
          <span className="ht-count">{overdueText}</span>
        </button>
        <button type="button" className="ht-task" onClick={() => openRegistry('due_soon')}>
          <span className="ht-main">
            <span className="ht-title">Срок близко</span>
            <span className="ht-preview">осталось не больше трёх дней</span>
          </span>
          <span className="ht-count">{dueSoonText}</span>
        </button>
      </div>
    </section>
  )
}

function assignmentErrorText(error: string): string {
  if (/503/.test(error)) {
    return 'Журнал поручений сейчас недоступен: сервер 1С ответил 503. Это не пароль — публикация OData не принимает запросы.'
  }
  if (/401|402|парол|учёт/i.test(error)) {
    return 'Журнал поручений не открылся: 1С не приняла учётную запись.'
  }
  return 'Журнал поручений не открылся. Повторите позже.'
}
