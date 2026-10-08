import { useEffect, useState } from 'react'
import { backendUrl } from '../api/client'
import type { AttachmentUpload, SessionAttachment } from '../api/types'
import { CloseIcon, FileIcon } from '../components/Icons'

export const MAX_FILES = 10
export const MAX_FILE_BYTES = 25 * 1024 * 1024
const IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp'])

export interface PendingFile {
  id: string
  file: File
  /** Object URL для миниатюры фотографии. */
  preview: string
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`
}

function extension(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(dot + 1).toUpperCase().slice(0, 4) : 'ФАЙЛ'
}

// Вставленный из буфера снимок экрана всегда называется image.png — даём различимое имя.
function displayName(file: File): string {
  if (file.name && file.name !== 'image.png') return file.name
  const stamp = new Date().toTimeString().slice(0, 8).replace(/:/g, '-')
  const ext = file.type.split('/')[1]?.replace('jpeg', 'jpg') || 'png'
  return `снимок-${stamp}.${ext}`
}

export function pendingFrom(files: File[]): { added: PendingFile[]; rejected: string[] } {
  const added: PendingFile[] = []
  const rejected: string[] = []
  for (const file of files) {
    if (file.size > MAX_FILE_BYTES) {
      rejected.push(`«${file.name}» больше ${MAX_FILE_BYTES / 1024 / 1024} МБ`)
      continue
    }
    const named = file.name && file.name !== 'image.png' ? file : new File([file], displayName(file), { type: file.type })
    added.push({
      id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      file: named,
      preview: IMAGE_TYPES.has(file.type) ? URL.createObjectURL(file) : ''
    })
  }
  return { added, rejected }
}

export function toUpload(item: PendingFile): Promise<AttachmentUpload> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error(`Не удалось прочитать «${item.file.name}»`))
    reader.onload = () => {
      const url = String(reader.result)
      resolve({ name: item.file.name, mime: item.file.type, data: url.slice(url.indexOf(',') + 1) })
    }
    reader.readAsDataURL(item.file)
  })
}

export function ComposerFiles({
  files,
  onRemove
}: {
  files: PendingFile[]
  onRemove: (id: string) => void
}): React.JSX.Element {
  return (
    <ul className="sess-files" aria-label="Вложения">
      {files.map((item) => (
        <li key={item.id} className={item.preview ? 'sess-file photo' : 'sess-file'} title={item.file.name}>
          {item.preview ? (
            <img src={item.preview} alt={item.file.name} />
          ) : (
            <>
              <span className="sess-file-ext">{extension(item.file.name)}</span>
              <span className="sess-file-text">
                <strong>{item.file.name}</strong>
                <span>{formatSize(item.file.size)}</span>
              </span>
            </>
          )}
          <button
            type="button"
            className="sess-file-remove"
            aria-label={`Убрать ${item.file.name}`}
            onClick={() => onRemove(item.id)}
          >
            <CloseIcon size={12} />
          </button>
        </li>
      ))}
    </ul>
  )
}

function fileUrl(sessionId: string, path: string): string {
  const encoded = path.split('/').map(encodeURIComponent).join('/')
  return `${backendUrl()}/api/v1/platform/sessions/${encodeURIComponent(sessionId)}/files/${encoded}`
}

export function MessageFiles({
  sessionId,
  files
}: {
  sessionId: string
  files: SessionAttachment[]
}): React.JSX.Element {
  const [open, setOpen] = useState<SessionAttachment | null>(null)
  const photos = files.filter((item) => item.image)
  const others = files.filter((item) => !item.image)

  useEffect(() => {
    if (!open) return
    const close = (event: globalThis.KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(null)
    }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [open])

  return (
    <div className="sess-message-files">
      {photos.length ? (
        <div className="sess-photos">
          {photos.map((item) => (
            <button key={item.path} type="button" className="sess-photo" title={item.name} onClick={() => setOpen(item)}>
              <img src={fileUrl(sessionId, item.path)} alt={item.name} loading="lazy" />
            </button>
          ))}
        </div>
      ) : null}
      {others.map((item) => (
        <div key={item.path} className="sess-file in-message" title={item.path}>
          <span className="sess-file-ext">{extension(item.name)}</span>
          <span className="sess-file-text">
            <strong>{item.name}</strong>
            <span>{formatSize(item.size)}</span>
          </span>
        </div>
      ))}
      {open ? (
        <div className="sess-lightbox" role="dialog" aria-label={open.name} onClick={() => setOpen(null)}>
          <img src={fileUrl(sessionId, open.path)} alt={open.name} />
          <span>
            <FileIcon size={14} />
            {open.name} · {formatSize(open.size)}
          </span>
        </div>
      ) : null}
    </div>
  )
}
