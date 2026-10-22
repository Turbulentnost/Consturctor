import { useEffect, useMemo, useState } from 'react'
import { Check, ChevronLeft, ChevronRight, X } from 'lucide-react'
import { api, type ExplorerAccessSuggestion } from '../../api/client'

function accessLabel(item: ExplorerAccessSuggestion): string {
  if (item.kind === 'private') return 'Закрыть'
  return item.permission === 'write' ? 'Запись' : 'Чтение'
}

function personMeta(item: ExplorerAccessSuggestion): string {
  if (item.kind !== 'user') return item.position
  return [item.position, item.department].filter(Boolean).join(' · ')
}

/** Предложения серверного агента: один файл — одна карточка, несколько файлов листаются. */
export function KnowledgeAccessPrompt(): React.JSX.Element | null {
  const [items, setItems] = useState<ExplorerAccessSuggestion[] | null>(null)
  const [busy, setBusy] = useState('')
  const [index, setIndex] = useState(0)
  const [error, setError] = useState('')

  const groups = useMemo(() => {
    const grouped = new Map<string, ExplorerAccessSuggestion[]>()
    for (const item of items ?? []) {
      const rows = grouped.get(item.fileId) ?? []
      rows.push(item)
      grouped.set(item.fileId, rows)
    }
    return [...grouped.entries()]
  }, [items])

  useEffect(() => {
    let alive = true
    const load = (): void => {
      void api
        .listExplorerAccessSuggestions()
        .then((rows) => {
          if (alive) setItems(rows)
        })
        .catch(() => {
          if (alive) setItems([])
        })
    }
    load()
    const timer = window.setInterval(load, 60_000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    setIndex((current) => Math.min(current, Math.max(0, groups.length - 1)))
  }, [groups.length])

  if (!groups.length) return null

  const several = groups.length > 1
  const safeIndex = Math.min(index, groups.length - 1)
  const [fileId, rows] = groups[safeIndex]

  const decide = (id: string, accept: boolean): void => {
    setBusy(id)
    setError('')
    void api
      .decideExplorerAccessSuggestion(id, accept)
      .then(() => setItems((prev) => (prev ?? []).filter((item) => item.id !== id)))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Не удалось сохранить решение'))
      .finally(() => setBusy(''))
  }

  return (
    <section className="ht-access" aria-label="Предложения доступа к базе знаний">
      <div className="ht-access-carousel">
        {several ? (
          <button
            type="button"
            className="ht-metrics-arrow"
            aria-label="Предыдущий файл"
            disabled={safeIndex === 0}
            onClick={() => setIndex((current) => Math.max(0, current - 1))}
          >
            <ChevronLeft size={16} />
          </button>
        ) : null}
        <article key={fileId} className="ht-access-row">
          <span className="ht-access-avatar" aria-hidden>
            И
          </span>
          <div className="ht-access-bubble">
            <p className="ht-access-kicker">
              База знаний
              {several ? <span>{safeIndex + 1} из {groups.length}</span> : null}
            </p>
            <p>
              «{rows[0].fileName}» — {rows[0].documentKind}. В тексте есть прямая связь с этими людьми.
              Галочка выдаёт ключ, крестик оставляет файл как есть.
            </p>
            <ul className="ht-access-people">
              {rows.map((item) => (
                <li key={item.id}>
                  <div className="ht-access-who">
                    <strong>{item.label}</strong>
                    {personMeta(item) ? <span>{personMeta(item)}</span> : null}
                    {item.reason ? <span className="ht-access-why">{item.reason}</span> : null}
                    {item.quote && !(item.reason || '').includes(item.quote.slice(0, 24)) ? <q>{item.quote}</q> : null}
                  </div>
                  <em>{accessLabel(item)}</em>
                  <button
                    type="button"
                    className="ht-access-yes"
                    aria-label={`Дать доступ: ${item.label}`}
                    disabled={busy === item.id}
                    onClick={() => decide(item.id, true)}
                  >
                    <Check size={16} />
                  </button>
                  <button
                    type="button"
                    className="ht-access-no"
                    aria-label={`Отклонить: ${item.label}`}
                    disabled={busy === item.id}
                    onClick={() => decide(item.id, false)}
                  >
                    <X size={16} />
                  </button>
                </li>
              ))}
            </ul>
            {error ? <p className="ht-access-error">{error}</p> : null}
          </div>
        </article>
        {several ? (
          <button
            type="button"
            className="ht-metrics-arrow"
            aria-label="Следующий файл"
            disabled={safeIndex >= groups.length - 1}
            onClick={() => setIndex((current) => Math.min(groups.length - 1, current + 1))}
          >
            <ChevronRight size={16} />
          </button>
        ) : null}
      </div>
    </section>
  )
}
