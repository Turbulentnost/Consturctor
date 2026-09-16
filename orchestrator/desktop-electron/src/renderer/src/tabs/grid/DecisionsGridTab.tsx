import type { UserProfile } from '../../api/types'
import { DecisionsTab } from '../../workplace/DecisionsWorkplace'

export function DecisionsGridTab({
  user,
  onOpenRun
}: {
  user?: UserProfile
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
}): React.JSX.Element {
  return <DecisionsTab onOpenRun={onOpenRun} inGridShell userId={user?.id || ''} />
}
