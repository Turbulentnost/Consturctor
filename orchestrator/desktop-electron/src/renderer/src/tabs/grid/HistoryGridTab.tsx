import { OrchSlotFilters } from '../../layout/GridSlots'
import { WorkplaceGlobalRangePicker } from '../../workplace/workplacePeriod'
import { HistoryTab } from '../../workplace/WorkplaceTabs'
import { HeavyTabEmbed } from './HeavyTabEmbed'

export function HistoryGridTab({
  onOpenRun
}: {
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
}): React.JSX.Element {
  return (
    <>
      <OrchSlotFilters>
        <div className="workplace-global-filters-strip wp-card">
          <WorkplaceGlobalRangePicker />
        </div>
      </OrchSlotFilters>
      <HeavyTabEmbed>
        <HistoryTab onOpenRun={onOpenRun} />
      </HeavyTabEmbed>
    </>
  )
}
