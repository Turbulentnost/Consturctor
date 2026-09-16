import { useEffect, useMemo, useState } from 'react'
import {
  Forward,
  Mail,
  Paperclip,
  Reply,
  ReplyAll,
  Search
} from 'lucide-react'
import { SpecPanel, SpecPill } from '../../workplace/specV04Components'
import type { SpecMailRow } from '../../workplace/specV04DemoData'
import { useTodayWidgetExpanded } from './TodayWidgetExpandContext'
import { TodayFileIcon } from './todayFileIcon'

function senderInitials(name: string): string {
  const parts = name
    .replace(/[«»"]/g, '')
    .split(/[\s,;]+/)
    .map((part) => part.trim())
    .filter(Boolean)
  if (!parts.length) return 'П'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return `${parts[0][0] || ''}${parts[1][0] || ''}`.toUpperCase()
}

function mailPreview(row: SpecMailRow): string {
  return row.preview || row.body?.replace(/\s+/g, ' ').slice(0, 140) || row.subject
}

function TodayCellText({ text }: { text: string }): React.JSX.Element {
  return (
    <span className="today-cell-text" title={text}>
      {text}
    </span>
  )
}

function OutlookCommandBar(): React.JSX.Element {
  return (
    <div className="today-outlook-command-bar" role="toolbar" aria-label="Действия с письмом">
      <button type="button" className="today-outlook-cmd today-outlook-cmd-primary">
        <Reply size={16} strokeWidth={2} aria-hidden />
        Ответить
      </button>
      <button type="button" className="today-outlook-cmd">
        <ReplyAll size={16} strokeWidth={2} aria-hidden />
        Ответить всем
      </button>
      <button type="button" className="today-outlook-cmd">
        <Forward size={16} strokeWidth={2} aria-hidden />
        Переслать
      </button>
    </div>
  )
}

function OutlookReadingPane({ row }: { row: SpecMailRow }): React.JSX.Element {
  const attachments = row.attachments || []
  return (
    <article className="today-outlook-reading">
      <OutlookCommandBar />
      <div className="today-outlook-reading-card">
        <header className="today-outlook-reading-head">
          <div className="today-outlook-avatar" aria-hidden>
            {senderInitials(row.sender)}
          </div>
          <div className="today-outlook-reading-meta">
            <div className="today-outlook-reading-title-row">
              <strong className="today-outlook-sender">{row.sender}</strong>
              <span className="today-outlook-when">{row.receivedLabel || row.time}</span>
            </div>
            {row.to ? (
              <div className="today-outlook-recipients">
                <span className="today-outlook-recipients-label">Кому</span>
                <span className="today-outlook-to">{row.to}</span>
              </div>
            ) : null}
            <div className="today-outlook-reading-tags">
              <SpecPill tone={row.priTone}>{row.priority}</SpecPill>
              <SpecPill tone={row.stTone}>{row.status}</SpecPill>
            </div>
          </div>
        </header>
        <h2 className="today-outlook-subject">{row.subject}</h2>
        {attachments.length ? (
          <div className="today-outlook-attachments-wrap">
            <div className="today-outlook-attachments-label">
              <Paperclip size={14} strokeWidth={2} aria-hidden />
              Вложения ({attachments.length})
            </div>
            <ul className="today-outlook-attachments">
              {attachments.map((file) => (
                <li key={file.name} className="today-outlook-attachment">
                  <TodayFileIcon name={file.name} size={32} />
                  <span title={file.name}>{file.name}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <div className="today-outlook-body">
          {row.body ? (
            row.body.split(/\n{2,}/).map((block, index) => <p key={index}>{block}</p>)
          ) : (
            <p className="today-outlook-body-empty">Текст письма недоступен.</p>
          )}
        </div>
      </div>
    </article>
  )
}

export function TodayOutlookMailPanel({
  rows,
  compactRows,
  loading,
  error,
  hint
}: {
  rows: SpecMailRow[]
  compactRows: SpecMailRow[]
  loading?: boolean
  error?: string
  hint?: string
}): React.JSX.Element {
  const expanded = useTodayWidgetExpanded()
  const [selectedId, setSelectedId] = useState(rows[0]?.id || '')
  const [filter, setFilter] = useState<'all' | 'unread'>('all')

  useEffect(() => {
    if (!rows.length) {
      setSelectedId('')
      return
    }
    if (!rows.some((row) => row.id === selectedId)) {
      setSelectedId(rows[0].id)
    }
  }, [rows, selectedId])

  const visibleRows = useMemo(() => {
    if (filter === 'unread') return rows.filter((row) => row.unread)
    return rows
  }, [filter, rows])

  const selected = useMemo(
    () => visibleRows.find((row) => row.id === selectedId) || visibleRows[0] || rows[0],
    [rows, selectedId, visibleRows]
  )

  const unreadCount = useMemo(() => rows.filter((row) => row.unread).length, [rows])

  if (!expanded) {
    const tableRows = compactRows
    const body = ((): React.ReactNode => {
      if (loading) {
        return (
          <tr>
            <td colSpan={5} className="today-table-status">
              Загружаем…
            </td>
          </tr>
        )
      }
      if (error) {
        return (
          <tr>
            <td colSpan={5} className="today-table-status today-table-error">
              {error}
            </td>
          </tr>
        )
      }
      if (!tableRows.length) {
        return (
          <tr>
            <td colSpan={5} className="today-table-status">
              Нет писем во входящих за выбранный день
            </td>
          </tr>
        )
      }
      return tableRows.map((row) => (
        <tr key={row.id}>
          <td>
            <TodayCellText text={row.sender} />
          </td>
          <td>
            <TodayCellText text={row.subject} />
          </td>
          <td>
            <TodayCellText text={row.time} />
          </td>
          <td>
            <SpecPill tone={row.priTone}>{row.priority}</SpecPill>
          </td>
          <td>
            <SpecPill tone={row.stTone}>{row.status}</SpecPill>
          </td>
        </tr>
      ))
    })()

    return (
      <SpecPanel
        title="Письма из Outlook"
        extra={hint ? <span className="spec-v04-muted today-table-hint">{hint}</span> : undefined}
      >
        <div className="spec-v04-table-wrap today-table-scroll">
          <table className="today-mini-table">
            <thead>
              <tr>
                <th>Отправитель</th>
                <th>Тема</th>
                <th>Время</th>
                <th>Приоритет</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </SpecPanel>
    )
  }

  return (
    <div className="today-outlook-shell">
      <div className="today-outlook-reader">
        <aside className="today-outlook-list-pane" aria-label="Список писем">
          <div className="today-outlook-list-toolbar">
            <div className="today-outlook-folder-row">
              <Mail size={16} strokeWidth={2} aria-hidden />
              <span className="today-outlook-folder">Входящие</span>
              <span className="today-outlook-folder-count">{rows.length}</span>
            </div>
            {hint ? <span className="today-outlook-folder-hint">{hint}</span> : null}
          </div>
          <div className="today-outlook-list-filters">
            <button
              type="button"
              className={filter === 'all' ? 'is-active' : ''}
              onClick={() => setFilter('all')}
            >
              Все
            </button>
            <button
              type="button"
              className={filter === 'unread' ? 'is-active' : ''}
              onClick={() => setFilter('unread')}
            >
              Непрочитанные{unreadCount ? ` (${unreadCount})` : ''}
            </button>
          </div>
          <label className="today-outlook-list-search">
            <Search size={14} strokeWidth={2} aria-hidden />
            <input type="search" placeholder="Поиск в письмах" aria-label="Поиск в письмах" />
          </label>
          <div className="today-outlook-list-head" aria-hidden>
            <span className="col-from">От</span>
            <span className="col-subject">Тема</span>
            <span className="col-time">Получено</span>
          </div>
          <div className="today-outlook-list-scroll">
            {!visibleRows.length ? (
              <p className="today-table-status today-outlook-list-empty">
                {loading
                  ? 'Загружаем…'
                  : filter === 'unread'
                    ? 'Нет непрочитанных писем'
                    : error || 'Нет писем во входящих за выбранный день'}
              </p>
            ) : (
              <ul className="today-outlook-list-rows">
                {visibleRows.map((row) => {
                  const active = selected?.id === row.id
                  const hasFiles = Boolean(row.attachments?.length)
                  return (
                    <li key={row.id}>
                      <button
                        type="button"
                        className={[
                          'today-outlook-list-item',
                          active ? 'is-active' : '',
                          row.unread ? 'is-unread' : ''
                        ]
                          .filter(Boolean)
                          .join(' ')}
                        onClick={() => setSelectedId(row.id)}
                      >
                        <span className="today-outlook-list-flags">
                          {row.unread ? <span className="today-outlook-unread-dot" aria-hidden /> : null}
                          {hasFiles ? (
                            <Paperclip size={12} strokeWidth={2} className="today-outlook-flag-clip" aria-hidden />
                          ) : null}
                        </span>
                        <span className="today-outlook-list-sender">{row.sender}</span>
                        <span className="today-outlook-list-subject-wrap">
                          <span className="today-outlook-list-subject">{row.subject}</span>
                          <span className="today-outlook-list-preview">{mailPreview(row)}</span>
                        </span>
                        <span className="today-outlook-list-time">{row.time}</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        </aside>
        <section className="today-outlook-pane">
          {selected ? (
            <OutlookReadingPane row={selected} />
          ) : (
            <div className="today-outlook-empty-pane">
              <Mail size={40} strokeWidth={1.5} aria-hidden />
              <p>Выберите письмо для просмотра</p>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
