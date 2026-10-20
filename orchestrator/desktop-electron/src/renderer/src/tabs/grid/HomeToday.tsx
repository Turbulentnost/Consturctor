import { useMemo, useState } from 'react'
import type { UserProfile } from '../../api/types'
import type { SpecMailRow } from '../../workplace/specV04DemoData'

type TodayRow = { id: string; title: string; status: string; deadline?: string }
import type { SpecSummaryTile } from '../../workplace/specV04Shell'
import type { TodayPreparedDecisionRow } from '../../workplace/useTodayPreparedDecisions'
import { useTodayPlanTimeline } from '../../workplace/useTodayPlanTimeline'
import { userGivenName } from '../../workplace/userContext'
import type { TodayPlanBlock } from './todayDemoData'

const DAY_START = 8
const DAY_END = 18
const PX = 48

function fmtHour(hour: number): string {
  const h = Math.floor(hour)
  const m = Math.round((hour - h) * 60) % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

function initialsOf(name: string): string {
  const parts = name.replace(/[.]/g, ' ').split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + (parts[1][0] || '')).toUpperCase()
}

function colorFor(seed: string): string {
  const colors = ['#3f3f46', '#1f4b3a', '#1e3a5f', '#5b3a29', '#3b2f4a', '#3f2f2a']
  let hash = 0
  for (const ch of seed) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return colors[hash % colors.length]
}

function pillClass(status: string): string {
  if (/выполн|готово/i.test(status)) return 'ht-pill ht-pill-done'
  if (/нов/i.test(status)) return 'ht-pill ht-pill-new'
  if (/работ/i.test(status)) return 'ht-pill ht-pill-work'
  return 'ht-pill ht-pill-wait'
}

function toneOf(block: TodayPlanBlock): string {
  if (block.lane === 'lunch' || block.who === 'ai' || block.kind === 'reg') return 'violet'
  if (block.tone === 'mint' || block.tone === 'teal') return 'green'
  if (block.tone === 'orange' || block.tone === 'pink') return 'sand'
  return 'blue'
}

function plural(n: number, one: string, few: string, many: string): string {
  const n10 = n % 10
  const n100 = n % 100
  if (n10 === 1 && n100 !== 11) return `${n} ${one}`
  if (n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14)) return `${n} ${few}`
  return `${n} ${many}`
}

export function HomeToday({
  user,
  periodDay,
  onPeriodDayChange,
  tiles,
  activeTileIds,
  onTile,
  mailRows,
  mailLoading,
  mailError,
  tasks,
  tasksLoading,
  tasksError,
  projects,
  decisions,
  decisionsLoading,
  onOpenMeetings,
  onOpenDecisions,
  onOpenMail,
  onOpenTask,
  onOpenDecision,
  assignments
}: {
  user: UserProfile
  periodDay: Date
  onPeriodDayChange: (day: Date) => void
  tiles: SpecSummaryTile[]
  activeTileIds: string[]
  onTile: (id: string) => void
  mailRows: SpecMailRow[]
  mailLoading: boolean
  mailError: string
  tasks: TodayRow[]
  tasksLoading: boolean
  tasksError: string
  projects: TodayRow[]
  decisions: TodayPreparedDecisionRow[]
  decisionsLoading: boolean
  onOpenMeetings: () => void
  onOpenDecisions: () => void
  onOpenMail: () => void
  onOpenTask: (row: TodayRow) => void
  onOpenDecision: (row: TodayPreparedDecisionRow) => void
  assignments?: React.ReactNode
}): React.JSX.Element {
  const [scale, setScale] = useState(false)
  const plan = useTodayPlanTimeline(periodDay, { userId: user.id || '', fio: user.fio || '' })
  const now = new Date()
  const nowHour = now.getHours() + now.getMinutes() / 60
  const sameDay =
    periodDay.getFullYear() === now.getFullYear() &&
    periodDay.getMonth() === now.getMonth() &&
    periodDay.getDate() === now.getDate()

  const agenda = useMemo(() => {
    const items = [...plan.meetingBlocks, plan.lunchBlock].filter(Boolean)
    return items.sort((a, b) => a.startHour - b.startHour)
  }, [plan.lunchBlock, plan.meetingBlocks])
  const agentCount = plan.aiBlocks.length

  const next = agenda.find((item) => item.startHour > nowHour)
  const unread = mailRows.filter((row) => row.unread).length
  const lede = next
    ? `Дальше в ${fmtHour(next.startHour)} — ${next.title}. В работе ${plural(tasks.length, 'задача', 'задачи', 'задач')} и ${plural(unread, 'непрочитанное письмо', 'непрочитанных письма', 'непрочитанных писем')}.`
    : `На этот день ${plural(agenda.length, 'событие', 'события', 'событий')} в плане. В работе ${plural(tasks.length, 'задача', 'задачи', 'задач')} и ${plural(unread, 'непрочитанное письмо', 'непрочитанных письма', 'непрочитанных писем')}.`

  const dateLabel = periodDay.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
  const weekday = periodDay.toLocaleDateString('ru-RU', { weekday: 'long' })
  const dateValue = `${periodDay.getFullYear()}-${String(periodDay.getMonth() + 1).padStart(2, '0')}-${String(periodDay.getDate()).padStart(2, '0')}`

  const focusIds = activeTileIds.filter((id) => id !== 'all')
  const focusEvents = focusIds.includes('ev')
  const focusTasks = focusIds.some((id) => id === 'onec' || id === 'onec-from-me')
  const focusMail = focusIds.includes('outlook')

  return (
    <div className="home-today">
      <header className="ht-hello">
        <div>
          <h1>Добрый день, {userGivenName(user.fio || '')}</h1>
          <p>{user.position || user.role || 'Оркестратор должности'}</p>
        </div>
        <div className="ht-hello-date">
          <strong>{dateLabel}</strong>
          <span>{weekday}</span>
          <input
            type="date"
            value={dateValue}
            aria-label="День"
            onChange={(event) => {
              const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(event.target.value)
              if (!match) return
              onPeriodDayChange(new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])))
            }}
          />
        </div>
      </header>
      <p className="ht-lede">{lede}</p>

      <div className="ht-metrics">
        {tiles.map((tile) => {
              const active = focusIds.includes(tile.id) || (tile.id === 'onec' && focusIds.includes('onec-from-me'))
          return (
            <button
              key={tile.id}
              type="button"
              className={`ht-metric ${active ? 'is-on' : ''} ${tile.value === '—' ? 'is-empty' : ''}`}
              title={tile.tooltip || tile.label}
              onClick={() => onTile(tile.id)}
            >
              <span className="ht-metric-value">{tile.value}</span>
              <span className="ht-metric-label">{tile.label}</span>
              <span className="ht-metric-hint">{active ? 'фильтр включён' : tile.hint}</span>
            </button>
          )
        })}
      </div>

      {focusIds.length ? (
        <div className="ht-filter">
          <span>Показан фильтр по выбранной плитке</span>
          <button type="button" onClick={() => onTile('day')}>
            Показать всё
          </button>
        </div>
      ) : null}

      <div className="ht-board">
        <div className="ht-stack">
          {!focusTasks && !focusMail ? (
            <section className="ht-card">
              <div className="ht-card-h">
                <h2>План на день</h2>
                <button className="ht-text" type="button" onClick={() => setScale((value) => !value)}>
                  {scale ? 'Списком' : 'Шкалой'}
                </button>
              </div>
              {plan.meetingsError ? <p className="ht-note">{plan.meetingsError}</p> : null}
              {plan.loading ? <p className="ht-note">Загружаем календарь…</p> : null}
              {scale ? (
                <DayScale blocks={agenda} nowHour={sameDay ? nowHour : null} />
              ) : (
                <Agenda blocks={agenda} nowHour={sameDay ? nowHour : null} onOpenMeetings={onOpenMeetings} />
              )}
              {agentCount ? (
                <p className="ht-note">
                  Регламентных запусков сегодня: {agentCount}. Почасовые срабатывания в план не выводятся.
                </p>
              ) : null}
            </section>
          ) : null}

          {!focusEvents && !focusTasks ? (
            <section className="ht-card">
              <div className="ht-card-h">
                <h2>Письма Outlook</h2>
                <button className="ht-text" type="button" onClick={onOpenMail}>
                  Входящие
                </button>
              </div>
              {mailLoading ? <p className="ht-note">Загружаем почту…</p> : null}
              {mailError ? <p className="ht-note ht-error">{mailError}</p> : null}
              {!mailLoading && !mailError && !mailRows.length ? <p className="ht-note">Писем за этот день нет</p> : null}
              <div className="ht-rows">
                {mailRows.slice(0, 8).map((mail) => (
                  <button key={mail.id} type="button" className={`ht-mail ${mail.unread ? 'is-unread' : ''}`} onClick={onOpenMail}>
                    <span className="ht-avatar" style={{ background: colorFor(mail.sender || '?') }}>
                      {initialsOf(mail.sender || '?')}
                    </span>
                    <span className="ht-main">
                      <span className="ht-mail-top">
                        <span className="ht-title">{mail.sender || 'Без отправителя'}</span>
                        <span className="ht-time">{mail.time}</span>
                      </span>
                      <span className="ht-subject">{mail.subject}</span>
                      {mail.preview || mail.bodyPreview ? (
                        <span className="ht-preview">{mail.preview || mail.bodyPreview}</span>
                      ) : null}
                    </span>
                  </button>
                ))}
              </div>
            </section>
          ) : null}

          {!focusTasks && !focusMail ? (
            <section className="ht-card">
              <div className="ht-card-h">
                <h2>Предстоящие события</h2>
                <button className="ht-text" type="button" onClick={onOpenMeetings}>
                  Все
                </button>
              </div>
              {!agenda.length ? <p className="ht-note">Нет событий на выбранный день</p> : null}
              <div className="ht-rows">
                {agenda
                  .filter((item) => item.lane !== 'lunch' && item.kind !== 'reg')
                  .map((item) => (
                    <button key={item.id} type="button" className="ht-event" onClick={onOpenMeetings}>
                      <span className="ht-time">{fmtHour(item.startHour)}</span>
                      <span className="ht-main">
                        <span className="ht-title">{item.title}</span>
                        <span className="ht-preview">
                          {fmtHour(item.startHour)}–{fmtHour(item.endHour)}
                          {item.subtitle ? ` · ${item.subtitle}` : ''}
                        </span>
                      </span>
                    </button>
                  ))}
              </div>
            </section>
          ) : null}
        </div>

        <div className="ht-stack">
          {assignments && !focusEvents && !focusMail ? assignments : null}
          {!focusEvents && !focusMail ? (
            <section className="ht-card">
              <div className="ht-card-h">
                <h2>Задачи 1С на сегодня</h2>
                <span className="ht-quiet">{tasksLoading ? '…' : tasks.length}</span>
              </div>
              {tasksError ? <p className="ht-note ht-error">{tasksError}</p> : null}
              {!tasksLoading && !tasks.length ? <p className="ht-note">Нет задач на этот день</p> : null}
              <div className="ht-rows">
                {tasks.slice(0, 8).map((task) => (
                  <button key={task.id} type="button" className="ht-task" onClick={() => onOpenTask(task)}>
                    <span className="ht-main">
                      <span className="ht-title">{task.title}</span>
                      <span className="ht-preview">1С · {task.deadline || 'без срока'}</span>
                    </span>
                    <span className={pillClass(task.status)}>{task.status}</span>
                  </button>
                ))}
              </div>
            </section>
          ) : null}

          {projects.length && !focusEvents && !focusMail ? (
            <section className="ht-card">
              <div className="ht-card-h">
                <h2>Проектные задачи</h2>
                <span className="ht-quiet">{projects.length}</span>
              </div>
              <div className="ht-rows">
                {projects.slice(0, 6).map((task) => (
                  <button key={task.id} type="button" className="ht-task" onClick={() => onOpenTask(task)}>
                    <span className="ht-main">
                      <span className="ht-title">{task.title}</span>
                      <span className="ht-preview">Turbo · {task.deadline || 'без срока'}</span>
                    </span>
                    <span className={pillClass(task.status)}>{task.status}</span>
                  </button>
                ))}
              </div>
            </section>
          ) : null}

          {!focusEvents && !focusMail ? (
            <section className="ht-card">
              <div className="ht-card-h">
                <h2>Подготовленные решения</h2>
                <button className="ht-text" type="button" onClick={onOpenDecisions}>
                  Открыть
                </button>
              </div>
              {decisionsLoading ? <p className="ht-note">Загружаем…</p> : null}
              {!decisionsLoading && !decisions.length ? (
                <p className="ht-note">Нет подготовленных решений за выбранный день</p>
              ) : null}
              {decisions.slice(0, 4).map((item) => (
                <button key={item.id} type="button" className="ht-decision" onClick={() => onOpenDecision(item)}>
                  <span className="ht-pill">{item.tag || item.status}</span>
                  <span className="ht-title">{item.title}</span>
                  {item.subtitle ? <span className="ht-preview">{item.subtitle}</span> : null}
                </button>
              ))}
            </section>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function Agenda({
  blocks,
  nowHour,
  onOpenMeetings
}: {
  blocks: TodayPlanBlock[]
  nowHour: number | null
  onOpenMeetings: () => void
}): React.JSX.Element {
  const nodes: React.ReactNode[] = []
  let placed = nowHour == null
  const marker =
    nowHour == null ? null : (
      <div className="ht-now" key="now">
        <span>Сейчас</span>
        <i />
        <b>{fmtHour(nowHour)}</b>
      </div>
    )
  for (const item of blocks) {
    if (!placed && marker && item.startHour >= (nowHour as number)) {
      nodes.push(marker)
      placed = true
    }
    const state =
      nowHour == null ? '' : nowHour >= item.endHour ? 'is-past' : nowHour >= item.startHour ? 'is-now' : ''
    nodes.push(
      <button key={item.id} type="button" className={`ht-agenda ${state}`} onClick={onOpenMeetings}>
        <span className="ht-agenda-time">{fmtHour(item.startHour)}</span>
        <span className={`ht-agenda-body tone-${toneOf(item)}`}>
          <span className="ht-agenda-top">
            <span className="ht-agenda-title">{item.title}</span>
            <span className="ht-tag">{item.who === 'ai' ? 'Агент' : 'Календарь'}</span>
          </span>
          <span className="ht-preview">
            {fmtHour(item.startHour)}–{fmtHour(item.endHour)}
            {item.subtitle ? ` · ${item.subtitle}` : ''}
          </span>
        </span>
      </button>
    )
  }
  if (!placed && marker) nodes.push(marker)
  return <div className="ht-agenda-list">{nodes}</div>
}

function DayScale({ blocks, nowHour }: { blocks: TodayPlanBlock[]; nowHour: number | null }): React.JSX.Element {
  const hours = Array.from({ length: DAY_END - DAY_START + 1 }, (_, index) => DAY_START + index)
  const span = DAY_END - DAY_START
  return (
    <div className="ht-scale" style={{ ['--px' as string]: `${PX}px`, ['--h' as string]: `${span * PX}px` }}>
      <div>
        <div className="ht-scale-spacer" />
        <div className="ht-scale-hours">
          {hours.map((hour) => (
            <span key={hour} style={{ top: `calc(${hour - DAY_START} * var(--px))` }}>
              {String(hour).padStart(2, '0')}:00
            </span>
          ))}
        </div>
      </div>
      <div>
        <div className="ht-lane-labels">
          <span>Календарь</span>
          <span>Агенты</span>
        </div>
        <div className="ht-lanes">
          {nowHour != null && nowHour >= DAY_START && nowHour <= DAY_END ? (
            <div className="ht-scale-now" style={{ top: `calc(${nowHour - DAY_START} * var(--px))` }} />
          ) : null}
          {(['calendar', 'agent'] as const).map((lane) => (
            <div key={lane} className="ht-lane">
              {blocks
                .filter((item) => (lane === 'agent' ? item.who === 'ai' : item.who !== 'ai'))
                .map((item) => (
                  <div
                    key={item.id}
                    className={`ht-block tone-${toneOf(item)}`}
                    style={{
                      top: `calc(${Math.max(0, item.startHour - DAY_START)} * var(--px) + 2px)`,
                      height: `calc(${Math.max(0.4, item.endHour - item.startHour)} * var(--px) - 4px)`
                    }}
                  >
                    <span>{fmtHour(item.startHour)}</span>
                    <strong>{item.title}</strong>
                  </div>
                ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
