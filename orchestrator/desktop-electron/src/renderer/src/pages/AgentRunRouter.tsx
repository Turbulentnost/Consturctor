import { useEffect, useState, type ComponentProps } from 'react'
import { api } from '../api/client'
import { PlatformAgentPage, platformAgentIdFromNotes } from '../agentPlatform/PlatformAgentPage'
import { isPersonalAgentWorkflowId } from '../workplace/personalAgent'
import { AgentRunPage } from './AgentRunPage'

type AgentRunRouterProps = ComponentProps<typeof AgentRunPage>

// workflowId → id агента TurboTester ('' — обычный агент Оркестратора).
const platformIds = new Map<string, string>()

/** Агент, опубликованный из TurboTester (notes = platform:<id>), запускается платформой конфигурации 2. */
export function AgentRunRouter(props: AgentRunRouterProps): React.JSX.Element {
  const { workflowId } = props
  const [platformId, setPlatformId] = useState<string | null>(() =>
    isPersonalAgentWorkflowId(workflowId) ? '' : (platformIds.get(workflowId) ?? null)
  )

  useEffect(() => {
    if (platformId !== null) return
    let alive = true
    api
      .getWorkflow(workflowId)
      .then((record) => {
        const id = platformAgentIdFromNotes(record.notes)
        platformIds.set(workflowId, id)
        if (alive) setPlatformId(id)
      })
      .catch(() => {
        if (alive) setPlatformId('')
      })
    return () => {
      alive = false
    }
  }, [platformId, workflowId])

  if (platformId === null) {
    return <div className="agent-run-resolving" aria-busy="true" />
  }
  if (platformId) {
    return (
      <PlatformAgentPage
        workflowId={workflowId}
        platformAgentId={platformId}
        title={props.title}
        onBack={props.onBack}
      />
    )
  }
  return <AgentRunPage {...props} />
}
