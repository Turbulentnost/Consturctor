import { Download, Eye } from 'lucide-react'
import { useState } from 'react'
import { api } from '../../api/client'
import { SpecPanel } from '../../workplace/specV04Components'
import {
  type TodayAgentResultItem,
  useTodayAgentResults
} from '../../workplace/useTodayAgentResults'
import { TodayResultPreviewModal } from './TodayResultPreviewModal'
import { resultAgentLabel, uniqueAgentResults } from './todayResultPreview'

export function TodayResultsPanel({
  periodDay,
  userId
}: {
  periodDay: Date
  userId?: string
}): React.JSX.Element {
  const { loading, error, items } = useTodayAgentResults(periodDay, userId)
  const rows = uniqueAgentResults(items)
  const [preview, setPreview] = useState<TodayAgentResultItem | null>(null)
  const [downloadingId, setDownloadingId] = useState('')

  async function downloadFile(file: TodayAgentResultItem): Promise<void> {
    if (downloadingId) return
    const canRemote = Boolean(file.downloadUrl)
    const localText = (file.summary || '').trim()
    if (!canRemote && !localText) return
    setDownloadingId(file.id)
    try {
      if (file.downloadUrl) {
        await api.download(file.downloadUrl, file.name)
        return
      }
      const blob = new Blob([localText], { type: 'text/plain;charset=utf-8' })
      const href = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = href
      link.download = file.name
      link.click()
      URL.revokeObjectURL(href)
    } finally {
      setDownloadingId('')
    }
  }

  const body = ((): React.ReactNode => {
    if (loading && !rows.length) {
      return <p className="today-table-status">Загружаем…</p>
    }
    if (error) {
      return <p className="today-table-status today-table-error">{error}</p>
    }
    if (!rows.length) {
      return <p className="today-table-status">Нет результатов агентов за выбранный день</p>
    }
    return (
      <ul className="today-results-list">
        {rows.map((file) => {
          const agentName = resultAgentLabel(file)
          const busy = downloadingId === file.id
          return (
            <li key={file.id} className="today-results-item">
              <div className="today-results-meta">
                <strong>{agentName}</strong>
              </div>
              <div className="today-results-actions">
                <button
                  type="button"
                  className="today-results-icon-btn"
                  aria-label={`Посмотреть: ${agentName}`}
                  title="Посмотреть"
                  onClick={() => setPreview(file)}
                >
                  <Eye size={16} strokeWidth={2} aria-hidden />
                </button>
                <button
                  type="button"
                  className="today-results-icon-btn"
                  aria-label={busy ? 'Скачивание…' : `Скачать отчёт: ${agentName}`}
                  title={busy ? 'Скачивание…' : 'Скачать отчёт'}
                  disabled={busy || (!file.downloadUrl && !(file.summary || '').trim())}
                  onClick={() => void downloadFile(file)}
                >
                  <Download size={16} strokeWidth={2} aria-hidden />
                </button>
              </div>
            </li>
          )
        })}
      </ul>
    )
  })()

  return (
    <SpecPanel>
      {body}
      {preview ? (
        <TodayResultPreviewModal
          file={preview}
          downloading={downloadingId === preview.id}
          onClose={() => setPreview(null)}
          onDownload={() => void downloadFile(preview)}
        />
      ) : null}
    </SpecPanel>
  )
}
