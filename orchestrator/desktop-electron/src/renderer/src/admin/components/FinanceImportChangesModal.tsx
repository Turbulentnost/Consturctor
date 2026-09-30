import { useEffect, useMemo, useState } from 'react'
import {
  fetchFinanceImportChanges,
  type FinanceChangeEntry,
  type FinanceImport,
  type FinanceImportChanges
} from '../financeApi'
import { AdminModal } from './shared/AdminModal'

type ChangeTab = 'added' | 'updated' | 'removed'

const TABS: { id: ChangeTab; label: string }[] = [
  { id: 'added', label: 'Добавлено' },
  { id: 'updated', label: 'Обновлено' },
  { id: 'removed', label: 'Удалено' }
]

interface FinanceImportChangesModalProps {
  item: FinanceImport | null
  onClose: () => void
}

function amountLabel(entry: FinanceChangeEntry): string {
  const value = Number(entry.amount)
  const amount = Number.isFinite(value) && entry.amount
    ? value.toLocaleString('ru-RU', { maximumFractionDigits: 2 })
    : entry.amount || '—'
  return entry.currency && entry.currency !== 'RUB' ? `${amount} ${entry.currency}` : `${amount} ₽`
}

function dateLabel(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value)
  return match ? `${match[3]}.${match[2]}.${match[1]}` : value
}

function EntryDetails({ entry, kind, tab }: {
  entry: FinanceChangeEntry
  kind: FinanceImport['kind']
  tab: ChangeTab
}): React.JSX.Element {
  if (tab === 'updated') {
    return (
      <ul className="finance-changes__diff">
        {entry.changes.map((change, index) => (
          <li key={index}>
            <span className="finance-changes__diff-label">{change.label}</span>
            {change.before ? <del>{change.before}</del> : null}
            {change.before && change.after ? <span aria-hidden="true">→</span> : null}
            {change.after ? <ins>{change.after}</ins> : null}
          </li>
        ))}
      </ul>
    )
  }
  if (kind === 'salary') {
    return (
      <span>
        Оклад <strong>{amountLabel(entry)}</strong>
        {entry.effectiveFrom ? ` с ${dateLabel(entry.effectiveFrom)}` : ''}
      </span>
    )
  }
  if (!entry.metrics.length) return <span className="finance-changes__muted">KPI не указаны</span>
  return (
    <ul className="finance-changes__metrics">
      {entry.metrics.map((metric) => (
        <li key={metric.name}>
          {metric.name} — <strong>{metric.weight}%</strong>
          {metric.plan ? `, цель ${metric.plan}` : ''}
        </li>
      ))}
    </ul>
  )
}

export function FinanceImportChangesModal({ item, onClose }: FinanceImportChangesModalProps): React.JSX.Element {
  const [changes, setChanges] = useState<FinanceImportChanges | null>(null)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<ChangeTab>('added')
  const [query, setQuery] = useState('')

  useEffect(() => {
    if (!item) return
    let alive = true
    setChanges(null)
    setError('')
    setQuery('')
    fetchFinanceImportChanges(item.id)
      .then((result) => {
        if (!alive) return
        setChanges(result)
        setTab(TABS.find((option) => result[option.id].length)?.id ?? 'added')
      })
      .catch((reason: unknown) => {
        if (alive) setError(reason instanceof Error ? reason.message : 'Не удалось загрузить изменения')
      })
    return () => {
      alive = false
    }
  }, [item])

  const visible = useMemo(() => {
    const entries = changes?.[tab] ?? []
    const needle = query.trim().toLocaleLowerCase('ru-RU')
    if (!needle) return entries
    return entries.filter((entry) =>
      `${entry.position} ${entry.department}`.toLocaleLowerCase('ru-RU').includes(needle)
    )
  }, [changes, tab, query])

  const subject = item?.kind === 'material_incentive' ? 'KPI должностей' : 'оклады должностей'

  return (
    <AdminModal
      title={item ? `Что изменилось — ${item.fileName || 'импорт'}` : ''}
      open={item !== null}
      onClose={onClose}
      className="admin-modal--wide"
    >
      {error ? <p className="finance-message finance-message--error" role="alert">{error}</p> : null}
      {!error && !changes ? <p className="finance-message">Сравниваю с предыдущей версией…</p> : null}
      {changes && item ? (
        <div className="finance-changes">
          <p className="finance-changes__note">
            {item.status === 'confirmed'
              ? `Сравнение с данными, которые действовали до записи этого файла (${subject}).`
              : 'Файл ещё не записан в БД — показано, что изменится после подтверждения.'}
            {changes.summary.hasBaseline
              ? ''
              : ' Это первая версия для этих подразделений, поэтому всё считается добавленным.'}
            {changes.summary.unchanged ? ` Без изменений: ${changes.summary.unchanged}.` : ''}
          </p>
          <div className="finance-changes__toolbar">
            <div className="finance-changes__tabs" role="tablist">
              {TABS.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  role="tab"
                  aria-selected={tab === option.id}
                  className={`finance-changes__tab finance-changes__tab--${option.id}${tab === option.id ? ' is-active' : ''}`}
                  onClick={() => setTab(option.id)}
                >
                  {option.label} <span>{changes[option.id].length}</span>
                </button>
              ))}
            </div>
            <input
              className="finance-changes__search"
              type="search"
              placeholder="Должность или подразделение"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          {visible.length ? (
            <div className="finance-changes__list">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th style={{ width: '32%' }}>Должность</th>
                    <th style={{ width: '24%' }}>Подразделение</th>
                    <th>{tab === 'updated' ? 'Что изменилось' : item.kind === 'salary' ? 'Оклад' : 'KPI'}</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((entry, index) => (
                    <tr key={`${entry.department}-${entry.position}-${index}`}>
                      <td>{entry.position || '—'}</td>
                      <td>{entry.department || 'Без подразделения'}</td>
                      <td>
                        <EntryDetails entry={entry} kind={item.kind} tab={tab} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="finance-empty">
              {query.trim() ? 'Ничего не найдено' : 'В этой категории изменений нет'}
            </p>
          )}
        </div>
      ) : null}
    </AdminModal>
  )
}
