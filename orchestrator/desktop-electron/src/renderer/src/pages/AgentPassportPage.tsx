import { useEffect, useMemo, useState } from 'react'
import { api, parseScheduleDraft } from '../api/client'
import type {
  AgentKpi,
  AgentRunHistoryItem,
  AgentRunnerEvent,
  ScheduleDraft,
  WorkflowFileItem,
  WorkflowRecord
} from '../api/types'
import { MarkdownBody } from '../components/agentfeed/MarkdownBody'
import { presentAgentText } from '../components/agentfeed/formatAgentText'
import { triggerChipLabel } from './AgentSchedulePage'
import { formatSize } from './filesGrouping'
import { fileTypeIconSrc } from '../utils/fileTypeIcon'
import { localizeStatusText } from '../utils/statusText'
import {
  filesForHistoryRun,
  formatRunWhen,
  historyResultText,
  historyStatusLabel,
  historyStatusTone
} from './historyDetail'

export type PassportTab = 'info' | 'files' | 'results'

interface AgentPassportPageProps {
  workflowId: string
  title: string
  initialTab?: PassportTab
  onBack: () => void
  onRun: (workflowId: string, title: string) => void
  onOpenRun: (workflowId: string, title: string, runId?: string) => void
}

interface PassportFormState {
  name: string
  goal: string
  notes: string
  receives: string
  checks: string
  decisions: string
  result: string
  canAutonomous: string
  needsHumanApproval: string
  forbidden: string
}

function draftFromRecord(record: WorkflowRecord | null): ScheduleDraft | null {
  if (!record) return null
  const local = record.localRun || {}
  const raw = local.schedule_draft ?? local.scheduleDraft
  if (raw && typeof raw === 'object') return parseScheduleDraft(raw as Record<string, unknown>)
  return null
}

function goalFromRecord(record: WorkflowRecord | null, draft: ScheduleDraft | null): string {
  const fromDraft = (draft?.goal || '').trim()
  if (fromDraft) return fromDraft
  const planGoal = (record?.plan?.goal || '').trim()
  if (planGoal) return planGoal
  const local = record?.localRun || {}
  for (const key of ['playbook_draft', 'playbook']) {
    const blob = local[key]
    if (blob && typeof blob === 'object') {
      const data = blob as Record<string, unknown>
      const expected = String(data.expected_result ?? '').trim()
      if (expected) return expected
      const instructions = String(data.instructions ?? '').trim()
      if (instructions) return instructions
    }
  }
  return (record?.notes || '').trim()
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function text(value: unknown): string {
  return String(value ?? '').trim()
}

function trimLongText(value: string, maxLength = 220): string {
  const source = (value || '').trim()
  if (!source) return ''
  if (source.length <= maxLength) return source
  return `${source.slice(0, maxLength).trimEnd()}...`
}

export function AgentPassportPage({
  workflowId,
  title,
  initialTab = 'info',
  onBack,
  onRun,
  onOpenRun
}: AgentPassportPageProps): React.JSX.Element {
  const [tab, setTab] = useState<PassportTab>(initialTab)
  const [record, setRecord] = useState<WorkflowRecord | null>(null)
  const [kpi, setKpi] = useState<AgentKpi | null>(null)
  const [files, setFiles] = useState<WorkflowFileItem[]>([])
  const [runs, setRuns] = useState<AgentRunHistoryItem[]>([])
  const [selectedRun, setSelectedRun] = useState('')
  const [runAnswer, setRunAnswer] = useState('')
  const [runEvents, setRunEvents] = useState<AgentRunnerEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<PassportFormState>({
    name: '',
    goal: '',
    notes: '',
    receives: '',
    checks: '',
    decisions: '',
    result: '',
    canAutonomous: '',
    needsHumanApproval: '',
    forbidden: ''
  })

  useEffect(() => {
    setTab(initialTab)
    setEditing(false)
  }, [initialTab, workflowId])

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError('')
    void Promise.all([
      api.getWorkflow(workflowId).catch(() => null),
      api.getWorkflowKpi(workflowId).catch(() => null),
      api.listWorkflowFiles(workflowId).catch(() => [] as WorkflowFileItem[]),
      api.listAgentRuns(workflowId).catch(() => [] as AgentRunHistoryItem[])
    ])
      .then(([nextRecord, nextKpi, nextFiles, nextRuns]) => {
        if (!alive) return
        setRecord(nextRecord)
        setKpi(nextKpi)
        setFiles(nextFiles)
        setRuns(nextRuns)
        if (nextRuns.length) setSelectedRun(nextRuns[0].runId)
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : 'Не удалось загрузить паспорт агента')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [workflowId])

  useEffect(() => {
    if (!selectedRun) {
      setRunAnswer('')
      setRunEvents([])
      return
    }
    let alive = true
    setDetailLoading(true)
    void api
      .getAgentRunDetail(workflowId, selectedRun)
      .then((detail) => {
        if (!alive) return
        const stored = (detail.item.answer || detail.item.summary || '').trim()
        setRunAnswer(historyResultText(stored, detail.events))
        setRunEvents(detail.events)
        setRuns((current) =>
          current.map((item) => (item.runId === detail.item.runId ? { ...item, ...detail.item } : item))
        )
      })
      .catch(() => {
        if (!alive) return
        setRunAnswer('')
        setRunEvents([])
      })
      .finally(() => {
        if (alive) setDetailLoading(false)
      })
    return () => {
      alive = false
    }
  }, [workflowId, selectedRun])

  const draft = useMemo(() => draftFromRecord(record), [record])
  const sourceForm = useMemo<PassportFormState>(() => {
    const local = asRecord(record?.localRun ?? {})
    const profile = asRecord(local.agent_passport_profile)
    return {
      name: text(draft?.name) || text(record?.title) || text(title) || 'ИИ-агент',
      goal: goalFromRecord(record, draft),
      notes: text(local.passport_notes) || text(record?.notes),
      receives: text(profile.receives),
      checks: text(profile.checks),
      decisions: text(profile.decisions),
      result: text(profile.result),
      canAutonomous: text(profile.canAutonomous),
      needsHumanApproval: text(profile.needsHumanApproval),
      forbidden: text(profile.forbidden)
    }
  }, [record, draft, title])
  useEffect(() => {
    if (editing) return
    setForm(sourceForm)
  }, [sourceForm, editing])
  const displayTitle = (form.name || sourceForm.name || 'ИИ-агент').trim()
  const triggers = draft?.triggers || []
  const selected = runs.find((item) => item.runId === selectedRun)
  const resultText = presentAgentText(runAnswer)
  const latestRun = runs[0] || null
  const runFiles = selected
    ? filesForHistoryRun(files, selected.runId, runAnswer, runEvents)
    : []

  const updateForm = (key: keyof PassportFormState, value: string): void => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  async function savePassport(): Promise<void> {
    if (!record) return
    setSaving(true)
    setError('')
    try {
      let nextRecord = record
      const baseDraft: ScheduleDraft = draft || {
        name: sourceForm.name || title || 'ИИ-агент',
        goal: sourceForm.goal,
        summary: text(draft?.summary),
        triggers: []
      }
      const nextDraft: ScheduleDraft = {
        ...baseDraft,
        name: (form.name || sourceForm.name || title || 'ИИ-агент').trim(),
        goal: form.goal.trim()
      }
      const draftChanged =
        text(baseDraft.name) !== text(nextDraft.name) ||
        text(baseDraft.goal) !== text(nextDraft.goal)
      if (draftChanged) nextRecord = await api.persistScheduleDraft(workflowId, nextDraft)

      const currentLocal = asRecord(nextRecord.localRun)
      const currentProfile = asRecord(currentLocal.agent_passport_profile)
      const nextProfile = {
        receives: form.receives.trim(),
        checks: form.checks.trim(),
        decisions: form.decisions.trim(),
        result: form.result.trim(),
        canAutonomous: form.canAutonomous.trim(),
        needsHumanApproval: form.needsHumanApproval.trim(),
        forbidden: form.forbidden.trim()
      }
      const notesChanged = text(currentLocal.passport_notes) !== form.notes.trim()
      const profileChanged =
        text(currentProfile.receives) !== nextProfile.receives ||
        text(currentProfile.checks) !== nextProfile.checks ||
        text(currentProfile.decisions) !== nextProfile.decisions ||
        text(currentProfile.result) !== nextProfile.result ||
        text(currentProfile.canAutonomous) !== nextProfile.canAutonomous ||
        text(currentProfile.needsHumanApproval) !== nextProfile.needsHumanApproval ||
        text(currentProfile.forbidden) !== nextProfile.forbidden

      if (notesChanged || profileChanged) {
        nextRecord = await api.updateWorkflowLocalRun(workflowId, {
          ...currentLocal,
          passport_notes: form.notes.trim(),
          agent_passport_profile: nextProfile
        })
      }

      setRecord(nextRecord)
      setEditing(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сохранить изменения паспорта')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="agent-studio passport-view">
      <div className="agent-studio-head">
        <button className="btn-ghost" type="button" onClick={onBack}>
          Назад
        </button>
        <div className="studio-titles">
          <h2>Паспорт агента</h2>
          <p>{displayTitle}</p>
        </div>
        <button className="btn-primary" type="button" onClick={() => onRun(workflowId, displayTitle)}>
          Запустить
        </button>
      </div>

      <div className="files-tabs passport-view-tabs">
        <button className={tab === 'info' ? 'active' : ''} type="button" onClick={() => setTab('info')}>
          Сведения
        </button>
        <button className={tab === 'files' ? 'active' : ''} type="button" onClick={() => setTab('files')}>
          Файлы
        </button>
        <button className={tab === 'results' ? 'active' : ''} type="button" onClick={() => setTab('results')}>
          Результаты
        </button>
      </div>

      {error ? <div className="feed-system error">{error}</div> : null}
      {loading ? <div className="wf-files-empty">Загружаем паспорт агента…</div> : null}

      {!loading && tab === 'info' ? (
        <div className="passport-view-body">
          <section className="passport-card">
            <div className="passport-card-head">
              <h3>О агенте</h3>
              <div className="passport-actions">
                {editing ? (
                  <>
                    <button className="btn-ghost" type="button" onClick={() => setForm(sourceForm)} disabled={saving}>
                      Сбросить
                    </button>
                    <button className="btn-ghost" type="button" onClick={() => setEditing(false)} disabled={saving}>
                      Отмена
                    </button>
                    <button className="btn-primary passport-save-btn" type="button" onClick={() => void savePassport()} disabled={saving}>
                      {saving ? 'Сохраняем...' : 'Сохранить'}
                    </button>
                  </>
                ) : (
                  <button className="btn-ghost-dark" type="button" onClick={() => setEditing(true)}>
                    Редактировать
                  </button>
                )}
              </div>
            </div>
            <dl className="passport-view-dl">
              <div>
                <dt>Название</dt>
                <dd>
                  {editing ? (
                    <input
                      className="passport-input"
                      value={form.name}
                      onChange={(event) => updateForm('name', event.target.value)}
                    />
                  ) : (
                    displayTitle
                  )}
                </dd>
              </div>
              <div>
                <dt>Цель</dt>
                <dd>
                  {editing ? (
                    <textarea
                      className="passport-textarea"
                      rows={3}
                      value={form.goal}
                      onChange={(event) => updateForm('goal', event.target.value)}
                    />
                  ) : (
                    form.goal || 'Цель ещё не заполнена'
                  )}
                </dd>
              </div>
              <div>
                <dt>Статус</dt>
                <dd>{localizeStatusText(record?.phase || '', 'Опубликован')}</dd>
              </div>
              <div>
                <dt>Когда запускается</dt>
                <dd>
                  {triggers.length ? (
                    <div className="passport-triggers">
                      {triggers.map((spec, index) => (
                        <span key={`${spec.kind}-${index}`} className="passport-chip">
                          <span className="passport-chip-label">{triggerChipLabel(spec)}</span>
                        </span>
                      ))}
                    </div>
                  ) : (
                    'Только вручную'
                  )}
                </dd>
              </div>
              <div>
                <dt>Описание и контекст</dt>
                <dd>
                  {editing ? (
                    <textarea
                      className="passport-textarea"
                      rows={5}
                      value={form.notes}
                      onChange={(event) => updateForm('notes', event.target.value)}
                    />
                  ) : (
                    <span className="passport-notes-preview">{form.notes || '—'}</span>
                  )}
                </dd>
              </div>
            </dl>
          </section>

          <section className="passport-card">
            <h3>Показатели</h3>
            {kpi?.tiles?.length ? (
              <dl className="passport-view-dl">
                {kpi.tiles.map((tile) => {
                  const kind = tile.measure?.kind || tile.id || ''
                  const label =
                    kind === 'runs_count' || tile.name === 'Число прогонов'
                      ? 'Запусков всего'
                      : tile.name
                  return (
                    <div key={tile.id || tile.name}>
                      <dt>{label}</dt>
                      <dd>
                        {tile.scorePercent != null
                          ? `${Math.round(tile.scorePercent)}%`
                          : tile.fact?.value ?? '—'}
                      </dd>
                    </div>
                  )
                })}
              </dl>
            ) : (
              <p className="passport-empty">KPI этого агента ещё не посчитаны.</p>
            )}
          </section>

          <section className="passport-card">
            <h3>Системные сведения</h3>
            <dl className="passport-view-dl">
              <div>
                <dt>Файлов всего</dt>
                <dd>{files.length}</dd>
              </div>
              <div>
                <dt>KPI метрик</dt>
                <dd>{kpi?.tiles?.length || 0}</dd>
              </div>
              <div>
                <dt>Последний запуск</dt>
                <dd>{latestRun?.startedAt ? formatRunWhen(latestRun.startedAt) : 'нет данных'}</dd>
              </div>
              <div>
                <dt>Последний статус запуска</dt>
                <dd>{latestRun ? historyStatusLabel(latestRun.status) : 'нет данных'}</dd>
              </div>
              <div>
                <dt>Последний результат</dt>
                <dd>{trimLongText((record?.lastResult || '').trim()) || 'нет сохранённого результата'}</dd>
              </div>
            </dl>
          </section>
        </div>
      ) : null}

      {!loading && tab === 'files' ? (
        <div className="passport-view-body">
          {!files.length ? (
            <div className="wp-card">У агента пока нет файлов.</div>
          ) : (
            <div className="files-table-wrap">
              <table className="files-table">
                <thead>
                  <tr>
                    <th>Файл</th>
                    <th>Источник</th>
                    <th>Дата</th>
                    <th>Размер</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {files.map((file) => (
                    <tr key={file.id || file.name}>
                      <td>
                        <div className="files-name-cell">
                          <img className="files-type-icon" src={fileTypeIconSrc(file.name || '')} alt="" />
                          <span>{file.name || 'file'}</span>
                        </div>
                      </td>
                      <td>{file.source === 'agent' ? 'Результат агента' : 'Загружен'}</td>
                      <td>{formatRunWhen(file.createdAt || '') || '—'}</td>
                      <td>{formatSize(file.sizeBytes) || '—'}</td>
                      <td>
                        {file.downloadUrl ? (
                          <button
                            className="btn-ghost"
                            type="button"
                            onClick={() => void api.download(file.downloadUrl || '', file.name || 'file')}
                          >
                            Скачать
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}

      {!loading && tab === 'results' ? (
        <div className="passport-view-results">
          <aside className="passport-view-runs">
            {!runs.length ? <div className="agent-side-card">Запусков пока нет.</div> : null}
            {runs.map((run) => (
              <button
                key={run.runId}
                className={
                  selectedRun === run.runId ? 'agent-side-card history-run active' : 'agent-side-card history-run'
                }
                type="button"
                onClick={() => setSelectedRun(run.runId)}
              >
                <div className={`history-status is-${historyStatusTone(run.status)}`}>
                  {historyStatusLabel(run.status)}
                </div>
                <div className="history-summary">{formatRunWhen(run.startedAt) || 'без даты'}</div>
              </button>
            ))}
          </aside>
          <div className="passport-view-result">
            {!selected ? (
              <div className="wf-files-empty">Выберите запуск, чтобы увидеть результат.</div>
            ) : detailLoading ? (
              <div className="wf-files-empty">Загружаем результат…</div>
            ) : (
              <section className="wf-result-card">
                <div className="wf-result-head">
                  <div className="wf-result-title">
                    {historyStatusLabel(selected.status)}
                    {selected.startedAt ? ` · ${formatRunWhen(selected.startedAt)}` : ''}
                  </div>
                  <button
                    className="btn-ghost wf-result-action"
                    type="button"
                    onClick={() => onOpenRun(workflowId, displayTitle, selected.runId)}
                  >
                    Открыть запуск
                  </button>
                </div>
                {resultText ? (
                  <MarkdownBody text={resultText} />
                ) : (
                  <p className="passport-empty">У этого запуска нет сохранённого результата.</p>
                )}
                <section className="wf-file-section" style={{ marginTop: 16 }}>
                  <h4>Файлы агента</h4>
                  {runFiles.length === 0 ? (
                    <div className="wf-files-empty">Агент не приложил файлы к этому запуску.</div>
                  ) : (
                    <ul className="wf-files">
                      {runFiles.map((file) => (
                        <li key={file.id || file.name}>
                          <button
                            className="wf-file-card history-file-btn"
                            type="button"
                            onClick={() => {
                              if (file.downloadUrl) void api.download(file.downloadUrl || '', file.name || 'file')
                            }}
                          >
                            <img className="files-type-icon" src={fileTypeIconSrc(file.name)} alt="" />
                            <div className="wf-file-copy">
                              <span className="wf-file-name">{file.name}</span>
                              {formatSize(file.sizeBytes) ? (
                                <span className="wf-file-meta">{formatSize(file.sizeBytes)}</span>
                              ) : null}
                            </div>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </section>
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}
