import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet, apiPost } from './api/client'
import type {
  ConstructorBrief,
  PlatformConfig,
  PlatformSession,
  PlatformSessionsResponse,
  SharedAgent,
  SharedAgentsResponse
} from './api/types'
import { ChecklistIcon, ChevronLeftIcon, PaperclipIcon, PlayIcon } from './components/Icons'
import { MarkdownView } from './components/MarkdownView'
import { Segmented } from './components/Segmented'
import { formatTime, SESSION_STATUS } from './platformLabels'
import { AgentSession } from './pages/AgentSession'
import { AgentIcon, AgentPassportView } from './pages/AgentPassportView'
import { ComposerFiles, MAX_FILES, pendingFrom, toUpload, type PendingFile } from './pages/SessionAttachments'
import './styles/index.css'

const SHOW_PROGRESS_KEY = 'orchestrator.agentPlatform.showProgress'
const SESSIONS_LIMIT = 200

type AgentTab = 'passport' | 'prompt'

const AGENT_TABS: { key: AgentTab; label: string }[] = [
  { key: 'passport', label: 'Паспорт' },
  { key: 'prompt', label: 'Промпт' }
]

/** Где лежит промпт агента: turbotest.agents (опубликован из TurboTester) или public.workflows (сформирован в Конструкторе). */
export type PlatformAgentSource = { kind: 'platform'; agentId: string } | { kind: 'constructor' }

// Открытый запуск агента переживает уход со страницы, пока приложение не перезапущено.
const openedSession = new Map<string, string>()

export function platformAgentIdFromNotes(notes: string): string {
  const match = /^platform:([0-9a-f-]{36})$/i.exec(notes.trim())
  return match ? match[1].toLowerCase() : ''
}

/** Id экрана запуска для агента TurboTester без своего workflow: тот же формат, что notes=platform:<id>. */
export function platformWorkflowId(agentId: string): string {
  return platformAgentIdFromNotes(`platform:${agentId}`) ? `platform:${agentId.trim().toLowerCase()}` : ''
}

export function forgetOpenedSession(workflowId: string): void {
  openedSession.delete(workflowId)
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

function briefMeta(brief: ConstructorBrief): string {
  return [brief.owner_fio, brief.owner_position, 'сформирован в Конструкторе'].filter(Boolean).join(' · ')
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

function ConstructorPassport({ brief }: { brief: ConstructorBrief }): React.JSX.Element {
  return (
    <>
      <section className="pagent-section">
        <h4>Цель</h4>
        <p className="pagent-request">{brief.goal || 'Цель не указана.'}</p>
      </section>
      {brief.steps.length ? (
        <section className="pagent-section">
          <h4>Шаги</h4>
          <ul className="tt-agent-brief-list">
            {brief.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {brief.tools.length ? (
        <section className="pagent-section">
          <h4>Инструменты</h4>
          <p className="pagent-request">{brief.tools.join(', ')}</p>
        </section>
      ) : null}
    </>
  )
}

interface PlatformAgentPageProps {
  workflowId: string
  source: PlatformAgentSource
  title: string
  /** Кнопка «Запустить» на доске: сразу новый запуск. */
  autoStart?: boolean
  onBack: () => void
}

/** Запуск ИИ-агента конфигурацией 2: раннер Cursor SDK, инструменты платформы и страница хода работы. */
export function PlatformAgentPage({ workflowId, source, title, autoStart = false, onBack }: PlatformAgentPageProps): React.JSX.Element {
  const platformAgentId = source.kind === 'platform' ? source.agentId : ''
  const runId = platformAgentId || workflowId
  const fromConstructor = source.kind === 'constructor'
  const [configs, setConfigs] = useState<PlatformConfig[]>([])
  const [agent, setAgent] = useState<SharedAgent | null>(null)
  const [brief, setBrief] = useState<ConstructorBrief | null>(null)
  const [sessions, setSessions] = useState<PlatformSession[] | null>(null)
  const [loadError, setLoadError] = useState('')
  const [notice, setNotice] = useState('')
  const [starting, setStarting] = useState(false)
  const [task, setTask] = useState('')
  const [files, setFiles] = useState<PendingFile[]>([])
  const [tab, setTab] = useState<AgentTab>('passport')
  const [sessionId, setSessionId] = useState<string | null>(() => openedSession.get(workflowId) ?? null)
  const [showProgress, setShowProgressState] = useState(readShowProgress)
  const pickerRef = useRef<HTMLInputElement | null>(null)
  const autoStartedRef = useRef(false)

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

  const start = useCallback(async (): Promise<void> => {
    setStarting(true)
    setNotice('')
    try {
      const body = fromConstructor
        ? { prompt: task.trim(), attachments: await Promise.all(files.map(toUpload)) }
        : {}
      const created = await apiPost<PlatformSession>(`/api/v1/platform/agents/${encodeURIComponent(runId)}/runs`, body)
      setTask('')
      setFiles([])
      openSession(created.id)
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : 'Не удалось запустить агента')
    } finally {
      setStarting(false)
    }
  }, [files, fromConstructor, openSession, runId, task])

  const load = useCallback(async () => {
    setLoadError('')
    try {
      const configData = await apiGet<{ items: PlatformConfig[] }>('/api/v1/platform/configs')
      setConfigs(configData.items)
      const sessionsRequest = apiGet<PlatformSessionsResponse>(`/api/v1/platform/sessions?limit=${SESSIONS_LIMIT}`)
      let ready = false
      if (!fromConstructor) {
        const found = await findAgent(platformAgentId, configData.items)
        setAgent(found.agent)
        ready = Boolean(found.agent?.instruction)
        if (!found.agent) {
          setLoadError(
            found.error ||
              'Агент не найден в общей базе TurboTester: автор мог удалить его или ещё не опубликовать план.'
          )
        }
      } else {
        try {
          const loaded = await apiGet<ConstructorBrief>(`/api/v1/platform/constructor-agents/${encodeURIComponent(workflowId)}`)
          setBrief(loaded)
          ready = Boolean(loaded.plan)
        } catch (reason) {
          setLoadError(reason instanceof Error ? reason.message : 'Агент Конструктора недоступен')
        }
      }
      const own = (await sessionsRequest).items.filter((item) => item.agent_id === runId)
      setSessions(own)
      const live = own.find((item) => item.status === 'running')
      if (live && !openedSession.has(workflowId)) openSession(live.id)
      else if (autoStart && ready && !live && !autoStartedRef.current) {
        autoStartedRef.current = true
        void start()
      }
    } catch (reason) {
      setLoadError(reason instanceof Error ? reason.message : 'Платформа агентов недоступна')
    }
    // start читает задачу и файлы на момент вызова; автозапуск идёт без них.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart, fromConstructor, openSession, platformAgentId, runId, workflowId])

  useEffect(() => {
    if (!sessionId) void load()
  }, [load, sessionId])

  function addFiles(list: File[]): void {
    if (!list.length) return
    const room = MAX_FILES - files.length
    const { added, rejected } = pendingFrom(list.slice(0, Math.max(room, 0)))
    if (list.length > room) rejected.push(`Не больше ${MAX_FILES} вложений за запуск`)
    setNotice(rejected.join(' · '))
    if (added.length) setFiles((current) => [...current, ...added])
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

  const shownTitle = (fromConstructor ? brief?.title : agent?.title) || title
  const ready = fromConstructor ? Boolean(brief?.plan) : Boolean(agent?.instruction)
  const runnable = ready && !starting
  const meta = fromConstructor
    ? brief
      ? briefMeta(brief)
      : null
    : agent
      ? agentMeta(agent)
      : null
  const lastStatus = fromConstructor ? sessions?.[0]?.status : agent?.last_run?.status

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
            <span>{meta ?? (loadError ? 'Агент недоступен' : 'Загружаем…')}</span>
          </div>
          {lastStatus ? (
            <span className={`session-badge ${lastStatus}`}>{SESSION_STATUS[lastStatus] ?? lastStatus}</span>
          ) : null}
          <button
            type="button"
            className="send tt-agent-run"
            disabled={!runnable}
            title={ready ? 'Новый запуск по плану' : 'План агента ещё не составлен'}
            onClick={() => void start()}
          >
            <PlayIcon size={14} />
            <span>{starting ? 'Запускаем…' : 'Запустить'}</span>
          </button>
        </header>
        {loadError ? <p className="agent-error platform-sessions-empty">{loadError}</p> : null}
        {notice ? <p className="agent-error platform-sessions-empty">{notice}</p> : null}

        {fromConstructor && brief ? (
          <form
            className={['composer sess-composer tt-agent-launch', files.length ? 'has-files' : ''].join(' ')}
            onSubmit={(event) => {
              event.preventDefault()
              if (runnable) void start()
            }}
            onDragOver={(event) => {
              if (event.dataTransfer.types.includes('Files')) event.preventDefault()
            }}
            onDrop={(event) => {
              event.preventDefault()
              addFiles([...event.dataTransfer.files])
            }}
          >
            {files.length ? (
              <ComposerFiles files={files} onRemove={(id) => setFiles((current) => current.filter((item) => item.id !== id))} />
            ) : null}
            <button
              type="button"
              className="icon-button"
              title="Прикрепить фото или файл к запуску (можно вставить из буфера или перетащить)"
              aria-label="Прикрепить фото или файл"
              disabled={starting || files.length >= MAX_FILES}
              onClick={() => pickerRef.current?.click()}
            >
              <PaperclipIcon />
            </button>
            <input
              ref={pickerRef}
              type="file"
              multiple
              hidden
              onChange={(event) => {
                addFiles([...(event.target.files ?? [])])
                event.target.value = ''
              }}
            />
            <textarea
              rows={1}
              value={task}
              placeholder="Задача к этому запуску — необязательно"
              onChange={(event) => setTask(event.target.value)}
              onPaste={(event) => {
                const pasted = [...event.clipboardData.files]
                if (!pasted.length) return
                event.preventDefault()
                addFiles(pasted)
              }}
            />
          </form>
        ) : null}

        <div key={tab} className="pagent-body">
          {tab === 'passport' ? (
            fromConstructor ? (
              brief ? (
                <ConstructorPassport brief={brief} />
              ) : null
            ) : agent?.passport ? (
              <AgentPassportView passport={agent.passport} />
            ) : (
              <p className="agent-muted">Паспорт заполнит облачный агент Cursor после успешного прогона.</p>
            )
          ) : fromConstructor ? (
            <section className="pagent-section">
              <h4>План запуска</h4>
              {brief?.plan ? (
                <div className="pagent-plan">
                  <MarkdownView text={brief.plan} />
                </div>
              ) : (
                <p className="agent-muted">План не собран.</p>
              )}
            </section>
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
