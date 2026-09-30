import type { UserProfile } from '../api/types'
import { formatIpcInvokeError, sidecarAckFailureMessage, type SidecarAck } from './sidecarAck'
import { outlookMailStoreId } from './outlookMail'
import { onecComInvokeArgs } from '../workplace/userContext'

function withMailStore(input: Record<string, unknown>): Record<string, unknown> {
  const entryId = String(input.entry_id || '').trim()
  if (!entryId || input.store_id) return input
  const storeId = outlookMailStoreId(entryId)
  return storeId ? { ...input, store_id: storeId } : input
}

const DEFAULT_TIMEOUT_MS = 180_000

export interface LocalAcToolResult {
  ok: boolean
  tool: string
  result?: Record<string, unknown>
  error?: string
}

function sidecarUnavailableMessage(): string {
  if (typeof window === 'undefined' || !window.agent) {
    return 'Локальные инструменты 1С/Outlook доступны только в desktop Electron'
  }
  if (typeof window.agent.onEvent !== 'function') {
    return 'Sidecar агента недоступен — перезапустите приложение'
  }
  if (typeof window.agent.invokeAcTool !== 'function') {
    return (
      'Preload без invokeAcTool — полностью закройте Orchestrator и запустите ' +
      'orchestrator\\orchestrator\\desktop-electron\\run_dev.bat (не Constructor/desktop-electron)'
    )
  }
  return 'Sidecar недоступен'
}

/** Invoke a desktop COM-backed tool via pybridge (`invoke_ac_tool`). */
export function invokeLocalAcTool(
  tool: string,
  input: Record<string, unknown> = {},
  timeoutMs = DEFAULT_TIMEOUT_MS,
  user: UserProfile | null = null
): Promise<LocalAcToolResult> {
  const toolName = tool.trim()
  if (!toolName) {
    return Promise.resolve({ ok: false, tool: toolName, error: 'Не указан инструмент' })
  }
  if (typeof window.agent?.invokeAcTool !== 'function') {
    return Promise.resolve({ ok: false, tool: toolName, error: sidecarUnavailableMessage() })
  }

  return new Promise((resolve) => {
    const requestId = `ac-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    let settled = false
    const finish = (result: LocalAcToolResult): void => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      unsubscribe()
      resolve(result)
    }
    const timer = setTimeout(
      () => finish({ ok: false, tool: toolName, error: 'Sidecar не ответил вовремя' }),
      timeoutMs
    )
    const unsubscribe = window.agent.onEvent((payload) => {
      if (String(payload.type || '') !== 'ac_tool_result') return
      if (String(payload.requestId || '') !== requestId) return
      if (payload.ok) {
        const raw = payload.result
        finish({
          ok: true,
          tool: String(payload.tool || toolName),
          result: raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {}
        })
      } else {
        finish({
          ok: false,
          tool: String(payload.tool || toolName),
          error: String(payload.error || 'Локальный инструмент завершился с ошибкой')
        })
      }
    })
    const payload = toolName.startsWith('onec.')
      ? onecComInvokeArgs(input, user)
      : toolName.startsWith('outlook.')
        ? withMailStore(input)
        : input
    void window.agent
      .invokeAcTool({ requestId, tool: toolName, input: payload })
      .then((ack) => {
        const fail = sidecarAckFailureMessage(
          ack as SidecarAck,
          'Sidecar не принял COM-запрос — дождитесь запуска sidecar или перезапустите Orchestrator'
        )
        if (fail) finish({ ok: false, tool: toolName, error: fail })
      })
      .catch((err: unknown) => {
        const detail = err instanceof Error ? err.message : String(err)
        const mapped = formatIpcInvokeError(detail)
        finish({
          ok: false,
          tool: toolName,
          error: mapped.trim()
            ? mapped.includes('Main-процесс')
              ? mapped
              : `Sidecar недоступен (${mapped})`
            : sidecarUnavailableMessage()
        })
      })
  })
}

/** Map `onec.search_tasks` COM payload to erpTaskToRow-friendly records. */
export function comSearchTasksToErpRecords(result: Record<string, unknown>): Record<string, unknown>[] {
  const raw = Array.isArray(result.tasks) ? result.tasks : []
  return raw
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((task) => ({
      number: String(task.number || '').trim(),
      title: String(task.description || task.title || task.number || 'Задача 1С').trim(),
      due_at: String(task.due_date || task.due_at || '').trim(),
      done: Boolean(task.done),
      late: Boolean(task.late),
      approval: String(result.task_source || result.source || '1С COM'),
      source: String(result.source || 'onec_com')
    }))
}
