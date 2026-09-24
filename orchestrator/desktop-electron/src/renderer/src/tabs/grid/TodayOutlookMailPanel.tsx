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
import { mailPartyLabel } from '../../workplace/specV04Mappers'
import {
  displayOutlookMail,
  hasOutlookEntryId,
  markOutlookMailRead,
  saveOutlookAttachment
} from '../../utils/outlookMailActions'
import { openAttachmentExternally } from '../../utils/mailAttachmentPreview'
import { decodeMimeHeader } from '../../utils/mimeHeader'
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
  return row.preview || row.body?.replace(/\s+/g, ' ').slice(0, 140) || decodeMimeHeader(row.subject)
}

function TodayCellText({ text }: { text: string }): React.JSX.Element {
  return (
    <span className="today-cell-text" title={text}>
      {text}
    </span>
  )
}

function OutlookCommandBar({
  row,
  busy,
  onAction
}: {
  row: SpecMailRow | null
  busy: string
  onAction: (mode: 'reply' | 'reply_all' | 'forward' | 'read' | 'open') => void
}): React.JSX.Element {
  const canAct = Boolean(row && hasOutlookEntryId(row))
  return (
    <div className="today-outlook-command-bar" role="toolbar" aria-label="Действия с письмом">
      <button
        type="button"
        className="today-outlook-cmd today-outlook-cmd-primary"
        disabled={!canAct || Boolean(busy)}
        onClick={() => onAction('reply')}
      >
        <Reply size={16} strokeWidth={2} aria-hidden />
        {busy === 'reply' ? '…' : 'Ответить'}
      </button>
      <button
        type="button"
        className="today-outlook-cmd"
        disabled={!canAct || Boolean(busy)}
        onClick={() => onAction('reply_all')}
      >
        <ReplyAll size={16} strokeWidth={2} aria-hidden />
        {busy === 'reply_all' ? '…' : 'Ответить всем'}
      </button>
      <button
        type="button"
        className="today-outlook-cmd"
        disabled={!canAct || Boolean(busy)}
        onClick={() => onAction('forward')}
      >
        <Forward size={16} strokeWidth={2} aria-hidden />
        {busy === 'forward' ? '…' : 'Переслать'}
      </button>
      <button
        type="button"
        className="today-outlook-cmd"
        disabled={!canAct || Boolean(busy)}
        onClick={() => onAction('read')}
      >
        <Mail size={16} strokeWidth={2} aria-hidden />
        {busy === 'read' ? '…' : 'Прочитано'}
      </button>
    </div>
  )
}

function OutlookReadingPane({
  row,
  busy,
  onAction,
  onOpenAttachment
}: {
  row: SpecMailRow
  busy: string
  onAction: (mode: 'reply' | 'reply_all' | 'forward' | 'read' | 'open') => void
  onOpenAttachment: (fileName: string, index: number) => void
}): React.JSX.Element {
  const attachments = row.attachments || []
  return (
    <article className="today-outlook-reading">
      <OutlookCommandBar row={row} busy={busy} onAction={onAction} />
      <div className="today-outlook-reading-card">
        <header className="today-outlook-reading-head">
          <div className="today-outlook-avatar" aria-hidden>
            {senderInitials(decodeMimeHeader(row.sender))}
          </div>
          <div className="today-outlook-reading-meta">
            <div className="today-outlook-reading-title-row">
              <strong className="today-outlook-sender">{decodeMimeHeader(row.sender)}</strong>
              <span className="today-outlook-when">{row.receivedLabel || row.time}</span>
            </div>
            {row.to ? (
              <div className="today-outlook-recipients">
                <span className="today-outlook-recipients-label">Кому</span>
                <span className="today-outlook-to">{row.to}</span>
              </div>
            ) : null}
            <div className="today-outlook-reading-tags">
              <SpecPill tone={row.stTone}>{row.status}</SpecPill>
            </div>
          </div>
        </header>
        <h2 className="today-outlook-subject">{decodeMimeHeader(row.subject)}</h2>
        {attachments.length ? (
          <div className="today-outlook-attachments-wrap">
            <div className="today-outlook-attachments-label">
              <Paperclip size={14} strokeWidth={2} aria-hidden />
              Вложения ({attachments.length})
            </div>
            <ul className="today-outlook-attachments">
              {attachments.map((file, index) => (
                <li key={file.name} className="today-outlook-attachment">
                  <button
                    type="button"
                    className="today-outlook-attachment-btn"
                    disabled={Boolean(busy)}
                    title={`Открыть ${file.name}`}
                    onClick={() => onOpenAttachment(file.name, index + 1)}
                  >
                    <TodayFileIcon name={file.name} size={32} />
                    <span>{file.name}</span>
                  </button>
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
  hint,
  onPatchRow
}: {
  rows: SpecMailRow[]
  compactRows: SpecMailRow[]
  loading?: boolean
  error?: string
  hint?: string
  onPatchRow?: (id: string, patch: Partial<SpecMailRow>) => void
}): React.JSX.Element {
  const expanded = useTodayWidgetExpanded()
  const [selectedId, setSelectedId] = useState(rows[0]?.id || '')
  const [filter, setFilter] = useState<'all' | 'unread'>('all')
  const [busy, setBusy] = useState('')
  const [actionNote, setActionNote] = useState('')

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

  const runMailAction = async (
    mode: 'reply' | 'reply_all' | 'forward' | 'read' | 'open'
  ): Promise<void> => {
    if (!selected || busy) return
    if (!hasOutlookEntryId(selected)) {
      setActionNote('Действие доступно только для писем Outlook COM')
      return
    }
    setBusy(mode)
    try {
      if (mode === 'read') {
        const res = await markOutlookMailRead(selected, false)
        if (res.ok) {
          onPatchRow?.(selected.id, { unread: false, status: 'Прочитано', stTone: 'blue' })
          setActionNote('Отмечено прочитанным')
        } else setActionNote(res.error || 'Ошибка')
        return
      }
      const displayMode = mode === 'open' ? 'open' : mode
      const res = await displayOutlookMail(selected, displayMode)
      setActionNote(res.ok ? 'Открыто в Outlook' : res.error || 'Ошибка')
    } finally {
      setBusy('')
      window.setTimeout(() => setActionNote(''), 4000)
    }
  }

  const openAttachment = async (fileName: string, index: number): Promise<void> => {
    if (!selected || busy) return
    if (!hasOutlookEntryId(selected)) {
      setActionNote('Вложения — только Outlook COM')
      return
    }
    setBusy('attachment')
    try {
      const saved = await saveOutlookAttachment(selected, index)
      if (!saved.ok) {
        setActionNote(saved.error)
        return
      }
      const opened = await openAttachmentExternally(saved.path)
      setActionNote(opened.ok ? `Открыто: ${fileName}` : opened.error || 'Ошибка')
    } finally {
      setBusy('')
      window.setTimeout(() => setActionNote(''), 4000)
    }
  }

  if (!expanded) {
    const tableRows = compactRows
    const body = ((): React.ReactNode => {
      if (loading) {
        return (
          <tr>
            <td colSpan={4} className="today-table-status">
              Загружаем…
            </td>
          </tr>
        )
      }
      if (error) {
        return (
          <tr>
            <td colSpan={4} className="today-table-status today-table-error">
              {error}
            </td>
          </tr>
        )
      }
      if (!tableRows.length) {
        return (
          <tr>
            <td colSpan={4} className="today-table-status">
              Нет писем мне и от меня за выбранный день
            </td>
          </tr>
        )
      }
      return tableRows.map((row) => (
        <tr key={row.id}>
          <td>
            <TodayCellText text={mailPartyLabel(row)} />
          </td>
          <td>
            <TodayCellText text={decodeMimeHeader(row.subject)} />
          </td>
          <td>
            <TodayCellText text={row.time} />
          </td>
          <td>
            <SpecPill tone={row.stTone}>{row.status}</SpecPill>
          </td>
        </tr>
      ))
    })()

    return (
      <SpecPanel title="Письма из Outlook">
        <div className="spec-v04-table-wrap today-table-scroll">
          <table className="today-mini-table">
            <thead>
              <tr>
                <th>От / Кому</th>
                <th>Тема</th>
                <th>Время</th>
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
              <span className="today-outlook-folder">Входящие и отправленные</span>
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
                    : error || 'Нет писем мне и от меня за выбранный день'}
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
                        <span className="today-outlook-list-sender">{mailPartyLabel(row)}</span>
                        <span className="today-outlook-list-subject-wrap">
                          <span className="today-outlook-list-subject">{decodeMimeHeader(row.subject)}</span>
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
            <>
              {actionNote ? (
                <p className="today-outlook-action-note spec-v04-muted">{actionNote}</p>
              ) : null}
              <OutlookReadingPane
                row={selected}
                busy={busy}
                onAction={(mode) => void runMailAction(mode)}
                onOpenAttachment={(name, index) => void openAttachment(name, index)}
              />
            </>
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
