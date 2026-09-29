import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Download, ExternalLink, FileText, Paperclip, X } from 'lucide-react'
import type { SpecMailRow } from '../../workplace/specV04DemoData'
import {
  fetchOutlookMailDetail,
  hasOutlookEntryId,
  saveOutlookAttachment,
  type OutlookMailAttachment,
  type OutlookMailDetail
} from '../../utils/outlookMailActions'
import { fetchImapMessage, parseImapUid } from '../../utils/imapMail'
import { decodeMimeHeader } from '../../utils/mimeHeader'
import {
  downloadAttachmentCopy,
  formatAttachmentSize,
  loadAttachmentPreview,
  openAttachmentExternally,
  type MailAttachmentPreview
} from '../../utils/mailAttachmentPreview'
import { PreviewPane } from './MailAttachmentsModal'
import { TodayFileIcon } from './todayFileIcon'
import './mailGrid.css'

/** Full letter (body + attachments): Outlook COM by entry id, otherwise IMAP by uid. */
export function useMailDetail(mail: SpecMailRow | null): {
  detail: OutlookMailDetail | null
  loading: boolean
  error: string
} {
  const [detail, setDetail] = useState<OutlookMailDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    setDetail(null)
    setError('')
    if (!mail) {
      setLoading(false)
      return
    }
    setLoading(true)
    const load = async (): Promise<void> => {
      if (hasOutlookEntryId(mail)) {
        const res = await fetchOutlookMailDetail(mail)
        if (!alive) return
        if (res.ok) setDetail(res.detail)
        else setError(res.error)
        return
      }
      const uid = parseImapUid(mail)
      if (!uid) return
      const res = await fetchImapMessage(uid)
      if (!alive) return
      if (!res.ok) {
        setError(res.error || 'IMAP: не удалось загрузить письмо')
        return
      }
      setDetail({
        entryId: '',
        subject: decodeMimeHeader(res.subject || mail.subject),
        sender: decodeMimeHeader(res.from || mail.sender),
        senderEmail: (String(res.from || '').match(/[\w.+-]+@[\w.-]+\.\w+/) || [''])[0],
        body: res.body,
        bodyPreview: res.body.slice(0, 400),
        unread: Boolean(mail.unread),
        attachments: []
      })
    }
    void load().finally(() => {
      if (alive) setLoading(false)
    })
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload only when selection changes
  }, [mail?.id, mail?.entryId, mail?.imapUid])

  return { detail, loading, error }
}

export function mailBodyText(mail: SpecMailRow, detail: OutlookMailDetail | null): string {
  return (
    detail?.body?.trim() ||
    detail?.bodyPreview?.trim() ||
    mail.body?.trim() ||
    mail.bodyPreview?.trim() ||
    mail.preview?.trim() ||
    ''
  )
}

export function mailAttachments(mail: SpecMailRow, detail: OutlookMailDetail | null): OutlookMailAttachment[] {
  if (detail?.attachments?.length) return detail.attachments
  const names = mail.attachmentNames?.length
    ? mail.attachmentNames
    : (mail.attachments || []).map((file) => file.name)
  return names.filter(Boolean).map((name, idx) => ({ index: idx + 1, file_name: name }))
}

export function MailLetterTabs({
  mail,
  detail,
  loading,
  onToast
}: {
  mail: SpecMailRow
  detail: OutlookMailDetail | null
  loading: boolean
  onToast: (text: string, isError?: boolean) => void
}): React.JSX.Element {
  const [tab, setTab] = useState<'text' | 'files'>('text')
  const [busy, setBusy] = useState('')
  const [viewer, setViewer] = useState<{
    att: OutlookMailAttachment
    path: string
    preview: MailAttachmentPreview
  } | null>(null)

  useEffect(() => {
    setTab('text')
    setViewer(null)
  }, [mail.id])

  const body = mailBodyText(mail, detail)
  const attachments = mailAttachments(mail, detail)
  const canFiles = hasOutlookEntryId(mail)

  const download = async (att: OutlookMailAttachment): Promise<boolean> => {
    const saved = await saveOutlookAttachment(mail, att.index)
    if (!saved.ok) {
      onToast(saved.error, true)
      return false
    }
    const res = await downloadAttachmentCopy(saved.path, att.file_name)
    if (res.canceled) return false
    if (!res.ok) {
      onToast(res.error || 'Не удалось сохранить файл', true)
      return false
    }
    return true
  }

  const downloadOne = async (att: OutlookMailAttachment): Promise<void> => {
    if (busy) return
    setBusy(`download-${att.index}`)
    try {
      if (await download(att)) onToast(`Сохранено: ${att.file_name}`)
    } finally {
      setBusy('')
    }
  }

  const downloadAll = async (): Promise<void> => {
    if (busy) return
    setBusy('download-all')
    try {
      let saved = 0
      for (const att of attachments) {
        if (await download(att)) saved += 1
      }
      if (saved) onToast(`Сохранено файлов: ${saved} из ${attachments.length}`)
    } finally {
      setBusy('')
    }
  }

  /** PDF / images / text — viewer in the app; Office and other formats — the desktop program. */
  const openFile = async (att: OutlookMailAttachment): Promise<void> => {
    if (busy) return
    setBusy(`open-${att.index}`)
    try {
      const saved = await saveOutlookAttachment(mail, att.index)
      if (!saved.ok) {
        onToast(saved.error, true)
        return
      }
      const preview = await loadAttachmentPreview(saved.path)
      if (preview.kind === 'text' || preview.kind === 'embed') {
        setViewer({ att, path: saved.path, preview })
        return
      }
      if (preview.kind === 'error') {
        onToast(preview.message, true)
        return
      }
      const opened = await openAttachmentExternally(saved.path)
      if (!opened.ok) onToast(opened.error || 'Не удалось открыть файл', true)
    } finally {
      setBusy('')
    }
  }

  const downloadViewed = async (): Promise<void> => {
    if (!viewer) return
    const res = await downloadAttachmentCopy(viewer.path, viewer.att.file_name)
    if (res.canceled) return
    if (res.ok) onToast(`Сохранено: ${viewer.att.file_name}`)
    else onToast(res.error || 'Не удалось сохранить файл', true)
  }

  const openViewedExternally = async (): Promise<void> => {
    if (!viewer) return
    const opened = await openAttachmentExternally(viewer.path)
    if (!opened.ok) onToast(opened.error || 'Не удалось открыть файл', true)
  }

  useEffect(() => {
    if (!viewer) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setViewer(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [viewer])

  return (
    <div className="mail-letter">
      <div className="mail-letter-tabs" role="tablist" aria-label="Содержимое письма">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'text'}
          className={tab === 'text' ? 'is-active' : ''}
          onClick={() => setTab('text')}
        >
          <FileText size={14} aria-hidden /> Текст
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'files'}
          className={tab === 'files' ? 'is-active' : ''}
          onClick={() => setTab('files')}
        >
          <Paperclip size={14} aria-hidden /> Вложения{attachments.length ? ` (${attachments.length})` : ''}
        </button>
      </div>

      {tab === 'text' ? (
        <div className="mail-letter-body" role="tabpanel">
          {body ? (
            body.split(/\n{2,}/).map((block, index) => <p key={index}>{block}</p>)
          ) : (
            <p className="mail-letter-empty">{loading ? 'Загружаем текст письма…' : 'Текст письма недоступен'}</p>
          )}
        </div>
      ) : (
        <div className="mail-letter-files" role="tabpanel">
          {!attachments.length ? (
            <p className="mail-letter-empty">{loading ? 'Загружаем вложения…' : 'Вложений нет'}</p>
          ) : (
            <>
              {!canFiles ? (
                <p className="mail-letter-empty">Скачать вложения можно только у писем из Outlook.</p>
              ) : (
                <div className="mail-letter-files-toolbar">
                  <button
                    type="button"
                    className="mail-letter-btn is-primary"
                    disabled={Boolean(busy)}
                    onClick={() => void downloadAll()}
                  >
                    <Download size={14} aria-hidden /> {busy === 'download-all' ? 'Сохраняем…' : 'Скачать все'}
                  </button>
                </div>
              )}
              <ul className="mail-letter-file-list">
                {attachments.map((att) => (
                  <li key={`${mail.id}-${att.index}`} className="mail-letter-file">
                    <TodayFileIcon name={att.file_name} size={28} />
                    <span className="mail-letter-file-name" title={att.file_name}>
                      {att.file_name}
                      {att.size != null ? (
                        <span className="mail-letter-file-size">{formatAttachmentSize(att.size)}</span>
                      ) : null}
                    </span>
                    <button
                      type="button"
                      className="mail-letter-btn"
                      disabled={Boolean(busy) || !canFiles}
                      onClick={() => void openFile(att)}
                    >
                      {busy === `open-${att.index}` ? '…' : 'Открыть'}
                    </button>
                    <button
                      type="button"
                      className="mail-letter-btn is-primary"
                      disabled={Boolean(busy) || !canFiles}
                      onClick={() => void downloadOne(att)}
                    >
                      {busy === `download-${att.index}` ? '…' : 'Скачать'}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {viewer
        ? createPortal(
            <div className="spec-mail-att-modal-backdrop" onClick={() => setViewer(null)} role="presentation">
              <div
                className="spec-mail-att-modal mail-file-viewer"
                role="dialog"
                aria-modal="true"
                aria-label={viewer.att.file_name}
                onClick={(event) => event.stopPropagation()}
              >
                <header className="mail-file-viewer-head">
                  <TodayFileIcon name={viewer.att.file_name} size={24} />
                  <strong className="mail-file-viewer-title" title={viewer.att.file_name}>
                    {viewer.att.file_name}
                  </strong>
                  <button type="button" className="mail-letter-btn is-primary" onClick={() => void downloadViewed()}>
                    <Download size={14} aria-hidden /> Скачать
                  </button>
                  <button type="button" className="mail-letter-btn" onClick={() => void openViewedExternally()}>
                    <ExternalLink size={14} aria-hidden /> В приложении
                  </button>
                  <button
                    type="button"
                    className="mail-letter-btn mail-file-viewer-close"
                    aria-label="Закрыть"
                    onClick={() => setViewer(null)}
                  >
                    <X size={16} aria-hidden />
                  </button>
                </header>
                <div className="mail-file-viewer-body">
                  <PreviewPane preview={viewer.preview} />
                </div>
              </div>
            </div>,
            document.body
          )
        : null}
    </div>
  )
}
