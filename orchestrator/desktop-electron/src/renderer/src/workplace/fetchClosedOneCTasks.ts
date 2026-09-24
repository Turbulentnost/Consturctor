import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import type { SpecTaskRow } from './specV04DemoData'
import { parseErpToolTasks } from './orchestratorTaskSources'
import { onecGatewayInvokeArgs } from './userContext'

export type ClosedTasksLoad = {
  rows: SpecTaskRow[]
  error: string
}

/** Задача закрыта: 1С отметила исполнение (erpTaskToRow → «Выполнена»). */
function isClosedRow(row: SpecTaskRow): boolean {
  return /выполн|заверш|закры/i.test(row.status)
}

/**
 * Закрытые задачи документооборота за период. Основной список тянется с
 * only_open=true, поэтому для архива нужен отдельный запрос с include_done.
 */
export async function loadClosedOneCTasks(
  user: UserProfile | null,
  erpFio: string,
  period: { from: string; to: string }
): Promise<ClosedTasksLoad> {
  const args = onecGatewayInvokeArgs(user, {
    limit: 200,
    only_open: false,
    include_done: true,
    closed_only: true,
    today_and_overdue: false,
    date_from: period.from,
    date_to: period.to
  })
  const res = await api.invokeServerTool('onec.docflow_tasks', args, 300_000)
  const parsed = parseErpToolTasks(res, erpFio)
  if (!res.ok && !parsed.rows.length) {
    return { rows: [], error: res.error || parsed.error || 'Не удалось прочитать закрытые задачи из 1С' }
  }
  const rows = parsed.rows.filter(isClosedRow)
  return { rows, error: parsed.warning || '' }
}
