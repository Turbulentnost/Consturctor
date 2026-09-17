import { useEffect, useId, useState } from 'react'
import { createPortal } from 'react-dom'
import type { TodayAgentResultItem } from '../../workplace/useTodayAgentResults'
import {
  loadResultFilePreview,
  resultAgentLabel,
  type ResultFilePreview
} from './todayResultPreview'

function PreviewBody({ preview }: { preview: ResultFilePreview | null }): React.JSX.Element {
  if (!preview) {
    return <p className="today-table-status">Открываем результат…</p>
  }
  if (preview.kind === 'error') {
    return <p className="today-table-status today-table-error">{preview.message}</p>
  }
  if (preview.kind === 'table') {
    return (
      <div className="today-result-preview-table-wrap">
        <table className="today-result-preview-table">
          <thead>
            <tr>
              {preview.headers.map((cell) => (
                <th key={cell}>{cell}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row, index) => (
              <tr key={`${row[0] || 'row'}:${index}`}>
                {row.map((cell, cellIndex) => (
                  <td key={`${cellIndex}:${cell}`}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }
  if (preview.kind === 'embed') {
    if (preview.mime === 'application/pdf') {
      return <iframe className="today-result-preview-embed" title="Результат" src={preview.dataUrl} />
    }
    return <img className="today-result-preview-img" src={preview.dataUrl} alt="" />
  }
  return <pre className="today-result-preview-text">{preview.text}</pre>
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

  return createPortal(
    <div className="modal-overlay today-result-preview-overlay" onClick={onClose} role="presentation">
      <div
        className="modal-card today-result-preview-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="today-plan-detail-head">
          <h4 className="modal-title" id={titleId}>
            {resultAgentLabel(file)}
          </h4>
          <button type="button" className="today-plan-detail-close" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </header>
        <div className="today-result-preview-body">
          <PreviewBody preview={preview} />
        </div>
        <div className="modal-actions">
          <button
            type="button"
            className="btn-light"
            disabled={downloading || (!file.downloadUrl && !(file.summary || '').trim())}
            onClick={onDownload}
          >
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
