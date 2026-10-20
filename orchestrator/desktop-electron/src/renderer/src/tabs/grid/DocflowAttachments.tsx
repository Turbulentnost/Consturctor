import { useEffect, useState } from 'react'
import { Paperclip } from 'lucide-react'
import type { UserProfile } from '../../api/types'
import {
  attachmentFileName,
  loadDocflowAttachments,
  openDocflowAttachment,
  type DocflowAttachment
} from '../../workplace/docflowAttachments'

function fileLabel(file: DocflowAttachment): string {
  return attachmentFileName(file)
}

export function DocflowFileOpenButton({
  file,
  className,
  children
}: {
  file: { id: string; name: string; extension?: string }
  className?: string
  children: React.ReactNode
}): React.JSX.Element {
  const [opening, setOpening] = useState(false)
  const [error, setError] = useState('')

  return (
    <span className="docflow-file-open-wrap">
      <button
        type="button"
        className={className || 'docflow-file-open'}
        disabled={opening}
        title="Открыть вложение"
        onClick={() => {
          if (opening) return
          setOpening(true)
          setError('')
          void openDocflowAttachment(file)
            .catch((err: unknown) => {
              setError(err instanceof Error ? err.message : 'Не удалось открыть вложение')
            })
            .finally(() => setOpening(false))
        }}
      >
        {children}
      </button>
      {error ? <em className="docflow-file-error">{error}</em> : null}
    </span>
  )
}

/** Список присоединённых файлов документа и открытие каждого, как письма во входящей. */
export function DocflowAttachments({
  user,
  entity,
  ownerId
}: {
  user: UserProfile | null
  entity: string
  ownerId: string
}): React.JSX.Element {
  const [files, setFiles] = useState<DocflowAttachment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError('')
    setFiles([])
    void loadDocflowAttachments(user, entity, ownerId)
      .then((next) => {
        if (alive) setFiles(next)
      })
      .catch((err: unknown) => {
        if (alive) setError(err instanceof Error ? err.message : 'Не удалось прочитать вложения')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [user, entity, ownerId])

  return (
    <section className="docflow-card-block">
      <h4>
        <Paperclip size={14} aria-hidden /> Вложения
        {files.length ? <span>{files.length}</span> : null}
      </h4>
      {loading ? <p className="docflow-muted">Загружаем вложения из 1С…</p> : null}
      {error ? <p className="docflow-edit-notice is-error">{error}</p> : null}
      {!loading && !error && !files.length ? <p className="docflow-muted">Вложений нет</p> : null}
      {files.length ? (
        <ul className="docflow-files">
          {files.map((file) => (
            <li key={file.id}>
              <DocflowFileOpenButton file={file}>
                <Paperclip size={12} aria-hidden />
                {fileLabel(file)}
              </DocflowFileOpenButton>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
