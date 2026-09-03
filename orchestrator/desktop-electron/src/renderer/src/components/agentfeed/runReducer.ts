import type { AgentEvent, AgentRunnerEvent } from '../../api/types'
import { isTaskTool, resolveToolName, toolArgHint, toolCardTitle, toolLabel } from './labels'
import { isAskQuestion, parseQuestionArgs } from './questionArgs'
import { appendThinkingText, streamDelta } from './thinkingText'
import type { FeedItem, PendingHitl, PendingQuestion, ToolItem } from './types'

export interface AgentResult {
  kind: 'design' | 'readiness' | 'demo' | 'run' | 'trigger'
  workflowId?: string
  draftId?: string
  agentId?: string
  runRef?: string
  answer?: string
  status?: string
  fired?: boolean
}

/** All per-run UI state. Held one-per-run in the store and in useAgentSession. */
export interface RunState {
  items: FeedItem[]
  status: string
  running: boolean
  runningSinceMs: number | null
  error: string
  pendingQuestion: PendingQuestion | null
  pendingHitl: PendingHitl | null
  activeRunId: string | null
}

/** Effects a single event can emit so callers can fire callbacks / navigate. */
export interface ApplyOutcome {
  state: RunState
  result?: AgentResult
  error?: string
}

export function createRunState(): RunState {
  return {
    items: [],
    status: '',
    running: false,
    runningSinceMs: null,
    error: '',
    pendingQuestion: null,
    pendingHitl: null,
    activeRunId: null
  }
}

let counter = 0
function nextId(prefix: string): string {
  counter += 1
  return `${prefix}-${counter}`
}

/** Strip constructor_tool / tool code fences from assistant text. */
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
  return cleaned
}

function normalizeResult(raw: unknown): Record<string, unknown> | null {
  if (raw == null) return null
  if (typeof raw === 'object') return raw as Record<string, unknown>
  return { value: raw }
}

/** Mirror desktop compact_tool_result: only the tool OUTPUT, summarized. */
function summarizeResult(result: Record<string, unknown> | null): string {
  if (!result || typeof result !== 'object') return 'Данные получены.'
  const summary = result.summary
  if (typeof summary === 'string' && summary.trim()) return summary.trim()
  if (typeof result.result_file === 'string' && result.result_file.trim()) {
    return `Файл: ${result.result_file}`
  }
  if (result.externalized && typeof result.result_file === 'string') {
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

function isRunningStatus(status: string): boolean {
  const value = (status || '').toLowerCase()
  return !value || value === 'running' || value === 'in_progress' || value === 'pending' || value === 'started'
}

function argsFingerprint(tool: string, args: Record<string, unknown>): string {
  const hint = toolArgHint(args)
  if (hint) return `${tool}:${hint}`
  try {
    return `${tool}:${JSON.stringify(args)}`
  } catch {
    return tool
  }
}

function toolStatusText(done: boolean, error: boolean, summary: string, hint: string): string {
  if (error) return summary || 'Ошибка'
  if (done) return summary || 'Готово'
  return hint ? `Выполняется: ${hint}` : 'Выполняется…'
}

function findToolIndex(
  items: FeedItem[],
  tool: string,
  requestId: string,
  args: Record<string, unknown>,
  running: boolean
): number {
  if (requestId) {
    const byId = items.findIndex((item) => item.kind === 'tool' && item.requestId === requestId)
    if (byId >= 0) return byId
  }
  const fingerprint = argsFingerprint(tool, args)
  const distinct = fingerprint !== tool && fingerprint !== `${tool}:{}` && !fingerprint.endsWith(':')
  if (distinct) {
    for (let i = items.length - 1; i >= 0; i -= 1) {
      const item = items[i]
      if (item.kind !== 'tool' || item.done || item.tool !== tool) continue
      if (argsFingerprint(item.tool, item.arguments) === fingerprint) return i
    }
  }
  if (!running) {
    for (let i = items.length - 1; i >= 0; i -= 1) {
      const item = items[i]
      if (item.kind === 'tool' && !item.done && item.tool === tool) return i
    }
  }
  return -1
}

function pushThinking(items: FeedItem[], text: string): FeedItem[] {
  const last = items[items.length - 1]
  if (last && last.kind === 'thinking') {
    const merged = [...items]
    merged[merged.length - 1] = { ...last, text: appendThinkingText(last.text, text) }
    return merged
  }
  return [...items, { kind: 'thinking', id: nextId('think'), text: appendThinkingText('', text) }]
}

function pushAssistant(items: FeedItem[], text: string): FeedItem[] {
  const clean = visibleAssistant(text)
  if (!clean.trim()) return items
  const last = items[items.length - 1]
  if (last && last.kind === 'message' && last.role === 'agent') {
    const merged = [...items]
    merged[merged.length - 1] = { ...last, text: last.text + streamDelta(last.text, clean) }
    return merged
  }
  return [...items, { kind: 'message', id: nextId('msg'), role: 'agent', text: clean }]
}

function isReadableText(value: string): boolean {
  const text = (value || '').trim()
  if (!text) return false
  return Boolean(text.replace(/[?？\s.,;:!…()[\]{}'"`+-]/g, ''))
}

function bestErrorText(...values: unknown[]): string {
  for (const value of values) {
    const text = String(value ?? '').trim()
    if (isReadableText(text)) return text
  }
  return ''
}

function fallbackErrorText(event: AgentEvent): string {
  const payload = (event.payload as Record<string, unknown> | undefined) || {}
  const code = String(event.code ?? payload.code ?? '').trim()
  const status = String(event.status ?? payload.status ?? '').trim()
  const runId = String(event.runId || '').trim()
  const parts: string[] = []
  if (status) parts.push(`status: ${status}`)
  if (code) parts.push(`code: ${code}`)
  if (runId) parts.push(`run: ${runId.slice(0, 8)}`)
  const tail = parts.length ? ` (${parts.join(', ')})` : ''
  return `Запуск прерван до получения ответа${tail}. Откройте «Диагностика» для деталей.`
}

export function pushSystem(items: FeedItem[], text: string, tone: 'info' | 'error' | 'success' = 'info'): FeedItem[] {
  const value = (text || '').trim()
  if (!value) return items
  return [...items, { kind: 'system', id: nextId('sys'), text: value, tone }]
}

export function pushUserMessage(items: FeedItem[], text: string): FeedItem[] {
  const value = (text || '').trim()
  if (!value) return items
  return [...items, { kind: 'message', id: nextId('user'), role: 'user', text: value }]
}

/**
 * Add the final result. If the trailing agent message only repeats it (the last
 * assistant segment already streamed live), drop that message so the answer is
 * shown once, as a crisp result — the way Cursor keeps the last block separate.
 */
function pushResult(items: FeedItem[], text: string): FeedItem[] {
  const value = (text || '').trim()
  if (!value) return items
  const last = items[items.length - 1]
  if (
    last &&
    last.kind === 'message' &&
    last.role === 'agent' &&
    visibleAssistant(last.text).trim() === visibleAssistant(value).trim()
  ) {
    return [...items.slice(0, -1), { kind: 'result', id: nextId('res'), text: value }]
  }
  return [...items, { kind: 'result', id: nextId('res'), text: value }]
}

function handleToolCall(state: RunState, payload: AgentRunnerEvent): RunState {
  const rawTool = String(payload.tool || '')
  const requestId = String(payload.requestId || '')
  const args = (payload.arguments as Record<string, unknown>) || {}
  const tool = resolveToolName(rawTool, args)
  if (isAskQuestion(tool) || isAskQuestion(rawTool)) {
    const parsed = parseQuestionArgs(payload.arguments)
    const question = parsed.question || state.pendingQuestion?.question || ''
    const options = parsed.options.length ? parsed.options : state.pendingQuestion?.options || []
    if (!question && options.length === 0 && !requestId) return state
    return {
      ...state,
      pendingQuestion: {
        requestId: requestId || state.pendingQuestion?.requestId || '',
        question,
        options,
        needsFile: parsed.needsFile || state.pendingQuestion?.needsFile,
        accept: parsed.accept.length ? parsed.accept : state.pendingQuestion?.accept
      },
      status: 'Нужен ваш ответ'
    }
  }
  const status = String(payload.status || '')
  const resultObj = normalizeResult(payload.result)
  const running = isRunningStatus(status) && !isDoneStatus(status)
  const done = isDoneStatus(status) || (!running && resultObj !== null)
  const errored = isErrorStatus(status)
  const hint = toolArgHint(args)
  const summary = done ? summarizeResult(resultObj) : ''
  const title = toolCardTitle(tool, args)
  const merged = [...state.items]
  const idx = findToolIndex(merged, tool, requestId, args, running)
  if (idx >= 0) {
    const current = merged[idx] as ToolItem
    const nextDone = current.done || done
    const nextError = current.error || errored
    const nextHint = hint || current.hint
    const nextSummary = nextDone ? summary || current.summary : current.summary
    const nextArgs = Object.keys(args).length ? args : current.arguments
    merged[idx] = {
      ...current,
      tool: tool || current.tool,
      requestId: requestId || current.requestId,
      title: title.startsWith('Инструмент: внешний') ? current.title : title,
      hint: nextHint,
      arguments: nextArgs,
      result: resultObj ?? current.result,
      summary: nextSummary,
      statusText: nextDone
        ? toolStatusText(nextDone, nextError, nextSummary, nextHint)
        : current.statusText || toolStatusText(false, false, '', nextHint),
      done: nextDone,
      error: nextError
    }
  } else {
    merged.push({
      kind: 'tool',
      id: nextId('tool'),
      tool,
      requestId,
      title,
      hint,
      arguments: args,
      result: resultObj,
      summary,
      statusText: toolStatusText(done, errored, summary, hint),
      done,
      error: errored
    })
  }
  return { ...state, items: merged, status: done ? state.status : `Вызываю ${toolLabel(tool)}…` }
}

function handleTask(state: RunState, payload: AgentRunnerEvent): RunState {
  const requestId = String(payload.requestId || '')
  const text = String(payload.text || payload.message || '')
  const status = String(payload.status || '')
  const done = isDoneStatus(status)
  const errored = isErrorStatus(status)
  if (!text && !requestId && !done) return state
  const merged = [...state.items]
  let idx = -1
  if (requestId) {
    idx = merged.findIndex((item) => item.kind === 'tool' && item.requestId === requestId)
  }
  if (idx < 0) {
    for (let i = merged.length - 1; i >= 0; i -= 1) {
      const item = merged[i]
      if (item.kind === 'tool' && !item.done && isTaskTool(item.tool)) {
        idx = i
        break
      }
    }
  }
  if (idx >= 0) {
    const current = merged[idx] as ToolItem
    const nextText = text ? current.statusText + streamDelta(current.statusText, text) : current.statusText
    merged[idx] = {
      ...current,
      requestId: requestId || current.requestId,
      statusText:
        nextText || toolStatusText(done || current.done, errored || current.error, current.summary, current.hint),
      done: current.done || done,
      error: current.error || errored
    }
  } else {
    merged.push({
      kind: 'tool',
      id: nextId('tool'),
      tool: 'Task',
      requestId,
      title: 'Вложенный агент',
      hint: '',
      arguments: {},
      result: null,
      summary: '',
      statusText: text || toolStatusText(done, errored, '', ''),
      done,
      error: errored
    })
  }
  return { ...state, items: merged, status: done ? state.status : 'Вложенный агент работает…' }
}

function handleToolResult(state: RunState, payload: AgentRunnerEvent): RunState {
  const tool = String(payload.tool || '')
  const requestId = String(payload.requestId || '')
  const ok = payload.ok !== false
  const errText = String(payload.error || '')
  const resultObj = normalizeResult(payload.result)
  const skipped =
    Boolean(payload.skipped) || Boolean(resultObj && (resultObj as Record<string, unknown>).skipped)
  const summary = !ok
    ? errText || 'Ошибка инструмента'
    : skipped
      ? 'Пропущено пользователем'
      : summarizeResult(resultObj)
  const merged = [...state.items]
  let idx = -1
  if (requestId) {
    idx = merged.findIndex((it) => it.kind === 'tool' && it.requestId === requestId)
  }
  if (idx < 0) {
    for (let i = merged.length - 1; i >= 0; i -= 1) {
      const candidate = merged[i]
      if (candidate.kind === 'tool' && !candidate.done && (!tool || candidate.tool === tool)) {
        idx = i
        break
      }
    }
  }
  if (idx >= 0) {
    const current = merged[idx] as ToolItem
    merged[idx] = {
      ...current,
      requestId: requestId || current.requestId,
      result: resultObj ?? current.result,
      summary,
      statusText: toolStatusText(true, !ok, summary, current.hint),
      done: true,
      error: !ok
    }
  } else {
    merged.push({
      kind: 'tool',
      id: nextId('tool'),
      tool,
      requestId,
      title: toolLabel(tool),
      hint: '',
      arguments: {},
      result: resultObj,
      summary,
      statusText: toolStatusText(true, !ok, summary, ''),
      done: true,
      error: !ok
    })
  }
  return { ...state, items: merged }
}

/** Apply one inner runner payload (from a top-level {type:'event'} message). */
export function applyRunnerEvent(state: RunState, payload: AgentRunnerEvent): RunState {
  const type = String(payload.type || '')
  const text = String(payload.text || payload.message || '')
  switch (type) {
    case 'thinking':
      return { ...pushThinkingState(state, text), status: 'Думает…' }
    case 'assistant':
    case 'agent_message':
      return { ...state, items: pushAssistant(state.items, text) }
    case 'tool_call':
      return handleToolCall(state, payload)
    case 'task':
      return handleTask(state, payload)
    case 'tool_result':
      return handleToolResult(state, payload)
    case 'decision':
    case 'progress':
      return { ...state, items: pushSystem(state.items, text) }
    case 'status':
      return { ...state, status: text || 'Агент работает…' }
    case 'final':
    case 'work_result':
      if (text) {
        return { ...state, items: pushResult(state.items, text) }
      }
      return state
    case 'error': {
      const message = bestErrorText(payload.text, payload.message, payload.error, payload.status)
      if (!message) return state
      return { ...state, items: pushSystem(state.items, message, 'error') }
    }
    default:
      return state
  }
}

function pushThinkingState(state: RunState, text: string): RunState {
  return { ...state, items: pushThinking(state.items, text) }
}

/**
 * Apply one top-level AgentEvent. The CALLER is responsible for run-id routing
 * (only pass events that belong to this run). Returns the new state plus any
 * result/error effect the caller should surface.
 */
export function applyAgentEvent(state: RunState, event: AgentEvent): ApplyOutcome {
  switch (event.type) {
    case 'event':
      return event.payload ? { state: applyRunnerEvent(state, event.payload) } : { state }
    case 'question': {
      const parsed = parseQuestionArgs({
        question: event.question,
        options: event.options,
        needsFile: event.needsFile,
        accept: event.accept,
        ...(event.arguments || {})
      })
      const question = parsed.question || state.pendingQuestion?.question || ''
      const options = parsed.options.length ? parsed.options : state.pendingQuestion?.options || []
      return {
        state: {
          ...state,
          pendingQuestion: {
            requestId: String(event.requestId || state.pendingQuestion?.requestId || ''),
            question,
            options,
            needsFile: parsed.needsFile || Boolean(event.needsFile) || state.pendingQuestion?.needsFile,
            accept: parsed.accept.length
              ? parsed.accept
              : event.accept?.length
                ? event.accept
                : state.pendingQuestion?.accept
          },
          status: 'Нужен ваш ответ'
        }
      }
    }
    case 'hitl': {
      const tool = String(event.tool || '')
      return {
        state: {
          ...state,
          pendingHitl: {
            requestId: String(event.requestId || ''),
            tool,
            title: toolLabel(tool),
            arguments: (event.arguments as Record<string, unknown>) || {}
          },
          status: 'Требуется подтверждение действия'
        }
      }
    }
    case 'result': {
      const answer = String(event.answer || '').trim()
      return {
        state: {
          ...state,
          running: false,
          runningSinceMs: null,
          status: '',
          pendingQuestion: null,
          pendingHitl: null,
          activeRunId: null,
          items: pushResult(state.items, answer)
        },
        result: {
          kind: (event.kind as AgentResult['kind']) || 'run',
          workflowId: event.workflowId,
          draftId: event.draftId,
          agentId: event.agentId,
          runRef: event.runRef,
          answer: event.answer,
          status: event.status,
          fired: event.fired
        }
      }
    }
    case 'error': {
      const message = bestErrorText(
        event.message,
        event.text,
        (event.payload as Record<string, unknown> | undefined)?.error,
        (event.payload as Record<string, unknown> | undefined)?.message,
        (event.payload as Record<string, unknown> | undefined)?.text
      )
      const finalMessage = message || fallbackErrorText(event)
      return {
        state: {
          ...state,
          running: false,
          runningSinceMs: null,
          status: '',
          error: finalMessage,
          pendingQuestion: null,
          pendingHitl: null,
          items: pushSystem(state.items, finalMessage, 'error'),
          activeRunId: null
        },
        error: finalMessage
      }
    }
    case 'ready_state':
      if (!event.ok && event.message) {
        return { state: { ...state, items: pushSystem(state.items, `Локальный Cursor SDK недоступен: ${event.message}`, 'error') } }
      }
      return { state }
    case 'sidecar_exit':
      return { state: { ...state, items: pushSystem(state.items, 'Процесс агента завершился. Перезапуск…', 'error') } }
    default:
      return { state }
  }
}

/** Latest plain agent output (result or agent message), for banner previews. */
export function deriveLatestOutput(items: FeedItem[]): string {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const item = items[i]
    if (item.kind === 'result') return item.text
    if (item.kind === 'message' && item.role === 'agent') return item.text
  }
  return ''
}
