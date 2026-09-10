import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ChatThread } from '../api/types'

interface ChatDockProps {
  onOpenThread: (thread: ChatThread) => void
  onOpenSupport: () => void
}

export function ChatDock({ onOpenThread, onOpenSupport }: ChatDockProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const [threads, setThreads] = useState<ChatThread[]>([])
  const unread = threads.reduce((acc, item) => acc + (item.unread || 0), 0)

  useEffect(() => {
    let alive = true
    let pending = 0
    const load = async (): Promise<void> => {
      try {
        const items = await api.listChatThreads()
        if (alive) setThreads(items)
      } catch {
        if (alive) setThreads([])
      }
    }
    void load()
    // Chat pushes replace polling; the debounce collapses message bursts.
    const unsubscribe = window.api.onChatEvent?.(() => {
      window.clearTimeout(pending)
      pending = window.setTimeout(() => void load(), 500)
    })
    return () => {
      alive = false
      window.clearTimeout(pending)
      unsubscribe?.()
    }
  }, [])

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
          <p className="chat-dock-hint">Сообщения сотрудникам. Поле «Задать вопрос оркестратору» — отдельно, не в этот канал.</p>
          <button type="button" className="btn-primary chat-dock-support" onClick={onOpenSupport}>
            Техническая поддержка
          </button>
          <div className="chat-dock-list">
            {threads.length === 0 && <p>Нет диалогов. Найдите сотрудника в меню слева.</p>}
            {threads.map((thread) => (
              <button
                key={thread.id}
                type="button"
                className="wp-row"
                onClick={() => {
                  setOpen(false)
                  onOpenThread(thread)
                }}
              >
                <strong>{thread.title}</strong>
                <span>{thread.preview || 'Диалог'}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      <button type="button" className="chat-dock-btn" onClick={() => setOpen((v) => !v)}>
        Чат
        {unread > 0 && <i>{unread > 9 ? '9+' : unread}</i>}
      </button>
    </div>
  )
}
