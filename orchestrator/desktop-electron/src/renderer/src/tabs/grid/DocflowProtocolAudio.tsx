import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { CassetteTape } from 'lucide-react'
import { api } from '../../api/client'
import { MarkdownBody } from '../../components/agentfeed/MarkdownBody'
import type { RunState } from '../../components/agentfeed/runReducer'
import type { ToolItem } from '../../components/agentfeed/types'
import { useRuns } from '../../store/runs'
import {
  buildSupplementMessage,
  PROTOCOL_AGENT_TITLE,
  PROTOCOL_AUDIO_EXTENSIONS,
  resolveProtocolAgentWorkflowId
} from '../../workplace/meetingProtocolAgent'
import type { ProtocolRow } from '../../workplace/fetchDocflowProtocols'
import {
  audioMarkTitle,
  markAudioNames,
  rememberProtocolAudio,
  saveProtocolAudioResult,
  useProtocolAudioMarks,
  type ProtocolAudioMark,
  type ProtocolAudioResult
} from '../../workplace/protocolAudioMarks'
import './meetingActions.css'

function basename(filePath: string): string {
  const parts = filePath.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || filePath
}

function clock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

function rows(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object') : []
}

function texts(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item || '').trim()).filter(Boolean) : []
}

const ACTION_LABELS: Record<string, string> = {
  add_tasks: 'Задачи в регистре протокола',
  check_tasks: 'Отметка выполнения',
  update: 'Протокол перезаписан',
  edit: 'Протокол исправлен',
  create: 'Протокол создан'
}

function toolIs(item: ToolItem, name: string): boolean {
  return item.tool === name || item.tool.endsWith(`__${name}`) || item.tool.endsWith(`.${name}`)
}

/** Что из ленты запуска показать человеку: расшифровки, записи в 1С, итоговое пояснение агента. */
function runResult(state: RunState, live: boolean): ProtocolAudioResult {
  const tools = state.items.filter((item): item is ToolItem => item.kind === 'tool' && item.done)
  const transcripts = tools
    .filter((item) => toolIs(item, 'audio.transcribe') && !item.error && item.result?.transcript_path)
    .map((item) => ({
      name: String(item.result?.filename || ''),
      path: String(item.result?.transcript_path || ''),
      durationSec: Number(item.result?.duration_sec) || 0
    }))
  const changes = tools
    .filter((item) => item.tool.endsWith('meeting_protocol_write'))
    .map((item) => {
      const result = item.result || {}
      const action = String(item.arguments.action || 'create')
      const details = [
        ...rows(result.added).map((row) => `добавлена задача ${row.item}: ${row.text}`),
        ...rows(result.changed).map((row) => `исправлена задача ${row.item}`),
        ...rows(result.marked).map((row) => `задача ${row.item} отмечена выполненной ${row.done_date || ''}`.trim()),
        ...texts(result.skipped).map((text) => `пропущено: ${text}`),
        ...texts(result.unresolved).map((text) => `не сопоставлено: ${text}`),
        ...texts(result.errors).map((text) => `ошибка: ${text}`)
      ]
      return {
        action,
        summary: String(result.summary || item.summary || item.statusText || ''),
        details,
        error: item.error
      }
    })
  const answers = state.items.filter((item) => item.kind === 'result' || (item.kind === 'message' && item.role === 'agent'))
  const last = answers.at(-1)
  return {
    transcripts,
    changes,
    explanation: last && 'text' in last ? last.text.trim() : '',
    error: state.error,
    finished: !live
  }
}

function TranscriptView({ path }: { path: string }): React.JSX.Element {
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let alive = true
    void api.invokeServerTool('audio.transcript', { transcript_path: path }, 30_000).then((res) => {
      if (!alive) return
      const result = (res.result || {}) as { text?: string }
      if (res.ok && result.text) setText(result.text)
      else setError(res.error || 'Расшифровка не найдена')
      setLoading(false)
    })
    return () => {
      alive = false
    }
  }, [path])
  if (loading) return <p className="spec-v04-muted">Загружаем расшифровку…</p>
  if (error) return <p className="meeting-report-error">{error}</p>
  return <pre className="docflow-audio-transcript">{text}</pre>
}

function ProtocolAudioReport({
  number,
  marks,
  onClose
}: {
  number: string
  marks: ProtocolAudioMark[]
  onClose: () => void
}): React.JSX.Element {
  const titleId = useId()
  const [open, setOpen] = useState('')
  const history = [...marks].reverse()
  return createPortal(
    <div className="modal-overlay meeting-report-overlay" onClick={onClose} role="presentation">
      <div
        className="modal-card meeting-report-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="meeting-report-toolbar">
          <h4 className="modal-title" id={titleId}>
            Протокол № {number}: расшифровка и изменения
          </h4>
          <div className="meeting-report-toolbar-actions">
            <button type="button" className="cal-btn" onClick={onClose}>
              Закрыть
            </button>
          </div>
        </div>
        <div className="meeting-report-body docflow-audio-report">
          {history.map((mark) => {
            const result = mark.result
            return (
              <section key={mark.runId || mark.at}>
                <h4>
                  <CassetteTape size={14} aria-hidden /> {mark.extra ? 'Догрузка ГС' : 'Аудиозапись'}: {markAudioNames(mark).join(', ')}
                  <span>{new Date(mark.at).toLocaleString('ru-RU')}</span>
                </h4>
                {!result ? <p className="spec-v04-muted">Результата этого запуска нет — агент ещё работает или лента запуска не сохранилась.</p> : null}
                {result && !result.finished ? <p className="spec-v04-muted">Агент ещё работает — здесь показано то, что уже сделано.</p> : null}
                {result?.error ? <p className="meeting-report-error">{result.error}</p> : null}
                {result ? (
                  <>
                    <h5>Изменения в 1С</h5>
                    {result.changes.length ? (
                      <ul>
                        {result.changes.map((change, index) => (
                          <li key={`${change.action}-${index}`} className={change.error ? 'is-error' : ''}>
                            <strong>{ACTION_LABELS[change.action] || change.action}</strong>
                            {change.summary ? ` — ${change.summary}` : ''}
                            {change.details.length ? (
                              <ul>
                                {change.details.map((line) => (
                                  <li key={line}>{line}</li>
                                ))}
                              </ul>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="spec-v04-muted">В 1С агент ничего не записал.</p>
                    )}
                    <h5>Пояснения агента</h5>
                    {result.explanation ? <MarkdownBody text={result.explanation} /> : <p className="spec-v04-muted">Пояснения нет.</p>}
                    <h5>Расшифровка</h5>
                    {result.transcripts.length ? (
                      result.transcripts.map((item) => (
                        <div key={item.path} className="docflow-audio-transcript-row">
                          <button
                            type="button"
                            className="cal-btn"
                            onClick={() => setOpen((value) => (value === item.path ? '' : item.path))}
                          >
                            {open === item.path ? 'Скрыть' : 'Показать'} · {item.name || 'запись'}
                            {item.durationSec ? ` · ${clock(item.durationSec)}` : ''}
                          </button>
                          {open === item.path ? <TranscriptView path={item.path} /> : null}
                        </div>
                      ))
                    ) : (
                      <p className="spec-v04-muted">Расшифровки в этом запуске нет.</p>
                    )}
                  </>
                ) : null}
              </section>
            )
          })}
        </div>
      </div>
    </div>,
    document.body
  )
}

/** Кассета у протокола, к которому прикрепляли аудиозапись (или агент упомянул её в комментарии 1С). */
export function ProtocolAudioBadge({ row }: { row: Pick<ProtocolRow, 'id' | 'comment'> }): React.JSX.Element | null {
  const marks = useProtocolAudioMarks()
  const title = audioMarkTitle(marks[row.id], row.comment)
  if (!title) return null
  return (
    <em className="docflow-audio-mark" title={title}>
      <CassetteTape size={13} aria-label={title} />
    </em>
  )
}

/** «Дополнить из аудио» / «Догрузить ГС»: агент протоколов дописывает задачи и проверяет по записи их выполнение. */
export function ProtocolAudioSupplement({
  row,
  onFinished
}: {
  row: ProtocolRow
  onFinished: () => void
}): React.JSX.Element {
  const runs = useRuns()
  const marks = useProtocolAudioMarks()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reportOpen, setReportOpen] = useState(false)
  const own = marks[row.id] || []
  const last = own.at(-1)
  const entry = last ? runs.getRun(last.workflowId) : undefined
  const state = entry && last?.runId && entry.state.activeRunId === last.runId ? entry.state : undefined
  const live = Boolean(state?.running || state?.pendingHitl || state?.pendingQuestion)
  const wasLive = useRef(false)

  useEffect(() => {
    if (wasLive.current && !live) onFinished()
    wasLive.current = live
  }, [live, onFinished])

  useEffect(() => {
    if (state && last?.runId) saveProtocolAudioResult(row.id, last.runId, runResult(state, live))
  }, [state, live, last?.runId, row.id])

  const start = async (extra: boolean): Promise<void> => {
    if (busy || live) return
    setError('')
    setBusy(true)
    try {
      const paths = await window.api.openFile({
        title: extra ? 'Голосовые сообщения для догрузки в протокол' : 'Аудиозапись совещания для дополнения протокола',
        filters: [{ name: 'Аудио', extensions: PROTOCOL_AUDIO_EXTENSIONS }],
        properties: extra ? ['openFile', 'multiSelections'] : ['openFile']
      })
      const audioPaths = (paths || []).filter(Boolean)
      if (!audioPaths.length) return
      const res = await api.invokeServerTool('onec.meeting_protocols', { ref_key: row.id }, 90_000)
      const card = (res.ok && res.result && typeof res.result === 'object'
        ? (res.result as { protocol?: Record<string, unknown> }).protocol
        : undefined) as { number?: string; editable?: boolean; form?: Record<string, unknown> } | undefined
      if (!card?.form) throw new Error(res.error || 'Не удалось прочитать протокол из 1С')
      const workflowId = await resolveProtocolAgentWorkflowId()
      const busyRun = runs.getRun(workflowId)?.state
      if (busyRun?.running || busyRun?.pendingHitl || busyRun?.pendingQuestion) {
        throw new Error('Агент протоколов сейчас занят другим запуском — дождитесь его окончания')
      }
      const names = audioPaths.map(basename)
      const message = buildSupplementMessage(
        null,
        audioPaths,
        {
          number: String(card.number || row.number),
          refKey: row.id,
          editable: card.editable !== false,
          form: card.form
        },
        { extra, previousAudio: own.flatMap(markAudioNames) }
      )
      const runId = runs.startRun({ workflowId, title: PROTOCOL_AGENT_TITLE, message, filePaths: audioPaths })
      rememberProtocolAudio({
        protocolId: row.id,
        audioName: names.join(', '),
        audioNames: names,
        extra,
        workflowId,
        runId: runId || '',
        at: new Date().toISOString()
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось запустить агента по аудиозаписи')
    } finally {
      setBusy(false)
    }
  }

  const hasReport = own.some((mark) => Boolean(mark.result))
  return (
    <div className="docflow-audio-row">
      <div className="docflow-audio-actions">
        {own.length ? (
          <button
            type="button"
            className="docflow-edit-btn"
            disabled={busy || live}
            title="Догрузить голосовые сообщения к протоколу: агент дополнит задачи и проверит выполнение"
            onClick={() => void start(true)}
          >
            {busy ? 'Запуск…' : live ? 'Агент работает…' : 'Догрузить ГС'}
          </button>
        ) : (
          <button
            type="button"
            className="docflow-edit-btn"
            disabled={busy || live}
            title="Прикрепить аудиозапись совещания: агент дополнит задачи и проверит их выполнение"
            onClick={() => void start(false)}
          >
            {busy ? 'Запуск…' : live ? 'Агент работает…' : 'Дополнить из аудио'}
          </button>
        )}
        {hasReport ? (
          <button
            type="button"
            className="docflow-edit-btn"
            title="Расшифровка записей и пояснения агента по изменениям в протоколе"
            onClick={() => setReportOpen(true)}
          >
            Расшифровка и изменения
          </button>
        ) : null}
      </div>
      {error || (state && live) ? (
        <div className="meeting-protocol-progress docflow-audio-progress">
          {last ? (
            <div className="meeting-protocol-progress-row">
              <span className="meeting-protocol-label">{last.extra ? 'ГС' : 'Аудио'}</span>
              <span>{markAudioNames(last).join(', ')}</span>
            </div>
          ) : null}
          {state ? (
            <div className="meeting-protocol-progress-row">
              <span className="meeting-protocol-label">Статус</span>
              <span>{state.status || 'В работе…'}</span>
            </div>
          ) : null}
          {error ? <p className="meeting-protocol-error">{error}</p> : null}
          {state?.pendingHitl && last ? (
            <div className="meeting-protocol-hitl">
              <p>{state.pendingHitl.title || 'Нужно ваше решение'}</p>
              {state.pendingHitl.intent ? <p className="meeting-protocol-hitl-intent">{state.pendingHitl.intent}</p> : null}
              <div className="meeting-protocol-hitl-actions">
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => runs.respondHitl(last.workflowId, state.pendingHitl!.requestId, true)}
                >
                  Подтвердить
                </button>
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={() => runs.respondHitl(last.workflowId, state.pendingHitl!.requestId, false)}
                >
                  Отклонить
                </button>
              </div>
            </div>
          ) : null}
          {state?.pendingQuestion ? (
            <p className="meeting-protocol-hint">Агент задал вопрос — ответьте во вкладке «Решения».</p>
          ) : null}
        </div>
      ) : null}
      {last?.result?.error && !live ? <p className="meeting-protocol-error">{last.result.error}</p> : null}
      {reportOpen ? <ProtocolAudioReport number={row.number} marks={own} onClose={() => setReportOpen(false)} /> : null}
    </div>
  )
}
