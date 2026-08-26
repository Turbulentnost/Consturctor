import { useCallback, useEffect, useRef, useState } from 'react'
import { agentClient, type StartCommand } from '../../api/agent'
import type { AgentEvent, AgentRunnerEvent } from '../../api/types'
import { toolLabel } from './labels'
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

function cleanThinking(text: string): string {
  const value = (text || '').trim()
  if (value && (value.startsWith('{') || value.toLowerCase().includes('traceback'))) {
    return 'Агент анализирует задачу…'
  }
  return value || 'Агент анализирует задачу…'
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
    const clean = cleanThinking(text)
    setItems((prev) => {
      const last = prev[prev.length - 1]
      if (last && last.kind === 'thinking') {
        const merged = [...prev]
        const prevText = last.text === 'Агент анализирует задачу…' ? '' : last.text
        merged[merged.length - 1] = { ...last, text: (prevText + clean).trim() || clean }
        return merged
      }
      return [...prev, { kind: 'thinking', id: nextId('think'), text: clean }]
    })
  }, [])

  const appendAssistant = useCallback((text: string) => {
    const clean = visibleAssistant(text)
    if (!clean) return
    setItems((prev) => {
      const last = prev[prev.length - 1]
      if (last && last.kind === 'message' && last.role === 'agent') {
        const merged = [...prev]
        merged[merged.length - 1] = { ...last, text: `${last.text}${clean}` }
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

  const addToolCall = useCallback((payload: AgentRunnerEvent) => {
    const tool = String(payload.tool || '')
    const item: ToolItem = {
      kind: 'tool',
      id: nextId('tool'),
      tool,
      title: toolLabel(tool),
      arguments: (payload.arguments as Record<string, unknown>) || {},
      result: null,
      summary: '',
      done: false
    }
    setItems((prev) => [...prev, item])
  }, [])

  const completeToolResult = useCallback((payload: AgentRunnerEvent) => {
    const tool = String(payload.tool || '')
    const result = (payload.result as Record<string, unknown>) || {}
    setItems((prev) => {
      const merged = [...prev]
      for (let i = merged.length - 1; i >= 0; i -= 1) {
        const candidate = merged[i]
        if (candidate.kind === 'tool' && !candidate.done && (!tool || candidate.tool === tool)) {
          merged[i] = {
            ...candidate,
            result,
            summary: summarizeResult(result),
            done: true
          }
          return merged
        }
      }
      merged.push({
        kind: 'tool',
        id: nextId('tool'),
        tool,
        title: toolLabel(tool),
        arguments: {},
        result,
        summary: summarizeResult(result),
        done: true
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
          break
        case 'assistant':
        case 'agent_message':
          appendAssistant(text)
          break
        case 'tool_call':
          addToolCall(payload)
          break
        case 'tool_result':
          completeToolResult(payload)
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
          if (text) appendSystem(text, 'success')
          break
        case 'error':
          if (text) appendSystem(text, 'error')
          break
        default:
          break
      }
    },
    [appendAssistant, appendSystem, appendThinking, addToolCall, completeToolResult]
  )

  useEffect(() => {
    const unsubscribe = agentClient.onEvent((event: AgentEvent) => {
      const runId = event.runId
      const matchesRun =
        !activeRunRef.current || !runId || runId === activeRunRef.current
      switch (event.type) {
        case 'event':
          if (matchesRun && event.payload) handleRunnerEvent(event.payload)
          break
        case 'question':
          if (matchesRun) {
            setPendingQuestion({
              requestId: String(event.requestId || ''),
              question: String(event.question || ''),
              options: Array.isArray(event.options) ? event.options.map(String) : []
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
