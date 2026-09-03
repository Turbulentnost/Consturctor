import type { AgentRunHistoryItem, AgentRunnerEvent, WorkflowFileItem } from '../api/types'

export const HISTORY_STATUS_LABELS: Record<string, string> = {
  ok: 'Успешно',
  error: 'Ошибка',
  running: 'Выполняется',
  started: 'Выполняется',
  canceled: 'Отменён',
  cancelled: 'Отменён'
}

const TRIGGER_PROMPT = /выполни рабочую задачу агента/i

export function historyStatusLabel(status: string): string {
  const key = (status || '').trim().toLowerCase()
  return HISTORY_STATUS_LABELS[key] || status || 'Запуск'
}

export function historyStatusTone(status: string): 'ok' | 'error' | 'running' | 'canceled' {
  const key = (status || '').trim().toLowerCase()
  if (key === 'error' || key === 'failed') return 'error'
  if (key === 'started' || key === 'running') return 'running'
  if (key === 'canceled' || key === 'cancelled') return 'canceled'
  return 'ok'
}

export function formatRunWhen(value: string): string {
  if (!value) return ''
  try {
    return new Date(value).toLocaleString('ru-RU')
  } catch {
    return value
  }
}

export function historySourceLabel(run: Pick<AgentRunHistoryItem, 'source' | 'triggerKind'>): string {
  if ((run.source || '').trim() !== 'trigger') return 'чат'
  const kind = (run.triggerKind || '').trim()
  if (kind === 'event') return 'триггер · изменение'
  if (kind === 'time' || kind === 'interval' || kind === 'datetime') return 'триггер · наступило время'
  return 'триггер'
}

function fileBaseName(raw: string): string {
  return raw.replace(/\\/g, '/').split('/').pop()?.trim() || ''
}

function collectPathNames(value: unknown, into: Set<string>): void {
  if (typeof value === 'string') {
    const name = fileBaseName(value)
    if (name && /\.[A-Za-z0-9]{1,8}$/.test(name)) into.add(name.toLowerCase())
    return
  }
  if (Array.isArray(value)) {
    for (const item of value) collectPathNames(item, into)
    return
  }
  if (!value || typeof value !== 'object') return
  const row = value as Record<string, unknown>
  for (const key of ['file', 'path', 'filename', 'result_file', 'absolute_path', 'filepath', 'dest']) {
    if (typeof row[key] === 'string') collectPathNames(row[key], into)
  }
  for (const key of ['files', 'items', 'documents']) {
    if (Array.isArray(row[key])) collectPathNames(row[key], into)
  }
}

export function mentionedOutputNames(answer: string, events: AgentRunnerEvent[]): Set<string> {
  const names = new Set<string>()
  const addFromText = (text: string): void => {
    for (const match of text.matchAll(/`([^`]+)`/g)) collectPathNames(match[1], names)
  }
  addFromText(answer)
  for (const event of events) {
    if (event.text) addFromText(event.text)
    if (event.message) addFromText(event.message)
    collectPathNames(event.result, names)
  }
  return names
}

function isAgentOutput(file: WorkflowFileItem): boolean {
  return file.source === 'agent' || file.scope === 'run_output'
}

export function filesForHistoryRun(
  files: WorkflowFileItem[],
  runId: string,
  answer: string,
  events: AgentRunnerEvent[]
): WorkflowFileItem[] {
  const mentioned = mentionedOutputNames(answer, events)
  return files.filter((file) => {
    if (!isAgentOutput(file)) return false
    const rid = (file.runId || '').trim()
    if (!rid || rid === runId || rid === 'local') return true
    return mentioned.has((file.name || '').toLowerCase())
  })
}

function visibleAssistant(text: string): string {
  return (text || '').replace(/\ufffd/g, '').trim()
}

function composeOnecDocuments(result: Record<string, unknown>): string {
  const documents = Array.isArray(result.documents) ? result.documents : []
  if (!documents.length) return ''
  const lines = [`Найдено документов 1С: ${documents.length}`]
  for (const raw of documents.slice(0, 10)) {
    if (!raw || typeof raw !== 'object') continue
    const item = raw as Record<string, unknown>
    const number = String(item.number || '').trim()
    const theme = String(item.meeting_topic || item.theme || '').trim()
    const title = String(item.title || '').trim()
    const status = String(item.status || '').trim()
    let label = ''
    if (number) label = theme ? `№ ${number} · ${theme}` : `№ ${number}`
    else if (theme) label = theme
    else if (title && !TRIGGER_PROMPT.test(title)) label = title
    else label = title || 'Документ'
    lines.push(`• ${label}${status ? ` — ${status}` : ''}`)
  }
  return lines.join('\n')
}

function textFromEvent(event: AgentRunnerEvent): string {
  const direct = visibleAssistant(event.text || event.message || '')
  if (direct && !TRIGGER_PROMPT.test(direct)) return direct
  if (event.result && typeof event.result === 'object') {
    const composed = composeOnecDocuments(event.result as Record<string, unknown>)
    if (composed) return composed
  }
  return direct
}

export function historyResultText(answer: string, events: AgentRunnerEvent[]): string {
  const preferredTypes = new Set(['work_result', 'final', 'result', 'agent_message'])
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    if (!preferredTypes.has(event.type)) continue
    const text = textFromEvent(event)
    if (text) return text
  }
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    if (event.type !== 'tool_result' && event.type !== 'tool') continue
    const text = textFromEvent(event)
    if (text) return text
  }
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    if (event.type !== 'assistant' && event.type !== 'agent') continue
    const text = visibleAssistant(event.text || '')
    if (text) return text
  }
  return sanitizeStoredAnswer((answer || '').trim())
}

function sanitizeStoredAnswer(text: string): string {
  if (!text) return text
  const lines = text.split('\n')
  const next = lines.map((line) => {
    const bullet = line.match(/^(\s*[•\-]\s*)(.+)$/)
    if (!bullet) return line
    const rest = bullet[2]
    const split = rest.match(/^(.*?)\s+[—-]\s+(.+)$/)
    const title = (split ? split[1] : rest).trim()
    const status = split ? split[2].trim() : ''
    if (!TRIGGER_PROMPT.test(title)) return line
    return `${bullet[1]}${status ? `Документ — ${status}` : 'Документ'}`
  })
  return next.join('\n')
}

export function eventsForHistoryRun(
  events: AgentRunnerEvent[],
  run: AgentRunHistoryItem | undefined,
  answer: string
): AgentRunnerEvent[] {
  if (events.length) return events
  const fallback: AgentRunnerEvent[] = []
  const message = (run?.message || '').trim()
  if (message) fallback.push({ type: 'user_message', text: message })
  const status = (run?.status || '').trim().toLowerCase()
  if (status === 'started' || status === 'running') {
    fallback.push({
      type: 'system',
      text: 'Запуск ещё выполняется. Этот экран показывает историю, а не живой ход.'
    })
  }
  if (status === 'error') {
    fallback.push({ type: 'error', message: answer || 'Прогон завершился с ошибкой.' })
  } else if (answer) {
    fallback.push({ type: 'agent_message', text: answer })
  }
  return fallback
}
