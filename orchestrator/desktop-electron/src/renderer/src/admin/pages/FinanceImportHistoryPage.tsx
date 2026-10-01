import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import {
  fetchFinanceImports,
  financeStatusLabel,
  openFinanceImport,
  type FinanceImport
} from '../financeApi'
import { FinanceImportChangesModal } from '../components/FinanceImportChangesModal'
import { AdminDataTable } from '../components/shared/AdminDataTable'
import { AdminPageHeader } from '../components/shared/AdminPageHeader'
import { AdminPageShell } from '../components/shared/AdminPageShell'

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Не удалось загрузить историю'
}

function kindLabel(kind: FinanceImport['kind']): string {
  return kind === 'material_incentive' ? 'Материальное стимулирование' : 'Оклады'
}

function dateTimeLabel(value: string): string {
  const date = new Date(value)
  if (!value || Number.isNaN(date.getTime())) return '—'
  return date
    .toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
    .replace(',', '')
}

function ChangesCell({ item, onOpen }: { item: FinanceImport; onOpen: () => void }): React.JSX.Element {
  const changes = item.changes
  if (!changes) return <span className="finance-changes__muted">—</span>
  const lines = [
    { id: 'added', label: 'Добавлено', value: changes.added },
    { id: 'updated', label: 'Обновлено', value: changes.updated },
    { id: 'removed', label: 'Удалено', value: changes.removed }
  ]
  const touched = changes.added + changes.updated + changes.removed
  const hint = !touched
    ? 'Без изменений'
    : !changes.hasBaseline
      ? 'Первая версия'
      : item.status !== 'confirmed'
        ? 'Если подтвердить'
        : ''
  return (
    <button
      type="button"
      className="finance-changes-cell"
      title="Показать, что изменилось в этой версии"
      onClick={onOpen}
    >
      {lines.map((line) => (
        <span
          key={line.id}
          className={`finance-changes-cell__line finance-changes-cell__line--${line.id}${line.value ? '' : ' is-zero'}`}
        >
          {line.label}: <strong>{line.value}</strong>
        </span>
      ))}
      {hint ? <span className="finance-changes-cell__hint">{hint}</span> : null}
    </button>
  )
}

export function FinanceImportHistoryPage(): React.JSX.Element {
  const [items, setItems] = useState<FinanceImport[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [openingId, setOpeningId] = useState('')
  const [changesItem, setChangesItem] = useState<FinanceImport | null>(null)

  async function load(silent = false): Promise<void> {
    if (!silent) setLoading(true)
    setError('')
    try {
      const result = await fetchFinanceImports()
      setItems(result)
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    const refresh = (): void => {
      if (document.visibilityState === 'visible') void load(true)
    }
    const timer = window.setInterval(refresh, 5000)
    window.addEventListener('focus', refresh)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
    }
  }, [])

  async function openFile(item: FinanceImport): Promise<void> {
    setOpeningId(item.id)
    setError('')
    try {
      await openFinanceImport(item)
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setOpeningId('')
    }
  }

  return (
    <AdminPageShell breadcrumb="" className="finance-page">
      <AdminPageHeader
        title="История"
        subtitle="Загруженные файлы, статусы обработки и исходные документы"
        actions={
          <button type="button" className="admin-outline-btn" disabled={loading} onClick={() => void load()}>
            <RefreshCw size={14} /> Обновить
          </button>
        }
      />
      {error ? <p className="finance-message finance-message--error" role="alert">{error}</p> : null}
      <section className="admin-panel">
        {loading ? <p className="finance-message">Загрузка…</p> : null}
        {!loading && !items.length ? <p className="finance-empty">Импорты ещё не выполнялись</p> : null}
        <AdminDataTable
          columns={[
            { id: 'date', label: 'Дата', width: '160px' },
            { id: 'kind', label: 'Тип' },
            { id: 'file', label: 'Файл' },
            { id: 'status', label: 'Статус', width: '130px' },
            { id: 'changes', label: 'Результат', width: '170px' },
            { id: 'rows', label: 'Строк', width: '80px', align: 'right' }
          ]}
          rows={items.map((item) => [
            dateTimeLabel(item.createdAt),
            kindLabel(item.kind),
            <button
              type="button"
              className="finance-link-button"
              disabled={openingId === item.id}
              onClick={() => void openFile(item)}
            >
              {openingId === item.id ? 'Открываю…' : item.fileName || `Импорт ${item.id}`}
            </button>,
            <span className="finance-status">{financeStatusLabel(item.status)}</span>,
            <ChangesCell item={item} onOpen={() => setChangesItem(item)} />,
            item.rowsCount
          ])}
        />
      </section>
      <FinanceImportChangesModal item={changesItem} onClose={() => setChangesItem(null)} />
    </AdminPageShell>
  )
}
