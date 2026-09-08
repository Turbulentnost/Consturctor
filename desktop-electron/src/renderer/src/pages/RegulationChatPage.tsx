import { useEffect, useRef, useState, type ReactNode } from 'react'
import { agentClient } from '../api/agent'
import { api } from '../api/client'
import { ApiError, type AgentEvent, type RegulationCreationProgress, type RegulationCreationSession, type RegulationCreationTurn } from '../api/types'
import wallpaperUrl from '../assets/chat/wallpaper.png'
import programIcon from '../assets/logo.png'
import iconAttention from '@agent-icons/agent-attention-animated.svg?raw'
import iconCompleted from '@agent-icons/agent-completed-animated.svg?raw'
import iconWorking from '@agent-icons/agent-working-animated.svg?raw'
import { fileTypeIconSrc } from '../utils/fileTypeIcon'
import {
  attachmentNamesFromContent,
  extractInterviewAnswer,
  formatRegulationMessageTime,
  hasSelectedProcessesText,
  isProcessSelectText,
  isReplacementGarbage,
  isCreationSessionReady,
  preserveReadyCreationSession,
  rewriteSelectAfterChoice,
  visibleAssistantText,
  visibleUserText
} from '../utils/regulationChat'

type AgentPhase = 'working' | 'attention' | 'completed'

interface RegulationChatPageProps {
  session: RegulationCreationSession
  onSessionChange: (session: RegulationCreationSession) => void
  onReady: (session: RegulationCreationSession) => void | Promise<void>
  onBack: () => void
  onStopped?: () => void
  onBusyChange?: (busy: boolean, kind?: BusyKind) => void
  banner?: ReactNode
  active?: boolean
}

interface PendingFile {
  path: string
  name: string
}

const DEFAULT_PLACEHOLDER = 'Опишите процесс или ответьте на вопрос ИИ...'
const EDIT_PLACEHOLDER = 'Измените предложенный вариант и отправьте...'
const FORCE_CREATE_PROMPT =
  'Создай регламент принудительно по текущей информации. ' +
  'Если каких-то данных не хватает, используй разумные типовые формулировки и явно отметь, что это предположение.'
const WORKING_STATUS = 'Готовлю вопрос...'
const DOCUMENT_STATUS = 'Формирую регламент...'
const COMPOSER_MIN_HEIGHT = 44
const COMPOSER_MAX_HEIGHT = 129

type BusyKind = 'reading' | 'question' | 'document'

function busyHeadLabel(kind: BusyKind, fileCount: number): string {
  if (kind === 'reading') {
    return fileCount > 1 ? 'Читаю документы' : 'Читаю документ'
  }
  if (kind === 'document') return 'Формирует регламент'
  return 'Готовит вопрос'
}

function busyStatusLabel(kind: BusyKind, fileCount: number): string {
  if (kind === 'reading') {
    return fileCount > 1 ? 'Читаю документы...' : 'Читаю документ...'
  }
  if (kind === 'document') return DOCUMENT_STATUS
  return WORKING_STATUS
}

function turnWritesDocument(
  turn: { writeDocument?: boolean; forceCreate?: boolean },
  session: RegulationCreationSession
): boolean {
  if (turn.writeDocument || turn.forceCreate) return true
  const progress = session.progress
  return Boolean(progress?.visible && Number(progress.remaining || 0) <= 0)
}

function fileCountLabel(count: number): string {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return 'файл'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'файла'
  return 'файлов'
}

function agentIcon(phase: AgentPhase): string {
  if (phase === 'working') return iconWorking
  if (phase === 'completed') return iconCompleted
  return iconAttention
}

function prepareAgentSvg(svg: string, prefix: string): string {
  const safe = prefix.replace(/[^a-zA-Z0-9_-]/g, '') || 'icon'
  return svg
    .replace(/\bid="([^"]+)"/g, `id="${safe}-$1"`)
    .replace(/url\(#([^)]+)\)/g, `url(#${safe}-$1)`)
    .replace(/\bhref="#([^"]+)"/g, `href="#${safe}-$1"`)
    .replace(/transform-origin:\s*[\d.]+px\s+[\d.]+px/g, 'transform-origin:center')
    .replace(/@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[\s\S]*?\n\s*\}/g, '')
    .replace('<style>', '<style>\n    * { transform-box: fill-box; }\n')
}

function AgentAvatar({
  phase,
  uid,
  frozen = false
}: {
  phase: AgentPhase
  uid: string
  frozen?: boolean
}): React.JSX.Element {
  if (frozen) {
    return (
      <div className="regchat-avatar program" aria-hidden>
        <img src={programIcon} alt="" />
      </div>
    )
  }
  return (
    <div
      className={`regchat-avatar ${phase}`}
      aria-hidden
      dangerouslySetInnerHTML={{ __html: prepareAgentSvg(agentIcon(phase), uid) }}
    />
  )
}

function quickAnswers(structured: Record<string, unknown>): string[] {
  const raw = structured.quickAnswers
  if (Array.isArray(raw)) return raw.map((x) => String(x)).filter(Boolean)
  return []
}

function InterviewProgressBar({
  progress,
  percent
}: {
  progress: RegulationCreationProgress
  percent: number
}): React.JSX.Element {
  const processTitle = progress.currentProcessTitle || progress.currentProcessId
  const processLine =
    progress.processCount > 0 && progress.currentProcessIndex > 0
      ? `Блок ${progress.currentProcessIndex} из ${progress.processCount}`
      : ''
  return (
    <div className="regchat-progress" aria-label="Прогресс интервью">
      {processTitle ? (
        <div className="regchat-progress-current">
          <span className="regchat-progress-current-label">Сейчас</span>
          <span className="regchat-progress-current-title" title={processTitle}>
            {processTitle}
          </span>
          {processLine ? <span className="regchat-progress-current-index">{processLine}</span> : null}
        </div>
      ) : null}
      <div className="regchat-progress-meta">
        <span>
          Известно {progress.answered} фактов · уточнить ещё {progress.remaining}
        </span>
        <span className="regchat-progress-hint">
          Это не число вопросов в чате: один ответ может закрыть факт или только уточнить его
        </span>
      </div>
      <div className="regchat-progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
        <div className="regchat-progress-fill" style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}

interface ProcessChoice {
  id: string
  title: string
}

function asStructuredRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function normalizeProcessId(value: string): string {
  const raw = value.trim()
  const block = raw.match(/^b-(p\d+)$/i)
  if (block) return block[1].toLowerCase()
  if (/^p\d+$/i.test(raw)) return raw.toLowerCase()
  return raw
}

function processChoices(structured: Record<string, unknown>): ProcessChoice[] {
  const out: ProcessChoice[] = []
  const seen = new Set<string>()
  const add = (raw: unknown): void => {
    const rec = asStructuredRecord(raw)
    if (!rec) return
    const id = normalizeProcessId(String(rec.processId || rec.id || ''))
    const title = String(rec.title || rec.name || id).trim()
    if (!id || seen.has(id)) return
    seen.add(id)
    out.push({ id, title })
  }
  if (Array.isArray(structured.processes)) structured.processes.forEach(add)
  const pipeline = asStructuredRecord(structured.pipeline)
  if (Array.isArray(pipeline?.blocks)) pipeline.blocks.forEach(add)
  return out
}

function isProcessSelect(structured: Record<string, unknown>, content: string): boolean {
  const pipeline = asStructuredRecord(structured.pipeline)
  const selected = pipeline?.selectedProcessIds
  if (Array.isArray(selected) && selected.length > 0) return false
  if (String(pipeline?.stage || '').toLowerCase() === 'select') return true
  const text = content.toLowerCase()
  return /отметьте нужн|отметьте процесс|выберите процесс/.test(text) && processChoices(structured).length > 0
}

function hasSelectedProcesses(messages: RegulationCreationSession['messages']): boolean {
  return messages.some((item) => item.role === 'user' && hasSelectedProcessesText(item.content || ''))
}

function selectedProcessIdsFromText(text: string): string[] {
  const match = text.match(/^\s*выбраны процессы\s*:\s*(.+)$/im)
  if (!match) return []
  const first = match[1].split(/\n/)[0]
  const seen = new Set<string>()
  const out: string[] = []
  for (const part of first.split(/[,;]/)) {
    const token = normalizeProcessId((part.trim().split(/\s+/)[0] || '').replace(/[.:;]+$/, ''))
    if (!token || seen.has(token)) continue
    seen.add(token)
    out.push(token)
  }
  return out
}

function selectedProcessIdsFromMessages(messages: RegulationCreationSession['messages']): string[] {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const item = messages[i]
    if (item.role !== 'user') continue
    const ids = selectedProcessIdsFromText(item.content || '')
    if (ids.length) return ids
  }
  return []
}

function lastUserIsProcessSelection(messages: RegulationCreationSession['messages']): boolean {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const item = messages[i]
    if (item.role !== 'user') continue
    return hasSelectedProcessesText(item.content || '')
  }
  return false
}

function askAfterSelectPrompt(ids: string[]): string {
  const listed = ids.length ? ids.join(', ') : 'уже выбранные'
  return (
    `Процессы уже выбраны: ${listed}. Этап выбора закрыт: не проси отметить процессы снова ` +
    `и не повторяй список. Переходи к вопросам по каждому выбранному процессу: по одному за ход, ` +
    `только факт, которого нет в тексте документа.`
  )
}

function selectedProcessesMessage(choices: ProcessChoice[]): string {
  const ids = choices.map((item) => item.id).join(', ')
  const lines = choices.map((item) => `- ${item.id}: ${item.title}`)
  return `Выбраны процессы: ${ids}\n${lines.join('\n')}`
}

function safeDownloadName(name: string): string {
  const cleaned = name.replace(/[<>:"/\\|?*]+/g, ' ').replace(/\s+/g, ' ').trim()
  return (cleaned || 'Регламент.docx').slice(0, 120)
}

function resultFileName(session: RegulationCreationSession): string {
  const fromPath = session.resultDocumentPath.split(/[\\/]/).pop() || ''
  if (fromPath) return safeDownloadName(fromPath)
  const title = String(session.resultDocument?.title || '').trim()
  if (title) return safeDownloadName(`${title}.docx`)
  return 'Регламент.docx'
}

function attachmentsOf(structured: Record<string, unknown>): string[] {
  const raw = structured.attachments
  if (!Array.isArray(raw)) return []
  return raw
    .map((item) => {
      if (typeof item === 'string') return item
      if (item && typeof item === 'object') {
        const rec = item as Record<string, unknown>
        return String(rec.name || rec.shortName || '')
      }
      return ''
    })
    .filter(Boolean)
}

class RegulationCancelledError extends Error {
  constructor() {
    super('cancelled')
    this.name = 'RegulationCancelledError'
  }
}

function isRegulationCancelled(err: unknown): boolean {
  if (err instanceof RegulationCancelledError) return true
  if (err instanceof Error && err.name === 'RegulationCancelledError') return true
  return false
}

function waitForRegulationSdk(
  runId: string,
  onEvent: (type: string, text: string) => void,
  signal?: AbortSignal
): Promise<{ answer: string; agentId: string }> {
  return new Promise((resolve, reject) => {
    const finish = (action: () => void): void => {
      off()
      signal?.removeEventListener('abort', onAbort)
      action()
    }
    const onAbort = (): void => {
      finish(() => reject(new RegulationCancelledError()))
    }
    if (signal?.aborted) {
      reject(new RegulationCancelledError())
      return
    }
    const off = agentClient.onEvent((event: AgentEvent) => {
      if (event.runId && event.runId !== runId) return
      if (event.type === 'event' && event.payload) {
        const payload = event.payload
        const text = String(payload.text || payload.message || '')
        const kind = String(payload.type || '')
        if (text) onEvent(kind, text)
      }
      if (event.type === 'result') {
        if (signal?.aborted) {
          finish(() => reject(new RegulationCancelledError()))
          return
        }
        finish(() =>
          resolve({
            answer: String(event.answer || ''),
            agentId: String(event.agentId || '')
          })
        )
        return
      }
      if (event.type === 'error') {
        if (signal?.aborted || String(event.code || '') === 'cancelled') {
          finish(() => reject(new RegulationCancelledError()))
          return
        }
        const recovered = extractInterviewAnswer(event.message || '')
        if (recovered) {
          finish(() => resolve({ answer: recovered, agentId: '' }))
          return
        }
        finish(() => reject(new Error(event.message || 'Ошибка локального агента')))
      }
    })
    signal?.addEventListener('abort', onAbort)
  })
}

function extractProposal(message: string): string {
  const text = (message || '').trim()
  if (!text) return ''
  const match = text.match(
    /Предлагаю\s+так\s*:\s*([\s\S]*?)(?:\n\s*\n\s*Оставить это или переделать\s*\??\s*$|$)/i
  )
  if (match) return match[1].replace(/\s+/g, ' ').trim()
  const parts = text
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean)
  if (parts.length >= 2) {
    for (const part of parts.slice(1)) {
      const lower = part.toLowerCase()
      if (lower.startsWith('оставить это или переделать')) continue
      if (lower.startsWith('вопрос')) continue
      const cleaned = part.replace(/^Предлагаю\s+так\s*:\s*/i, '').trim()
      if (cleaned) return cleaned.replace(/\s+/g, ' ').trim()
    }
  }
  return ''
}

export function RegulationChatPage({
  session,
  onSessionChange,
  onReady,
  onBack,
  onStopped,
  onBusyChange,
  banner,
  active = true
}: RegulationChatPageProps): React.JSX.Element {
  const [input, setInput] = useState('')
  const [placeholder, setPlaceholder] = useState(DEFAULT_PLACEHOLDER)
  const [busy, setBusy] = useState(false)
  const [busyKind, setBusyKind] = useState<BusyKind>('question')
  const [readingFileCount, setReadingFileCount] = useState(0)
  const [error, setError] = useState('')
  const [savedNote, setSavedNote] = useState('')
  const [attachments, setAttachments] = useState<PendingFile[]>([])
  const [filesOpen, setFilesOpen] = useState(false)
  const [pickedProcessIds, setPickedProcessIds] = useState<string[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)
  const pinnedRef = useRef(true)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const resumeKeyRef = useRef('')
  const askAfterSelectRef = useRef('')
  const runIdRef = useRef('')
  const abortRef = useRef<AbortController | null>(null)
  const stoppedRef = useRef(false)
  const sessionRef = useRef(session)
  sessionRef.current = session

  function pushSession(next: RegulationCreationSession): void {
    onSessionChange(preserveReadyCreationSession(sessionRef.current, next))
  }

  useEffect(() => {
    setError('')
    setSavedNote('')
    setAttachments([])
    setFilesOpen(false)
    setInput('')
    setPlaceholder(DEFAULT_PLACEHOLDER)
    setBusyKind('question')
    setReadingFileCount(0)
    setPickedProcessIds([])
    stoppedRef.current = false
    abortRef.current = null
    runIdRef.current = ''
    askAfterSelectRef.current = ''
  }, [session.draftId])

  useEffect(() => {
    onBusyChange?.(busy, busyKind)
  }, [busy, busyKind, onBusyChange])

  useEffect(() => {
    if (!pinnedRef.current) return
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [session.messages.length, busy])

  useEffect(() => {
    const node = textareaRef.current
    if (!node) return
    node.style.height = '0px'
    node.style.overflowY = 'hidden'
    const content = node.scrollHeight
    node.style.height = `${Math.min(Math.max(content, COMPOSER_MIN_HEIGHT), COMPOSER_MAX_HEIGHT)}px`
    node.style.overflowY = content > COMPOSER_MAX_HEIGHT ? 'auto' : 'hidden'
  }, [input])

  useEffect(() => {
    if (!active || busy || isCreationSessionReady(session)) return
    let cancelled = false
    void api
      .getRegulationCreationSession(session.draftId)
      .then((latest) => {
        if (cancelled || !isCreationSessionReady(latest)) return
        pushSession(latest)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [active, busy, session.draftId, session.status, session.resultDocumentPath])

  const ready = isCreationSessionReady(session)
  const hasUserMessage = session.messages.some((m) => m.role === 'user')
  const resultName = resultFileName(session)
  const phase: AgentPhase = ready ? 'completed' : busy ? 'working' : 'attention'
  const progress = session.progress
  const showProgress = Boolean(progress?.visible) && !ready
  const progressPercent =
    showProgress && progress && progress.total > 0
      ? Math.min(100, Math.round((progress.answered / progress.total) * 100))
      : 0

  async function downloadResult(): Promise<void> {
    if (!ready) return
    setError('')
    setSavedNote('')
    try {
      const res = await window.api.download({
        url: `/api/v1/regulation-creation/sessions/${session.draftId}/document`,
        defaultName: resultName,
        token: api.getToken()
      })
      if (res.canceled) return
      if (!res.ok) {
        setError(res.error || 'Не удалось скачать файл регламента')
        return
      }
      setSavedNote(res.path ? `Файл сохранён: ${res.path}` : 'Файл сохранён')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось скачать файл регламента')
    }
  }

  async function continueReady(): Promise<void> {
    setError('')
    try {
      await onReady(session)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Не удалось открыть регламент')
    }
  }

  function onScroll(): void {
    const el = scrollRef.current
    if (!el) return
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight
    pinnedRef.current = distance < 80
  }

  async function stopGeneration(): Promise<void> {
    if (!busy) return
    stoppedRef.current = true
    abortRef.current?.abort()
    if (runIdRef.current) {
      agentClient.cancel(runIdRef.current)
      runIdRef.current = ''
    }
    setBusy(false)
    setError('')
    await api.terminateRegulationCreationSessions()
    onStopped?.()
  }

  async function send(text: string, files: PendingFile[]): Promise<void> {
    const message = text.trim()
    if ((!message && files.length === 0) || busy) return
    stoppedRef.current = false
    setInput('')
    setPlaceholder(DEFAULT_PLACEHOLDER)
    setError('')
    setBusy(true)
    const forceCreate = message === FORCE_CREATE_PROMPT
    const progressClosed = Boolean(session.progress?.visible && Number(session.progress.remaining || 0) <= 0)
    setBusyKind(
      files.length > 0 ? 'reading' : forceCreate || progressClosed ? 'document' : 'question'
    )
    setReadingFileCount(files.length)
    pinnedRef.current = true
    const optimistic: RegulationCreationSession = {
      ...session,
      status: 'generating',
      messages: [
        ...session.messages,
        {
          messageId: 'local-pending',
          draftId: session.draftId,
          role: 'user',
          content: message,
          structured: files.length ? { attachments: files.map((f) => ({ name: f.name })) } : {},
          createdAt: new Date().toISOString()
        }
      ]
    }
    pushSession(optimistic)
    let persisted = false
    try {
      const filePaths = files.map((f) => f.path)
      const onStreamEvent = (type: string, text: string): void => {
        if (type === 'error' && text) setError(text)
        if ((type === 'status' && text && text !== 'reading') || (type === 'assistant' && text)) {
          setBusyKind((prev) => (prev === 'document' || prev === 'reading' ? prev : 'question'))
        }
      }
      if (typeof window.agent.start === 'function') {
        let turn: RegulationCreationTurn
        try {
          turn = await api.persistRegulationCreationTurn(session.draftId, message, filePaths)
        } catch (err) {
          if (!(err instanceof ApiError) || (err.status !== 404 && err.status !== 405)) {
            throw err
          }
          const updated = await api.streamRegulationCreationMessage(
            session.draftId,
            message,
            filePaths,
            (event) => onStreamEvent(event.type, event.text || event.message || '')
          )
          persisted = true
          if (stoppedRef.current) throw new RegulationCancelledError()
          setAttachments([])
          setFilesOpen(false)
          pushSession(updated)
          return
        }
        persisted = true
        if (stoppedRef.current) throw new RegulationCancelledError()
        setAttachments([])
        setFilesOpen(false)
        pushSession(turn.session)
        if (isCreationSessionReady(turn.session)) return
        const writing = turnWritesDocument(turn, turn.session)
        setBusyKind(writing ? 'document' : 'question')
        await runSdkAndApply(turn)
      } else {
        const updated = await api.streamRegulationCreationMessage(
          session.draftId,
          message,
          filePaths,
          (event) => onStreamEvent(event.type, event.text || event.message || '')
        )
        persisted = true
        if (stoppedRef.current) throw new RegulationCancelledError()
        setAttachments([])
        setFilesOpen(false)
        pushSession(updated)
      }
    } catch (err) {
      if (isRegulationCancelled(err) || stoppedRef.current) {
        return
      }
      setError(err instanceof ApiError ? err.message : 'Ошибка отправки сообщения')
      setInput(text)
      setAttachments(files)
      setFilesOpen(files.length > 0)
      let next: RegulationCreationSession = { ...optimistic, status: 'idle' }
      if (persisted) {
        try {
          const latest = await api.getRegulationCreationSession(session.draftId)
          const hasUser = latest.messages.some((item) => item.role === 'user')
          next = hasUser ? latest : { ...latest, messages: optimistic.messages, status: 'idle' }
        } catch {
          /* keep the optimistic session with the user text and files */
        }
      }
      pushSession(next)
    } finally {
      setBusy(false)
    }
  }

  function handleQuick(answer: string, sourceText: string): void {
    if (/^передел/i.test(answer.trim())) {
      const proposal = extractProposal(sourceText)
      setInput(proposal)
      setPlaceholder(EDIT_PLACEHOLDER)
      requestAnimationFrame(() => {
        const el = textareaRef.current
        if (el) {
          el.focus()
          el.setSelectionRange(el.value.length, el.value.length)
        }
      })
      return
    }
    void send(answer, [])
  }

  function toggleProcess(id: string): void {
    setPickedProcessIds((prev) => (prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]))
  }

  function confirmProcesses(choices: ProcessChoice[]): void {
    const picked = choices.filter((item) => pickedProcessIds.includes(item.id))
    if (picked.length === 0 || busy) return
    void send(selectedProcessesMessage(picked), [])
  }

  async function pickFiles(): Promise<void> {
    if (busy) return
    const paths = await window.api.openFile({
      title: 'Выберите файлы для регламента',
      filters: [{ name: 'Документы', extensions: ['docx', 'pdf', 'md', 'txt'] }],
      properties: ['openFile', 'multiSelections']
    })
    if (!paths.length) return
    setAttachments((prev) => {
      const seen = new Set(prev.map((f) => f.path))
      const next = [...prev]
      for (const p of paths) {
        if (seen.has(p)) continue
        next.push({ path: p, name: p.split(/[\\/]/).pop() || p })
      }
      return next
    })
    setFilesOpen(true)
  }

  function removeAttachment(path: string): void {
    setAttachments((prev) => {
      const next = prev.filter((f) => f.path !== path)
      if (next.length === 0) setFilesOpen(false)
      return next
    })
  }

  const visible = session.messages.filter((m) => m.role === 'assistant' || m.role === 'user')
  const lastAssistantId = [...visible].reverse().find((item) => item.role === 'assistant')?.messageId || ''
  const lastVisible = visible[visible.length - 1]

  useEffect(() => {
    setPickedProcessIds([])
  }, [lastAssistantId])
  const pendingUserId =
    lastVisible?.role === 'user' && lastVisible.messageId !== 'local-pending'
      ? lastVisible.messageId
      : ''

  async function runSdkAndApply(turn: RegulationCreationTurn): Promise<void> {
    if (stoppedRef.current) throw new RegulationCancelledError()
    const abort = new AbortController()
    abortRef.current = abort
    const selectedIds = selectedProcessIdsFromMessages(session.messages)
    const afterSelect = selectedIds.length ? askAfterSelectPrompt(selectedIds) : ''
    const interview = afterSelect
      ? { ...turn.interview, selectedProcessIds: selectedIds }
      : turn.interview
    const writing = turnWritesDocument(turn, session)
    if (writing) setBusyKind('document')
    const runId = agentClient.start({
      kind: 'regulation_creation',
      draftId: session.draftId,
      prompt: afterSelect ? `${turn.sdkPrompt}\n\n${afterSelect}` : turn.sdkPrompt,
      rules: afterSelect ? `${turn.sdkRules}\n${afterSelect}` : turn.sdkRules,
      interview,
      resumeAgentId: turn.sdkAgentId || session.sdkAgentId,
      writeDocument: turn.writeDocument || turn.forceCreate || writing,
      useTools: turn.useTools || turn.writeDocument || turn.forceCreate || writing,
      forceCreate: turn.forceCreate
    })
    runIdRef.current = runId
    try {
      const sdk = await waitForRegulationSdk(
        runId,
        (type, text) => {
          if (type === 'error' && text) setError(text)
          if (type === 'assistant' && text) {
            setBusyKind((prev) => (prev === 'document' || writing ? 'document' : 'question'))
          }
        },
        abort.signal
      )
      if (abort.signal.aborted || stoppedRef.current) {
        throw new RegulationCancelledError()
      }
      const answer = rewriteSelectAfterChoice(
        extractInterviewAnswer(sdk.answer) || sdk.answer,
        selectedIds
      )
      const visibleText = visibleAssistantText(answer) || answer
      if (!answer || isReplacementGarbage(visibleText)) {
        throw new Error('Агент вернул нечитаемый ответ. Попробуйте ещё раз.')
      }
      const updated = await api.applyRegulationCreationReply(session.draftId, answer, {
        sdkAgentId: sdk.agentId || turn.sdkAgentId,
        forceCreate: turn.forceCreate
      })
      if (abort.signal.aborted || stoppedRef.current) {
        throw new RegulationCancelledError()
      }
      pushSession(updated)
      if (!isCreationSessionReady(updated)) return
      try {
        const latest = await api.getRegulationCreationSession(session.draftId)
        pushSession(latest)
      } catch {
        /* keep apply payload */
      }
    } finally {
      if (abortRef.current === abort) abortRef.current = null
      if (runIdRef.current === runId) runIdRef.current = ''
    }
  }

  async function continuePendingTurn(): Promise<void> {
    if (busy || ready || stoppedRef.current) return
    setError('')
    setBusy(true)
    setBusyKind(
      session.progress?.visible && Number(session.progress.remaining || 0) <= 0
        ? 'document'
        : 'question'
    )
    pinnedRef.current = true
    try {
      const turn = await api.peekRegulationCreationTurn(session.draftId)
      if (stoppedRef.current) throw new RegulationCancelledError()
      pushSession(turn.session)
      if (isCreationSessionReady(turn.session)) return
      if (turnWritesDocument(turn, turn.session)) setBusyKind('document')
      await runSdkAndApply(turn)
    } catch (err) {
      if (isRegulationCancelled(err) || stoppedRef.current) return
      setError(err instanceof ApiError ? err.message : 'Не удалось получить вопрос ИИ')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (busy || ready || stoppedRef.current || !pendingUserId || !window.agent?.start) return
    const key = `${session.draftId}:${pendingUserId}`
    if (resumeKeyRef.current === key) return
    resumeKeyRef.current = key
    void continuePendingTurn()
  }, [session.draftId, pendingUserId, busy, ready])

  useEffect(() => {
    if (!active || busy || ready || stoppedRef.current || !window.agent?.start) return
    if (!lastUserIsProcessSelection(session.messages)) return
    const lastAssistant = [...session.messages].reverse().find((item) => item.role === 'assistant')
    if (!lastAssistant || !isProcessSelectText(lastAssistant.content || '')) return
    const key = `${session.draftId}:ask-after-select:${lastAssistant.messageId}`
    if (askAfterSelectRef.current === key) return
    askAfterSelectRef.current = key
    const ids = selectedProcessIdsFromMessages(session.messages)
    void send(askAfterSelectPrompt(ids), [])
  }, [session.draftId, session.messages, busy, ready])

  return (
    <div className="regchat-page">
      <div className="regchat-head">
        <div className="regchat-head-top">
          <button className="btn-ghost" onClick={onBack}>
            {'\u2039'} Назад
          </button>
          <h1 className="page-title" style={{ fontSize: 24 }}>
            Создание регламента
          </h1>
          <button
            className="regchat-force"
            onClick={() => void send(FORCE_CREATE_PROMPT, [])}
            disabled={!hasUserMessage || busy}
          >
            Создать принудительно
          </button>
        </div>
        <div className="regchat-subtitle">
          Ответьте на вопросы, и ИИ подготовит регламент в стиле ваших документов
        </div>
        {showProgress && progress ? <InterviewProgressBar progress={progress} percent={progressPercent} /> : null}
      </div>
      {banner ? <div className="regchat-banner">{banner}</div> : null}

      <div className="regchat-stage">
        <div
          className="regchat-page-bg"
          style={{ backgroundImage: `url(${wallpaperUrl})` }}
          aria-hidden
        />
        <div className="regchat-feed-wrap">
            <div className="regchat-scroll" ref={scrollRef} onScroll={onScroll}>
              <div className="regchat-column">
              {visible.length === 0 && !busy && (
                <div className="regchat-hint">
                  ИИ задаст несколько вопросов, чтобы собрать регламент. Опишите процесс, который нужно
                  автоматизировать, или приложите файлы.
                </div>
              )}
              {visible.map((m, index) => {
                const isUser = m.role === 'user'
                const structuredNames = attachmentsOf(m.structured)
                const names = structuredNames.length
                  ? structuredNames
                  : isUser
                    ? attachmentNamesFromContent(m.content)
                    : []
                const text = isUser ? visibleUserText(m.content) : visibleAssistantText(m.content)
                const timeLabel = formatRegulationMessageTime(m.createdAt)
                const quicks = quickAnswers(m.structured)
                const processes = processChoices(m.structured)
                const showProcessPicker =
                  !isUser &&
                  !busy &&
                  !ready &&
                  m.messageId === lastAssistantId &&
                  !hasSelectedProcesses(session.messages) &&
                  isProcessSelect(m.structured, m.content) &&
                  processes.length > 0
                const isCurrentStage =
                  !isUser &&
                  !busy &&
                  !ready &&
                  Boolean(lastAssistantId) &&
                  m.messageId === lastAssistantId
                const blockLabel =
                  isCurrentStage && showProgress && progress
                    ? [
                        progress.processCount > 0 && progress.currentProcessIndex > 0
                          ? `Блок ${progress.currentProcessIndex} из ${progress.processCount}`
                          : '',
                        progress.currentProcessTitle || progress.currentProcessId
                      ]
                        .filter(Boolean)
                        .join(' · ')
                    : ''
                return (
                  <div key={m.messageId || index} className={isUser ? 'regchat-row user' : 'regchat-row ai'}>
                    {!isUser && (
                      <AgentAvatar
                        phase={phase}
                        uid={`msg-${m.messageId || index}`}
                        frozen={!isCurrentStage}
                      />
                    )}
                    <div className="regchat-bubble-col">
                      <div className={isUser ? 'regchat-bubble user' : 'regchat-bubble ai'}>
                        {blockLabel ? <div className="regchat-block-tag">{blockLabel}</div> : null}
                        {text ? <div className="regchat-bubble-text">{text}</div> : null}
                        {names.length > 0 && (
                          <div className="regchat-attach-list">
                            {names.map((n, i) => (
                              <span key={i} className="regchat-file-row">
                                <img className="regchat-file-icon" src={fileTypeIconSrc(n)} alt="" />
                                <span className="regchat-file-name" title={n}>
                                  {n}
                                </span>
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                      {timeLabel ? (
                        <div className={isUser ? 'regchat-time user' : 'regchat-time'}>{timeLabel}</div>
                      ) : null}
                      {!isUser && isCurrentStage && !showProcessPicker && quicks.length > 0 && (
                        <div className="regchat-quick-row">
                          {quicks.map((qa) => (
                            <button
                              key={qa}
                              className="regchat-quick-chip"
                              onClick={() => handleQuick(qa, m.content)}
                            >
                              {qa}
                            </button>
                          ))}
                        </div>
                      )}
                      {showProcessPicker && (
                        <div className="regchat-process-picker">
                          <div className="regchat-process-picker-head">
                            <span>Отметьте процессы для регламента</span>
                            <button
                              type="button"
                              className="regchat-process-link"
                              onClick={() =>
                                setPickedProcessIds(
                                  pickedProcessIds.length === processes.length
                                    ? []
                                    : processes.map((item) => item.id)
                                )
                              }
                            >
                              {pickedProcessIds.length === processes.length ? 'Снять все' : 'Выбрать все'}
                            </button>
                          </div>
                          <div className="regchat-process-list">
                            {processes.map((item) => {
                              const checked = pickedProcessIds.includes(item.id)
                              return (
                                <label key={item.id} className={checked ? 'regchat-process-item is-on' : 'regchat-process-item'}>
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => toggleProcess(item.id)}
                                  />
                                  <span>{item.title}</span>
                                </label>
                              )
                            })}
                          </div>
                          <button
                            type="button"
                            className="regchat-process-submit"
                            disabled={pickedProcessIds.length === 0}
                            onClick={() => confirmProcesses(processes)}
                          >
                            Продолжить
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
              {busy && (
                <div className="regchat-row ai">
                  <AgentAvatar phase="working" uid="working" />
                  <div className="regchat-bubble-col">
                    <div className="regchat-think">
                      <div className="regchat-think-head">
                        <span>{busyHeadLabel(busyKind, readingFileCount)}</span>
                      </div>
                    </div>
                    <div className="regchat-status">{busyStatusLabel(busyKind, readingFileCount)}</div>
                  </div>
                </div>
              )}
              {ready && (
                <div className="regchat-row ai">
                  <AgentAvatar phase="completed" uid="completed" />
                  <div className="regchat-bubble-col">
                    <div className="regchat-doc-card">
                      <div className="regchat-file-row">
                        <img className="regchat-file-icon" src={fileTypeIconSrc(resultName)} alt="" />
                        <span className="regchat-file-name" title={resultName}>
                          {resultName}
                        </span>
                      </div>
                      <button
                        type="button"
                        className="regchat-doc-download"
                        onClick={() => void downloadResult()}
                      >
                        Скачать
                      </button>
                    </div>
                  </div>
                </div>
              )}
              </div>
            </div>
          </div>

          {error && (
            <div className="status-line" style={{ color: 'var(--error)' }}>
              {error}
            </div>
          )}
          {savedNote && !error && (
            <div className="status-line">{savedNote}</div>
          )}

          {ready && (
            <div className="chat-ready">
              <div>Регламент готов. Файл можно скачать в чате или перейти к проверке.</div>
              <button
                className="btn-primary"
                style={{ maxWidth: 260 }}
                onClick={() => void continueReady()}
              >
                Продолжить
              </button>
            </div>
          )}

          {!ready && (
            <div className="regchat-composer">
              <div className="regchat-composer-box">
                {attachments.length > 0 && (
                  <div className="regchat-files">
                    <button
                      type="button"
                      className="regchat-files-toggle"
                      onClick={() => setFilesOpen((open) => !open)}
                    >
                      <span>{filesOpen ? '\u25BE' : '\u25B8'}</span>
                      <span>
                        {attachments.length} {fileCountLabel(attachments.length)}
                      </span>
                    </button>
                    {filesOpen ? (
                      <div className="regchat-pending">
                        {attachments.map((f) => (
                          <span key={f.path} className="regchat-file-row pending">
                            <img className="regchat-file-icon" src={fileTypeIconSrc(f.name)} alt="" />
                            <span className="regchat-file-name" title={f.name}>
                              {f.name}
                            </span>
                            <button
                              className="regchat-pending-remove"
                              onClick={() => removeAttachment(f.path)}
                              disabled={busy}
                              aria-label="Убрать файл"
                            >
                              {'\u00D7'}
                            </button>
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                )}
            <div className="regchat-composer-input">
              <textarea
                ref={textareaRef}
                value={input}
                placeholder={placeholder}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    void send(input, attachments)
                  }
                }}
                disabled={busy}
                rows={1}
              />
              <div className="regchat-composer-tools">
                <button
                  className="regchat-tool-btn"
                  onClick={() => void pickFiles()}
                  disabled={busy}
                  title="Приложить файлы"
                  aria-label="Приложить файлы"
                  type="button"
                >
                  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden>
                    <path
                      d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
                {busy ? (
                  <button
                    className="regchat-send-btn stop"
                    onClick={() => void stopGeneration()}
                    title="Остановить"
                    aria-label="Остановить"
                    type="button"
                  >
                    <span className="regchat-stop-icon" />
                  </button>
                ) : (
                  <button
                    className="regchat-send-btn"
                    onClick={() => void send(input, attachments)}
                    disabled={!input.trim() && attachments.length === 0}
                    title="Отправить"
                    aria-label="Отправить"
                    type="button"
                  >
                    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden>
                      <path d="M12 19V5M5 12l7-7 7 7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                )}
              </div>
            </div>
              </div>
            </div>
          )}
      </div>
    </div>
  )
}
