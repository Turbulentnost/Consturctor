import { Download } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api/client'
import type { TodayAgentResultItem } from '../../workplace/useTodayAgentResults'
import { DocumentFileBadge } from './todayFileIcon'
import { ResultPreviewContent } from './ResultPreviewContent'
import {
  loadReferencedFilePreview,
  resolveAgentFileDownload,
  type ResultFilePreview
} from './todayResultPreview'

export function ReferencedFilePreviewModal({
  fileName,
  context,
  onClose
}: {
  fileName: string
  context: TodayAgentResultItem
  onClose: () => void
}): React.JSX.Element {
  const titleId = useId()
  const [preview, setPreview] = useState<ResultFilePreview | null>(null)
  const [downloading, setDownloading] = useState(false)

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])

  useEffect(() => {
    let alive = true
    setPreview(null)
    void loadReferencedFilePreview(fileName, context)
      .then((next) => {
        if (alive) setPreview(next)
      })
      .catch(() => {
        if (alive) setPreview({ kind: 'error', message: 'Не удалось открыть файл' })
      })
    return () => {
      alive = false
    }
  }, [fileName, context])

  async function downloadFile(): Promise<void> {
    if (downloading) return
    setDownloading(true)
    try {
      const resolved = await resolveAgentFileDownload(fileName, context)
      if (!resolved?.url) return
      await api.download(resolved.url, resolved.name)
    } finally {
      setDownloading(false)
    }
  }

  const bodyKind = preview?.kind || 'loading'

  return createPortal(
    <div
      className="modal-overlay today-result-file-preview-overlay"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="modal-card today-result-file-preview-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="today-result-file-preview-head">
          <div className="today-result-file-preview-titles">
            <p className="today-result-preview-kicker">Просмотр файла</p>
            <h4 className="modal-title" id={titleId}>
              <DocumentFileBadge name={fileName} />
            </h4>
          </div>
          <button type="button" className="today-plan-detail-close" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </header>
        <div className={`today-result-file-preview-body is-${bodyKind}`}>
          <ResultPreviewContent preview={preview} />
        </div>
        <div className="today-result-preview-actions">
          <button type="button" className="btn-primary" disabled={downloading} onClick={() => void downloadFile()}>
            <Download size={16} strokeWidth={2} aria-hidden />
            {downloading ? 'Скачивание…' : 'Скачать файл'}
          </button>
          <button type="button" className="btn-light" onClick={onClose}>
            Закрыть
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}
