import { useEffect, useMemo, useState } from 'react'
import { FileSpreadsheet, Upload } from 'lucide-react'
import {
  confirmFinanceImport,
  fetchFinancePositions,
  financeStatusLabel,
  saveFinanceImportRows,
  uploadFinanceImport,
  type FinanceImport,
  type FinanceImportKind,
  type FinancePosition,
  type FinanceRow
} from '../financeApi'
import { AdminPageHeader } from '../components/shared/AdminPageHeader'
import { AdminPageShell } from '../components/shared/AdminPageShell'

const IMPORT_CARDS: Array<{ kind: FinanceImportKind; title: string; description: string }> = [
  { kind: 'salary', title: 'Оклады', description: 'Загрузите файл с окладами по должностям' },
  {
    kind: 'material_incentive',
    title: 'Материальное стимулирование',
    description: 'Загрузите положение с ЦРП и KPI по должностям'
  }
]

interface FinanceActivity {
  time: string
  text: string
  tone?: 'success' | 'error'
}

function clock(): string {
  return new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Не удалось выполнить операцию'
}

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

function columnLabel(column: string): string {
  const labels: Record<string, string> = {
    position: 'Должность',
    amount: 'Оклад',
    currency: 'Валюта',
    effective_from: 'Действует с',
    position_id: 'Должность',
    position_name: 'Должность',
    bonus_base_pct: 'База премии, %',
    bonus_kind: 'Правило премии',
    metrics: 'KPI'
  }
  return labels[column] ?? column
}

export function FinanceUploadPage(): React.JSX.Element {
  const [files, setFiles] = useState<Partial<Record<FinanceImportKind, string>>>({})
  const [hovered, setHovered] = useState<FinanceImportKind | null>(null)
  const [busyKind, setBusyKind] = useState<FinanceImportKind | null>(null)
  const [currentImport, setCurrentImport] = useState<FinanceImport | null>(null)
  const [draftRows, setDraftRows] = useState<FinanceRow[]>([])
  const [positions, setPositions] = useState<FinancePosition[]>([])
  const [effectiveFrom, setEffectiveFrom] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [activity, setActivity] = useState<FinanceActivity[]>([])
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const columns = useMemo(
    () =>
      Array.from(new Set(draftRows.flatMap((row) => Object.keys(row)))).filter(
        (column) =>
          column !== 'row_id' &&
          !(currentImport?.kind === 'salary' && column === 'position_name')
      ),
    [currentImport?.kind, draftRows]
  )

  useEffect(() => {
    if (startedAt === null) return
    const update = (): void => setElapsedSeconds(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)))
    update()
    const timer = window.setInterval(update, 1000)
    return () => window.clearInterval(timer)
  }, [startedAt])

  async function pickFile(kind: FinanceImportKind): Promise<void> {
    const paths = await window.api.openFile({
      title: kind === 'salary' ? 'Выберите файл с окладами' : 'Выберите файл со стимулированием',
      filters: [
        {
          name: 'Документы',
          extensions: ['xlsx', 'xlsm', 'csv', 'tsv', 'txt', 'pdf', 'docx', 'png', 'jpg', 'jpeg']
        }
      ],
      properties: ['openFile']
    })
    if (paths[0]) setFiles((previous) => ({ ...previous, [kind]: paths[0] }))
  }

  function handleDrop(kind: FinanceImportKind, event: React.DragEvent): void {
    event.preventDefault()
    setHovered(null)
    const file = event.dataTransfer.files?.[0]
    const path = file ? window.api.getPathForFile(file) : ''
    if (!path) {
      setError('Не удалось получить путь к файлу. Выберите файл через диалог.')
      return
    }
    setFiles((previous) => ({ ...previous, [kind]: path }))
  }

  async function upload(kind: FinanceImportKind): Promise<void> {
    const path = files[kind]
    if (!path) return
    setBusyKind(kind)
    setError('')
    setMessage('')
    setElapsedSeconds(0)
    setStartedAt(Date.now())
    setActivity([
      { time: clock(), text: `Читаю файл «${fileName(path)}» и передаю его в backend.` },
      {
        time: clock(),
        text:
          kind === 'salary'
            ? 'Backend сохранит оригинал и запустит Cursor SDK для извлечения окладов по должностям.'
            : 'Backend сохранит оригинал и извлечёт положение о материальном стимулировании.'
      }
    ])
    try {
      const result = await uploadFinanceImport(kind, path)
      setActivity((previous) => [
        ...previous,
        {
          time: clock(),
          text: `Обработка завершена: извлечено ${result.rows.length} строк.`,
          tone: 'success'
        }
      ])
      setCurrentImport(result)
      setDraftRows(result.rows)
      setEffectiveFrom(result.effectiveFrom)
      if (kind === 'salary' && !positions.length) {
        setActivity((previous) => [
          ...previous,
          { time: clock(), text: 'Сопоставляю извлечённые названия со справочником должностей.' }
        ])
        try {
          setPositions(await fetchFinancePositions())
          setActivity((previous) => [
            ...previous,
            { time: clock(), text: 'Справочник должностей загружен.', tone: 'success' }
          ])
        } catch {
          setError('Файл обработан, но список должностей загрузить не удалось.')
          setActivity((previous) => [
            ...previous,
            { time: clock(), text: 'Не удалось загрузить справочник должностей.', tone: 'error' }
          ])
        }
      }
      if (result.errors.length) {
        setActivity((previous) => [
          ...previous,
          {
            time: clock(),
            text: `Проверка нашла ошибок: ${result.errors.length}. Исправьте отмеченные строки.`,
            tone: 'error'
          }
        ])
      } else {
        setActivity((previous) => [
          ...previous,
          { time: clock(), text: 'Проверка завершена без ошибок.', tone: 'success' }
        ])
      }
      setMessage(`Файл «${result.fileName || fileName(path)}» обработан. Проверьте извлечённые строки.`)
    } catch (reason) {
      setError(errorMessage(reason))
      setActivity((previous) => [
        ...previous,
        { time: clock(), text: `Обработка остановлена: ${errorMessage(reason)}`, tone: 'error' }
      ])
    } finally {
      setStartedAt(null)
      setBusyKind(null)
    }
  }

  function updateCell(rowIndex: number, key: string, value: string): void {
    setDraftRows((previous) =>
      previous.map((row, index) => (index === rowIndex ? { ...row, [key]: value } : row))
    )
  }

  function selectPosition(rowIndex: number, positionId: string): void {
    const position = positions.find((item) => item.id === positionId)
    setDraftRows((previous) =>
      previous.map((row, index) =>
        index === rowIndex
          ? {
              ...row,
              position_id: positionId,
              position_name: position?.name ?? row.position_name
            }
          : row
      )
    )
  }

  async function saveRows(): Promise<void> {
    if (!currentImport) return
    setBusyKind(currentImport.kind)
    setError('')
    try {
      const saved = await saveFinanceImportRows(currentImport, draftRows, effectiveFrom)
      setCurrentImport({ ...saved, rows: saved.rows.length ? saved.rows : draftRows })
      if (saved.rows.length) setDraftRows(saved.rows)
      setEffectiveFrom(saved.effectiveFrom)
      setMessage('Изменения сохранены.')
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setBusyKind(null)
    }
  }

  async function confirm(): Promise<void> {
    if (!currentImport) return
    setBusyKind(currentImport.kind)
    setError('')
    try {
      await saveFinanceImportRows(currentImport, draftRows, effectiveFrom)
      const confirmed = await confirmFinanceImport(currentImport.id)
      setCurrentImport(confirmed)
      setMessage('Импорт подтверждён.')
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setBusyKind(null)
    }
  }

  return (
    <AdminPageShell breadcrumb="" className="finance-page">
      <AdminPageHeader
        title="Загрузить"
        subtitle="Импортируйте таблицу и проверьте строки перед подтверждением"
      />
      {error ? <p className="finance-message finance-message--error" role="alert">{error}</p> : null}
      {message ? <p className="finance-message finance-message--success">{message}</p> : null}
      <div className="finance-upload-grid">
        {IMPORT_CARDS.map((card) => {
          const path = files[card.kind]
          const busy = busyKind === card.kind
          return (
            <section className="admin-panel finance-upload-card" key={card.kind}>
              <div className="finance-upload-card__icon"><FileSpreadsheet size={24} /></div>
              <h2>{card.title}</h2>
              <p>{card.description}</p>
              <div
                className={`finance-dropzone${hovered === card.kind ? ' is-hovered' : ''}`}
                onDragOver={(event) => {
                  event.preventDefault()
                  setHovered(card.kind)
                }}
                onDragLeave={() => setHovered(null)}
                onDrop={(event) => handleDrop(card.kind, event)}
              >
                <Upload size={22} />
                <strong>{path ? fileName(path) : 'Перетащите один файл сюда'}</strong>
                <button type="button" onClick={() => void pickFile(card.kind)}>Выбрать файл</button>
                <span>Excel, CSV, PDF, Word или изображение</span>
              </div>
              <button
                type="button"
                className="admin-primary-btn finance-upload-card__submit"
                disabled={!path || busy}
                onClick={() => void upload(card.kind)}
              >
                {busy ? 'Загрузка…' : 'Загрузить и распознать'}
              </button>
            </section>
          )
        })}
      </div>

      {activity.length ? (
        <section className="admin-panel finance-activity" aria-live="polite">
          <div className="finance-activity__header">
            <h2 className="finance-section-title">Журнал обработки</h2>
            {startedAt !== null ? (
              <span className="finance-activity__running">
                <i aria-hidden="true" />
                Выполняется · {elapsedSeconds} сек.
              </span>
            ) : null}
          </div>
          <ol>
            {activity.map((item, index) => (
              <li className={item.tone ? `is-${item.tone}` : ''} key={`${item.time}-${index}`}>
                <time>{item.time}</time>
                <span>{item.text}</span>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {currentImport ? (
        <section className="admin-panel finance-confirmation">
          <div className="finance-confirmation__header">
            <div>
              <h2 className="finance-section-title">Подтверждение данных</h2>
              <p>{currentImport.fileName} · {draftRows.length} строк</p>
            </div>
            <span className="finance-status">{financeStatusLabel(currentImport.status)}</span>
          </div>
          {!draftRows.length ? <p className="finance-empty">Извлечённые строки отсутствуют</p> : null}
          {currentImport.kind === 'material_incentive' ? (
            <label className="finance-effective-date">
              Дата вступления в силу
              <input
                type="date"
                value={effectiveFrom}
                onChange={(event) => setEffectiveFrom(event.target.value)}
              />
            </label>
          ) : null}
          {draftRows.length ? (
            <div className="finance-edit-table-wrap">
              <table className="finance-edit-table">
                <thead>
                  <tr>{columns.map((column) => <th key={column}>{columnLabel(column)}</th>)}</tr>
                </thead>
                <tbody>
                  {draftRows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {columns.map((column) => (
                        <td key={column}>
                          {currentImport.kind === 'salary' && column === 'position_id' ? (
                            <select
                              aria-label={`Должность, строка ${rowIndex + 1}`}
                              value={String(row[column] ?? '')}
                              onChange={(event) => selectPosition(rowIndex, event.target.value)}
                            >
                              <option value="">Выберите должность</option>
                              {positions.map((position) => (
                                <option key={position.id} value={position.id}>
                                  {position.name}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <input
                              aria-label={`${column}, строка ${rowIndex + 1}`}
                              value={String(row[column] ?? '')}
                              onChange={(event) => updateCell(rowIndex, column, event.target.value)}
                            />
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {currentImport.errors.length ? (
            <ul className="finance-import-errors">
              {currentImport.errors.map((item, index) => <li key={index}>{item}</li>)}
            </ul>
          ) : null}
          <div className="finance-confirmation__actions">
            <button type="button" className="admin-outline-btn" disabled={Boolean(busyKind)} onClick={() => void saveRows()}>
              Сохранить изменения
            </button>
            <button type="button" className="admin-primary-btn" disabled={Boolean(busyKind) || !draftRows.length} onClick={() => void confirm()}>
              Подтвердить импорт
            </button>
          </div>
        </section>
      ) : null}
    </AdminPageShell>
  )
}
