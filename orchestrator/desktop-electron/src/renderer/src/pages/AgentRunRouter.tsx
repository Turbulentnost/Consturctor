import { useEffect, useState, type ComponentProps } from 'react'
import { api } from '../api/client'
import type { WorkflowRecord } from '../api/types'
import { PlatformAgentPage, platformAgentIdFromNotes, type PlatformAgentSource } from '../agentPlatform/PlatformAgentPage'
import { useRuns } from '../store/runs'
import { isPersonalAgentWorkflowId } from '../workplace/personalAgent'
import { AgentRunPage } from './AgentRunPage'

type AgentRunRouterProps = ComponentProps<typeof AgentRunPage>

// workflowId → чем запускать агента; null — прежний запуск Оркестратора.
const routes = new Map<string, PlatformAgentSource | null>()

const PUBLISHED_STATUSES = new Set(['published', 'active', 'ready'])

function flag(value: unknown): boolean {
  return value === true || ['true', '1', 'yes'].includes(String(value ?? '').trim().toLowerCase())
}

// То же правило, что app/constructor/owners.py is_published на платформе.
function formedInConstructor(record: WorkflowRecord): boolean {
  const local = record.localRun ?? {}
  const playbook = (local.playbook ?? {}) as Record<string, unknown>
  if (record.phase === 'deleted' || flag(local.deleted)) return false
  if (String(local.kind ?? '').toLowerCase() === 'draft' || flag(local.unformed)) return false
  const published =
    flag(local.published) ||
    record.phase === 'done' ||
    PUBLISHED_STATUSES.has(String(local.status ?? '').trim().toLowerCase())
  return published && typeof playbook.instructions === 'string' && playbook.instructions.trim() !== ''
}

// workflowId = platform:<id> — агент TurboTester без workflow в Конструкторе (кнопка «Запустить процесс»).
function directRoute(workflowId: string): PlatformAgentSource | undefined {
  const agentId = platformAgentIdFromNotes(workflowId)
  return agentId ? { kind: 'platform', agentId } : undefined
}

function routeOf(record: WorkflowRecord): PlatformAgentSource | null {
  const platformId = platformAgentIdFromNotes(record.notes)
  if (platformId) return { kind: 'platform', agentId: platformId }
  return formedInConstructor(record) ? { kind: 'constructor' } : null
}

/**
 * Агентов TurboTester (notes = platform:<id>) и сформированных в Конструкторе запускает платформа
 * конфигурации 2. Плановый запуск, уже идущий прежним раннером, и вопрос с «Сегодня» остаются на старой странице.
 */
export function AgentRunRouter(props: AgentRunRouterProps): React.JSX.Element {
  const { workflowId } = props
  const runs = useRuns()
  const [route, setRoute] = useState<PlatformAgentSource | null | undefined>(() =>
    isPersonalAgentWorkflowId(workflowId) ? null : (directRoute(workflowId) ?? routes.get(workflowId))
  )
  const [legacyRunning] = useState(() => Boolean(runs.entries[workflowId]?.state?.running))

  useEffect(() => {
    if (route !== undefined) return
    let alive = true
    api
      .getWorkflow(workflowId)
      .then((record) => {
        const found = routeOf(record)
        routes.set(workflowId, found)
        if (alive) setRoute(found)
      })
      .catch(() => {
        if (alive) setRoute(null)
      })
    return () => {
      alive = false
    }
  }, [route, workflowId])

  if (route === undefined) {
    return <div className="agent-run-resolving" aria-busy="true" />
  }
  const legacy = route?.kind === 'constructor' && (legacyRunning || Boolean(props.initialMessage?.trim()))
  if (route && !legacy) {
    return (
      <PlatformAgentPage
        workflowId={workflowId}
        source={route}
        title={props.title}
        autoStart={props.autoStart}
        onBack={props.onBack}
      />
    )
  }
  return <AgentRunPage {...props} />
}
