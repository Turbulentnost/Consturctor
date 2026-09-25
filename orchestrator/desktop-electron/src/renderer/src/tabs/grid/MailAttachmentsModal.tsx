import { useCallback, useEffect, useState } from 'react'
import type { SpecMailRow } from '../../workplace/specV04DemoData'
import type { OutlookMailAttachment } from '../../utils/outlookMailActions'
import { decodeMimeHeader } from '../../utils/mimeHeader'
import {
  downloadAttachmentCopy,
  ensureAttachmentSaved,
  formatAttachmentSize,
  loadAttachmentPreview,
  openAttachmentExternally,
  type MailAttachmentPreview,
  type SavedAttachment
} from '../../utils/mailAttachmentPreview'

function PreviewPane({ preview }: { preview: MailAttachmentPreview | undefined }): React.JSX.Element {
  if (!preview || preview.kind === 'idle') {
    return <p className="spec-v04-muted spec-mail-att-preview-empty">Выберите файл и нажмите «Просмотр».</p>
  }
  if (preview.kind === 'error') {
    return <p className="spec-mail-att-preview-error">{preview.message}</p>
  }
  if (preview.kind === 'too_large') {
    return (
      <p className="spec-v04-muted">
        Файл слишком большой для встроенного просмотра
        {preview.size ? ` (${formatAttachmentSize(preview.size)})` : ''}. Используйте «Скачать» или «Внешнее
        приложение».
      </p>
    )
  }
  if (preview.kind === 'external') {
    return (
      <div className="spec-mail-att-preview-external">
        <p>{preview.hint}</p>
        <p className="spec-v04-muted">Нажмите «Внешнее приложение», чтобы открыть файл на компьютере.</p>
      </div>
    )
  }
  if (preview.kind === 'text') {
    return <pre className="spec-mail-att-preview-text">{preview.text}</pre>
  }
  if (preview.mime === 'application/pdf') {
    return (
      <iframe
        className="spec-mail-att-preview-embed"
        title="PDF"
        src={preview.dataUrl}
      />
    )
  }
  return (
    <img
      className="spec-mail-att-preview-img"
      src={preview.dataUrl}
      alt=""
    />
  )
}

export function MailAttachmentsModal({
  open,
  mail,
  attachments,
  initialIndex,
  onClose,
  onToast
}: {
  open: boolean
  mail: SpecMailRow
  attachments: OutlookMailAttachment[]
  initialIndex?: number
  onClose: () => void
  onToast?: (text: string, isError?: boolean) => void
}): React.JSX.Element | null {
  const [items, setItems] = useState<SavedAttachment[]>([])
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const [batchBusy, setBatchBusy] = useState('')

  const syncItems = useCallback(() => {
    setItems(
      attachments.map((att) => ({
        index: att.index,
        file_name: att.file_name,
        size: att.size
      }))
    )
  }, [attachments])

  useEffect(() => {
    if (!open) return
    syncItems()
    setSelectedIndex(initialIndex ?? (attachments[0]?.index ?? null))
  }, [open, syncItems, initialIndex, attachments])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const patchItem = (index: number, patch: Partial<SavedAttachment>): void => {
    setItems((prev) => prev.map((row) => (row.index === index ? { ...row, ...patch } : row)))
  }

  const saveOne = async (att: OutlookMailAttachment): Promise<{ path: string } | { error: string }> => {
    let pathFromState: string | undefined
    setItems((prev) => {
      pathFromState = prev.find((i) => i.index === att.index)?.path
      return prev
    })
    if (pathFromState) return { path: pathFromState }
    const saved = await ensureAttachmentSaved(mail, att)
    if (!saved.ok) {
      patchItem(att.index, { saveError: saved.error })
      return { error: saved.error }
    }
    patchItem(att.index, { path: saved.path, saveError: undefined })
    return { path: saved.path }
  }

  const runPreview = async (att: OutlookMailAttachment): Promise<void> => {
    setSelectedIndex(att.index)
    patchItem(att.index, { previewLoading: true, preview: { kind: 'idle' } })
    const saved = await saveOne(att)
    if ('error' in saved) {
      patchItem(att.index, {
        previewLoading: false,
        preview: { kind: 'error', message: saved.error || 'Ошибка сохранения' }
      })
      return
    }
    const preview = await loadAttachmentPreview(saved.path)
    patchItem(att.index, { previewLoading: false, preview })
  }

  useEffect(() => {
    if (!open || !attachments.length) return
    const idx = initialIndex ?? attachments[0]?.index
    const att = attachments.find((a) => a.index === idx)
    if (!att) return
    void runPreview(att)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- preview once when modal opens
  }, [open, mail.id, initialIndex])

  const runDownload = async (att: OutlookMailAttachment): Promise<void> => {
    const saved = await saveOne(att)
    if ('error' in saved) {
      onToast?.(saved.error || 'Ошибка', true)
      return
    }
    const res = await downloadAttachmentCopy(saved.path, att.file_name)
    if (res.canceled) return
    if (res.ok) onToast?.('Файл сохранён')
    else onToast?.(res.error || 'Ошибка', true)
  }

  const runExternal = async (att: OutlookMailAttachment): Promise<void> => {
    const saved = await saveOne(att)
    if ('error' in saved) {
      onToast?.(saved.error || 'Не удалось получить файл', true)
      return
    }
    const res = await openAttachmentExternally(saved.path)
    if (res.ok) onToast?.('Открыто во внешнем приложении')
    else onToast?.(res.error || 'Ошибка', true)
  }

  const runBatch = async (mode: 'preview_all' | 'download_all'): Promise<void> => {
    if (batchBusy || !attachments.length) return
    setBatchBusy(mode)
    try {
      for (const att of attachments) {
        if (mode === 'download_all') {
          await runDownload(att)
        } else {
          await runPreview(att)
        }
      }
      if (mode === 'download_all') onToast?.('Сохранение завершено')
      else onToast?.('Просмотр завершён')
    } finally {
      setBatchBusy('')
    }
  }

  if (!open) return null

  const selected = items.find((i) => i.index === selectedIndex)

  return (
    <div className="spec-mail-att-modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="spec-mail-att-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-labelledby="spec-mail-att-modal-title"
        aria-modal="true"
      >
        <header className="spec-mail-att-modal-head">
          <div>
            <h3 id="spec-mail-att-modal-title">Вложения письма</h3>
            <p className="spec-v04-muted spec-mail-att-modal-sub">{decodeMimeHeader(mail.subject)}</p>
          </div>
          <button type="button" className="spec-mail-att-modal-close" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </header>
        <div className="spec-mail-att-modal-toolbar">
          <button
            type="button"
            className="spec-btn-launch spec-mail-att-toolbar-btn"
            disabled={Boolean(batchBusy)}
            onClick={() => void runBatch('preview_all')}
          >
            {batchBusy === 'preview_all' ? '…' : 'Открыть все'}
          </button>
          <button
            type="button"
            className="spec-btn-outline spec-mail-att-toolbar-btn"
            disabled={Boolean(batchBusy)}
            onClick={() => void runBatch('download_all')}
          >
            {batchBusy === 'download_all' ? '…' : 'Скачать все'}
          </button>
        </div>
        <div className="spec-mail-att-modal-body">
          <ul className="spec-mail-att-list">
            {items.map((row) => {
              const att = attachments.find((a) => a.index === row.index)!
              const active = row.index === selectedIndex
              return (
                <li key={row.index} className={active ? 'is-active' : undefined}>
                  <div className="spec-mail-att-list-main">
                    <span className="spec-mail-att-name">{row.file_name}</span>
                    {row.size != null ? (
                      <span className="spec-v04-muted spec-mail-att-size">{formatAttachmentSize(row.size)}</span>
                    ) : null}
                    {row.saveError ? <span className="spec-mail-att-preview-error">{row.saveError}</span> : null}
                  </div>
                  <div className="spec-mail-att-list-actions">
                    <button
                      type="button"
                      className="spec-btn-launch spec-mail-att-action-btn"
                      disabled={Boolean(batchBusy) || row.previewLoading}
                      onClick={() => void runPreview(att)}
                    >
                      {row.previewLoading ? '…' : 'Просмотр'}
                    </button>
                    <button
                      type="button"
                      className="spec-btn-outline spec-mail-att-action-btn"
                      disabled={Boolean(batchBusy)}
                      onClick={() => void runDownload(att)}
                    >
                      Скачать
                    </button>
                    <button
                      type="button"
                      className="spec-btn-outline spec-mail-att-action-btn"
                      disabled={Boolean(batchBusy)}
                      onClick={() => void runExternal(att)}
                    >
                      Внешнее приложение
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
          <div className="spec-mail-att-preview-pane">
            <h4 className="spec-detail-pane">{selected?.file_name || 'Предпросмотр'}</h4>
            <PreviewPane preview={selected?.preview} />
          </div>
        </div>
      </div>
    </div>
  )
}
