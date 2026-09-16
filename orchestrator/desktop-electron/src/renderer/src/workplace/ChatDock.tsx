import { useState } from 'react'

interface ChatDockProps {
  onAskOrchestrator: (message: string) => void
  onOpenSupport: () => void
}

export function ChatDock({ onAskOrchestrator, onOpenSupport }: ChatDockProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')

  function openOrchestrator(message = ''): void {
    setOpen(false)
    setDraft('')
    onAskOrchestrator(message)
  }

  function openSupport(): void {
    setOpen(false)
    onOpenSupport()
  }

  return (
    <div className="chat-dock">
      {open && (
        <div className="chat-dock-panel">
          <div className="chat-dock-head">
            <strong>Чат</strong>
            <button type="button" className="btn-ghost" onClick={() => setOpen(false)}>
              Свернуть
            </button>
          </div>
          <div className="chat-dock-actions">
            <button type="button" className="btn-primary chat-dock-action" onClick={() => openOrchestrator()}>
              Оркестратор
            </button>
            <button type="button" className="btn-ghost chat-dock-action" onClick={openSupport}>
              Поддержка
            </button>
          </div>
          <form
            className="chat-dock-form"
            onSubmit={(event) => {
              event.preventDefault()
              const text = draft.trim()
              if (!text) return
              openOrchestrator(text)
            }}
          >
            <input
              type="text"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Спросить оркестратора…"
              autoComplete="off"
            />
            <button type="submit" className="btn-primary" disabled={!draft.trim()}>
              Отправить
            </button>
          </form>
        </div>
      )}
      <button type="button" className="chat-dock-btn" onClick={() => setOpen((v) => !v)}>
        Чат
      </button>
    </div>
  )
}
