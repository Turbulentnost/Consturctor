import { useState } from 'react'
import { MessageCircle, Send, X } from 'lucide-react'

interface ChatDockProps {
  onAskOrchestrator: (message: string) => void
  onOpenSupport: () => void
}

type DockTarget = 'orchestrator' | 'support'

export function ChatDock({ onAskOrchestrator, onOpenSupport }: ChatDockProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const [target, setTarget] = useState<DockTarget>('orchestrator')

  function close(): void {
    setOpen(false)
  }

  function askOrchestrator(): void {
    const text = draft.trim()
    setDraft('')
    close()
    onAskOrchestrator(text)
  }

  function openSupport(): void {
    setDraft('')
    close()
    onOpenSupport()
  }

  return (
    <div className="chat-dock">
      {open ? (
        <div className="chat-dock-panel" role="dialog" aria-label="Чат">
          <div className="chat-dock-head">
            <strong>Чат</strong>
            <button type="button" className="chat-dock-collapse" onClick={close}>
              Свернуть
            </button>
          </div>
          <div className="chat-dock-tabs" role="tablist" aria-label="Куда отправить">
            <button
              type="button"
              role="tab"
              aria-selected={target === 'orchestrator'}
              className={target === 'orchestrator' ? 'is-active' : undefined}
              onClick={() => setTarget('orchestrator')}
            >
              Оркестратор
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={target === 'support'}
              className={target === 'support' ? 'is-active' : undefined}
              onClick={() => setTarget('support')}
            >
              Поддержка
            </button>
          </div>
          {target === 'orchestrator' ? (
            <>
              <p className="chat-dock-hint">Вопрос уйдёт оркестратору с контекстом текущей вкладки.</p>
              <form
                className="chat-dock-form"
                onSubmit={(event) => {
                  event.preventDefault()
                  askOrchestrator()
                }}
              >
                <div className="chat-dock-input-row">
                  <input
                    type="text"
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    placeholder="Спросить оркестратора…"
                    autoComplete="off"
                    aria-label="Сообщение оркестратору"
                  />
                  <button type="submit" className="chat-dock-send" aria-label="Отправить">
                    <Send size={16} strokeWidth={2} absoluteStrokeWidth />
                  </button>
                </div>
              </form>
            </>
          ) : (
            <>
              <p className="chat-dock-hint">Откроется чат с технической поддержкой. Обращение попадёт в журнал заявок.</p>
              <button type="button" className="chat-dock-open" onClick={openSupport}>
                Открыть чат поддержки
              </button>
            </>
          )}
        </div>
      ) : null}
      <button
        type="button"
        className="chat-dock-btn"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label={open ? 'Свернуть чат' : 'Открыть чат'}
      >
        {open ? <X size={22} strokeWidth={2} absoluteStrokeWidth /> : <MessageCircle size={22} strokeWidth={2} absoluteStrokeWidth />}
      </button>
    </div>
  )
}
