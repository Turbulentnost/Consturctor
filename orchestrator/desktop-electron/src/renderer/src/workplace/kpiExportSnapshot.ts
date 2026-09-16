import type { WorkplaceKpiDashboard } from './workplaceKpiTypes'

export interface KpiExportSnapshot {
  from: string
  to: string
  data: WorkplaceKpiDashboard | null
}

let snapshot: KpiExportSnapshot = { from: '', to: '', data: null }

export function setKpiExportSnapshot(next: KpiExportSnapshot): void {
  snapshot = next
}

export function getKpiExportSnapshot(): KpiExportSnapshot {
  return snapshot
}
