import { useEffect, useMemo, useRef, useState } from 'react'
import { api, parseChatMessage } from '../api/client'
import { agentShareFromBoard, encodeAgentMessage } from '../api/chatCodec'
import { loadUserAvatar } from '../api/avatars'
import wallpaperUrl from '../assets/chat/wallpaper.png'
import type {
  AgentSharePayload,
  BoardAgent,
  ChatAttachment,
  ChatMessage,
  ChatThread,
  UserProfile
} from '../api/types'

interface MessengerPageProps {
  thread: ChatThread
  me: UserProfile
  onThreadChange: (thread: ChatThread) => void
  onOpenAgent: (workflowId: string, title: string) => void
}

function initials(name: string): string {
  const parts = (name || '').replace(/\./g, ' ').split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  if (parts.length === 1) return parts[0][0].toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}

function formatSize(size: number): string {
  if (size <= 0) return ''
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} КБ`
  return `${(size / (1024 * 1024)).toFixed(1).replace('.', ',')} МБ`
}

function dateLabel(value: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value.slice(0, 10)
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const diff = Math.round((today.getTime() - day.getTime()) / 86400000)
  if (diff === 0) return 'Сегодня'
  if (diff === 1) return 'Вчера'
  const dd = String(day.getDate()).padStart(2, '0')
  const mm = String(day.getMonth() + 1).padStart(2, '0')
  return `${dd}.${mm}.${day.getFullYear()}`
}

function formatTime(value: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

function statusLabel(thread: ChatThread): string {
  if (thread.kind === 'support') return 'Поддержка'
  if (thread.online) return 'В сети'
  if (thread.activityStatus === 'busy') return 'Занят'
  if (thread.activityStatus === 'away') return 'Не активен'
  return 'Не в сети'
}

function statusTone(thread: ChatThread): string {
  if (thread.kind === 'support' || thread.online) return 'online'
  if (thread.activityStatus === 'busy') return 'busy'
  return 'offline'
}

function newClientId(): string {
  return crypto.randomUUID().replace(/-/g, '')
}

export function MessengerPage({
  thread,
  me,
  onThreadChange,
  onOpenAgent
}: MessengerPageProps): React.JSX.Element {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [text, setText] = useState('')
  const [pendingFiles, setPendingFiles] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [avatar, setAvatar] = useState<string | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [offer, setOffer] = useState<{ agent: AgentSharePayload; mine: boolean } | null>(null)
  const [agents, setAgents] = useState<BoardAgent[]>([])
  const feedRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const isSupport = thread.kind === 'support'
  const composerMaxPx = 220

  function fitComposer(): void {
    const node = composerRef.current
    if (!node) return
    node.style.height = '0px'
    node.style.overflowY = 'hidden'
    const content = node.scrollHeight
    node.style.height = `${Math.min(Math.max(content, 42), composerMaxPx)}px`
    node.style.overflowY = content > composerMaxPx ? 'auto' : 'hidden'
  }

  useEffect(() => {
    let alive = true
    setMessages([])
    setError('')
    void loadUserAvatar({ id: thread.peerId, avatarUrl: thread.avatarUrl }).then((url) => {
      if (alive) setAvatar(url)
    })
    if (thread.id && thread.id !== 'support') {
      void api
        .listChatMessages(thread.id)
        .then((rows) => {
          if (alive) setMessages(rows)
        })
        .catch((err) => {
          if (alive) setError(err instanceof Error ? err.message : 'Не удалось загрузить чат')
        })
      void api.markChatRead(thread.id)
    }
    return () => {
      alive = false
    }
  }, [thread.id, thread.peerId, thread.avatarUrl])

  useEffect(() => {
    const node = feedRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [messages.length])

  useEffect(() => {
    fitComposer()
  }, [text])

  useEffect(() => {
    const onResize = (): void => fitComposer()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  useEffect(() => {
    const unsubscribe = window.api.onChatEvent?.((payload) => {
      const kind = String(payload.type || '')
      if (kind === 'chat_message') {
        const raw = payload.message && typeof payload.message === 'object' ? payload.message : payload
        const incoming = parseChatMessage({
          ...(raw as Record<string, unknown>),
          mine: String((raw as Record<string, unknown>).sender_id ?? '') === me.id
        })
        const eventThread = String(payload.thread_id ?? incoming.threadId ?? '')
        if (eventThread && eventThread !== thread.id && thread.id !== 'support') return
        setMessages((prev) => {
          if (prev.some((item) => item.id === incoming.id || (incoming.clientId && item.clientId === incoming.clientId))) {
            return prev.map((item) =>
              item.clientId && item.clientId === incoming.clientId ? { ...incoming, agent: incoming.agent ?? item.agent } : item
            )
          }
          return [...prev, incoming]
        })
        if (eventThread && thread.id === 'support') {
          onThreadChange({ ...thread, id: eventThread })
        }
        return
      }
      if (kind === 'thread_opened') {
        const nextId = String(payload.thread_id ?? '')
        const peerId = String(payload.peer_id ?? '')
        if (peerId && peerId === thread.peerId && nextId) {
          onThreadChange({ ...thread, id: nextId })
        }
        return
      }
      if (kind === 'presence') {
        const userId = String(payload.user_id ?? '')
        if (userId && userId === thread.peerId) {
          onThreadChange({
            ...thread,
            activityStatus: String(payload.activity_status ?? thread.activityStatus),
            online: String(payload.activity_status ?? '') === 'online'
          })
        }
      }
    })
    return () => unsubscribe?.()
  }, [me.id, onThreadChange, thread])

  const materials = useMemo(() => {
    const seen = new Set<string>()
    const items: ChatAttachment[] = []
    for (const message of messages) {
      for (const file of message.attachments) {
        const key = file.id || file.filename
        if (!key || seen.has(key)) continue
        seen.add(key)
        items.push(file)
      }
    }
    return items.slice(-8)
  }, [messages])

  const linkedAgents = useMemo(() => {
    const seen = new Set<string>()
    const items: AgentSharePayload[] = []
    for (const message of messages) {
      if (!message.agent) continue
      const key = message.agent.workflowId || message.agent.title
      if (!key || seen.has(key)) continue
      seen.add(key)
      items.push(message.agent)
    }
    return items.slice(-6)
  }, [messages])

  async function send(agent?: AgentSharePayload): Promise<void> {
    const body = text.trim()
    if (!body && !pendingFiles.length && !agent) return
    setBusy(true)
    setError('')
    try {
      const uploaded: ChatAttachment[] = []
      for (const path of pendingFiles) {
        uploaded.push(await api.uploadChatFile(path))
      }
      const clientId = newClientId()
      const payloadText = agent ? encodeAgentMessage(agent, body) : body
      const optimistic: ChatMessage = {
        id: `local-${clientId}`,
        threadId: thread.id,
        senderId: me.id,
        mine: true,
        text: body,
        clientId,
        createdAt: new Date().toISOString(),
        receipt: 'sending',
        attachments: uploaded,
        agent: agent ?? null
      }
      setMessages((prev) => [...prev, optimistic])
      setText('')
      setPendingFiles([])
      await api.chatCommand({
        type: 'send_message',
        client_id: clientId,
        thread_id: thread.id === 'support' ? '' : thread.id,
        peer_id: thread.peerId,
        kind: isSupport ? 'support' : '',
        text: payloadText,
        file_ids: uploaded.map((item) => item.id)
      })
      setMessages((prev) =>
        prev.map((item) => (item.clientId === clientId ? { ...item, receipt: 'delivered' } : item))
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось отправить')
    } finally {
      setBusy(false)
    }
  }

  async function pickFiles(): Promise<void> {
    const paths = await window.api.openFile({
      title: 'Прикрепить файлы',
      properties: ['openFile', 'multiSelections']
    })
    if (paths.length) setPendingFiles((prev) => [...prev, ...paths])
  }

  async function openAgentPicker(): Promise<void> {
    setPickerOpen(true)
    try {
      const board = await api.getWorkflowBoard()
      setAgents(board.agents.filter((item) => item.kind !== 'draft'))
    } catch {
      setAgents([])
    }
  }

  async function acceptAgent(agent: AgentSharePayload): Promise<void> {
    setOffer(null)
    if (agent.workflowId) {
      try {
        const record = await api.getWorkflow(agent.workflowId)
        onOpenAgent(record.id, record.title || agent.title)
        return
      } catch {
        /* create a local copy */
      }
    }
    const notes = [
      `Агент из чата: ${agent.title}`,
      agent.description,
      agent.goal ? `Цель: ${agent.goal}` : '',
      agent.triggerSummary || agent.triggerKind ? `Триггер: ${agent.triggerSummary || agent.triggerKind}` : ''
    ]
      .filter(Boolean)
      .join('\n')
    try {
      const created = await api.createWorkflow(notes)
      window.alert(`«${created.title || agent.title}» добавлен в ваши агенты.`)
      onOpenAgent(created.id, created.title || agent.title)
    } catch (err) {
      window.alert(err instanceof Error ? err.message : 'Не удалось добавить агента')
    }
  }

  return (
    <div className="messenger">
      <section className="messenger-main">
        <header className="messenger-head">
          <span className="messenger-head-avatar">
            {avatar ? <img src={avatar} alt="" /> : initials(thread.title)}
          </span>
          <div>
            <div className="messenger-head-name">{thread.title || 'Чат'}</div>
            <div className="messenger-head-meta">
              <span>{thread.position || (isSupport ? 'Служба поддержки' : 'Должность не указана')}</span>
              <span className={`messenger-head-status ${statusTone(thread)}`}>{statusLabel(thread)}</span>
            </div>
          </div>
        </header>

        <div className="messenger-feed-wrap">
          <div
            className="messenger-feed-bg"
            style={{ backgroundImage: `url(${wallpaperUrl})` }}
            aria-hidden
          />
          <div className="messenger-feed" ref={feedRef}>
            <div className="messenger-feed-items">
            {messages.length === 0 && <div className="messenger-empty">Нет сообщений</div>}
            {messages.map((message, index) => {
              const label = dateLabel(message.createdAt)
              const prev = index > 0 ? dateLabel(messages[index - 1].createdAt) : ''
              return (
                <div key={message.id} className="messenger-item">
                  {label && label !== prev && <div className="messenger-date">{label}</div>}
                  <article className={message.mine ? 'messenger-bubble mine' : 'messenger-bubble'}>
                    {message.text && <div className="messenger-bubble-text">{message.text}</div>}
                    {message.agent && (
                      <button
                        type="button"
                        className="messenger-agent-card"
                        onClick={() => setOffer({ agent: message.agent!, mine: message.mine })}
                      >
                        <span className="messenger-agent-ico">{(message.agent.title[0] || 'А').toUpperCase()}</span>
                        <span>
                          <strong>{message.agent.title}</strong>
                          <em>{message.agent.status || message.agent.phase || 'Агент'}</em>
                        </span>
                      </button>
                    )}
                    {message.attachments.map((file) => (
                      <button
                        key={file.id || file.filename}
                        type="button"
                        className="messenger-file-card"
                        onClick={() => {
                          void window.api.download({
                            url: `/api/v1/chat/files/${file.id}`,
                            defaultName: file.filename,
                            token: api.getToken()
                          })
                        }}
                      >
                        <span>{(file.filename.split('.').pop() || 'FILE').slice(0, 3).toUpperCase()}</span>
                        <b>{file.filename}</b>
                      </button>
                    ))}
                    <div className="messenger-bubble-time">{formatTime(message.createdAt)}</div>
                  </article>
                </div>
              )
            })}
            </div>
          </div>
        </div>

        {error && <div className="messenger-error">{error}</div>}
        {pendingFiles.length > 0 && (
          <div className="messenger-pending">
            {pendingFiles.map((path) => (
              <span key={path}>{path.split(/[/\\]/).pop()}</span>
            ))}
          </div>
        )}

        <div className="messenger-composer">
          <button type="button" className="messenger-icon-btn" title="Файл" onClick={() => void pickFiles()}>
            +
          </button>
          <button type="button" className="messenger-icon-btn" title="Агент" onClick={() => void openAgentPicker()}>
            А
          </button>
          <textarea
            ref={composerRef}
            value={text}
            placeholder="Сообщение"
            rows={1}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                void send()
              }
            }}
          />
          <button className="btn-primary messenger-send" disabled={busy} onClick={() => void send()}>
            Отправить
          </button>
        </div>
      </section>

      {!isSupport && (
        <aside className="messenger-side">
          <div className="messenger-side-title">О сотруднике</div>
          <div className="messenger-profile">
            <div className="messenger-side-avatar">
              {avatar ? <img src={avatar} alt="" /> : initials(thread.title)}
            </div>
            <div className="messenger-side-name">{thread.title}</div>
            <div className="messenger-side-pos">{thread.position || 'Должность не указана'}</div>
            <div className={`messenger-side-status ${statusTone(thread)}`}>{statusLabel(thread)}</div>
          </div>

          <div className="messenger-side-label">Общие материалы</div>
          {materials.length === 0 && <div className="messenger-side-empty">Нет общих материалов</div>}
          {materials.map((file) => (
            <button
              key={file.id || file.filename}
              type="button"
              className="messenger-side-card"
              onClick={() => {
                void window.api.download({
                  url: `/api/v1/chat/files/${file.id}`,
                  defaultName: file.filename,
                  token: api.getToken()
                })
              }}
            >
              <span>{(file.filename.split('.').pop() || 'FILE').slice(0, 3).toUpperCase()}</span>
              <div>
                <b>{file.filename}</b>
                <i>{[file.mime.split('/').pop()?.toUpperCase(), formatSize(file.size)].filter(Boolean).join(' · ')}</i>
              </div>
            </button>
          ))}

          <div className="messenger-side-label">Связанные агенты</div>
          {linkedAgents.length === 0 && <div className="messenger-side-empty">Нет связанных агентов</div>}
          {linkedAgents.map((agent) => (
            <button
              key={agent.workflowId || agent.title}
              type="button"
              className="messenger-side-card"
              onClick={() => setOffer({ agent, mine: false })}
            >
              <span className="round">{(agent.title[0] || 'А').toUpperCase()}</span>
              <div>
                <b>{agent.title}</b>
                <i>{agent.status || agent.phase || 'Агент'}</i>
              </div>
            </button>
          ))}
        </aside>
      )}

      {pickerOpen && (
        <div className="messenger-modal" onClick={() => setPickerOpen(false)}>
          <div className="messenger-dialog" onClick={(event) => event.stopPropagation()}>
            <h3>Поделиться агентом</h3>
            <p>Выберите агента, карточку увидит собеседник и сможет добавить к себе.</p>
            <div className="messenger-dialog-list">
              {agents.length === 0 && <div className="messenger-side-empty">Нет агентов для отправки</div>}
              {agents.map((agent) => (
                <button
                  key={agent.id}
                  type="button"
                  className="messenger-side-card"
                  onClick={() => {
                    setPickerOpen(false)
                    void send(agentShareFromBoard(agent))
                  }}
                >
                  <span className="round">{(agent.title[0] || 'А').toUpperCase()}</span>
                  <div>
                    <b>{agent.title}</b>
                    <i>{agent.status || agent.phase || 'Агент'}</i>
                  </div>
                </button>
              ))}
            </div>
            <button className="btn-ghost" onClick={() => setPickerOpen(false)}>
              Отмена
            </button>
          </div>
        </div>
      )}

      {offer && (
        <div className="messenger-modal" onClick={() => setOffer(null)}>
          <div className="messenger-dialog" onClick={(event) => event.stopPropagation()}>
            <h3>{offer.agent.title}</h3>
            <p>
              {offer.mine
                ? 'Так выглядит отправленная карточка агента.'
                : 'Карточка агента из чата. Можно добавить к себе или отказаться.'}
            </p>
            <div className="messenger-offer-rows">
              <label>Описание</label>
              <div>{offer.agent.description || 'не указано'}</div>
              <label>Цель</label>
              <div>{offer.agent.goal || 'не указана'}</div>
              <label>Триггер</label>
              <div>{offer.agent.triggerSummary || offer.agent.triggerKind || 'не указан'}</div>
              <label>Инструменты</label>
              <div>{offer.agent.tools.join(', ') || 'не указаны'}</div>
            </div>
            {offer.mine ? (
              <button className="btn-primary" onClick={() => setOffer(null)}>
                Закрыть
              </button>
            ) : (
              <div className="messenger-offer-actions">
                <button className="btn-ghost" onClick={() => setOffer(null)}>
                  Отказаться
                </button>
                <button className="btn-primary" onClick={() => void acceptAgent(offer.agent)}>
                  Добавить
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
