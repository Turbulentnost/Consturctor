import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { CassetteTape, Trash2 } from 'lucide-react'
import { api } from '../../api/client'
import { buildFeedItems, settleOpenFeedTools } from '../../components/agentfeed/build'
import { MarkdownBody } from '../../components/agentfeed/MarkdownBody'
import type { FeedItem, ToolItem } from '../../components/agentfeed/types'
import { isInFlightRunStatus } from '../../store/liveRun'
import {
  buildSpeakerMessage,
  buildSupplementMessage,
  buildTranscribeOnlyMessage,
  PROTOCOL_AUDIO_EXTENSIONS,
  resolveProtocolAgentWorkflowId,
  resolveSpeakerAgentWorkflowId,
  type ExistingProtocol,
  type IdentifiedTranscript
} from '../../workplace/meetingProtocolAgent'
import type { ProtocolRow } from '../../workplace/fetchDocflowProtocols'
import {
  decidePlatformApproval,
  lastPlatformResult,
  startPlatformProtocolRun,
  uploadRunAudio,
  usePlatformRun,
  type PlatformRunView
} from '../../workplace/platformProtocolRun'
import {
  audioMarkTitle,
  forgetProtocolAudio,
  markAudioNames,
  patchProtocolAudio,
  rememberProtocolAudio,
  saveProtocolAudioBackendRun,
  saveProtocolAudioResult,
  useProtocolAudioMarks,
  type ProtocolAudioMark,
  type ProtocolAudioResult
} from '../../workplace/protocolAudioMarks'
import { PlatformRunDialog } from './PlatformRunDialog'
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

function changeDetails(result: Record<string, unknown>): string[] {
  return [
    ...rows(result.added).map((row) => `добавлена задача ${row.item}: ${row.text}`),
    ...rows(result.changed).map((row) => `исправлена задача ${row.item}`),
    ...rows(result.marked).map((row) => `задача ${row.item} отмечена выполненной ${row.done_date || ''}`.trim()),
    ...texts(result.skipped).map((text) => `пропущено: ${text}`),
    ...texts(result.unresolved).map((text) => `не сопоставлено: ${text}`),
    ...texts(result.errors).map((text) => `ошибка: ${text}`)
  ]
}

/** Что из ленты старого раннера показать человеку: расшифровки, записи в 1С, итоговое пояснение агента. */
function feedResult(items: FeedItem[], error: string, finished: boolean): ProtocolAudioResult {
  const tools = items.filter((item): item is ToolItem => item.kind === 'tool' && item.done)
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
      return {
        action: String(item.arguments.action || 'create'),
        summary: String(result.summary || item.summary || item.statusText || ''),
        details: changeDetails(result),
        error: item.error
      }
    })
  const answers = items.filter((item) => item.kind === 'result' || (item.kind === 'message' && item.role === 'agent'))
  const last = answers.at(-1)
  return {
    transcripts,
    changes,
    explanation: last && 'text' in last ? last.text.trim() : '',
    error,
    finished
  }
}

function transcriptOf(result: Record<string, unknown> | null): ProtocolAudioMark['transcript'] {
  const path = String(result?.transcript_path || '').trim()
  if (!path) return undefined
  return { name: String(result?.filename || ''), path, durationSec: Number(result?.duration_sec) || 0 }
}

/** То же по сессии платформы агентов (конфигурация 2). Расшифровка из первого этапа берётся из отметки. */
function platformResult(run: PlatformRunView, mark?: ProtocolAudioMark): ProtocolAudioResult {
  const done = run.steps.filter((step) => step.done)
  const own = done
    .filter((step) => step.tool === 'audio.transcribe')
    .map((step) => transcriptOf(step.result))
    .filter((item): item is NonNullable<typeof item> => Boolean(item))
  return {
    transcripts: own.length ? own : mark?.transcript ? [mark.transcript] : [],
    changes: done
      .filter((step) => step.tool === 'onec.meeting_protocol_write')
      .map((step) => ({
        action: String(step.args.action || 'create'),
        summary: String(step.result?.summary || ''),
        details: step.result ? changeDetails(step.result) : [],
        error: step.error
      })),
    explanation: run.answer,
    error: run.error || mark?.chainError || '',
    finished: !run.running
  }
}

type ProtocolCard = { number?: string; editable?: boolean; form: Record<string, unknown> }

async function readProtocolCard(refKey: string): Promise<ProtocolCard> {
  const res = await api.invokeServerTool('onec.meeting_protocols', { ref_key: refKey }, 90_000)
  const card = (res.ok && res.result && typeof res.result === 'object'
    ? (res.result as { protocol?: Record<string, unknown> }).protocol
    : undefined) as Partial<ProtocolCard> | undefined
  if (!card?.form) throw new Error(res.error || 'Не удалось прочитать протокол из 1С')
  return { ...card, form: card.form }
}

function existingProtocol(card: ProtocolCard, row: ProtocolRow): ExistingProtocol {
  return { number: String(card.number || row.number), refKey: row.id, editable: card.editable !== false, form: card.form }
}

/** Присутствующие, руководитель и ответственный протокола 1С — люди, чьи голоса могут быть в записи. */
function cardPeople(form: Record<string, unknown>): string[] {
  const listed = Array.isArray(form.participants) ? form.participants : []
  const names = [...listed, form.leader, form.responsible].map((value) => (typeof value === 'string' ? value.trim() : ''))
  return [...new Set(names.filter(Boolean))]
}

function rosterLines(value: unknown): string {
  return rows(value)
    .map((row) => {
      const fio = String(row.fio || '').trim()
      const label = String(row.label || '').trim()
      const speaker = String(row.speaker || '').trim()
      if (!fio) return ''
      return label && label !== fio ? `${label} — ${fio} (был ${speaker})` : `${speaker} — ${fio}`
    })
    .filter(Boolean)
    .join('\n')
}

/**
 * ФИО, которые предложил агент говорящих, подставляются в расшифровку инициалами.
 * Отпечатки голосов в банк не пишутся: это догадка агента, человек её не проверял.
 */
async function applyProposedSpeakers(transcriptId: string): Promise<IdentifiedTranscript> {
  const spoken = await api.invokeServerTool('audio.speakers', { transcript_id: transcriptId }, 60_000)
  if (!spoken.ok) throw new Error(spoken.error || 'Не удалось прочитать голоса расшифровки')
  const payload = (spoken.result || {}) as { transcript_path?: string; voices?: unknown }
  const named = rows(payload.voices).filter((voice) => String(voice.fio || '').trim())
  const unnamed = 'Остальные голоса не определены: в протоколе оставляй метки «Голос N».'
  if (!named.length) {
    return { transcriptId, transcriptPath: String(payload.transcript_path || ''), roster: unnamed }
  }
  const bound = await api.invokeServerTool(
    'audio.bind_speakers',
    {
      transcript_id: transcriptId,
      voices: named.map((voice) => ({
        speaker: String(voice.speaker || ''),
        fio: String(voice.fio || '').trim(),
        user_id: String(voice.user_id || '')
      })),
      save_voices: false,
      initials: true
    },
    60_000
  )
  if (!bound.ok) throw new Error(bound.error || 'Не удалось подставить ФИО в расшифровку')
  const result = (bound.result || {}) as { transcript_path?: string; people?: unknown }
  const roster = rosterLines(result.people)
  return {
    transcriptId,
    transcriptPath: String(result.transcript_path || payload.transcript_path || ''),
    roster: named.length < rows(payload.voices).length ? `${roster}\n${unnamed}` : roster
  }
}

const RUN_MATCH_BEFORE_MS = 60_000
const RUN_MATCH_AFTER_MS = 5 * 60_000

/** Старые отметки не знают id запуска на backend — ищем запуск агента, стартовавший рядом с отметкой. */
async function findBackendRun(mark: ProtocolAudioMark, number: string): Promise<string> {
  if (mark.backendRunId) return mark.backendRunId
  const at = Date.parse(mark.at)
  if (!Number.isFinite(at)) return ''
  const list = await api.listAgentRuns(mark.workflowId)
  let best = ''
  let bestGap = Infinity
  for (const item of list) {
    const started = Date.parse(item.startedAt)
    if (!Number.isFinite(started)) continue
    if (started < at - RUN_MATCH_BEFORE_MS || started > at + RUN_MATCH_AFTER_MS) continue
    if (number && item.message && !item.message.includes(number)) continue
    const gap = Math.abs(started - at)
    if (gap < bestGap) {
      best = item.runId
      bestGap = gap
    }
  }
  return best
}

/** Лента запуска старого раннера с сервера: переживает перезапуск программы и не путается с соседними запусками. */
async function loadServerResult(
  mark: ProtocolAudioMark,
  number: string
): Promise<{ backendRunId: string; result: ProtocolAudioResult } | null> {
  const backendRunId = await findBackendRun(mark, number)
  if (!backendRunId) return null
  const detail = await api.getAgentRunDetail(mark.workflowId, backendRunId)
  const inFlight = isInFlightRunStatus(detail.item.status)
  let items = buildFeedItems(detail.events, { live: inFlight })
  if (!inFlight) items = settleOpenFeedTools(items)
  const answer = (detail.item.answer || detail.item.summary || '').trim()
  const failed = /error|fail/i.test(detail.item.status)
  if (!inFlight && !failed && answer && !items.some((item) => item.kind === 'result')) {
    items = [...items, { kind: 'result', id: `hist-res-${backendRunId}`, text: answer }]
  }
  return {
    backendRunId,
    result: feedResult(items, failed ? answer || 'Запуск завершился с ошибкой' : '', !inFlight)
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

type SectionProps = {
  protocolId: string
  number: string
  mark: ProtocolAudioMark
  open: string
  onToggle: (path: string) => void
}

function AudioRunSection(props: SectionProps): React.JSX.Element {
  return props.mark.platformSessionId ? <PlatformAudioRun {...props} /> : <LegacyAudioRun {...props} />
}

function PlatformAudioRun({ protocolId, mark, open, onToggle }: SectionProps): React.JSX.Element {
  const run = usePlatformRun(mark.platformSessionId || '')
  const [progressOpen, setProgressOpen] = useState(false)
  const loaded = Boolean(run.status) && run.sessionId === mark.platformSessionId
  const result = loaded ? platformResult(run, mark) : mark.result
  useEffect(() => {
    if (loaded) saveProtocolAudioResult(protocolId, mark.runId, platformResult(run, mark))
  }, [loaded, mark, protocolId, run])
  return (
    <>
      <AudioRunBody
        protocolId={protocolId}
        mark={mark}
        live={run.running}
        loading={!loaded && !run.error && !mark.result}
        result={result}
        open={open}
        onToggle={onToggle}
        onProgress={() => setProgressOpen(true)}
      />
      {progressOpen && mark.platformSessionId ? (
        <PlatformRunDialog sessionId={mark.platformSessionId} onClose={() => setProgressOpen(false)} />
      ) : null}
    </>
  )
}

function LegacyAudioRun({ protocolId, number, mark, open, onToggle }: SectionProps): React.JSX.Element {
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let alive = true
    setLoading(true)
    void loadServerResult(mark, number)
      .then((loaded) => {
        if (!alive || !loaded) return
        saveProtocolAudioBackendRun(protocolId, mark.runId, loaded.backendRunId)
        saveProtocolAudioResult(protocolId, mark.runId, loaded.result)
      })
      .catch(() => undefined)
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
    // Перечитываем ленту, только когда меняется сам запуск, а не его сохранённый результат.
  }, [protocolId, mark.runId, mark.at, number])
  return (
    <AudioRunBody
      protocolId={protocolId}
      mark={mark}
      live={false}
      loading={loading}
      result={mark.result}
      open={open}
      onToggle={onToggle}
    />
  )
}

function AudioRunBody({
  protocolId,
  mark,
  live,
  loading,
  result,
  open,
  onToggle,
  onProgress
}: {
  protocolId: string
  mark: ProtocolAudioMark
  live: boolean
  loading: boolean
  result: ProtocolAudioResult | undefined
  open: string
  onToggle: (path: string) => void
  onProgress?: () => void
}): React.JSX.Element {
  const remove = (): void => {
    const names = markAudioNames(mark).join(', ') || 'запись'
    if (!window.confirm(`Убрать «${names}» из списка записей протокола? То, что агент уже записал в 1С, останется.`)) return
    forgetProtocolAudio(protocolId, mark)
  }

  return (
    <section>
      <h4>
        <CassetteTape size={14} aria-hidden /> {mark.extra ? 'Догрузка ГС' : 'Аудиозапись'}: {markAudioNames(mark).join(', ')}
        <span>{new Date(mark.at).toLocaleString('ru-RU')}</span>
        {onProgress ? (
          <button type="button" className="cal-btn" onClick={onProgress}>
            Ход работы
          </button>
        ) : null}
        <button
          type="button"
          className="docflow-edit-btn docflow-audio-remove"
          disabled={live}
          title={live ? 'Агент ещё работает с этой записью' : 'Убрать запись из списка протокола'}
          aria-label="Удалить запись"
          onClick={remove}
        >
          <Trash2 size={13} aria-hidden />
        </button>
      </h4>
      {loading && !result ? <p className="spec-v04-muted">Загружаем ход запуска с сервера…</p> : null}
      {!loading && !result ? (
        <p className="spec-v04-muted">Ход этого запуска не найден на сервере.</p>
      ) : null}
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
                <button type="button" className="cal-btn" onClick={() => onToggle(item.path)}>
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
}

function ProtocolAudioReport({
  protocolId,
  number,
  marks,
  onClose
}: {
  protocolId: string
  number: string
  marks: ProtocolAudioMark[]
  onClose: () => void
}): React.JSX.Element {
  const titleId = useId()
  const [open, setOpen] = useState('')
  const history = [...marks].reverse()

  useEffect(() => {
    if (!marks.length) onClose()
  }, [marks.length, onClose])
  return createPortal(
    <div className="modal-overlay meeting-report-overlay" onClick={onClose} role="presentation">
      <div
        className="modal-card is-resizable meeting-report-dialog"
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
          {history.map((mark) => (
            <AudioRunSection
              key={`${mark.runId}-${mark.at}`}
              protocolId={protocolId}
              number={number}
              mark={mark}
              open={open}
              onToggle={(path) => setOpen((value) => (value === path ? '' : path))}
            />
          ))}
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

/**
 * «Дополнить из аудио» / «Догрузить ГС» на платформе агентов (конфигурация 2). Одна запись идёт тремя
 * запусками: расшифровка audio.transcribe → агент говорящих (голос → сотрудник по базе и контексту,
 * в репликах инициалы) → агент протоколов дописывает задачи и проверяет выполнение. Несколько ГС —
 * одним запуском агента протоколов, он расшифровывает каждое сам.
 */
export function ProtocolAudioSupplement({
  row,
  onFinished
}: {
  row: ProtocolRow
  onFinished: () => void
}): React.JSX.Element {
  const marks = useProtocolAudioMarks()
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [reportOpen, setReportOpen] = useState(false)
  const [progressOpen, setProgressOpen] = useState(false)
  const [deciding, setDeciding] = useState(false)
  const own = marks[row.id] || []
  const last = own.at(-1)
  const sessionId = last?.platformSessionId || ''
  const run = usePlatformRun(sessionId)
  const stage = last?.stage
  const chained = Boolean(sessionId) && (stage === 'transcribe' || stage === 'speakers') && !last?.chainError
  const live = (Boolean(sessionId) && run.running) || chained
  const wasLive = useRef(false)

  useEffect(() => {
    if (wasLive.current && !live) onFinished()
    wasLive.current = live
  }, [live, onFinished])

  const current = Boolean(sessionId) && run.sessionId === sessionId
  useEffect(() => {
    if (current && last?.runId && run.status) saveProtocolAudioResult(row.id, last.runId, platformResult(run, last))
  }, [current, last, row.id, run])

  const chainKey = useRef('')
  useEffect(() => {
    if (!last || !chained || !current || run.running || !run.status) return
    const key = `${stage}:${sessionId}`
    if (chainKey.current === key) return
    chainKey.current = key
    const fail = (err: unknown): void =>
      patchProtocolAudio(row.id, last.at, {
        chainError: err instanceof Error ? err.message : 'Не удалось передать запись следующему агенту'
      })
    if (stage === 'transcribe') {
      void (async () => {
        if (run.status !== 'finished') throw new Error(run.error || 'Расшифровка остановлена')
        const result = lastPlatformResult(run.steps, 'audio.transcribe')
        const transcriptId = String(result?.transcript_id || '').trim()
        if (!transcriptId) throw new Error('Агент закончил без расшифровки — подробности в «Ход работы»')
        const known = rows(result?.known_speakers)
          .map((item) => `${item.speaker} — ${item.fio}`)
          .join('\n')
        const speakerWorkflow = await resolveSpeakerAgentWorkflowId()
        const next = await startPlatformProtocolRun(
          speakerWorkflow,
          buildSpeakerMessage(transcriptId, null, known, last.participants || [])
        )
        patchProtocolAudio(row.id, last.at, {
          stage: 'speakers',
          platformSessionId: next,
          transcriptId,
          transcript: transcriptOf(result)
        })
      })().catch(fail)
      return
    }
    void (async () => {
      const transcriptId = (last.transcriptId || '').trim()
      if (!transcriptId) throw new Error('Нет расшифровки для протокола')
      // Агент говорящих мог упасть или ничего не предложить — протокол всё равно дописываем по меткам голосов.
      const identified = await applyProposedSpeakers(transcriptId)
      const card = await readProtocolCard(row.id)
      const workflowId = await resolveProtocolAgentWorkflowId()
      const message = buildSupplementMessage(null, last.audioPath || '', existingProtocol(card, row), {
        extra: last.extra,
        previousAudio: own.slice(0, -1).flatMap(markAudioNames),
        identified
      })
      const next = await startPlatformProtocolRun(workflowId, message)
      patchProtocolAudio(row.id, last.at, {
        stage: 'protocol',
        platformSessionId: next,
        workflowId,
        transcript: last.transcript && identified.transcriptPath ? { ...last.transcript, path: identified.transcriptPath } : last.transcript
      })
    })().catch(fail)
  }, [chained, current, last, own, row, run, sessionId, stage])

  const decide = async (allow: boolean): Promise<void> => {
    if (!sessionId || !run.approval || deciding) return
    setDeciding(true)
    try {
      await decidePlatformApproval(sessionId, run.approval.id, allow)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось передать решение агенту')
    } finally {
      setDeciding(false)
    }
  }

  const start = async (extra: boolean): Promise<void> => {
    if (busy || live) return
    setError('')
    setBusy('Запуск…')
    try {
      const paths = await window.api.openFile({
        title: extra ? 'Голосовые сообщения для догрузки в протокол' : 'Аудиозапись совещания для дополнения протокола',
        filters: [{ name: 'Аудио', extensions: PROTOCOL_AUDIO_EXTENSIONS }],
        properties: extra ? ['openFile', 'multiSelections'] : ['openFile']
      })
      const audioPaths = (paths || []).filter(Boolean)
      if (!audioPaths.length) return
      const card = await readProtocolCard(row.id)
      const workflowId = await resolveProtocolAgentWorkflowId()
      setBusy('Загрузка аудио…')
      const files = await uploadRunAudio(workflowId, audioPaths)
      setBusy('Запуск…')
      const single = audioPaths.length === 1
      const people = cardPeople(card.form)
      const message = single
        ? buildTranscribeOnlyMessage(null, audioPaths[0], files, people)
        : buildSupplementMessage(null, audioPaths, existingProtocol(card, row), {
            extra,
            previousAudio: own.flatMap(markAudioNames),
            files
          })
      const platformSessionId = await startPlatformProtocolRun(workflowId, message)
      const names = audioPaths.map(basename)
      rememberProtocolAudio({
        protocolId: row.id,
        audioName: names.join(', '),
        audioNames: names,
        audioPath: audioPaths[0],
        extra,
        workflowId,
        runId: platformSessionId,
        at: new Date().toISOString(),
        stage: single ? 'transcribe' : 'protocol',
        platformSessionId,
        participants: people
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось запустить агента по аудиозаписи')
    } finally {
      setBusy('')
    }
  }

  const status = run.approval
    ? 'Ждёт вашего разрешения'
    : run.question
      ? 'Агент задал вопрос'
      : stage === 'transcribe' || run.steps.some((step) => step.tool === 'audio.transcribe' && !step.done)
        ? 'Расшифровка записи…'
        : stage === 'speakers'
          ? 'Определение говорящих…'
          : 'Агент дополняет протокол…'
  const chainError = last?.chainError || ''
  return (
    <div className="docflow-audio-row">
      <div className="docflow-audio-actions">
        {own.length ? (
          <button
            type="button"
            className="docflow-edit-btn"
            disabled={Boolean(busy) || live}
            title="Догрузить голосовые сообщения к протоколу: агент дополнит задачи и проверит выполнение"
            onClick={() => void start(true)}
          >
            {busy || (live ? 'Агент работает…' : 'Догрузить ГС')}
          </button>
        ) : (
          <button
            type="button"
            className="docflow-edit-btn"
            disabled={Boolean(busy) || live}
            title="Прикрепить аудиозапись совещания: агент дополнит задачи и проверит их выполнение"
            onClick={() => void start(false)}
          >
            {busy || (live ? 'Агент работает…' : 'Дополнить из аудио')}
          </button>
        )}
        {own.length ? (
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
      {error || live ? (
        <div className="meeting-protocol-progress docflow-audio-progress">
          {last ? (
            <div className="meeting-protocol-progress-row">
              <span className="meeting-protocol-label">{last.extra ? 'ГС' : 'Аудио'}</span>
              <span>{markAudioNames(last).join(', ')}</span>
            </div>
          ) : null}
          {live ? (
            <div className="meeting-protocol-progress-row">
              <span className="meeting-protocol-label">Статус</span>
              <span>{status}</span>
            </div>
          ) : null}
          {error ? <p className="meeting-protocol-error">{error}</p> : null}
          {live && run.approval ? (
            <div className="meeting-protocol-hitl">
              <p>{run.approval.title || 'Нужно ваше разрешение'}</p>
              {run.approval.subject ? <p className="meeting-protocol-hitl-intent">{run.approval.subject}</p> : null}
              <div className="meeting-protocol-hitl-actions">
                <button type="button" className="btn-primary" disabled={deciding} onClick={() => void decide(true)}>
                  Разрешить
                </button>
                <button type="button" className="btn-ghost" disabled={deciding} onClick={() => void decide(false)}>
                  Отклонить
                </button>
                <button type="button" className="btn-ghost" onClick={() => setProgressOpen(true)}>
                  Подробнее
                </button>
              </div>
            </div>
          ) : null}
          {live && run.question ? (
            <div className="meeting-protocol-hitl">
              <p>{run.question.title || 'Агент задал вопрос'}</p>
              <div className="meeting-protocol-hitl-actions">
                <button type="button" className="btn-primary" onClick={() => setProgressOpen(true)}>
                  Ответить
                </button>
              </div>
            </div>
          ) : null}
          {live ? (
            <button type="button" className="cal-btn meeting-protocol-progress-open" onClick={() => setProgressOpen(true)}>
              Ход работы
            </button>
          ) : null}
        </div>
      ) : null}
      {!live && (chainError || last?.result?.error) ? (
        <p className="meeting-protocol-error">{chainError || last?.result?.error}</p>
      ) : null}
      {progressOpen && sessionId ? <PlatformRunDialog sessionId={sessionId} onClose={() => setProgressOpen(false)} /> : null}
      {reportOpen ? (
        <ProtocolAudioReport protocolId={row.id} number={row.number} marks={own} onClose={() => setReportOpen(false)} />
      ) : null}
    </div>
  )
}
