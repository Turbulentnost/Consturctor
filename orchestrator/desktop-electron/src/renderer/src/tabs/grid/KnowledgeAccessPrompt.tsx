import { useEffect, useState } from 'react'
import { Check, X } from 'lucide-react'
import { api, type ExplorerAccessSuggestion } from '../../api/client'

function accessLabel(item: ExplorerAccessSuggestion): string {
  if (item.kind === 'private') return 'Закрыть'
  return item.permission === 'write' ? 'Запись' : 'Чтение'
}

function personMeta(item: ExplorerAccessSuggestion): string {
  if (item.kind !== 'user') return item.position
  return [item.position, item.department].filter(Boolean).join(' · ')
}

/** Предложения серверного агента: под плитками «Сегодня», в виде сообщения. */
export function KnowledgeAccessPrompt(): React.JSX.Element | null {
  const [items, setItems] = useState<ExplorerAccessSuggestion[] | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

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

  if (!items?.length) return null

  const groups = new Map<string, ExplorerAccessSuggestion[]>()
  for (const item of items) {
    const rows = groups.get(item.fileId) ?? []
    rows.push(item)
    groups.set(item.fileId, rows)
  }

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
      {[...groups.entries()].map(([fileId, rows]) => (
        <article key={fileId} className="ht-access-row">
          <span className="ht-access-avatar" aria-hidden>
            И
          </span>
          <div className="ht-access-bubble">
            <p className="ht-access-kicker">База знаний</p>
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
                    {item.kind === 'all' || item.kind === 'private' ? (
                      item.reason ? <q>{item.reason}</q> : null
                    ) : item.quote ? (
                      <q>{item.quote}</q>
                    ) : null}
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
      ))}
    </section>
  )
}
