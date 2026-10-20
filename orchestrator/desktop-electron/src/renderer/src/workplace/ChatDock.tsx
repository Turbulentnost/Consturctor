import { Send } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { PageKey } from '../components/Sidebar'
import { useRuns } from '../store/runs'
import { personalAgentWorkflowId } from './personalAgent'
import {
  agentPrompt,
  assistantGreeting,
  replyToAssistant,
  takeMarkers,
  type AssistantAction
} from './pageAssistant'

interface ChatDockProps {
  userId: string
  pageKey: PageKey | null
  onNavigate: (key: PageKey) => void
  onOpenSupport: () => void
}

type ChatLine = {
  id: string
  role: 'user' | 'assistant'
  text: string
}

function lineId(): string {
  return `c-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

function openInBrowser(url: string): void {
  window.open(url, '_blank', 'noopener')
}

function applyActions(actions: AssistantAction[], onNavigate: (key: PageKey) => void): void {
  for (const action of actions) {
    if (action.type === 'navigate') onNavigate(action.key)
    else openInBrowser(action.url)
  }
}

export function ChatDock({ userId, pageKey, onNavigate, onOpenSupport }: ChatDockProps): React.JSX.Element {
  const runs = useRuns()
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<'orch' | 'support'>('orch')
  const [draft, setDraft] = useState('')
  const [lines, setLines] = useState<ChatLine[]>([])
  const [awaitingRun, setAwaitingRun] = useState('')
  const logRef = useRef<HTMLDivElement | null>(null)
  const greeted = useRef(false)
  const consumedRun = useRef('')
  const workflowId = personalAgentWorkflowId(userId)
  const run = runs.getRun(workflowId)
  const pending = run?.state.pendingQuestion

  useEffect(() => {
    if (!open || greeted.current) return
    greeted.current = true
    setLines([{ id: lineId(), role: 'assistant', text: assistantGreeting(pageKey) }])
  }, [open, pageKey])

  useEffect(() => {
    const box = logRef.current
    if (!box) return
    box.scrollTop = box.scrollHeight
  }, [lines, awaitingRun, pending])

  useEffect(() => {
    if (!awaitingRun || consumedRun.current === awaitingRun) return
    const state = runs.getRun(workflowId)?.state
    if (!state || state.running) return
    if (state.activeRunId && state.activeRunId !== awaitingRun) return
    const result = [...state.items].reverse().find((item) => item.kind === 'result')
    const errorItem = [...state.items].reverse().find((item) => item.kind === 'system' && item.tone === 'error')
    const raw = result?.text || state.error || errorItem?.text || ''
    consumedRun.current = awaitingRun
    setAwaitingRun('')
    if (!raw.trim()) {
      setLines((prev) => [
        ...prev,
        { id: lineId(), role: 'assistant', text: 'Не получилось получить ответ. Спросите ещё раз или назовите раздел, который открыть.' }
      ])
      return
    }
    const parsed = takeMarkers(raw)
    setLines((prev) => [...prev, { id: lineId(), role: 'assistant', text: parsed.text }])
    applyActions(parsed.actions, onNavigate)
  }, [awaitingRun, onNavigate, runs, workflowId, run?.state.running, run?.state.items, run?.state.error])

  function pushAssistant(text: string, actions: AssistantAction[]): void {
    setLines((prev) => [...prev, { id: lineId(), role: 'assistant', text }])
    applyActions(actions, onNavigate)
  }

  function send(text: string): void {
    if (tab === 'support') {
      setLines((prev) => [...prev, { id: lineId(), role: 'user', text }])
      onOpenSupport()
      return
    }
    setLines((prev) => [...prev, { id: lineId(), role: 'user', text }])
    if (pending?.requestId) {
      runs.answer(workflowId, pending.requestId, text)
      setAwaitingRun(run?.state.activeRunId || awaitingRun || 'answer')
      return
    }
    const local = replyToAssistant(text, pageKey)
    if (!local.askAgent) {
      pushAssistant(local.text, local.actions)
      return
    }
    if (run?.state.running) {
      pushAssistant('Помощник ещё отвечает на предыдущий вопрос.', [])
      return
    }
    const runId = runs.startRun({
      workflowId,
      title: 'Помощник',
      message: agentPrompt(text, pageKey),
      shownMessage: text,
      appContext: assistantGreeting(pageKey),
      source: 'chat'
    })
    if (!runId) {
      pushAssistant('Помощник сейчас занят. Повторите вопрос через несколько секунд.', [])
      return
    }
    setAwaitingRun(runId)
  }

  return (
    <div className="chat-dock">
      {open && (
        <div className="chat-dock-panel is-assistant" role="dialog" aria-label="Помощник">
          <div className="chat-dock-tabs">
            <button
              type="button"
              className={`chat-dock-tab${tab === 'orch' ? ' is-active' : ''}`}
              onClick={() => setTab('orch')}
            >
              Оркестратор
            </button>
            <button
              type="button"
              className={`chat-dock-tab${tab === 'support' ? ' is-active' : ''}`}
              onClick={() => setTab('support')}
            >
              Поддержка
            </button>
          </div>
          <div className="chat-dock-log" ref={logRef}>
            {lines.map((line) => (
              <p key={line.id} className={`chat-dock-line is-${line.role}`}>
                {line.text}
              </p>
            ))}
            {pending?.question ? <p className="chat-dock-line is-assistant">{pending.question}</p> : null}
            {awaitingRun ? <p className="chat-dock-line is-wait">Смотрю по приложению…</p> : null}
          </div>
          <form
            className="chat-dock-form"
            onSubmit={(event) => {
              event.preventDefault()
              const text = draft.trim()
              if (!text) return
              setDraft('')
              send(text)
            }}
          >
            <input
              type="text"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Введите сообщение"
              autoComplete="off"
            />
            <button type="submit" className="messenger-send-btn" title="Отправить" disabled={!draft.trim()}>
              <Send size={16} aria-hidden />
            </button>
          </form>
        </div>
      )}
      <button type="button" className="chat-dock-btn" onClick={() => setOpen((value) => !value)}>
        Чат
      </button>
    </div>
  )
}
