import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { DocflowActionRow, DocflowWaitingRow } from '../components/agentfeed/DocflowActionsBlock'
import type { ClosureCheckAssignment, ClosureCheckLine } from '../components/agentfeed/docflowActions'
import { closureConclusionTone, type AutoCloseState, type ClosureCheckResult } from './closureCheckResult'

function lineTone(conclusion: string): 'close' | 'partial' | 'none' {
  const value = conclusion.toLowerCase()
  if (value.startsWith('можно закрыв') || value.startsWith('выполнено')) return 'close'
  if (value.includes('доработ') || value.includes('частично')) return 'partial'
  return 'none'
}

function waitsForExecutor(line: ClosureCheckLine): boolean {
  return Boolean(line.openTaskId) || line.taskState.toLowerCase().includes('у исполнителя')
}

const SHORT_CONCLUSION: Record<'close' | 'partial' | 'none', string> = {
  close: 'Можно закрыть',
  partial: 'Частично',
  none: 'Нет оснований'
}

function ConclusionPill({ item }: { item: ClosureCheckAssignment }): React.JSX.Element {
  const tone = closureConclusionTone(item.conclusion)
  return (
    <span className={`closure-pill ${tone}`} title={item.conclusion}>
      {SHORT_CONCLUSION[tone]}
      {item.total ? ` · ${item.done}/${item.total}` : ''}
    </span>
  )
}

const AUTO_CLOSE_LABEL: Record<AutoCloseState['state'], string> = {
  closing: 'Закрываю в 1С…',
  closed: 'Закрыто в 1С',
  kept: 'Не закрыто',
  error: 'Ошибка закрытия'
}

function AutoClosePill({ state }: { state: AutoCloseState | undefined }): React.JSX.Element | null {
  if (!state) return null
  return (
    <span className={`closure-pill auto-${state.state}`} title={state.message}>
      {AUTO_CLOSE_LABEL[state.state]}
    </span>
  )
}

function AutoCloseNote({ state }: { state: AutoCloseState | undefined }): React.JSX.Element | null {
  if (!state || state.state === 'closing' || !state.message) return null
  return <div className={`closure-auto-note auto-${state.state}`}>{state.message}</div>
}

/** Проверка до перехода на задачи ДО оценивала мероприятия: такие строки подписаны «п.N». */
function checkedByMeasures(item: ClosureCheckAssignment): boolean {
  return item.lines.some((line) => String(line.line).startsWith('п.'))
}

function StaleCheckNote({ item }: { item: ClosureCheckAssignment }): React.JSX.Element | null {
  if (!checkedByMeasures(item)) return null
  return (
    <div className="closure-auto-note auto-kept">
      Проверка по старой схеме: оценены мероприятия, а не задачи в Документообороте. Запустите проверку заново.
    </div>
  )
}

function ClosureLines({ item }: { item: ClosureCheckAssignment }): React.JSX.Element {
  return (
    <ol className="closure-lines">
      {item.lines.map((line) => (
        <li key={line.line || line.event} className="closure-line">
          <div className="closure-line-title">
            <span className="closure-line-no">{line.line}</span>
            <span>{line.event}</span>
          </div>
          <div className="closure-line-meta">
            <span className={`closure-pill small ${lineTone(line.conclusion)}`}>{line.conclusion}</span>
            {line.executor ? <span>{line.executor}</span> : null}
          </div>
          {line.evidence ? <div className="closure-line-text">{line.evidence}</div> : null}
          {line.taskState ? <div className="closure-line-text muted">В Документообороте: {line.taskState}</div> : null}
          {line.comment ? (
            <div className="closure-line-remark">
              <span>{lineTone(line.conclusion) === 'close' ? 'Заключение' : 'Почему нельзя закрыть'}</span>
              {line.comment}
            </div>
          ) : null}
          {line.action ? (
            <ul className="closure-line-action">
              <DocflowActionRow item={line.action} bare />
            </ul>
          ) : waitsForExecutor(line) ? (
            <ul className="closure-line-action">
              <DocflowWaitingRow taskId={line.openTaskId} performer={line.executor} />
            </ul>
          ) : null}
        </li>
      ))}
    </ol>
  )
}

function formatAt(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

type Tone = 'close' | 'partial' | 'none'

type ClosureCheckDialogProps = {
  result: ClosureCheckResult | null
  running: boolean
  status: string
  checkedCount: number
  autoClose: Record<string, AutoCloseState>
  topicOf: (number: string) => string
  onPick: (number: string) => void
  onStart: () => void
  onOpenFeed: () => void
  onClose: () => void
}

/** Окно кнопки «Проверка к закрытию»: результат последнего запуска и запуск новой проверки. */
export function ClosureCheckDialog({
  result,
  running,
  status,
  checkedCount,
  autoClose,
  topicOf,
  onPick,
  onStart,
  onOpenFeed,
  onClose
}: ClosureCheckDialogProps): React.JSX.Element {
  const [filter, setFilter] = useState<Tone | ''>('')
  const [open, setOpen] = useState<string>('')
  const items = result?.assignments ?? []
  const count = (tone: Tone): number => items.filter((item) => closureConclusionTone(item.conclusion) === tone).length
  const order: Record<Tone, number> = { close: 0, partial: 1, none: 2 }
  const shown = items
    .filter((item) => !filter || closureConclusionTone(item.conclusion) === filter)
    .sort((a, b) => order[closureConclusionTone(a.conclusion)] - order[closureConclusionTone(b.conclusion)])

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const statButton = (tone: Tone, label: string): React.JSX.Element => (
    <button
      type="button"
      className={`closure-pill ${tone} closure-filter${filter === tone ? ' is-active' : ''}`}
      aria-pressed={filter === tone}
      onClick={() => setFilter(filter === tone ? '' : tone)}
    >
      {label} {count(tone)}
    </button>
  )

  return createPortal(
    <div className="modal-overlay" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="closure-dialog" role="dialog" aria-modal="true" aria-label="Проверка поручений к закрытию">
        <header className="closure-dialog-head">
          <div>
            <div className="closure-dialog-title">Проверка поручений к закрытию</div>
            <div className="closure-dialog-sub">
              {result ? `Результат запуска ${formatAt(result.at)} · поручений: ${items.length}` : 'Проверок ещё не было'}
            </div>
          </div>
          <button type="button" className="closure-dialog-x" aria-label="Закрыть окно" onClick={onClose}>
            ✕
          </button>
        </header>

        <div className="closure-dialog-bar">
          <button type="button" className="closure-btn primary" disabled={running} onClick={onStart}>
            {running ? 'Идёт проверка…' : checkedCount ? `Запустить проверку отмеченных (${checkedCount})` : 'Запустить проверку'}
          </button>
          {running || result ? (
            <button type="button" className="closure-btn ghost" onClick={onOpenFeed}>
              {running ? 'Ход работы' : 'Отчёт агента и Word'}
            </button>
          ) : null}
          {running ? <span className="closure-dialog-status">{status || 'Агент проверяет поручения'}</span> : null}
        </div>
        {running && result ? (
          <div className="closure-dialog-note">Пока идёт новая проверка, ниже результат предыдущего запуска.</div>
        ) : null}

        {items.length ? (
          <>
            <div className="closure-dialog-stats">
              {statButton('close', 'Можно закрыть')}
              {statButton('partial', 'Частично')}
              {statButton('none', 'Нет оснований')}
            </div>
            <ul className="closure-dialog-list">
              {shown.map((item) => {
                const expanded = open === item.number
                const topic = topicOf(item.number)
                return (
                  <li key={item.number} className={`closure-dialog-item${expanded ? ' is-open' : ''}`}>
                    <button
                      type="button"
                      className="closure-dialog-row"
                      aria-expanded={expanded}
                      onClick={() => setOpen(expanded ? '' : item.number)}
                    >
                      <span className="closure-dialog-caret" aria-hidden>
                        {expanded ? '▾' : '▸'}
                      </span>
                      <span className="closure-dialog-num">{item.number}</span>
                      <span className="closure-dialog-main">
                        {topic ? <span className="closure-dialog-topic">{topic}</span> : null}
                        {item.reason ? <span className="closure-dialog-reason">{item.reason}</span> : null}
                      </span>
                      <AutoClosePill state={autoClose[item.number]} />
                      <ConclusionPill item={item} />
                    </button>
                    {expanded ? (
                      <div className="closure-dialog-body">
                        <AutoCloseNote state={autoClose[item.number]} />
                        <StaleCheckNote item={item} />
                        <ClosureLines item={item} />
                        <button type="button" className="closure-link" onClick={() => onPick(item.number)}>
                          Показать в реестре
                        </button>
                      </div>
                    ) : null}
                  </li>
                )
              })}
            </ul>
          </>
        ) : (
          <div className="closure-dialog-empty">
            {running
              ? 'Агент проверяет поручения. Результат появится здесь, когда он закончит.'
              : 'Нажмите «Запустить проверку»: агент в фоне проверит артефакты и задачи в Документообороте и вынесет решение по каждому поручению.'}
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}

/** Вывод агента в карточке выбранного поручения. */
export function ClosureCheckRowPanel({
  item,
  autoClose
}: {
  item: ClosureCheckAssignment | undefined
  autoClose?: AutoCloseState
}): React.JSX.Element | null {
  if (!item) return null
  return (
    <section className="closure-card">
      <div className="closure-card-label">Вывод агента</div>
      <ConclusionPill item={item} /> <AutoClosePill state={autoClose} />
      {item.reason ? <p className="closure-card-reason">{item.reason}</p> : null}
      <AutoCloseNote state={autoClose} />
      <StaleCheckNote item={item} />
      <ClosureLines item={item} />
    </section>
  )
}
