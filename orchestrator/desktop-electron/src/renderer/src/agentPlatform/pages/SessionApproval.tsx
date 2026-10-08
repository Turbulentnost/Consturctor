import { useEffect, useRef, useState } from 'react'
import { apiPost } from '../api/client'
import type { AgentApproval, ApprovalKind, SessionEvent } from '../api/types'
import { BanIcon, CheckIcon, ClockIcon, FileIcon, PlugIcon, StopIcon, TerminalIcon, TrashIcon } from '../components/Icons'

const HEADLINE: Record<ApprovalKind, string> = {
  shell: 'Агент хочет выполнить команду',
  write: 'Агент хочет записать файл',
  delete: 'Агент хочет удалить файл',
  mcp: 'Агент хочет вызвать инструмент'
}

function KindIcon({ kind, size }: { kind: string; size: number }): React.JSX.Element {
  if (kind === 'shell') return <TerminalIcon size={size} />
  if (kind === 'delete') return <TrashIcon size={size} />
  if (kind === 'mcp') return <PlugIcon size={size} />
  return <FileIcon size={size} />
}

interface ApprovalFormProps {
  sessionId: string
  approval: AgentApproval
  onDecided: () => void
  onStop: () => void
}

// Запрос разрешения вместо поля ввода: хук агента стоит, пока человек не решит.
export function ApprovalForm({ sessionId, approval, onDecided, onStop }: ApprovalFormProps): React.JSX.Element {
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const allowRef = useRef<HTMLButtonElement>(null)

  async function decide(allow: boolean, remember = false): Promise<void> {
    if (sending) return
    setSending(true)
    setError('')
    try {
      await apiPost(
        `/api/v1/platform/sessions/${encodeURIComponent(sessionId)}/approvals/${encodeURIComponent(approval.id)}/decision`,
        { allow, remember }
      )
      onDecided()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось отправить решение')
      setSending(false)
    }
  }

  const decideRef = useRef(decide)
  decideRef.current = decide

  useEffect(() => {
    allowRef.current?.focus({ preventScroll: true })
    const onKey = (event: globalThis.KeyboardEvent): void => {
      const target = event.target as HTMLElement | null
      if (target?.closest('input, textarea, [contenteditable="true"]')) return
      if (event.key === 'Escape') {
        event.preventDefault()
        void decideRef.current(false)
      } else if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        if (target instanceof HTMLButtonElement) target.click()
        else void decideRef.current(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const isShell = approval.kind === 'shell'
  const isFile = approval.kind === 'write' || approval.kind === 'delete'

  return (
    <div className="sess-approval" role="alertdialog" aria-label={HEADLINE[approval.kind]}>
      <div className="sess-approval-head">
        <KindIcon kind={approval.kind} size={15} />
        <span className="sess-approval-title">{HEADLINE[approval.kind] ?? approval.title}</span>
        <span className="sess-question-wait">ждёт разрешения</span>
      </div>
      {isShell ? (
        <pre className="sess-approval-code">
          <span className="sess-approval-prompt">$ </span>
          {approval.subject}
        </pre>
      ) : (
        <div className="sess-approval-subject" title={approval.subject}>
          {isFile ? approval.subject : approval.title.replace(/^Вызвать инструмент /, '')}
        </div>
      )}
      {approval.preview && !isShell ? (
        <details className="sess-approval-preview" open={approval.kind === 'write'}>
          <summary>{approval.kind === 'mcp' ? 'Аргументы' : 'Содержимое'}</summary>
          <pre>{approval.preview}</pre>
        </details>
      ) : null}
      <div className="sess-approval-actions">
        {error ? <span className="sess-question-error">{error}</span> : null}
        {approval.remember_label ? (
          <button
            type="button"
            className="sess-approval-remember"
            disabled={sending}
            onClick={() => void decide(true, true)}
          >
            {approval.remember_label}
          </button>
        ) : null}
        <button type="button" className="send sess-stop" title="Остановить агента" aria-label="Остановить агента" onClick={onStop}>
          <StopIcon size={16} />
        </button>
        <button type="button" className="sess-approval-deny" disabled={sending} onClick={() => void decide(false)}>
          Отклонить
          <kbd>Esc</kbd>
        </button>
        <button
          ref={allowRef}
          type="button"
          className="sess-approval-allow"
          disabled={sending}
          onClick={() => void decide(true)}
        >
          Разрешить
          <kbd>⏎</kbd>
        </button>
      </div>
    </div>
  )
}

const OUTCOME: Record<string, string> = {
  waiting: 'Ждёт разрешения',
  allowed: 'Разрешено',
  denied: 'Отклонено',
  expired: 'Без ответа — отклонено',
  cancelled: 'Отменено'
}

// Аргументы, по которым видно, что именно делает вызов: команда, код, файл, запрос.
const MAIN_ARGS = ['command', 'inline_code', 'code', 'sql', 'query', 'filename', 'path', 'url', 'search']

/** Главный аргумент вызова MCP одной строкой — чтобы без раскрытия было видно, что разрешили. */
function mainArgument(preview: string): string {
  let args: unknown
  try {
    args = JSON.parse(preview)
  } catch {
    return ''
  }
  if (!args || typeof args !== 'object') return ''
  const record = args as Record<string, unknown>
  const key = MAIN_ARGS.find((name) => typeof record[name] === 'string' && record[name])
  const value = key ? String(record[key]) : Object.values(record).find((item) => typeof item === 'string' && item)
  if (typeof value !== 'string') return ''
  return value.split('\n').map((line) => line.trim()).find(Boolean) ?? ''
}

/** Решение по разрешению в ленте: одна строка, как в истории Cursor; аргументы — по раскрытию. */
export function ApprovalLine({ event }: { event: SessionEvent }): React.JSX.Element {
  const outcome = event.status || 'waiting'
  const Mark = outcome === 'allowed' ? CheckIcon : outcome === 'waiting' ? ClockIcon : BanIcon
  const isShell = event.name === 'shell'
  const tool = event.text.replace(/^Вызвать инструмент /, '')
  const hint = event.name === 'mcp' ? mainArgument(event.result) : ''
  const details = isShell ? '' : event.result
  const line = (
    <>
      <span className="sess-approval-mark">
        <Mark size={12} />
      </span>
      <KindIcon kind={event.name} size={13} />
      <span className="sess-approval-line-text">
        <span className="sess-approval-outcome">{OUTCOME[outcome] ?? outcome}</span>
        {isShell ? (
          <code title={event.args}>{event.args}</code>
        ) : (
          <span className="sess-approval-tool" title={event.args}>
            {tool}
          </span>
        )}
        {hint ? <code title={hint}>{hint}</code> : null}
      </span>
      {event.label ? <span className="sess-approval-scope">{event.label}</span> : null}
    </>
  )
  if (!details) return <div className={`sess-approval-line ${outcome}`}>{line}</div>
  return (
    <details className={`sess-approval-entry ${outcome}`}>
      <summary className={`sess-approval-line ${outcome}`}>{line}</summary>
      <div className="sess-approval-details">
        {event.name === 'mcp' && event.args ? <div className="sess-approval-id">{event.args}</div> : null}
        <pre>{details}</pre>
      </div>
    </details>
  )
}
