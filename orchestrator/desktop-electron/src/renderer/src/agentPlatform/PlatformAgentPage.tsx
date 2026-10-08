import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost } from './api/client'
import type {
  PlatformConfig,
  PlatformSession,
  PlatformSessionsResponse,
  SharedAgent,
  SharedAgentsResponse
} from './api/types'
import { ChecklistIcon, ChevronLeftIcon, PlayIcon } from './components/Icons'
import { MarkdownView } from './components/MarkdownView'
import { Segmented } from './components/Segmented'
import { formatTime, SESSION_STATUS } from './platformLabels'
import { AgentSession } from './pages/AgentSession'
import { AgentIcon, AgentPassportView } from './pages/AgentPassportView'
import './styles/index.css'

const SHOW_PROGRESS_KEY = 'orchestrator.agentPlatform.showProgress'
const SESSIONS_LIMIT = 200

type AgentTab = 'passport' | 'prompt'

const AGENT_TABS: { key: AgentTab; label: string }[] = [
  { key: 'passport', label: 'Паспорт' },
  { key: 'prompt', label: 'Промпт' }
]

// Открытый запуск агента переживает уход со страницы, пока приложение не перезапущено.
const openedSession = new Map<string, string>()

export function platformAgentIdFromNotes(notes: string): string {
  const match = /^platform:([0-9a-f-]{36})$/i.exec(notes.trim())
  return match ? match[1].toLowerCase() : ''
}

function readShowProgress(): boolean {
  try {
    return localStorage.getItem(SHOW_PROGRESS_KEY) === 'true'
  } catch {
    return false
  }
}

function runsLabel(runs: number): string {
  const mod10 = runs % 10
  const mod100 = runs % 100
  const word =
    mod10 === 1 && mod100 !== 11 ? 'запуск' : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? 'запуска' : 'запусков'
  return `${runs} ${word}`
}

function agentMeta(agent: SharedAgent): string {
  const parts = [agent.author || 'автор неизвестен', agent.instruction ? runsLabel(agent.runs) : 'составляет план']
  const stamp = formatTime(agent.updated_at || agent.created_at)
  if (stamp) parts.push(stamp)
  return parts.join(' · ')
}

async function findAgent(agentId: string, configs: PlatformConfig[]): Promise<{ agent: SharedAgent | null; error: string }> {
  let error = ''
  for (const config of configs.filter((item) => item.plan_instruction)) {
    const data = await apiGet<SharedAgentsResponse>(`/api/v1/platform/agents?config_id=${encodeURIComponent(config.id)}`)
    const found = data.items.find((item) => item.id === agentId)
    if (found) return { agent: found, error: '' }
    error = data.shared?.error || error
  }
  return { agent: null, error }
}

interface PlatformAgentPageProps {
  workflowId: string
  platformAgentId: string
  title: string
  onBack: () => void
}

/** Запуск агента, опубликованного из TurboTester: та же конфигурация 2, раннер Cursor SDK и страница хода работы. */
export function PlatformAgentPage({ workflowId, platformAgentId, title, onBack }: PlatformAgentPageProps): React.JSX.Element {
  const [configs, setConfigs] = useState<PlatformConfig[]>([])
  const [agent, setAgent] = useState<SharedAgent | null>(null)
  const [sessions, setSessions] = useState<PlatformSession[] | null>(null)
  const [loadError, setLoadError] = useState('')
  const [notice, setNotice] = useState('')
  const [starting, setStarting] = useState(false)
  const [tab, setTab] = useState<AgentTab>('passport')
  const [sessionId, setSessionId] = useState<string | null>(() => openedSession.get(workflowId) ?? null)
  const [showProgress, setShowProgressState] = useState(readShowProgress)

  const setShowProgress = useCallback((value: boolean) => {
    setShowProgressState(value)
    try {
      localStorage.setItem(SHOW_PROGRESS_KEY, String(value))
    } catch {
      /* настройка остаётся только в этом окне */
    }
  }, [])

  const openSession = useCallback(
    (id: string | null) => {
      if (id) openedSession.set(workflowId, id)
      else openedSession.delete(workflowId)
      setSessionId(id)
    },
    [workflowId]
  )

  const load = useCallback(async () => {
    setLoadError('')
    try {
      const configData = await apiGet<{ items: PlatformConfig[] }>('/api/v1/platform/configs')
      setConfigs(configData.items)
      const [found, sessionData] = await Promise.all([
        findAgent(platformAgentId, configData.items),
        apiGet<PlatformSessionsResponse>(`/api/v1/platform/sessions?limit=${SESSIONS_LIMIT}`)
      ])
      setAgent(found.agent)
      if (!found.agent) {
        setLoadError(
          found.error ||
            'Агент не найден в общей базе TurboTester: автор мог удалить его или ещё не опубликовать план.'
        )
      }
      const own = sessionData.items.filter((item) => item.agent_id === platformAgentId)
      setSessions(own)
      const live = own.find((item) => item.status === 'running')
      if (live && !openedSession.has(workflowId)) openSession(live.id)
    } catch (reason) {
      setLoadError(reason instanceof Error ? reason.message : 'Платформа агентов недоступна')
    }
  }, [openSession, platformAgentId, workflowId])

  useEffect(() => {
    if (!sessionId) void load()
  }, [load, sessionId])

  async function start(): Promise<void> {
    if (starting) return
    setStarting(true)
    setNotice('')
    try {
      const created = await apiPost<PlatformSession>(
        `/api/v1/platform/agents/${encodeURIComponent(platformAgentId)}/runs`,
        {}
      )
      openSession(created.id)
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : 'Не удалось запустить агента')
    } finally {
      setStarting(false)
    }
  }

  if (sessionId) {
    return (
      <div className="tt-root" data-theme="light">
        <AgentSession
          target={{ kind: 'session', sessionId }}
          configs={configs}
          backLabel="К агенту"
          showProgress={showProgress}
          onShowProgress={setShowProgress}
          onBack={() => openSession(null)}
          onOpened={(id) => openSession(id)}
        />
      </div>
    )
  }

  const shownTitle = agent?.title || title
  const runnable = Boolean(agent?.instruction) && !starting

  return (
    <div className="tt-root" data-theme="light">
      <div className="platform-view pagent tt-agent-page">
        <div className="pagent-bar">
          <button type="button" className="agent-back" onClick={onBack}>
            <ChevronLeftIcon size={16} />
            Назад
          </button>
          <Segmented items={AGENT_TABS} value={tab} label="Разделы агента" className="pagent-tabs" onChange={setTab} />
        </div>

        <header className="pagent-head">
          <span className="pagent-avatar">
            {agent?.icon_svg ? <AgentIcon svg={agent.icon_svg} size={24} /> : <ChecklistIcon size={24} />}
          </span>
          <div className="pagent-title">
            <strong title={shownTitle}>{shownTitle}</strong>
            <span>{agent ? agentMeta(agent) : loadError ? 'Агент недоступен' : 'Загружаем…'}</span>
          </div>
          {agent?.last_run ? (
            <span className={`session-badge ${agent.last_run.status}`}>
              {SESSION_STATUS[agent.last_run.status] ?? agent.last_run.status}
            </span>
          ) : null}
          <button
            type="button"
            className="send tt-agent-run"
            disabled={!runnable}
            title={agent?.instruction ? 'Новый запуск по плану' : 'План агента ещё не составлен'}
            onClick={() => void start()}
          >
            <PlayIcon size={14} />
            <span>{starting ? 'Запускаем…' : 'Запустить'}</span>
          </button>
        </header>
        {loadError ? <p className="agent-error platform-sessions-empty">{loadError}</p> : null}
        {notice ? <p className="agent-error platform-sessions-empty">{notice}</p> : null}

        <div key={tab} className="pagent-body">
          {tab === 'passport' ? (
            agent?.passport ? (
              <AgentPassportView passport={agent.passport} />
            ) : (
              <p className="agent-muted">Паспорт заполнит облачный агент Cursor после успешного прогона.</p>
            )
          ) : (
            <>
              <section className="pagent-section">
                <h4>Задача</h4>
                <p className="pagent-request">{agent?.request || 'Задача не сохранилась.'}</p>
              </section>
              <section className="pagent-section">
                <h4>План</h4>
                {agent?.instruction ? (
                  <div className="pagent-plan">
                    <MarkdownView text={agent.instruction} />
                  </div>
                ) : (
                  <p className="agent-muted">План ещё составляется.</p>
                )}
              </section>
            </>
          )}

          <section className="pagent-section tt-agent-runs">
            <h4>Запуски на этом компьютере{sessions ? ` · ${sessions.length}` : ''}</h4>
            {sessions === null && !loadError ? <p className="agent-muted">Загружаем…</p> : null}
            {sessions && sessions.length === 0 ? <p className="agent-muted">Агента здесь ещё не запускали.</p> : null}
            {sessions && sessions.length > 0 ? (
              <ul className="owner-agents tt-agent-run-list">
                {sessions.map((item) => (
                  <li key={item.id}>
                    <button type="button" className="owner-agent" onClick={() => openSession(item.id)}>
                      <span className="owner-agent-text">
                        <span className="owner-agent-title">{formatTime(item.updated_at || item.created_at) || item.id}</span>
                        <span className="owner-agent-desc">{item.error || item.config_title}</span>
                      </span>
                      <span className={`session-badge ${item.status}`}>{SESSION_STATUS[item.status] ?? item.status}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </section>
        </div>
      </div>
    </div>
  )
}
