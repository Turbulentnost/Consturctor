import { useEffect, useId, useState } from 'react'
import { createPortal } from 'react-dom'
import mammoth from 'mammoth'
import { api } from '../../api/client'
import { fetchProtocolForm } from '../../workplace/meetingProtocolCreate'
import { protocolPrintTitle, renderProtocolHtml } from '../../workplace/meetingProtocolPrint'

function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const comma = base64.indexOf(',')
  const clean = comma >= 0 && base64.startsWith('data:') ? base64.slice(comma + 1) : base64
  const binary = atob(clean)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  return bytes.buffer
}

/** docx is a ZIP container: first bytes are "PK\x03\x04". */
function looksLikeDocx(buffer: ArrayBuffer): boolean {
  const bytes = new Uint8Array(buffer)
  return bytes.length >= 4 && bytes[0] === 0x50 && bytes[1] === 0x4b && bytes[2] === 0x03 && bytes[3] === 0x04
}

async function fetchReportBytes(url: string, token: string | null): Promise<ArrayBuffer> {
  if (typeof window.api.fetchBinary !== 'function') {
    throw new Error('Просмотр отчёта недоступен — перезапустите приложение (обновлён preload).')
  }
  const res = await window.api.fetchBinary({ url, token })
  if (!res.ok || !res.base64) {
    throw new Error(res.error || 'Не удалось загрузить файл отчёта')
  }
  const buffer = base64ToArrayBuffer(res.base64)
  if (!looksLikeDocx(buffer)) {
    throw new Error(`Файл отчёта не является docx (${res.contentType || 'неизвестный тип'})`)
  }
  return buffer
}

/** Printable HTML wrapper (fonts + table borders), same spirit as registryPrint.ts. */
export function wrapProtocolPrintHtml(title: string, bodyHtml: string): string {
  return `<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<title>${escapeHtml(title)}</title>
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 12px;
    color: #10141a;
    padding: 20px;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
    line-height: 1.45;
  }
  h1, h2, h3 { page-break-after: avoid; }
  h1 { font-size: 18px; margin: 0 0 12px; }
  h2 { font-size: 14px; margin: 16px 0 8px; }
  h3 { font-size: 13px; margin: 12px 0 6px; }
  p { margin: 0 0 8px; }
  table {
    width: 100%;
    border-collapse: collapse;
    margin: 8px 0 12px;
  }
  th, td {
    border: 1px solid #c8d0dc;
    padding: 4px 8px;
    text-align: left;
    vertical-align: top;
  }
  th { background: #e8edf4; font-weight: 600; }
  ul, ol { margin: 0 0 10px; padding-left: 20px; }
</style>
</head>
<body>
${bodyHtml}
</body>
</html>`
}

export function MeetingReportModal({
  open,
  onClose,
  reportUrl,
  reportName,
  protocolRefKey = ''
}: {
  open: boolean
  onClose: () => void
  /** docx from the agent run; when empty, the protocol is rendered from 1C data (protocolRefKey). */
  reportUrl: string
  reportName: string
  protocolRefKey?: string
}): React.JSX.Element | null {
  const titleId = useId()
  const [html, setHtml] = useState('')
  const [onecTitle, setOnecTitle] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [printBusy, setPrintBusy] = useState(false)
  const [printError, setPrintError] = useState('')
  const fromOnec = !reportUrl && Boolean(protocolRefKey)

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !printBusy) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, printBusy, onClose])

  useEffect(() => {
    if (!open || (!reportUrl && !protocolRefKey)) {
      setHtml('')
      setOnecTitle('')
      setError('')
      return
    }
    let cancelled = false
    setLoading(true)
    setError('')
    setHtml('')
    setOnecTitle('')
    void (async () => {
      try {
        if (!reportUrl) {
          const card = await fetchProtocolForm(protocolRefKey)
          if (cancelled) return
          if (!card.ok) throw new Error(card.error)
          setOnecTitle(protocolPrintTitle(card.card))
          setHtml(renderProtocolHtml(card.card))
          return
        }
        const token = api.getToken()
        const buffer = await fetchReportBytes(reportUrl, token)
        if (cancelled) return
        const result = await mammoth.convertToHtml({ arrayBuffer: buffer })
        if (cancelled) return
        setHtml(result.value || '<p>Отчёт пуст.</p>')
      } catch (err) {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Не удалось открыть отчёт')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [open, reportUrl, protocolRefKey])

  if (!open) return null

  const title = fromOnec
    ? onecTitle || 'Протокол совещания'
    : (reportName || 'Протокол совещания').replace(/\.docx$/i, '')

  const printPdf = async (): Promise<void> => {
    if (printBusy || !html) return
    setPrintBusy(true)
    setPrintError('')
    try {
      if (typeof window.api.printToPdf !== 'function') {
        setPrintError('Печать недоступна — перезапустите приложение.')
        return
      }
      const result = await window.api.printToPdf({
        html: wrapProtocolPrintHtml(title, html),
        openAfter: true,
        defaultName: `${title}.pdf`
      })
      if (!result.ok && !result.canceled) {
        setPrintError(result.error || 'Не удалось сохранить PDF')
      }
    } catch (err) {
      setPrintError(err instanceof Error ? err.message : 'Не удалось сохранить PDF')
    } finally {
      setPrintBusy(false)
    }
  }

  const downloadDocx = (): void => {
    if (!reportUrl) return
    void api.download(reportUrl, reportName || 'protocol.docx')
  }

  return createPortal(
    <div className="modal-overlay meeting-report-overlay" onClick={() => !printBusy && onClose()} role="presentation">
      <div
        className="modal-card meeting-report-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="meeting-report-toolbar">
          <h4 className="modal-title" id={titleId}>
            {title}
          </h4>
          <div className="meeting-report-toolbar-actions">
            <button type="button" className="btn-primary" onClick={() => void printPdf()} disabled={printBusy || !html || Boolean(error)}>
              {printBusy ? 'Печать…' : 'Печать в PDF'}
            </button>
            {reportUrl ? (
              <button type="button" className="btn-ghost" onClick={downloadDocx}>
                Скачать docx
              </button>
            ) : null}
            <button type="button" className="btn-light" onClick={onClose} disabled={printBusy}>
              Закрыть
            </button>
          </div>
        </div>
        {printError ? <p className="meeting-report-error">{printError}</p> : null}
        {loading ? <p className="spec-v04-muted">{fromOnec ? 'Читаем протокол из 1С…' : 'Загрузка отчёта…'}</p> : null}
        {error ? <p className="meeting-report-error">{error}</p> : null}
        {!loading && !error && html ? (
          <div className="meeting-report-body" dangerouslySetInnerHTML={{ __html: html }} />
        ) : null}
      </div>
    </div>,
    document.body
  )
}
