import { useCallback, useEffect, useState } from 'react'
import { Plus } from 'lucide-react'
import type { UserProfile } from '../../api/types'
import type { SpecMailRow } from '../../workplace/specV04DemoData'
import { SpecPill } from '../../workplace/specV04Components'
import { MailIncomingCreateDialog } from './MailIncomingCreateDialog'
import {
  displayOutlookMail,
  hasOutlookEntryId,
  markOutlookMailRead,
  type OutlookMailDetail
} from '../../utils/outlookMailActions'
import { decodeMimeHeader } from '../../utils/mimeHeader'
import { MailLetterTabs, useMailDetail } from './MailLetterTabs'
import { formatMailTime } from '../../utils/outlookMail'
import './mailGrid.css'

export function MailDetailPanel({
  mail,
  user,
  onPatchRow,
  onAskOrchestrator
}: {
  mail: SpecMailRow
  user: UserProfile
  onPatchRow?: (id: string, patch: Partial<SpecMailRow>) => void
  onAskOrchestrator?: (message: string) => void
}): React.JSX.Element {
  const loaded = useMailDetail(mail)
  const [detail, setDetail] = useState<OutlookMailDetail | null>(null)
  const [busy, setBusy] = useState('')
  const [note, setNote] = useState('')
  const [incomingDialogOpen, setIncomingDialogOpen] = useState(false)

  const showNote = useCallback((text: string, isError = false): void => {
    setNote(isError ? text : text)
    if (text) {
      window.setTimeout(() => setNote(''), 6000)
    }
  }, [])

  const canOutlookActions = hasOutlookEntryId(mail)

  useEffect(() => {
    setNote('')
  }, [mail.id])

  useEffect(() => {
    setDetail(loaded.detail)
    if (loaded.detail && hasOutlookEntryId(mail) && typeof loaded.detail.unread === 'boolean') {
      onPatchRow?.(mail.id, {
        unread: loaded.detail.unread,
        status: loaded.detail.unread ? 'Непрочитано' : 'Прочитано',
        stTone: loaded.detail.unread ? 'orange' : 'blue'
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sync once per loaded letter
  }, [loaded.detail])

  useEffect(() => {
    if (loaded.error) showNote(loaded.error, true)
  }, [loaded.error, showNote])

  const runAction = async (label: string, fn: () => Promise<{ ok: boolean; error?: string }>): Promise<void> => {
    if (busy) return
    setBusy(label)
    try {
      const res = await fn()
      if (res.ok) {
        showNote(
          label === 'open' || label === 'reply' || label === 'reply_all'
            ? 'Открыто в Outlook'
            : 'Готово'
        )
      }
      else showNote(res.error || 'Ошибка', true)
    } finally {
      setBusy('')
    }
  }

  const openCreateIncoming = (): void => {
    if (busy) return
    setIncomingDialogOpen(true)
  }

  return (
    <>
      <div className="spec-detail-card spec-mail-detail-grid wp-card">
        <header className="spec-mail-detail-grid__head">
          <h2>{decodeMimeHeader(mail.subject)}</h2>
          <p className="spec-v04-muted">
            От: {decodeMimeHeader(mail.sender)} · {formatMailTime(mail.time)}
          </p>
          <div className="spec-detail-tags">
            <SpecPill tone={mail.priTone}>{mail.priority}</SpecPill>
            <SpecPill tone={mail.stTone}>{mail.status}</SpecPill>
            <SpecPill tone={mail.catTone}>{mail.category}</SpecPill>
          </div>
        </header>

        <div className="spec-mail-detail-grid__content">
          <MailLetterTabs mail={mail} detail={detail} loading={loaded.loading} onToast={showNote} />
        </div>

        <footer className="spec-mail-detail-grid__actions">
          {note ? <p className="spec-v04-muted spec-mail-detail-grid__note">{note}</p> : null}
          {!canOutlookActions ? (
            <p className="spec-v04-muted spec-mail-detail-grid__note">
              Ответ / входящая в 1С — через Outlook COM (это письмо только из IMAP).
            </p>
          ) : null}
          <button
            type="button"
            className="spec-btn-launch"
            disabled={Boolean(busy)}
            onClick={() => void runAction('reply', () => displayOutlookMail(mail, 'reply'))}
          >
            {busy === 'reply' ? '…' : 'Ответить'}
          </button>
          <button
            type="button"
            className="spec-btn-outline"
            disabled={Boolean(busy)}
            onClick={() => void runAction('reply_all', () => displayOutlookMail(mail, 'reply_all'))}
          >
            {busy === 'reply_all' ? '…' : 'Ответить всем'}
          </button>
          <button
            type="button"
            className="spec-btn-launch"
            disabled={Boolean(busy)}
            onClick={() => void runAction('open', () => displayOutlookMail(mail, 'open'))}
          >
            {busy === 'open' ? '…' : 'В Outlook'}
          </button>
          {onAskOrchestrator ? (
            <button
              type="button"
              className="spec-btn-outline"
              disabled={Boolean(busy)}
              onClick={() =>
                onAskOrchestrator(
                  `Помоги с письмом «${decodeMimeHeader(mail.subject)}» от ${decodeMimeHeader(mail.sender)}`
                )
              }
            >
              Передать ИИ
            </button>
          ) : (
            <span aria-hidden />
          )}
          <div className="spec-mail-read-row">
            <button
              type="button"
              className="spec-btn-launch spec-mail-read-btn"
              disabled={Boolean(busy)}
              onClick={() =>
                void runAction('read', async () => {
                  if (!canOutlookActions) {
                    return {
                      ok: false,
                      error: 'Это письмо из IMAP. Статус «прочитано» меняется только у письма в Outlook.'
                    }
                  }
                  const res = await markOutlookMailRead(mail, false)
                  if (res.ok) {
                    onPatchRow?.(mail.id, {
                      unread: false,
                      status: 'Прочитано',
                      stTone: 'blue',
                      priority: 'Средний',
                      priTone: 'orange'
                    })
                    setDetail((prev) => (prev ? { ...prev, unread: false } : prev))
                  }
                  return res
                })
              }
            >
              Прочитано
            </button>
            <button
              type="button"
              className="spec-btn-outline spec-mail-read-btn"
              disabled={Boolean(busy)}
              onClick={() =>
                void runAction('unread', async () => {
                  if (!canOutlookActions) {
                    return {
                      ok: false,
                      error: 'Это письмо из IMAP. Статус «прочитано» меняется только у письма в Outlook.'
                    }
                  }
                  const res = await markOutlookMailRead(mail, true)
                  if (res.ok) {
                    onPatchRow?.(mail.id, {
                      unread: true,
                      status: 'Непрочитано',
                      stTone: 'orange',
                      priority: 'Высокий',
                      priTone: 'red'
                    })
                    setDetail((prev) => (prev ? { ...prev, unread: true } : prev))
                  }
                  return res
                })
              }
            >
              Непрочитано
            </button>
          </div>
          <button
            type="button"
            className="spec-btn-launch spec-mail-incoming-btn"
            disabled={Boolean(busy)}
            title="Заполнить маршрут и создать входящую в 1С через OData (как agent-pochta)"
            onClick={openCreateIncoming}
          >
            <Plus size={14} aria-hidden /> Зарегистрировать входящую
          </button>
        </footer>
      </div>
      <MailIncomingCreateDialog
        open={incomingDialogOpen}
        mail={mail}
        user={user}
        detail={detail}
        onClose={() => setIncomingDialogOpen(false)}
        onCreated={(message, isError) => showNote(message, Boolean(isError))}
      />
    </>
  )
}
