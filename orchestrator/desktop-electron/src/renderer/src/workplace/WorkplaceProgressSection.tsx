import type { UserProfile } from '../api/types'
import { TaskProgressEditor } from './TaskProgressEditor'
import { TaskSourceActionsPanel } from './TaskSourceActionsPanel'
import type { TaskActionContext } from './taskSourceKind'

export function WorkplaceProgressSection({
  user,
  rowId,
  baseProgress,
  actionContext,
  projectUrl,
  onActionCompleted
}: {
  user: UserProfile
  rowId: string
  baseProgress: number
  actionContext?: TaskActionContext | null
  projectUrl?: string
  onActionCompleted?: () => void
}): React.JSX.Element {
  return (
    <div className="workplace-progress-section">
      <TaskProgressEditor rowId={rowId} baseProgress={baseProgress} />
      {actionContext ? (
        <TaskSourceActionsPanel
          user={user}
          ctx={actionContext}
          projectUrl={projectUrl}
          onCompleted={onActionCompleted}
        />
      ) : null}
    </div>
  )
}
