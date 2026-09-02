import type { AgentRunnerEvent } from '../api/types'
import { toolArgHint, toolLabel } from '../components/agentfeed/labels'

const NEVER_CONFIRM = new Set(['notify.send', 'notify', 'code.write_python', 'code.run_python'])

const READ_EXACT = new Set([
  'web_search',
  'site_browser',
  'browser.search_web',
  'browser.open_page',
  'browser.list_installed_browsers',
  'browser.screenshot',
  'browser.get_page_html',
  'outlook.search_mail',
  'outlook.read_calendar',
  'calendar.show_meetings',
  'excel.list_files',
  'excel.read_workbook',
  'onec.odata_catalog',
  'onec.odata_get',
  'onec.sql_query',
  'onec.erp_tasks_current',
  'onec.erp_tasks_period',
  'onec.erp_subordinate_tasks',
  'onec.docflow_tasks',
  'onec.meeting_service_notes',
  'agent.wait',
  'turboproject',
  'users.list',
  'users.current',
  'users.subordinates',
  'agent.schedule',
  'agent.schedule.cancel',
  'read',
  'grep',
  'glob',
  'ls',
  'semsearch',
  'semanticsearch'
])

const READ_PREFIXES = ['onec.search_', 'onec.get_', 'imap.', 'turboproject.']

const WRITE_MARKERS = /write|create|edit|delete|send|post|patch|attach|export|notify/

const TOOL_INTENT: Record<string, string> = {
  'onec.odata_post': 'Создаёт документ или элемент справочника в 1С.',
  'onec.odata_patch': 'Меняет уже существующий объект в 1С.',
  'onec.attach_file': 'Прикрепляет файл к документу в 1С.',
  'outlook.send_mail': 'Отправляет письмо через Outlook.',
  'email.send': 'Отправляет письмо через Outlook.',
  'email.create_draft': 'Создаёт черновик письма в Outlook.',
  'excel.create_workbook': 'Создаёт новую книгу Excel в папке агента.',
  'excel.edit_workbook': 'Правит существующую книгу Excel.',
  'outlook.create_event': 'Создаёт событие в календаре Outlook.',
  'report.export_document': 'Сохраняет отчёт файлом в папке агента.',
  'code.write_python': 'Сохраняет Python-файл в папке агента.',
  'code.run_python': 'Запускает Python-скрипт на этом компьютере.',
  'notify.send': 'Отправляет уведомление пользователю.',
  write: 'Записывает файл в рабочую область агента.',
  Write: 'Записывает файл в рабочую область агента.',
  Edit: 'Правит файл в рабочей области агента.',
  Delete: 'Удаляет файл в рабочей области агента.'
}

export function isReadTool(name: string): boolean {
  const tool = (name || '').trim()
  const lower = tool.toLowerCase()
  if (NEVER_CONFIRM.has(tool) || READ_EXACT.has(tool) || READ_EXACT.has(lower)) return true
  return READ_PREFIXES.some((prefix) => tool.startsWith(prefix) || lower.startsWith(prefix))
}

export function needsConfirmation(name: string): boolean {
  const tool = (name || '').trim()
  if (!tool || NEVER_CONFIRM.has(tool)) return false
  return !isReadTool(tool)
}

export function isWriteTool(name: string): boolean {
  const tool = (name || '').trim()
  if (!tool) return false
  if (NEVER_CONFIRM.has(tool)) return true
  if (WRITE_MARKERS.test(tool.toLowerCase())) return true
  return needsConfirmation(tool)
}

export function isDecisionTool(name: string, forcedConfirm = false): boolean {
  if (forcedConfirm) return true
  return needsConfirmation(name) || isWriteTool(name)
}

export function toolIntent(tool: string, args?: Record<string, unknown>): string {
  const known = TOOL_INTENT[tool] || TOOL_INTENT[tool.toLowerCase()] || ''
  const hint = toolArgHint(args)
  if (known && hint) return `${known} Цель: ${hint}`
  if (known) return known
  if (hint) return `Инструмент ${toolLabel(tool)}: ${hint}`
  return `Инструмент ${toolLabel(tool)} должен выполнить запись или действие, которое меняет данные.`
}

export function toolFromText(text: string): string {
  const value = text || ''
  const quoted = value.match(/[«"]([a-zA-Z][\w.]+)[»"]/)
  if (quoted?.[1]) return quoted[1]
  const labeled = value.match(/подтверждение:\s*([a-zA-Z][\w.]+)/i)
  if (labeled?.[1]) return labeled[1]
  return ''
}

export function summarizeToolResult(result: unknown, fallback = ''): string {
  if (typeof result === 'string' && result.trim()) return result.replace(/\s+/g, ' ').trim()
  if (result && typeof result === 'object') {
    const rec = result as Record<string, unknown>
    for (const key of ['summary', 'text', 'answer', 'path', 'file', 'message']) {
      const value = rec[key]
      if (typeof value === 'string' && value.trim()) return value.replace(/\s+/g, ' ').trim()
    }
  }
  return (fallback || '').replace(/\s+/g, ' ').trim()
}

export function eventLooksLikeConfirm(event: AgentRunnerEvent): boolean {
  const type = String(event.type || '').toLowerCase()
  if (type === 'hitl') return true
  if (event.confirmOnly === true) return true
  const text = String(event.text || event.message || '')
  return /нужно подтверждение|жду подтверждения|подтверждение:|требуется hitl/i.test(text)
}

export function eventLooksLikeReject(event: AgentRunnerEvent): boolean {
  const text = String(event.text || event.message || event.error || '')
  return /отклон|reject/i.test(text)
}

export interface ToolDecisionItem {
  id: string
  workflowId: string
  agentName: string
  runId: string
  tool: string
  title: string
  intent: string
  result: string
  status: 'pending' | 'confirmed' | 'rejected' | 'done'
  requestId: string
  at: string
  live: boolean
}

function eventTool(event: AgentRunnerEvent): string {
  return String(event.tool || toolFromText(String(event.text || event.message || ''))).trim()
}

export function extractToolDecisions(
  events: AgentRunnerEvent[],
  meta: { workflowId: string; agentName: string; runId: string; at: string; runClosed?: boolean }
): ToolDecisionItem[] {
  const items: ToolDecisionItem[] = []
  const open: ToolDecisionItem[] = []

  const makeItem = (
    tool: string,
    event: AgentRunnerEvent,
    status: ToolDecisionItem['status']
  ): ToolDecisionItem => ({
    id: `${meta.runId}:${event.requestId || tool}:${items.length}`,
    workflowId: meta.workflowId,
    agentName: meta.agentName,
    runId: meta.runId,
    tool,
    title: String(event.title || '').trim() || toolLabel(tool),
    intent: toolIntent(tool, event.arguments),
    result: '',
    status,
    requestId: String(event.requestId || ''),
    at: meta.at,
    live: false
  })

  const findOpen = (tool: string, requestId: string): ToolDecisionItem | undefined => {
    if (requestId) {
      const byId = [...open].reverse().find((item) => item.requestId === requestId)
      if (byId) return byId
    }
    return [...open].reverse().find((item) => item.tool === tool && item.status === 'pending')
  }

  for (const event of events) {
    const type = String(event.type || '').toLowerCase()
    const tool = eventTool(event)
    const confirm = eventLooksLikeConfirm(event)
    const rejected = eventLooksLikeReject(event) || Boolean(event.skipped)
    if (confirm && tool && isDecisionTool(tool, true)) {
      let item = findOpen(tool, String(event.requestId || ''))
      if (!item) {
        item = makeItem(tool, event, rejected ? 'rejected' : 'pending')
        items.push(item)
        open.push(item)
      } else if (event.requestId) {
        item.requestId = String(event.requestId)
      }
      if (rejected) {
        item.status = 'rejected'
        item.result = summarizeToolResult(event.result, String(event.text || event.message || 'Отклонено'))
      }
      continue
    }
    if (rejected) {
      const last = findOpen(tool, String(event.requestId || '')) || [...open].reverse().find((item) => item.status === 'pending')
      if (last) {
        last.status = 'rejected'
        last.result = summarizeToolResult(event.result, String(event.text || event.message || 'Отклонено'))
      }
      continue
    }
    const isToolEvent = type === 'tool_call' || type === 'tool' || type === 'tool_result'
    if (!isToolEvent || !tool || !isDecisionTool(tool, confirm)) continue
    const statusRaw = String(event.status || '').toLowerCase()
    const hasResult = event.result != null || Boolean(event.error) || /done|ok|error|fail|success/.test(statusRaw)
    const failed = Boolean(event.error) || statusRaw.includes('error') || statusRaw.includes('fail') || event.ok === false
    let item = findOpen(tool, String(event.requestId || ''))
    if (!item) {
      item = makeItem(tool, event, hasResult ? 'done' : 'pending')
      items.push(item)
      open.push(item)
    }
    if (hasResult) {
      item.result = summarizeToolResult(
        event.result,
        String(event.error || event.text || event.message || (failed ? 'Ошибка выполнения' : 'Выполнено'))
      )
      item.status = failed ? 'done' : item.status === 'pending' ? 'confirmed' : 'done'
      if (event.requestId) item.requestId = String(event.requestId)
    }
  }
  if (meta.runClosed) {
    for (const item of items) {
      if (item.status !== 'pending') continue
      item.status = 'done'
      item.result = item.result || 'Инструмент не был выполнен.'
    }
  }
  return items
}
