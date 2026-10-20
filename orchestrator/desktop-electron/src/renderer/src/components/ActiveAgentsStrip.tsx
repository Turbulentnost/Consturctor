import { useEffect, useMemo, useRef, useState } from 'react'
import { apiGet, backendUrl } from '../agentPlatform/api/client'
import type { AgentApproval, AgentQuestion, PlatformSession, PlatformSessionDetail } from '../agentPlatform/api/types'
import { useRuns } from '../store/runs'
import { isLiveRunState } from '../store/liveRun'
import { PlatformRunDialog } from '../tabs/grid/PlatformRunDialog'
import { decidePlatformApproval } from '../workplace/platformProtocolRun'
import { agentWantsText } from './agentfeed/explainTool'
import './activeAgentsStrip.css'

const PLATFORM_POLL_MS = 3000

type PlatformLive = { session: PlatformSession; approval: AgentApproval | null; question: AgentQuestion | null }

type StripItem = {
  key: string
  title: string
  status: string
  approval: { id: string; text: string; detail: string } | null
  question: boolean
  open: () => void
  decide?: (allow: boolean) => Promise<void> | void
}

/** Идущие запуски платформы агентов. Платформу не поднимает: опрашивает, только если её уже запустили. */
function usePlatformLive(): PlatformLive[] {
  const [live, setLive] = useState<PlatformLive[]>([])
  useEffect(() => {
    let alive = true
    let timer = 0
    const tick = async (): Promise<void> => {
      try {
        if (backendUrl()) {
          const list = await apiGet<{ items: PlatformSession[] }>('/api/v1/platform/sessions?limit=30')
          const running = list.items.filter((item) => item.status === 'running' && !item.ephemeral)
          const details = await Promise.all(
            running.map((item) =>
              apiGet<PlatformSessionDetail>(
                `/api/v1/platform/sessions/${encodeURIComponent(item.id)}?since=${item.rev}`
              ).catch(() => null)
            )
          )
          if (!alive) return
          setLive(
            details
              .filter((detail): detail is PlatformSessionDetail => detail !== null && detail.session.status === 'running')
              .map((detail) => ({
                session: detail.session,
                approval: detail.approval ?? null,
                question: detail.question ?? null
              }))
          )
        } else if (alive) {
          setLive([])
        }
      } catch {
        if (alive) setLive([])
      }
      if (alive) timer = window.setTimeout(() => void tick(), PLATFORM_POLL_MS)
    }
    void tick()
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [])
  return live
}

function rank(item: StripItem): number {
  return item.approval ? 0 : item.question ? 1 : 2
}

/**
 * Полоса над страницей: какие агенты сейчас работают. Запрос разрешения — первым, с «Разрешить» и «Отклонить»,
 * и полосу с ним не скрыть. Несколько агентов листаются стрелками по бокам.
 */
export function ActiveAgentsStrip({
  onOpenRun
}: {
  onOpenRun: (workflowId: string, title: string) => void
}): React.JSX.Element | null {
  const runs = useRuns()
  const platform = usePlatformLive()
  const [dialogSession, setDialogSession] = useState('')
  const [collapsed, setCollapsed] = useState(false)
  const [selectedKey, setSelectedKey] = useState('')
  const [deciding, setDeciding] = useState('')
  const seenApprovals = useRef(new Set<string>())

  const items = useMemo<StripItem[]>(() => {
    const local: StripItem[] = Object.values(runs.entries)
      .filter((entry) => !entry.background && isLiveRunState(entry.state))
      .map((entry) => {
        const hitl = entry.state.pendingHitl
        return {
          key: `run:${entry.workflowId}`,
          title: entry.title || 'ИИ-агент',
          status: entry.state.pendingQuestion ? 'Задал вопрос' : entry.state.status || 'Работает…',
          approval: hitl
            ? {
                id: hitl.requestId,
                text: hitl.title?.startsWith('Агент хочет') ? hitl.title : agentWantsText(hitl.tool, hitl.arguments),
                detail: hitl.intent || ''
              }
            : null,
          question: Boolean(entry.state.pendingQuestion),
          open: () => onOpenRun(entry.workflowId, entry.title),
          decide: hitl ? (allow) => runs.respondHitl(entry.workflowId, hitl.requestId, allow) : undefined
        }
      })
    const remote: StripItem[] = platform.map(({ session, approval, question }) => ({
      key: `platform:${session.id}`,
      title: session.agent_title || session.config_title || 'ИИ-агент',
      status: question ? 'Задал вопрос' : 'Работает…',
      approval: approval ? { id: approval.id, text: approval.title, detail: approval.subject } : null,
      question: Boolean(question),
      open: () => setDialogSession(session.id),
      decide: approval ? (allow) => decidePlatformApproval(session.id, approval.id, allow) : undefined
    }))
    return [...local, ...remote].sort((a, b) => rank(a) - rank(b))
  }, [onOpenRun, platform, runs])

  const asking = items.filter((item) => item.approval)
  const freshApproval = asking.find((item) => !seenApprovals.current.has(`${item.key}:${item.approval?.id}`))

  useEffect(() => {
    if (!items.length) setCollapsed(false)
  }, [items.length])

  useEffect(() => {
    if (!freshApproval) return
    for (const item of asking) seenApprovals.current.add(`${item.key}:${item.approval?.id}`)
    setSelectedKey(freshApproval.key)
  }, [asking, freshApproval])

  const dialog = dialogSession ? (
    <PlatformRunDialog sessionId={dialogSession} onClose={() => setDialogSession('')} />
  ) : null

  if (!items.length) return dialog
  const index = Math.max(
    0,
    items.findIndex((item) => item.key === selectedKey)
  )
  const current = items[index]
  const pinned = asking.length > 0

  if (collapsed && !pinned) {
    return (
      <>
        <div className="agents-strip agents-strip-collapsed">
          <button type="button" className="agents-strip-tab" onClick={() => setCollapsed(false)}>
            <span className="agents-strip-dot" aria-hidden />
            {items.length === 1 ? 'Работает агент' : `Работают агенты: ${items.length}`}
            <span className="agents-strip-chevron" aria-hidden>
              ▾
            </span>
          </button>
        </div>
        {dialog}
      </>
    )
  }

  const step = (delta: number): void => {
    setSelectedKey(items[(index + delta + items.length) % items.length].key)
  }
  const decide = async (allow: boolean): Promise<void> => {
    if (!current.decide || !current.approval) return
    setDeciding(current.approval.id)
    try {
      await current.decide(allow)
    } finally {
      setDeciding('')
    }
  }
  const busy = Boolean(current.approval && deciding === current.approval.id)

  return (
    <>
      <div className="agents-strip" role="status" aria-live="polite">
        {items.length > 1 ? (
          <button type="button" className="agents-strip-arrow" aria-label="Предыдущий агент" onClick={() => step(-1)}>
            ‹
          </button>
        ) : null}
        <div className={current.approval ? 'agents-strip-card asking' : 'agents-strip-card'}>
          <span className="agents-strip-dot" aria-hidden />
          <div className="agents-strip-text">
            <strong>{current.title}</strong>
            {current.approval ? (
              <span title={[current.approval.text, current.approval.detail].filter(Boolean).join('\n')}>
                просит разрешение: {current.approval.text}
                {current.approval.detail ? <em> · {current.approval.detail}</em> : null}
              </span>
            ) : (
              <span>{current.status}</span>
            )}
          </div>
          {items.length > 1 ? (
            <span className="agents-strip-count">
              {index + 1} / {items.length}
            </span>
          ) : null}
          {current.approval ? (
            <div className="agents-strip-actions">
              <button type="button" className="agents-strip-allow" disabled={busy} onClick={() => void decide(true)}>
                Разрешить
              </button>
              <button type="button" className="agents-strip-deny" disabled={busy} onClick={() => void decide(false)}>
                Отклонить
              </button>
              <button type="button" className="agents-strip-link" onClick={current.open}>
                Подробнее
              </button>
            </div>
          ) : (
            <div className="agents-strip-actions">
              <button type="button" className="agents-strip-go" onClick={current.open}>
                Перейти
              </button>
              {pinned ? null : (
                <button
                  type="button"
                  className="agents-strip-hide"
                  aria-label="Скрыть"
                  title="Скрыть"
                  onClick={() => setCollapsed(true)}
                >
                  ▴
                </button>
              )}
            </div>
          )}
        </div>
        {items.length > 1 ? (
          <button type="button" className="agents-strip-arrow" aria-label="Следующий агент" onClick={() => step(1)}>
            ›
          </button>
        ) : null}
      </div>
      {dialog}
    </>
  )
}
