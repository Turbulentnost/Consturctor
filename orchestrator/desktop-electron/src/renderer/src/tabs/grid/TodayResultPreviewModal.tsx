import { Download, FileText } from 'lucide-react'

import { useCallback, useEffect, useId, useState } from 'react'

import { createPortal } from 'react-dom'

import { formatFileWhen } from '../../pages/filesGrouping'

import type { TodayAgentResultItem } from '../../workplace/useTodayAgentResults'

import { ReferencedFilePreviewModal } from './ReferencedFilePreviewModal'

import { ResultFileOpenProvider } from './resultFileOpenContext'

import { ResultPreviewContent } from './ResultPreviewContent'

import { stripInlineMarkdown } from './TodayResultReport'

import {

  loadResultFilePreview,

  resultAgentLabel,

  type ResultFilePreview

} from './todayResultPreview'



function DocumentMeta({ file }: { file: TodayAgentResultItem }): React.JSX.Element {

  const when = file.createdAt ? formatFileWhen(file.createdAt) : ''

  return <div className="today-result-doc-meta">{when || 'Сегодня'}</div>

}



function DocumentSheet({

  file,

  children,

  kind

}: {

  file: TodayAgentResultItem

  children: React.ReactNode

  kind: string

}): React.JSX.Element {

  return (

    <div className={`today-result-doc-sheet is-${kind}`}>

      <header className="today-result-doc-sheet-head">

        <div className="today-result-doc-mark" aria-hidden>

          <FileText size={18} strokeWidth={2} />

        </div>

        <div className="today-result-doc-sheet-titles">

          <p className="today-result-doc-eyebrow">Отчёт · результат агента</p>

          <h5 className="today-result-doc-title">{stripInlineMarkdown(resultAgentLabel(file))}</h5>

          <DocumentMeta file={file} />

        </div>

      </header>

      <div className="today-result-doc-rule" aria-hidden />

      <div className="today-result-doc-sheet-body">{children}</div>

      <footer className="today-result-doc-sheet-foot">

        <span>Оркестратор</span>

        <span>Предпросмотр документа</span>

      </footer>

    </div>

  )

}



function PreviewBody({

  preview,

  file

}: {

  preview: ResultFilePreview | null

  file: TodayAgentResultItem

}): React.JSX.Element {

  if (!preview) {

    return (

      <DocumentSheet file={file} kind="loading">

        <ResultPreviewContent preview={null} attachmentName={file.name} />

      </DocumentSheet>

    )

  }

  if (preview.kind === 'error') {

    return (

      <DocumentSheet file={file} kind="error">

        <ResultPreviewContent preview={preview} attachmentName={file.name} />

      </DocumentSheet>

    )

  }

  if (preview.kind === 'table' || preview.kind === 'embed') {

    return (

      <DocumentSheet file={file} kind={preview.kind === 'table' ? 'table' : 'embed'}>

        <ResultPreviewContent preview={preview} attachmentName={file.name} />

      </DocumentSheet>

    )

  }

  return (

    <DocumentSheet file={file} kind="text">

      <ResultPreviewContent preview={preview} attachmentName={file.name} />

    </DocumentSheet>

  )

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

  const [referencedFile, setReferencedFile] = useState<string | null>(null)



  const openReferencedFile = useCallback((fileName: string) => {

    setReferencedFile(fileName)

  }, [])



  useEffect(() => {

    const onKey = (event: KeyboardEvent): void => {

      if (event.key === 'Escape') {

        if (referencedFile) {

          event.stopPropagation()

          setReferencedFile(null)

          return

        }

        onClose()

      }

    }

    window.addEventListener('keydown', onKey)

    return () => window.removeEventListener('keydown', onKey)

  }, [onClose, referencedFile])



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



  return createPortal(

    <>

      <div className="modal-overlay today-result-preview-overlay" onClick={onClose} role="presentation">

        <div

          className="modal-card today-result-preview-dialog today-result-preview-dialog--doc"

          role="dialog"

          aria-modal="true"

          aria-labelledby={titleId}

          onClick={(event) => event.stopPropagation()}

        >

          <header className="today-result-preview-head">

            <div className="today-result-preview-titles">

              <p className="today-result-preview-kicker">Предпросмотр документа</p>

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

          <div className={`today-result-preview-body today-result-preview-body--desk is-${bodyKind}`}>

            <ResultFileOpenProvider onOpen={openReferencedFile}>

              <PreviewBody preview={preview} file={file} />

            </ResultFileOpenProvider>

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

      </div>

      {referencedFile ? (

        <ReferencedFilePreviewModal

          fileName={referencedFile}

          context={file}

          onClose={() => setReferencedFile(null)}

        />

      ) : null}

    </>,

    document.body

  )

}


