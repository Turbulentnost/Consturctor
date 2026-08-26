import type { AgentRunnerEvent } from '../../api/types'
import { toolLabel } from './labels'
import { appendThinkingText } from './thinkingText'
import type { FeedItem, ToolItem } from './types'

let counter = 0
function nextId(prefix: string): string {
  counter += 1
  return `hist-${prefix}-${counter}`
}

function visibleAssistant(text: string): string {
  let cleaned = (text || '').replace(/\ufffd/g, '')
  if (cleaned.includes('```constructor_tool') || cleaned.includes('```tool')) {
    const out: string[] = []
    let skip = false
    for (const line of cleaned.split('\n')) {
      const fence = line.trim()
      if (fence.startsWith('```constructor_tool') || fence.startsWith('```tool')) {
        skip = true
        continue
      }
      if (skip && fence.startsWith('```')) {
        skip = false
        continue
      }
      if (!skip) out.push(line)
    }
    cleaned = out.join('\n')
  }
  return cleaned.trim()
}

function normalizeResult(raw: unknown): Record<string, unknown> | null {
  if (raw == null) return null
  if (typeof raw === 'object') return raw as Record<string, unknown>
  return { value: raw }
}

function summarizeResult(result: Record<string, unknown> | null): string {
  if (!result || typeof result !== 'object') return 'Данные получены.'
  const summary = result.summary
  if (typeof summary === 'string' && summary.trim()) return summary.trim()
  if (typeof result.result_file === 'string' && result.result_file.trim()) {
    return `Файл: ${result.result_file}`
  }
  if (result.skipped) return 'Пропущено пользователем'
  if (result.rejected) return 'Отклонено пользователем'
  for (const key of ['items', 'rows', 'results', 'messages', 'events', 'files', 'records', 'documents', 'tasks']) {
    const value = result[key]
    if (Array.isArray(value)) return `Получено записей: ${value.length}`
  }
  if (typeof result.text === 'string' && result.text.trim()) return result.text.trim().slice(0, 200)
  if (typeof result.value === 'string' && result.value.trim()) return result.value.trim().slice(0, 200)
  return 'Данные получены.'
}

const _DONE_STATUS = new Set([
  'completed',
  'complete',
  'success',
  'succeeded',
  'ok',
  'done',
  'error',
  'failed',
  'cancelled',
  'canceled'
])

function isDoneStatus(status: string): boolean {
  return _DONE_STATUS.has((status || '').toLowerCase())
}

function isErrorStatus(status: string): boolean {
  const value = (status || '').toLowerCase()
  return value === 'error' || value === 'failed'
}

/** Build a static feed from persisted runner events (history view). */
export function buildFeedItems(events: AgentRunnerEvent[]): FeedItem[] {
  const items: FeedItem[] = []
  const pushSystem = (text: string, tone: 'info' | 'error' | 'success' = 'info'): void => {
    const value = (text || '').trim()
    if (value) items.push({ kind: 'system', id: nextId('sys'), text: value, tone })
  }

  for (const event of events) {
    const type = String(event.type || '')
    const text = String(event.text || event.message || '')
    switch (type) {
      case 'user_message':
        if (text.trim()) items.push({ kind: 'message', id: nextId('user'), role: 'user', text })
        break
      case 'thinking': {
        const last = items[items.length - 1]
        if (last && last.kind === 'thinking') {
          last.text = appendThinkingText(last.text, text)
        } else {
          items.push({ kind: 'thinking', id: nextId('think'), text: appendThinkingText('', text) })
        }
        break
      }
      case 'assistant':
      case 'agent_message': {
        const clean = visibleAssistant(text)
        if (!clean) break
        const last = items[items.length - 1]
        if (last && last.kind === 'message' && last.role === 'agent') {
          last.text = `${last.text}${clean}`
        } else {
          items.push({ kind: 'message', id: nextId('msg'), role: 'agent', text: clean })
        }
        break
      }
      case 'tool_call': {
        const tool = String(event.tool || '')
        const requestId = String(event.requestId || '')
        const status = String(event.status || '')
        const resultObj = normalizeResult(event.result)
        const done = isDoneStatus(status) || (resultObj !== null && status !== 'running')
        const errored = isErrorStatus(status)
        let idx = -1
        if (requestId) {
          idx = items.findIndex((it) => it.kind === 'tool' && it.requestId === requestId)
        }
        if (idx < 0) {
          for (let i = items.length - 1; i >= 0; i -= 1) {
            const candidate = items[i]
            if (candidate.kind === 'tool' && !candidate.done && !candidate.requestId && candidate.tool === tool) {
              idx = i
              break
            }
          }
        }
        if (idx >= 0) {
          const current = items[idx] as ToolItem
          current.requestId = requestId || current.requestId
          current.result = resultObj ?? current.result
          if (done) current.summary = summarizeResult(current.result)
          current.done = current.done || done
          current.error = current.error || errored
        } else {
          items.push({
            kind: 'tool',
            id: nextId('tool'),
            tool,
            requestId,
            title: toolLabel(tool),
            arguments: (event.arguments as Record<string, unknown>) || {},
            result: resultObj,
            summary: done ? summarizeResult(resultObj) : '',
            done,
            error: errored
          })
        }
        break
      }
      case 'tool_result': {
        const tool = String(event.tool || '')
        const requestId = String(event.requestId || '')
        const ok = event.ok !== false
        const errText = String(event.error || '')
        const resultObj = normalizeResult(event.result)
        const skipped =
          Boolean(event.skipped) || Boolean(resultObj && (resultObj as Record<string, unknown>).skipped)
        const summary = !ok
          ? errText || 'Ошибка инструмента'
          : skipped
            ? 'Пропущено пользователем'
            : summarizeResult(resultObj)
        let idx = -1
        if (requestId) {
          idx = items.findIndex((it) => it.kind === 'tool' && it.requestId === requestId)
        }
        if (idx < 0) {
          for (let i = items.length - 1; i >= 0; i -= 1) {
            const candidate = items[i]
            if (candidate.kind === 'tool' && !candidate.done && (!tool || candidate.tool === tool)) {
              idx = i
              break
            }
          }
        }
        if (idx >= 0) {
          const current = items[idx] as ToolItem
          current.requestId = requestId || current.requestId
          current.result = resultObj ?? current.result
          current.summary = summary
          current.done = true
          current.error = !ok
        } else {
          items.push({
            kind: 'tool',
            id: nextId('tool'),
            tool,
            requestId,
            title: toolLabel(tool),
            arguments: {},
            result: resultObj,
            summary,
            done: true,
            error: !ok
          })
        }
        break
      }
      case 'decision':
      case 'progress':
        pushSystem(text)
        break
      case 'final':
      case 'work_result':
        pushSystem(text, 'success')
        break
      case 'error':
        pushSystem(text, 'error')
        break
      default:
        break
    }
  }
  return items
}
