import { Download } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { createPortal } from 'react-dom'
import { formatFileWhen } from '../../pages/filesGrouping'
import type { TodayAgentResultItem } from '../../workplace/useTodayAgentResults'
import { TodayResultReport } from './TodayResultReport'
import { TodayResultWorkbook, WorkbookPreviewGuard } from './TodayResultWorkbook'
import {
  loadResultFilePreview,
  resultAgentLabel,
  type ResultFilePreview
} from './todayResultPreview'
import { isUsefulWorkbook, tableToWorkbook } from './todayWorkbookPreview'

function PreviewBody({ preview }: { preview: ResultFilePreview | null }): React.JSX.Element {
  if (!preview) {
    return <p className="today-result-preview-status">Открываем результат…</p>
  }
  if (preview.kind === 'error') {
    return <p className="today-result-preview-status today-table-error">{preview.message}</p>
  }
  if (preview.kind === 'workbook') {
    if (!isUsefulWorkbook(preview) && preview.fallbackText) {
      return <TodayResultReport text={preview.fallbackText} />
    }
    return (
      <WorkbookPreviewGuard fallbackText={preview.fallbackText}>
        <TodayResultWorkbook sheets={preview.sheets} />
      </WorkbookPreviewGuard>
    )
  }
  if (preview.kind === 'table') {
    return (
      <WorkbookPreviewGuard>
        <TodayResultWorkbook sheets={tableToWorkbook(preview.headers, preview.rows).sheets} />
      </WorkbookPreviewGuard>
    )
  }
  if (preview.kind === 'embed') {
    if (preview.mime === 'application/pdf') {
      return <iframe className="today-result-preview-embed" title="Результат" src={preview.dataUrl} />
    }
    return <img className="today-result-preview-img" src={preview.dataUrl} alt="" />
  }
  return <TodayResultReport text={preview.text} />
}

export function TodayResultPreviewModal({
  file,
  downloading,
  onClose,
  onDownload
}: {
  file: TodayAgentResultItem
  downloading?: boolean
  onClose: () => void
  onDownload: () => void
}): React.JSX.Element {
  const titleId = useId()
  const [preview, setPreview] = useState<ResultFilePreview | null>(null)

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    let alive = true
    setPreview(null)
    void loadResultFilePreview(file)
      .then((next) => {
        if (alive) setPreview(next)
      })
      .catch(() => {
        if (alive) setPreview({ kind: 'error', message: 'Не удалось открыть результат' })
      })
    return () => {
      alive = false
    }
  }, [file])

  const bodyKind = preview?.kind || 'loading'
  const wide = bodyKind === 'workbook' || bodyKind === 'table'

  return createPortal(
    <div className="modal-overlay today-result-preview-overlay" onClick={onClose} role="presentation">
      <div
        className={`modal-card today-result-preview-dialog${wide ? ' is-wide' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="today-result-preview-head">
          <div className="today-result-preview-titles">
            <p className="today-result-preview-kicker">Результат агента</p>
            <h4 className="modal-title" id={titleId}>
              {resultAgentLabel(file)}
            </h4>
            {file.createdAt ? (
              <p className="today-result-preview-when spec-v04-muted">{formatFileWhen(file.createdAt)}</p>
            ) : null}
          </div>
          <button type="button" className="today-plan-detail-close" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </header>
        <div className={`today-result-preview-body is-${bodyKind}`}>
          <PreviewBody preview={preview} />
        </div>
        <div className="today-result-preview-actions">
          <button
            type="button"
            className="btn-primary"
            disabled={downloading || (!file.downloadUrl && !(file.summary || '').trim())}
            onClick={onDownload}
          >
            <Download size={16} strokeWidth={2} aria-hidden />
            {downloading ? 'Скачивание…' : 'Скачать отчёт'}
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
