import type { AgentRunnerEvent } from '../../api/types'
import { toolLabel } from './labels'
import type { FeedItem, ToolItem } from './types'

let counter = 0
function nextId(prefix: string): string {
  counter += 1
  return `hist-${prefix}-${counter}`
}

function cleanThinking(text: string): string {
  const value = (text || '').trim()
  if (value && (value.startsWith('{') || value.toLowerCase().includes('traceback'))) {
    return 'Агент анализирует задачу…'
  }
  return value || 'Агент анализирует задачу…'
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

function summarizeResult(result: Record<string, unknown> | null): string {
  if (!result || typeof result !== 'object') return 'Готово'
  const summary = result.summary
  if (typeof summary === 'string' && summary.trim()) return summary.trim()
  if (result.externalized && typeof result.result_file === 'string') {
    return `Данные сохранены в файл ${result.result_file}`
  }
  if (result.skipped) return 'Пропущено пользователем'
  if (result.rejected) return 'Отклонено пользователем'
  return 'Готово'
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
        const clean = cleanThinking(text)
        const last = items[items.length - 1]
        if (last && last.kind === 'thinking') {
          const prev = last.text === 'Агент анализирует задачу…' ? '' : last.text
          last.text = (prev + clean).trim() || clean
        } else {
          items.push({ kind: 'thinking', id: nextId('think'), text: clean })
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
        const item: ToolItem = {
          kind: 'tool',
          id: nextId('tool'),
          tool,
          title: toolLabel(tool),
          arguments: (event.arguments as Record<string, unknown>) || {},
          result: null,
          summary: '',
          done: false
        }
        items.push(item)
        break
      }
      case 'tool_result': {
        const tool = String(event.tool || '')
        const result = (event.result as Record<string, unknown>) || {}
        let matched = false
        for (let i = items.length - 1; i >= 0; i -= 1) {
          const candidate = items[i]
          if (candidate.kind === 'tool' && !candidate.done && (!tool || candidate.tool === tool)) {
            candidate.result = result
            candidate.summary = summarizeResult(result)
            candidate.done = true
            matched = true
            break
          }
        }
        if (!matched) {
          items.push({
            kind: 'tool',
            id: nextId('tool'),
            tool,
            title: toolLabel(tool),
            arguments: {},
            result,
            summary: summarizeResult(result),
            done: true
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
