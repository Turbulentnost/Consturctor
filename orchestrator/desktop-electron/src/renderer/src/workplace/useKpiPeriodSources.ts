import { useMemo } from 'react'
import { useSpecV04Sources } from './useSpecV04Data'
import type { KpiPeriodSources } from './mergeKpiEmployee'

function isDoneRegStatus(status: string): boolean {
  return status === 'Выполнен'
}

/** Live 1С + регламенты + Outlook для KPI периода (фильтр по датам в merge). */
export function useKpiPeriodSources(): KpiPeriodSources {
  const data = useSpecV04Sources()
  return useMemo(() => {
    const regRows = data.todayProcessRows
    return {
      erpTasks: data.erpTasks,
      meetings: data.meetings,
      regDone: regRows.filter((r) => isDoneRegStatus(r.status)).length,
      regTotal: regRows.length,
      mailCount: data.mailRows.length
    }
  }, [data.erpTasks, data.meetings, data.mailRows.length, data.todayProcessRows])
}
