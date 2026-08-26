import { useCallback, useEffect, useRef, useState } from 'react'
import { agentClient, type StartCommand } from '../../api/agent'
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

interface UseAgentSessionOptions {
  onResult?: (result: AgentResult) => void
  onError?: (message: string) => void
}

interface UseAgentSessionValue {
  items: FeedItem[]
  status: string
  running: boolean
  error: string
  pendingQuestion: PendingQuestion | null
  pendingHitl: PendingHitl | null
  activeRunId: string | null
  start: (command: StartCommand) => string
  answer: (requestId: string, value: string, filePaths?: string[], ok?: boolean) => void
  respondHitl: (requestId: string, approved: boolean) => void
  skip: () => void
  cancel: () => void
  reset: () => void
  pushUserMessage: (text: string) => void
  pushSystem: (text: string) => void
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

export function useAgentSession(options: UseAgentSessionOptions = {}): UseAgentSessionValue {
  const [items, setItems] = useState<FeedItem[]>([])
  const [status, setStatus] = useState('')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [pendingQuestion, setPendingQuestion] = useState<PendingQuestion | null>(null)
  const [pendingHitl, setPendingHitl] = useState<PendingHitl | null>(null)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)

  const activeRunRef = useRef<string | null>(null)
  const optionsRef = useRef(options)
  optionsRef.current = options

  const appendThinking = useCallback((text: string) => {
    setItems((prev) => {
      const last = prev[prev.length - 1]
      if (last && last.kind === 'thinking') {
        const merged = [...prev]
        merged[merged.length - 1] = { ...last, text: appendThinkingText(last.text, text) }
        return merged
      }
      return [...prev, { kind: 'thinking', id: nextId('think'), text: appendThinkingText('', text) }]
    })
  }, [])

  const appendAssistant = useCallback((text: string) => {
    const clean = visibleAssistant(text)
    if (!clean.trim()) return
    setItems((prev) => {
      const last = prev[prev.length - 1]
      if (last && last.kind === 'message' && last.role === 'agent') {
        const merged = [...prev]
        merged[merged.length - 1] = { ...last, text: last.text + streamDelta(last.text, clean) }
        return merged
      }
      return [...prev, { kind: 'message', id: nextId('msg'), role: 'agent', text: clean }]
    })
  }, [])

  const appendSystem = useCallback((text: string, tone: 'info' | 'error' | 'success' = 'info') => {
    const value = (text || '').trim()
    if (!value) return
    setItems((prev) => [...prev, { kind: 'system', id: nextId('sys'), text: value, tone }])
  }, [])

  /**
   * Handle a runner `tool_call`. Two shapes exist:
   * - host tools: {requestId, tool, arguments} (result arrives later as tool_result)
   * - SDK-native tools: repeated {tool, status, arguments, result} with status
   *   running -> completed and the result inline (no separate tool_result).
   * We upsert one card per invocation (correlated by requestId, else the last
   * running card with the same tool name) instead of pushing duplicates.
   */
  const applyQuestion = useCallback((requestId: string, raw: unknown, fallback?: PendingQuestion | null) => {
    const parsed = parseQuestionArgs(raw)
    const question = parsed.question || fallback?.question || ''
    const options = parsed.options.length ? parsed.options : fallback?.options || []
    if (!question && options.length === 0 && !requestId) return
    setPendingQuestion({
      requestId: requestId || fallback?.requestId || '',
      question,
      options
    })
    setStatus('Нужен ваш ответ')
  }, [])

  const handleToolCall = useCallback((payload: AgentRunnerEvent) => {
    const rawTool = String(payload.tool || '')
    const requestId = String(payload.requestId || '')
    const args = (payload.arguments as Record<string, unknown>) || {}
    const tool = resolveToolName(rawTool, args)
    if (isAskQuestion(tool) || isAskQuestion(rawTool)) {
      applyQuestion(requestId, payload.arguments)
      return
    }
    const status = String(payload.status || '')
    const resultObj = normalizeResult(payload.result)
    const running = isRunningStatus(status) && !isDoneStatus(status)
    const done = isDoneStatus(status) || (!running && resultObj !== null)
    const errored = isErrorStatus(status)
    const hint = toolArgHint(args)
    const summary = done ? summarizeResult(resultObj) : ''
    const title = toolCardTitle(tool, args)
    setItems((prev) => {
      const merged = [...prev]
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
        return merged
      }
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
      return merged
    })
    if (!done) setStatus(`Вызываю ${toolLabel(tool)}…`)
  }, [applyQuestion])

  const handleTask = useCallback((payload: AgentRunnerEvent) => {
    const requestId = String(payload.requestId || '')
    const text = String(payload.text || payload.message || '')
    const status = String(payload.status || '')
    const done = isDoneStatus(status)
    const errored = isErrorStatus(status)
    if (!text && !requestId && !done) return
    setItems((prev) => {
      const merged = [...prev]
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
          statusText: nextText || toolStatusText(done || current.done, errored || current.error, current.summary, current.hint),
          done: current.done || done,
          error: current.error || errored
        }
        return merged
      }
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
      return merged
    })
    if (!done) setStatus('Вложенный агент работает…')
  }, [])

  /** Handle a host-tool `tool_result` (ok/error/skipped). Completes the card. */
  const handleToolResult = useCallback((payload: AgentRunnerEvent) => {
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
    setItems((prev) => {
      const merged = [...prev]
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
        return merged
      }
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
      return merged
    })
  }, [])

  const handleRunnerEvent = useCallback(
    (payload: AgentRunnerEvent) => {
      const type = String(payload.type || '')
      const text = String(payload.text || payload.message || '')
      switch (type) {
        case 'thinking':
          appendThinking(text)
          setStatus('Думает…')
          break
        case 'assistant':
        case 'agent_message':
          appendAssistant(text)
          break
        case 'tool_call':
          handleToolCall(payload)
          break
        case 'task':
          handleTask(payload)
          break
        case 'tool_result':
          handleToolResult(payload)
          break
        case 'decision':
        case 'progress':
          appendSystem(text)
          break
        case 'status':
          setStatus(text || 'Агент работает…')
          break
        case 'final':
        case 'work_result':
          if (text) {
            setItems((prev) => [...prev, { kind: 'result', id: nextId('res'), text }])
          }
          break
        case 'error':
          if (text) appendSystem(text, 'error')
          break
        default:
          break
      }
    },
    [appendAssistant, appendSystem, appendThinking, handleTask, handleToolCall, handleToolResult]
  )

  useEffect(() => {
    const unsubscribe = agentClient.onEvent((event: AgentEvent) => {
      const runId = event.runId
      const matchesRun =
        !activeRunRef.current || !runId || runId === activeRunRef.current
      switch (event.type) {
        case 'event':
          // Feed events are processed regardless of runId: only one run is
          // active at a time and strict gating risks silently dropping the feed.
          if (event.payload) handleRunnerEvent(event.payload)
          break
        case 'question':
          if (matchesRun) {
            setPendingQuestion((prev) => {
              const parsed = parseQuestionArgs({
                question: event.question,
                options: event.options,
                ...(event.arguments || {})
              })
              const question = parsed.question || prev?.question || ''
              const options = parsed.options.length ? parsed.options : prev?.options || []
              return {
                requestId: String(event.requestId || prev?.requestId || ''),
                question,
                options
              }
            })
            setStatus('Нужен ваш ответ')
          }
          break
        case 'hitl':
          if (matchesRun) {
            const tool = String(event.tool || '')
            setPendingHitl({
              requestId: String(event.requestId || ''),
              tool,
              title: toolLabel(tool),
              arguments: (event.arguments as Record<string, unknown>) || {}
            })
            setStatus('Требуется подтверждение действия')
          }
          break
        case 'result':
          if (matchesRun) {
            setRunning(false)
            setStatus('')
            setPendingQuestion(null)
            setPendingHitl(null)
            activeRunRef.current = null
            setActiveRunId(null)
            optionsRef.current.onResult?.({
              kind: (event.kind as AgentResult['kind']) || 'run',
              workflowId: event.workflowId,
              draftId: event.draftId,
              agentId: event.agentId,
              runRef: event.runRef,
              answer: event.answer,
              status: event.status,
              fired: event.fired
            })
          }
          break
        case 'error':
          if (matchesRun || !runId) {
            const message = String(event.message || 'Ошибка агента')
            setRunning(false)
            setStatus('')
            setError(message)
            setPendingQuestion(null)
            setPendingHitl(null)
            appendSystem(message, 'error')
            activeRunRef.current = null
            setActiveRunId(null)
            optionsRef.current.onError?.(message)
          }
          break
        case 'ready_state':
          if (!event.ok && event.message) {
            appendSystem(`Локальный Cursor SDK недоступен: ${event.message}`, 'error')
          }
          break
        case 'sidecar_exit':
          appendSystem('Процесс агента завершился. Перезапуск…', 'error')
          break
        default:
          break
      }
    })
    return unsubscribe
  }, [appendSystem, handleRunnerEvent])

  const start = useCallback((command: StartCommand): string => {
    setError('')
    setPendingQuestion(null)
    setPendingHitl(null)
    setRunning(true)
    setStatus('Агент запускается…')
    const id = agentClient.start(command)
    activeRunRef.current = id
    setActiveRunId(id)
    return id
  }, [])

  const answer = useCallback((requestId: string, value: string, _filePaths?: string[], ok = true) => {
    agentClient.answer(requestId, value, ok)
    setPendingQuestion(null)
    setStatus('Агент работает…')
  }, [])

  const respondHitl = useCallback((requestId: string, approved: boolean) => {
    agentClient.hitl(requestId, approved)
    setPendingHitl(null)
    setStatus(approved ? 'Выполняю действие…' : 'Действие отклонено')
  }, [])

  const skip = useCallback(() => {
    agentClient.skip('')
    setPendingHitl(null)
    setStatus('Пропускаю инструмент…')
  }, [])

  const cancel = useCallback(() => {
    if (activeRunRef.current) agentClient.cancel(activeRunRef.current)
    setStatus('Останавливаю…')
  }, [])

  const reset = useCallback(() => {
    setItems([])
    setStatus('')
    setError('')
    setRunning(false)
    setPendingQuestion(null)
    setPendingHitl(null)
    activeRunRef.current = null
    setActiveRunId(null)
  }, [])

  const pushUserMessage = useCallback((text: string) => {
    const value = (text || '').trim()
    if (!value) return
    setItems((prev) => [...prev, { kind: 'message', id: nextId('user'), role: 'user', text: value }])
  }, [])

  const pushSystem = useCallback((text: string) => appendSystem(text), [appendSystem])

  return {
    items,
    status,
    running,
    error,
    pendingQuestion,
    pendingHitl,
    activeRunId,
    start,
    answer,
    respondHitl,
    skip,
    cancel,
    reset,
    pushUserMessage,
    pushSystem
  }
}
