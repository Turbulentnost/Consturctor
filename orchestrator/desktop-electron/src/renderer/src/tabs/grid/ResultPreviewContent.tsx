import { OfficeHtmlFrame } from './OfficeHtmlFrame'
import { TodayResultReport } from './TodayResultReport'
import type { ResultFilePreview } from './todayResultPreview'

export function ResultPreviewContent({
  preview,
  attachmentName
}: {
  preview: ResultFilePreview | null
  attachmentName?: string
}): React.JSX.Element {
  if (!preview) {
    return <p className="today-result-preview-status">Открываем документ…</p>
  }
  if (preview.kind === 'error') {
    return <p className="today-result-preview-status today-table-error">{preview.message}</p>
  }
  if (preview.kind === 'table') {
    return (
      <div className="today-result-preview-table-wrap today-result-preview-table-wrap--office">
        <table className="today-result-preview-table">
          <thead>
            <tr>
              {preview.headers.map((cell, index) => (
                <th key={`${cell}:${index}`}>{cell}</th>
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
    if (preview.mime === 'text/html') {
      return (
        <OfficeHtmlFrame
          className="today-result-preview-embed today-result-preview-embed--office"
          dataUrl={preview.dataUrl}
        />
      )
    }
    if (preview.mime === 'application/pdf') {
      return (
        <iframe
          className="today-result-preview-embed today-result-preview-embed--office"
          title="Файл"
          src={preview.dataUrl}
        />
      )
    }
    return <img className="today-result-preview-img" src={preview.dataUrl} alt="" />
  }
  return <TodayResultReport text={preview.text} attachmentName={attachmentName} />
}
