import { fileTypeIconSrc } from '../../utils/fileTypeIcon'

export type TodayFileKind = 'doc' | 'pdf' | 'xls' | 'csv'

export function fileKindFromName(name: string): TodayFileKind {
  const lower = (name || '').toLowerCase()
  if (/\.pdf$/.test(lower)) return 'pdf'
  if (/\.csv$/.test(lower)) return 'csv'
  if (/\.(xlsx?|xlsm)$/.test(lower)) return 'xls'
  return 'doc'
}

export function TodayFileIcon({
  name,
  kind,
  size = 28
}: {
  name: string
  kind?: TodayFileKind
  size?: number
}): React.JSX.Element {
  const label = kind ? `${kind} file` : name
  return (
    <img
      className="today-file-ico"
      src={fileTypeIconSrc(name)}
      alt=""
      title={name}
      aria-label={label}
      width={size}
      height={size}
      loading="lazy"
      decoding="async"
    />
  )
}

const FILE_EXTENSIONS =
  'xlsx?|xlsm|xlsb|docx?|pdf|csv|txt|md|pptx?|ppt|ods|odt|rtf|png|jpe?g|gif|webp|zip|7z'

const DOCUMENT_FILE_NAME_RE = new RegExp(
  `[A-Za-zА-Яа-яЁё0-9_][A-Za-zА-Яа-яЁё0-9_.\\-\\s]*\\.(?:${FILE_EXTENSIONS})`,
  'i'
)

export function isDocumentFileName(value: string): boolean {
  const trimmed = (value || '').trim().replace(/^["'`]+|["'`]+$/g, '')
  if (!trimmed) return false
  return new RegExp(`^${DOCUMENT_FILE_NAME_RE.source}$`, 'i').test(trimmed)
}

export function documentFileNamePattern(): RegExp {
  return new RegExp(
    `([A-Za-zА-Яа-яЁё0-9_][A-Za-zА-Яа-яЁё0-9_.\\-\\s]*\\.(?:${FILE_EXTENSIONS}))\\b`,
    'gi'
  )
}

export function DocumentFileBadge({
  name,
  onOpen
}: {
  name: string
  onOpen?: () => void
}): React.JSX.Element {
  const label = (name || '').trim()
  if (onOpen) {
    return (
      <button
        type="button"
        className="today-result-doc-file-badge today-result-doc-file-badge-btn"
        title={label}
        onClick={(event) => {
          event.stopPropagation()
          onOpen()
        }}
      >
        <TodayFileIcon name={label} size={20} />
        <span className="today-result-doc-file-badge-label">{label}</span>
      </button>
    )
  }
  return (
    <span className="today-result-doc-file-badge" title={label}>
      <TodayFileIcon name={label} size={20} />
      <span className="today-result-doc-file-badge-label">{label}</span>
    </span>
  )
}

export function collectDocumentFileNames(text: string): string[] {
  const found = new Set<string>()
  const source = (text || '').trim()
  if (!source) return []

  for (const match of source.matchAll(/`([^`]+)`/g)) {
    const name = match[1].trim()
    if (isDocumentFileName(name)) found.add(name)
  }

  const fileRe = documentFileNamePattern()
  let match: RegExpExecArray | null
  while ((match = fileRe.exec(source))) {
    found.add(match[1].trim())
  }

  return [...found]
}
