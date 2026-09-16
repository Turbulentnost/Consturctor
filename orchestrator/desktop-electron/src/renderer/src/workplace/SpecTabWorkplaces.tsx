import { useCallback, useEffect, useMemo, useState } from 'react'
import { MailDetailPanel } from '../tabs/grid/MailDetailPanel'
import { AgentsPage } from '../pages/AgentsPage'
import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { ensureOutlookMeetings } from '../utils/outlookMeetings'
import type { SpecSummaryTile } from './specV04Shell'
import {
  SpecAskOrchestratorBlock,
  SpecBottomRow,
  SpecFilters,
  SpecPageHead,
  SpecPanel,
  SpecPill,
  SpecProgress,
  SpecQuickActions,
  SpecQuickLaunchButton,
  SpecSplit,
  SpecSummaryTiles
} from './specV04Components'
import { ASK_CHIPS, type SpecKnowledgeRow } from './specV04DemoData'
import { buildTaskTiles, useSpecV04Sources } from './useSpecV04Data'
import { useTurboProjectOpenTasks } from './useTurboProjectOpenTasks'

function standardFilters(): React.JSX.Element {
  return (
    <>
      <select className="wp-select" defaultValue="month">
        <option value="month">Период: текущий месяц</option>
        <option value="week">Неделя</option>
      </select>
      <select className="wp-select" defaultValue="">
        <option value="">Источник: все</option>
      </select>
      <select className="wp-select" defaultValue="">
        <option value="">Проект: все</option>
      </select>
      <select className="wp-select" defaultValue="">
        <option value="">Статус: все</option>
      </select>
      <input className="wp-search" placeholder="Поиск…" />
      <select className="wp-select" defaultValue="new">
        <option value="new">Сортировка: сначала новые</option>
      </select>
      <button type="button" className="btn-ghost">
        Сбросить фильтры
      </button>
    </>
  )
}

export function TasksTabWorkplace({
  user,
  onAskOrchestrator
}: {
  user: UserProfile
  onAskOrchestrator: (message: string, context: string) => void
}): React.JSX.Element {
  const data = useSpecV04Sources(user)
  const taskRows = data.erpTasks
  const [selectedId, setSelectedId] = useState('')
  const effectiveId = selectedId || taskRows[0]?.id || ''
  const selected = taskRows.find((item) => item.id === effectiveId)
  const tiles: SpecSummaryTile[] = buildTaskTiles(data)
  const ask = (m: string) => onAskOrchestrator(m, 'Вкладка «Задачи»')

  return (
    <div className="wp-page spec-v04-page">
      <SpecPageHead
        title="Задачи"
        subtitle="Единый центр управления задачами сотрудника"
        actions={
          <button type="button" className="btn-primary">
            + Создать задачу ▾
          </button>
        }
      />
      <SpecSummaryTiles tiles={tiles} />
      <SpecFilters>{standardFilters()}</SpecFilters>
      <SpecSplit
        wideSide
        main={
          <div className="spec-v04-table-wrap wp-card">
            <table className="spec-v04-table">
              <thead>
                <tr>
                  <th />
                  <th>Задача</th>
                  <th>Источник</th>
                  <th>Процесс</th>
                  <th>Проект</th>
                  <th>Срок</th>
                  <th>Приоритет</th>
                  <th>Статус</th>
                  <th>Исполнитель</th>
                  <th>Кто выполняет</th>
                  <th>Прогресс</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {!taskRows.length ? (
                  <tr>
                    <td colSpan={12} className="spec-v04-empty">
                      {data.erpLoading
                        ? 'Загружаем задачи из 1С…'
                        : `Нет открытых задач 1С для ${data.erpFio || 'пользователя'}.`}
                    </td>
                  </tr>
                ) : null}
                {taskRows.map((row) => (
                  <tr
                    key={row.id}
                    className={effectiveId === row.id ? 'selected' : ''}
                    onClick={() => setSelectedId(row.id)}
                  >
                    <td>
                      <input type="checkbox" onClick={(e) => e.stopPropagation()} />
                    </td>
                    <td>
                      <strong>{row.title}</strong>
                    </td>
                    <td>
                      <SpecPill tone={row.sourceTone}>{row.source}</SpecPill>
                    </td>
                    <td>{row.process}</td>
                    <td>{row.project}</td>
                    <td className={row.urgent ? 'spec-deadline-urgent' : ''}>{row.deadline}</td>
                    <td>
                      <SpecPill tone={row.priorityTone}>{row.priority}</SpecPill>
                    </td>
                    <td>
                      <SpecPill tone={row.statusTone}>{row.status}</SpecPill>
                    </td>
                    <td>{row.executor}</td>
                    <td>{row.who}</td>
                    <td>
                      <SpecProgress value={row.progress} />
                    </td>
                    <td>⋮</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        }
        side={
          selected ? (
            <div className="spec-detail-card">
              <h2>{selected.title}</h2>
              <div className="spec-detail-tags">
                <SpecPill tone={selected.statusTone}>{selected.status}</SpecPill>
                <SpecPill tone={selected.priorityTone}>{selected.priority} приоритет</SpecPill>
              </div>
              <div className="spec-detail-tabs">
                <button type="button" className="active">
                  Детали
                </button>
                <button type="button">Документы (3)</button>
                <button type="button">История (6)</button>
                <button type="button">Связанные (4)</button>
              </div>
              <p className="spec-v04-muted">
                Описание задачи, основание из регламента REG-003 и связанные материалы из базы знаний.
              </p>
              <dl className="spec-detail-meta">
                <div>
                  <dt>Процесс</dt>
                  <dd>{selected.process}</dd>
                </div>
                <div>
                  <dt>Проект</dt>
                  <dd>{selected.project}</dd>
                </div>
                <div>
                  <dt>Срок</dt>
                  <dd>{selected.deadline}</dd>
                </div>
              </dl>
              <SpecProgress value={selected.progress} />
              <footer className="spec-detail-actions">
                <button type="button" className="btn-primary">
                  Отметить выполненной
                </button>
                <button type="button" className="btn-ghost">
                  Изменить
                </button>
              </footer>
            </div>
          ) : null
        }
      />
      <SpecBottomRow>
        <SpecPanel title="Мои задачи на сегодня">
          <ul className="spec-today-list">
            {taskRows.slice(0, 5).map((row) => (
              <li key={row.id}>
                <span>{row.deadline}</span>
                <strong>{row.title}</strong>
                <SpecProgress value={row.progress} />
              </li>
            ))}
          </ul>
        </SpecPanel>
        <SpecPanel title="Быстрые действия">
          <SpecQuickActions
            items={[
              'Создать задачу из письма',
              'Создать из документа',
              'Назначить исполнителя',
              'Перенести срок',
              'Связать с процессом'
            ]}
          />
        </SpecPanel>
        <SpecAskOrchestratorBlock
          placeholder="Например: «Покажи просроченные задачи»"
          chips={ASK_CHIPS.tasks}
          onSubmit={ask}
        />
      </SpecBottomRow>
    </div>
  )
}

export function ProjectsTabWorkplace({
  user,
  onAskOrchestrator
}: {
  user: UserProfile
  onAskOrchestrator: (message: string, context: string) => void
}): React.JSX.Element {
  const data = useSpecV04Sources(user)
  const projectRows = data.projects
  const [selectedId, setSelectedId] = useState('')
  const effectiveId = selectedId || projectRows[0]?.id || ''
  const selected = projectRows.find((item) => item.id === effectiveId)
  const projectTasks = useTurboProjectOpenTasks(
    effectiveId,
    user,
    data.erpFio,
    Boolean(effectiveId) && projectRows.length > 0,
    { openOnly: true, assigneeOnly: true, limit: 200 }
  )
  const tiles: SpecSummaryTile[] = [
    { id: 'a', label: 'Активные проекты', value: String(projectRows.length || '—'), tone: 'purple' },
    {
      id: 't',
      label: 'Задачи на сегодня',
      value: String(projectRows.reduce((s, p) => s + p.tasks, 0) || '—'),
      tone: 'blue'
    },
    {
      id: 'r',
      label: 'Проекты с риском',
      value: String(projectRows.filter((p) => p.riskTone !== 'green').length || '—'),
      tone: 'orange'
    },
    { id: 'd', label: 'Источник', value: data.sources.turbo, tone: 'green' },
    { id: 'l', label: 'Сотрудник', value: data.erpFio || '—', tone: 'neutral' }
  ]
  const ask = (m: string) => onAskOrchestrator(m, 'Вкладка «Проекты»')

  return (
    <div className="wp-page spec-v04-page">
      <SpecPageHead
        title="Проекты"
        subtitle="Ваши проекты, роли, задачи, сроки и результаты"
        actions={<SpecQuickLaunchButton />}
      />
      <SpecSummaryTiles tiles={tiles} />
      <SpecFilters>{standardFilters()}</SpecFilters>
      <SpecSplit
        main={
          <div className="spec-v04-table-wrap wp-card">
            <h3 className="spec-table-caption">Проекты ({projectRows.length})</h3>
            <table className="spec-v04-table">
              <thead>
                <tr>
                  <th>Проект</th>
                  <th>Код</th>
                  <th>Роль</th>
                  <th>Мои задачи</th>
                  <th>Статус</th>
                  <th>Срок</th>
                  <th>Прогресс</th>
                  <th>Риск</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {!projectRows.length ? (
                  <tr>
                    <td colSpan={9} className="spec-v04-empty">
                      {data.turboLoading
                        ? 'Загружаем портфель TurboProject…'
                        : `Нет проектов для ${data.erpFio}. Проверьте turboproject.get_user_portfolio.`}
                    </td>
                  </tr>
                ) : null}
                {projectRows.map((row) => (
                  <tr
                    key={row.id}
                    className={effectiveId === row.id ? 'selected' : ''}
                    onClick={() => setSelectedId(row.id)}
                  >
                    <td>
                      <strong>{row.name}</strong>
                    </td>
                    <td>{row.code}</td>
                    <td>{row.role}</td>
                    <td>{row.tasks}</td>
                    <td>
                      <SpecPill tone={row.statusTone}>{row.status}</SpecPill>
                    </td>
                    <td>{row.deadline}</td>
                    <td>
                      <SpecProgress value={row.progress} />
                    </td>
                    <td>
                      <SpecPill tone={row.riskTone}>{row.risk}</SpecPill>
                    </td>
                    <td>⋮</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        }
        side={
          selected ? (
            <div className="spec-detail-card">
              <h2>{selected.name}</h2>
              <div className="spec-detail-tags">
                <SpecPill tone={selected.statusTone}>{selected.status}</SpecPill>
                <SpecPill tone={selected.riskTone}>{selected.risk}</SpecPill>
              </div>
              <p className="spec-v04-muted">Роль: {selected.role}. Срок: {selected.deadline}.</p>
              <h4>
                Открытых задач в MPP: {selected.tasks}
                {projectTasks.showingAllAssignees ? ' · все исполнители' : ''}
              </h4>
              <SpecProgress value={selected.progress} />
              {projectTasks.loading ? (
                <p className="spec-v04-muted">Загружаем задачи…</p>
              ) : projectTasks.error ? (
                <p className="spec-v04-muted">{projectTasks.error}</p>
              ) : projectTasks.rows.length ? (
                <table className="spec-v04-table spec-v04-table-compact">
                  <tbody>
                    {projectTasks.rows.map((task) => (
                      <tr key={task.id}>
                        <td>
                          <strong>{task.title}</strong>
                        </td>
                        <td className={task.status === 'Просрочена' ? 'spec-deadline-urgent' : undefined}>
                          {task.deadline}
                        </td>
                        <td>
                          <SpecPill tone={task.statusTone}>{task.status}</SpecPill>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="spec-v04-muted">Нет задач в MPP по фильтру</p>
              )}
              <footer className="spec-detail-actions">
                <button type="button" className="btn-ghost">
                  Открыть в проекте
                </button>
                <button type="button" className="btn-primary">
                  + Создать задачу
                </button>
              </footer>
            </div>
          ) : null
        }
      />
      <SpecBottomRow>
        <SpecPanel title="Задачи по проектам на сегодня (12)">
          <table className="spec-v04-table spec-v04-table-compact">
            <tbody>
              <tr>
                <td>09:30</td>
                <td>Проверить ТЗ</td>
                <td>CRM</td>
                <td>
                  <SpecPill tone="red">Высокий</SpecPill>
                </td>
              </tr>
            </tbody>
          </table>
        </SpecPanel>
        <SpecPanel title="Календарь проекта">
          <p className="spec-v04-muted">Август 2024 — контрольные точки и этапы.</p>
        </SpecPanel>
        <SpecAskOrchestratorBlock placeholder="Например: «Какой статус проекта CRM?»" chips={ASK_CHIPS.projects} onSubmit={ask} />
      </SpecBottomRow>
    </div>
  )
}

export function MailTabWorkplace({
  user,
  onAskOrchestrator
}: {
  user: UserProfile
  onAskOrchestrator: (message: string, context: string) => void
}): React.JSX.Element {
  const data = useSpecV04Sources(user)
  const [rowPatches, setRowPatches] = useState<Record<string, Partial<import('./specV04DemoData').SpecMailRow>>>({})
  const mailRows = useMemo(
    () => data.mailRows.map((row) => ({ ...row, ...rowPatches[row.id] })),
    [data.mailRows, rowPatches]
  )
  const [selectedId, setSelectedId] = useState('')
  const effectiveId = selectedId || mailRows[0]?.id || ''
  const selected = mailRows.find((item) => item.id === effectiveId)
  const patchRow = useCallback((id: string, patch: Partial<(typeof mailRows)[0]>) => {
    setRowPatches((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }))
  }, [])
  const tiles: SpecSummaryTile[] = [
    { id: 'p', label: 'К обработке', value: String(mailRows.length || '—'), tone: 'blue' },
    { id: 'box', label: data.mailImapPrimary ? 'Ящик IMAP' : 'Ящик Outlook', value: data.outlookMailbox || 'локальный профиль', tone: 'orange' },
    { id: 'src', label: 'Источник списка', value: data.sources.mail, tone: 'purple' }
  ]
  const ask = (m: string) => onAskOrchestrator(m, 'Вкладка «Письма»')

  return (
    <div className="wp-page spec-v04-page">
      <SpecPageHead
        title="Письма"
        subtitle={
          data.mailImapPrimary
            ? `Почта IMAP (primary) · ${data.sources.mail}${data.outlookMailbox ? ` · COM fallback: ${data.outlookMailbox}` : ''}`
            : data.outlookMailbox
              ? `Почта Outlook: ${data.outlookMailbox} · список через ${data.sources.mail} · ${data.mailImapStatus}`
              : `Единый центр обработки рабочей почты · ${data.mailImapStatus || data.sources.mail}`
        }
        actions={<SpecQuickLaunchButton />}
      />
      <SpecSummaryTiles tiles={tiles} />
      <SpecFilters>{standardFilters()}</SpecFilters>
      <SpecSplit
        main={
          <div className="spec-v04-table-wrap wp-card">
            <h3 className="spec-table-caption">Письма ({mailRows.length})</h3>
            {data.mailComError || data.mailImapError ? (
              <p className="spec-v04-muted">
                {[data.mailComError, data.mailImapError].filter(Boolean).join(' · ')}
              </p>
            ) : null}
            <table className="spec-v04-table">
              <thead>
                <tr>
                  <th />
                  <th>Отправитель</th>
                  <th>Тема</th>
                  <th>Категория</th>
                  <th>Процесс / проект</th>
                  <th>Время</th>
                  <th>Приоритет</th>
                  <th>Статус</th>
                  <th>Исполнитель</th>
                </tr>
              </thead>
              <tbody>
                {!mailRows.length ? (
                  <tr>
                    <td colSpan={9} className="spec-v04-empty">
                      {data.mailLoading
                        ? 'Загружаем письма…'
                        : data.mailImapPrimary
                          ? `Нет писем в IMAP. ${data.mailImapStatus}`
                          : `Нет писем за неделю (Outlook COM). Ящик: ${data.outlookMailbox || 'проверьте профиль'}. ${data.mailImapStatus}`}
                    </td>
                  </tr>
                ) : null}
                {mailRows.map((row) => (
                  <tr
                    key={row.id}
                    className={effectiveId === row.id ? 'selected' : ''}
                    onClick={() => setSelectedId(row.id)}
                  >
                    <td>
                      <input type="checkbox" onClick={(e) => e.stopPropagation()} />
                    </td>
                    <td>{row.sender}</td>
                    <td>
                      <strong>{row.subject}</strong>
                    </td>
                    <td>
                      <SpecPill tone={row.catTone}>{row.category}</SpecPill>
                    </td>
                    <td>{row.link}</td>
                    <td>{row.time}</td>
                    <td>
                      <SpecPill tone={row.priTone}>{row.priority}</SpecPill>
                    </td>
                    <td>
                      <SpecPill tone={row.stTone}>{row.status}</SpecPill>
                    </td>
                    <td>{row.assignee}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        }
        side={
          selected ? (
            <MailDetailPanel
              mail={selected}
              onPatchRow={patchRow}
              onAskOrchestrator={(message) => ask(message)}
            />
          ) : null
        }
      />
      <SpecBottomRow>
        <SpecPanel title="Письма, требующие ответа сегодня">
          <ul className="spec-today-list">
            <li>
              <span>11:00</span>
              <strong>{selected?.subject}</strong>
            </li>
          </ul>
        </SpecPanel>
        <SpecPanel title="Связанные задачи">
          <p className="spec-v04-muted">8 задач, созданных из писем.</p>
        </SpecPanel>
        <SpecAskOrchestratorBlock
          placeholder={data.outlookMailbox ? `Что важного в ${data.outlookMailbox}?` : 'Спросить по почте'}
          chips={ASK_CHIPS.mail}
          onSubmit={ask}
        />
      </SpecBottomRow>
    </div>
  )
}

export function MeetingsTabWorkplace({
  user,
  onAskOrchestrator,
  onOpenRun,
  onOpenSchedule,
  onOpenHistory
}: {
  user: UserProfile
  onAskOrchestrator: (message: string, context: string) => void
  onOpenRun: (workflowId: string, runId?: string, autoStart?: boolean) => void
  onOpenSchedule: (workflowId: string, title: string) => void
  onOpenHistory: (workflowId: string, title: string) => void
}): React.JSX.Element {
  const data = useSpecV04Sources(user)
  const [meetings, setMeetings] = useState<
    { time: string; title: string; format: string; participants: string; prep: string; prepTone: 'green' | 'orange'; status: string; stTone: 'blue' | 'gray' }[]
  >([])
  useEffect(() => {
    let alive = true
    void ensureOutlookMeetings('week', new Date(), { owner: data.erpFio }).then((res) => {
      if (!alive) return
      setMeetings(
        (res.meetings || []).slice(0, 20).map((m) => ({
          time: (m.start || '').slice(11, 16) || '—',
          title: m.subject,
          format: m.location || '—',
          participants: m.attendees ? `${m.attendees.split(';').length} чел.` : '—',
          prep: '—',
          prepTone: 'orange' as const,
          status: 'Запланировано',
          stTone: 'gray' as const
        }))
      )
    })
    return () => {
      alive = false
    }
  }, [data.erpFio])

  const tiles: SpecSummaryTile[] = [
    { id: 't', label: 'На неделе (Outlook)', value: String(data.meetingCount || meetings.length || '—'), tone: 'lilac' },
    { id: 'box', label: 'Календарь', value: data.outlookMailbox || data.erpFio, tone: 'blue' }
  ]
  const ask = (m: string) => onAskOrchestrator(m, 'Вкладка «Совещания»')

  return (
    <div className="wp-page spec-v04-page">
      <SpecPageHead title="Совещания" subtitle="Календарь, подготовка и материалы" actions={<SpecQuickLaunchButton />} />
      <SpecSummaryTiles tiles={tiles} />
      <SpecFilters>{standardFilters()}</SpecFilters>
      <div className="spec-meetings-grid">
        <SpecPanel title="Календарь на 12 августа 2024">
          <div className="spec-day-calendar">
            {['09:00', '10:00', '12:00', '14:00', '16:00'].map((slot) => (
              <div key={slot} className="spec-cal-slot">
                <span>{slot}</span>
                <div className="spec-cal-event">Совещание</div>
              </div>
            ))}
          </div>
        </SpecPanel>
        <SpecPanel title="Ближайшие совещания (12)">
          <table className="spec-v04-table spec-v04-table-compact">
            <thead>
              <tr>
                <th>Время</th>
                <th>Название</th>
                <th>Формат</th>
                <th>Участники</th>
                <th>Подготовка</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {!meetings.length ? (
                <tr>
                  <td colSpan={6} className="spec-v04-empty">
                    Нет событий Outlook на неделе для {data.erpFio}.
                  </td>
                </tr>
              ) : null}
              {meetings.map((row) => (
                <tr key={`${row.time}-${row.title}`}>
                  <td>{row.time}</td>
                  <td>
                    <strong>{row.title}</strong>
                  </td>
                  <td>{row.format}</td>
                  <td>{row.participants}</td>
                  <td>
                    <SpecPill tone={row.prepTone}>{row.prep}</SpecPill>
                  </td>
                  <td>
                    <SpecPill tone={row.stTone}>{row.status}</SpecPill>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </SpecPanel>
        <div className="spec-detail-card">
          <h2>{meetings[0]?.title || 'Совещание'}</h2>
          <p className="spec-v04-muted">{meetings[0]?.time || '—'} · {meetings[0]?.format || '—'}</p>
          <p className="spec-v04-muted">Данные из outlook.read_calendar (локальный Outlook).</p>
        </div>
      </div>
      <div className="spec-v04-meetings-embed">
        <AgentsPage
          variant="calendar"
          onOpenRun={onOpenRun}
          onOpenSchedule={onOpenSchedule}
          onOpenHistory={onOpenHistory}
        />
      </div>
      <SpecAskOrchestratorBlock
        placeholder="Например: «Подготовить краткое резюме совещания»"
        chips={ASK_CHIPS.meetings}
        onSubmit={ask}
      />
    </div>
  )
}

export function KnowledgeTabWorkplace({
  user,
  onAskOrchestrator
}: {
  user: UserProfile
  onAskOrchestrator: (message: string, context: string) => void
}): React.JSX.Element {
  const data = useSpecV04Sources(user)
  const [catalog, setCatalog] = useState<SpecKnowledgeRow[]>([])
  const [catalogLoading, setCatalogLoading] = useState(true)
  useEffect(() => {
    let alive = true
    void api
      .listWorkflows()
      .then((items) => {
        if (!alive) return
        setCatalog(
          items
            .filter((w) => w.documentName)
            .slice(0, 50)
            .map((w) => ({
              id: w.id,
              name: w.documentName || w.title,
              type: 'Регламент',
              typeTone: 'green' as const,
              section: w.phase || '—',
              process: w.title,
              project: '—',
              version: '—',
              updated: '—',
              author: 'Constructor'
            }))
        )
      })
      .finally(() => {
        if (alive) setCatalogLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])
  const [selectedId, setSelectedId] = useState('')
  const effectiveId = selectedId || catalog[0]?.id || ''
  const selected = catalog.find((item) => item.id === effectiveId)
  const tiles: SpecSummaryTile[] = useMemo(
    () => [
      { id: 'all', label: 'Документов (агенты)', value: String(catalog.length || '—'), tone: 'neutral' },
      { id: 'reg', label: 'Регламенты', value: String(catalog.length || '—'), tone: 'green' }
    ],
    [catalog.length]
  )
  const ask = (m: string) => onAskOrchestrator(m, 'Вкладка «База знаний»')

  return (
    <div className="wp-page spec-v04-page">
      <SpecPageHead
        title="База знаний"
        subtitle="Регламенты, шаблоны, инструкции и связанные материалы"
        actions={<SpecQuickLaunchButton />}
      />
      <SpecSummaryTiles tiles={tiles} />
      <SpecFilters>{standardFilters()}</SpecFilters>
      <SpecSplit
        main={
          <div className="spec-v04-table-wrap wp-card">
            <h3 className="spec-table-caption">Каталог материалов</h3>
            <table className="spec-v04-table">
              <thead>
                <tr>
                  <th>Название</th>
                  <th>Тип</th>
                  <th>Раздел</th>
                  <th>Процесс</th>
                  <th>Проект</th>
                  <th>Версия</th>
                  <th>Обновлено</th>
                  <th>Автор</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {catalogLoading ? (
                  <tr>
                    <td colSpan={9} className="spec-v04-empty">
                      Загружаем регламенты с backend…
                    </td>
                  </tr>
                ) : null}
                {!catalogLoading && !catalog.length ? (
                  <tr>
                    <td colSpan={9} className="spec-v04-empty">
                      Нет опубликованных регламентов на сервере.
                    </td>
                  </tr>
                ) : null}
                {catalog.map((row) => (
                  <tr
                    key={row.id}
                    className={effectiveId === row.id ? 'selected' : ''}
                    onClick={() => setSelectedId(row.id)}
                  >
                    <td>
                      <strong>{row.name}</strong>
                    </td>
                    <td>
                      <SpecPill tone={row.typeTone}>{row.type}</SpecPill>
                    </td>
                    <td>{row.section}</td>
                    <td>{row.process}</td>
                    <td>{row.project}</td>
                    <td>{row.version}</td>
                    <td>{row.updated}</td>
                    <td>{row.author}</td>
                    <td>⋮</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        }
        side={
          selected ? (
            <div className="spec-detail-card">
              <h2>{selected.name}</h2>
              <div className="spec-detail-tags">
                <SpecPill tone={selected.typeTone}>{selected.type}</SpecPill>
                <span className="wp-code">{selected.version}</span>
              </div>
              <p className="spec-v04-muted">Краткое содержание регламента и ключевые разделы 1–6.</p>
              <h4>Связанные шаблоны</h4>
              <ul className="spec-link-list">
                <li>Протокол совещания.docx</li>
                <li>Повестка.docx</li>
              </ul>
              <footer className="spec-detail-actions">
                <button type="button" className="btn-primary">
                  Открыть
                </button>
                <button type="button" className="btn-ghost">
                  Использовать в процессе
                </button>
              </footer>
            </div>
          ) : null
        }
      />
      <SpecBottomRow>
        <SpecPanel title="Популярные материалы">
          <ul className="spec-link-list">
            <li>Регламент совещаний · 128 просмотров</li>
          </ul>
        </SpecPanel>
        <SpecPanel title="Недавно обновлённые">
          <ul className="spec-link-list">
            <li>{selected?.name} · {selected?.updated}</li>
          </ul>
        </SpecPanel>
        <SpecAskOrchestratorBlock placeholder="Найти регламент по совещаниям" chips={ASK_CHIPS.knowledge} onSubmit={ask} />
      </SpecBottomRow>
    </div>
  )
}
