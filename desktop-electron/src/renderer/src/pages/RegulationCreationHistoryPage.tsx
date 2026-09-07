import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { ApiError, type RegulationCreationHistoryItem, type RegulationCreationSession } from '../api/types'
import { formatRegulationMessageTime } from '../utils/regulationChat'

interface RegulationCreationHistoryPageProps {
  onBack: () => void
  onContinue: (draftId: string) => void | Promise<void>
}

const STATUS_LABELS: Record<string, string> = {
  collecting_positions: 'Новый',
  interview: 'Интервью',
  generating: 'Формируется',
  finalized: 'Готов',
  error: 'Ошибка',
  closed: 'Закрыт'
}

function formatDateTime(value: string): string {
  if (!value) return 'Без даты'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date)
}

function roleLabel(role: string): string {
  if (role === 'user') return 'Вы'
  if (role === 'assistant') return 'ИИ'
  return 'Система'
}

export function RegulationCreationHistoryPage({
  onBack,
  onContinue
}: RegulationCreationHistoryPageProps): React.JSX.Element {
  const [items, setItems] = useState<RegulationCreationHistoryItem[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [selected, setSelected] = useState<RegulationCreationSession | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState('')

  async function loadHistory(): Promise<void> {
    setLoading(true)
    setError('')
    try {
      const list = await api.listRegulationCreationHistory()
      setItems(list)
      const nextId = selectedId || list[0]?.draftId || ''
      setSelectedId(nextId)
      if (nextId) await loadDetails(nextId)
      else setSelected(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить историю')
    } finally {
      setLoading(false)
    }
  }

  async function loadDetails(draftId: string): Promise<void> {
    setDetailLoading(true)
    setError('')
    try {
      setSelected(await api.getRegulationCreationSession(draftId))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось открыть черновик')
    } finally {
      setDetailLoading(false)
    }
  }

  useEffect(() => {
    void loadHistory()
  }, [])

  const selectedItem = useMemo(
    () => items.find((item) => item.draftId === selectedId) || null,
    [items, selectedId]
  )
  const messages = selected?.messages.slice(-12) ?? []
  const canContinue = Boolean(selectedItem?.canContinue && selectedId)

  return (
    <div className="reg-history-page">
      <div className="reg-history-head">
        <button className="btn-ghost" onClick={onBack}>
          {'\u2039'} Назад
        </button>
        <div>
          <h1 className="page-title">История создания регламентов</h1>
          <p className="page-subtitle">Откройте черновик и продолжите формирование с сохранённого места</p>
        </div>
      </div>

      {error && <div className="status-line error">{error}</div>}

      <div className="reg-history-shell">
        <aside className="reg-history-list">
          <div className="reg-history-list-head">
            <span>История</span>
            <button className="reg-history-refresh" type="button" onClick={() => void loadHistory()}>
              Обновить
            </button>
          </div>
          {loading ? (
            <div className="reg-history-empty">Загружаю историю...</div>
          ) : items.length === 0 ? (
            <div className="reg-history-empty">История пока пуста</div>
          ) : (
            items.map((item) => (
              <button
                key={item.draftId}
                type="button"
                className={
                  item.draftId === selectedId ? 'reg-history-item active' : 'reg-history-item'
                }
                onClick={() => {
                  setSelectedId(item.draftId)
                  void loadDetails(item.draftId)
                }}
              >
                <span className="reg-history-item-title">{formatDateTime(item.updatedAt)}</span>
                <span className="reg-history-item-meta">
                  {STATUS_LABELS[item.status] || item.status}
                  {item.messageCount ? ` · ${item.messageCount} сообщ.` : ''}
                </span>
                <span className="reg-history-item-preview">{item.title || item.preview}</span>
              </button>
            ))
          )}
        </aside>

        <section className="reg-history-detail">
          {!selectedId ? (
            <div className="reg-history-empty big">Выберите запись слева</div>
          ) : detailLoading ? (
            <div className="reg-history-empty big">Открываю черновик...</div>
          ) : (
            <>
              <div className="reg-history-detail-top">
                <div className="reg-history-detail-main">
                  <div className="reg-history-detail-kicker">
                    {selectedItem ? formatDateTime(selectedItem.updatedAt) : 'Черновик'}
                  </div>
                  <h2>{selectedItem?.title || 'Черновик регламента'}</h2>
                  <div className="reg-history-detail-meta">
                    <span>{STATUS_LABELS[selectedItem?.status || ''] || selectedItem?.status}</span>
                    {selectedItem?.hasResult ? <span>Есть файл регламента</span> : null}
                  </div>
                </div>
                <button
                  className="btn-primary reg-history-continue"
                  type="button"
                  disabled={!canContinue}
                  onClick={() => void onContinue(selectedId)}
                >
                  Продолжить
                </button>
              </div>

              <div className="reg-history-messages">
                {messages.length === 0 ? (
                  <div className="reg-history-empty">Сообщений пока нет</div>
                ) : (
                  messages.map((message) => {
                    const timeLabel = formatRegulationMessageTime(message.createdAt)
                    return (
                      <div key={message.messageId} className={`reg-history-message ${message.role}`}>
                        <div className="reg-history-message-role">
                          {roleLabel(message.role)}
                          {timeLabel ? ` · ${timeLabel}` : ''}
                        </div>
                        <div className="reg-history-message-text">{message.content || 'Файл без текста'}</div>
                      </div>
                    )
                  })
                )}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
