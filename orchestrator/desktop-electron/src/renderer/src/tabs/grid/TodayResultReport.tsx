import type { JSX, ReactNode } from 'react'
import { isBrokenResultText } from '../../utils/cleanRunResult'
import {
  collectDocumentFileNames,
  DocumentFileBadge,
  documentFileNamePattern,
  isDocumentFileName
} from './todayFileIcon'
import { useOpenReferencedFile } from './resultFileOpenContext'

function countMarkers(text: string, marker: string): number {
  return (text.match(new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')) || []).length
}

export function stripInlineMarkdown(text: string): string {
  return (text || '')
    .replace(/\\\*\\\*/g, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*/g, '')
    .replace(/`/g, '')
    .trim()
}

function repairInlineMarkdown(text: string): string {
  let value = text.replace(/\\\*\\\*/g, '**')
  value = value.replace(/\*{4,}([^*]+?)\*{4,}/g, '**$1**')
  value = value.replace(/\*\*\*([^*]+?)\*\*\*/g, '**$1**')
  for (let i = 0; i < 4; i += 1) {
    value = value.replace(/\*\*([^*\n]+?)\s+\*\*/g, '**$1**')
    value = value.replace(/\*\*\s+([^*\n]+?)\*\*/g, '**$1**')
  }
  while (countMarkers(value, '**') % 2 === 1) {
    const open = value.indexOf('**')
    if (open < 0) break
    value = `${value.slice(0, open)}${value.slice(open + 2)}`
  }
  return value
}

/** Agent log / soft-wrap text → readable document prose. */
export function normalizeDocumentProse(text: string): string {
  let value = (text || '')
    .replace(/\r\n/g, '\n')
    .replace(/\u00ad/g, '')
    .replace(/\u200b/g, '')
    .replace(/\uFEFF/g, '')
    .replace(/\\\*\\\*/g, '**')
    .trim()
  if (!value) return ''

  for (let pass = 0; pass < 6; pass += 1) {
    value = value.replace(/([А-Яа-яA-Za-z0-9])-\n(?!\n)([а-яa-z])/g, '$1$2')
    value = value.replace(/([А-Яа-яA-Za-z])\n(?!\n)([а-яa-z])/g, '$1$2')
    value = value.replace(/([а-яa-z0-9»")])\n(?!\n)([а-яa-z«(])/g, '$1 $2')
    value = value.replace(/\*\*([^*\n]*?)\n([^*\n]*?)\*\*/g, '**$1 $2**')
    value = value.replace(/`([^`\n]*?)\n([^`\n]*?)`/g, '`$1 $2`')
  }

  const rawBlocks = value
    .split(/\n{2,}/)
    .map((block) =>
      block
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line && line !== '.' && line !== '—' && line !== '-')
        .join(' ')
        .replace(/[ \t]{2,}/g, ' ')
        .replace(/\s+([.,;:!?…])/g, '$1')
        .replace(/([«„(])\s+/g, '$1')
        .replace(/\s+([»“)])/g, '$1')
        .replace(/\s+\./g, '.')
        .trim()
    )
    .filter(Boolean)

  const merged: string[] = []
  for (const block of rawBlocks) {
    const prev = merged[merged.length - 1]
    const continues =
      /^[а-яa-z«(]/.test(block) ||
      /^на\b/.test(block) ||
      /^и\b/.test(block) ||
      /^или\b/.test(block)
    const prevIncomplete = prev && !/[.!?…:»"]\s*$/.test(prev)
    const prevOpensBold = prev ? countMarkers(prev, '**') % 2 === 1 : false

    if (prev && (prevOpensBold || (prevIncomplete && continues && !/^\*\*/.test(block)))) {
      merged[merged.length - 1] = `${prev} ${block}`.replace(/[ \t]{2,}/g, ' ').trim()
      continue
    }
    merged.push(block)
  }

  return merged
    .map((block) => repairInlineMarkdown(block))
    .filter(Boolean)
    .join('\n\n')
    .replace(/\n\s*[.]\s*\n/g, '\n\n')
    .trim()
}

function renderInline(text: string, onOpenFile?: (name: string) => void): ReactNode[] {
  const nodes: ReactNode[] = []
  const pattern = new RegExp(
    `\\*\\*([^*]+)\\*\\*|` + '`([^`]+)`|' + documentFileNamePattern().source,
    'gi'
  )
  let last = 0
  let match: RegExpExecArray | null
  let key = 0
  while ((match = pattern.exec(text))) {
    if (match.index > last) nodes.push(text.slice(last, match.index))
    const bold = match[1]
    const code = match[2]
    const fileName = match[3]
    if (bold !== undefined) {
      nodes.push(
        <strong key={`b-${key}`} className="today-result-doc-strong">
          {bold}
        </strong>
      )
    } else if (code !== undefined) {
      const trimmed = code.trim()
      if (isDocumentFileName(trimmed)) {
        nodes.push(
          <DocumentFileBadge
            key={`f-${key}`}
            name={trimmed}
            onOpen={onOpenFile ? () => onOpenFile(trimmed) : undefined}
          />
        )
      } else {
        nodes.push(
          <span key={`c-${key}`} className="today-result-doc-code">
            {trimmed}
          </span>
        )
      }
    } else if (fileName !== undefined) {
      nodes.push(
        <DocumentFileBadge
          key={`f-${key}`}
          name={fileName.trim()}
          onOpen={onOpenFile ? () => onOpenFile(fileName.trim()) : undefined}
        />
      )
    }
    last = match.index + match[0].length
    key += 1
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

function paragraphFileOnly(paragraph: string): string | null {
  const trimmed = paragraph.trim()
  const match = trimmed.match(
    /^(?:—\s*)?([A-Za-zА-Яа-яЁё0-9_][A-Za-zА-Яа-яЁё0-9_.\-\s]*\.(?:xlsx?|xlsm|xlsb|docx?|pdf|csv|txt|md|pptx?|ppt|ods|odt|rtf|png|jpe?g|gif|webp|zip|7z))\.?\s*$/i
  )
  return match?.[1] || null
}

function DocumentMarkdown({
  text,
  onOpenFile
}: {
  text: string
  onOpenFile?: (name: string) => void
}): JSX.Element {
  const paragraphs = text
    .split(/\n{2,}/)
    .map((item) => item.trim())
    .filter(Boolean)
  return (
    <div className="today-result-doc-markdown">
      {paragraphs.map((paragraph, index) => {
        const fileOnly = paragraphFileOnly(paragraph)
        if (fileOnly) {
          return (
            <div key={index} className="today-result-doc-file-row">
              <DocumentFileBadge
                name={fileOnly}
                onOpen={onOpenFile ? () => onOpenFile(fileOnly) : undefined}
              />
            </div>
          )
        }
        return (
          <p key={index} className="today-result-doc-paragraph">
            {renderInline(paragraph, onOpenFile)}
          </p>
        )
      })}
    </div>
  )
}

function DocumentFilesSummary({
  files,
  onOpenFile
}: {
  files: string[]
  onOpenFile?: (name: string) => void
}): JSX.Element | null {
  if (!files.length) return null
  return (
    <section className="today-result-doc-files-summary" aria-label="Файлы в отчёте">
      <h6 className="today-result-doc-files-summary-title">Файлы</h6>
      <div className="today-result-doc-files-summary-list">
        {files.map((name) => (
          <DocumentFileBadge
            key={name}
            name={name}
            onOpen={onOpenFile ? () => onOpenFile(name) : undefined}
          />
        ))}
      </div>
    </section>
  )
}

export function TodayResultReport({
  text,
  attachmentName
}: {
  text: string
  attachmentName?: string
}): JSX.Element {
  if (isBrokenResultText(text)) {
    return (
      <article className="today-result-preview-doc today-result-report">
        <p className="today-result-preview-plain">{text}</p>
      </article>
    )
  }
  const onOpenFile = useOpenReferencedFile()
  const normalized = normalizeDocumentProse(text)
  const files = collectDocumentFileNames(normalized)
  const attachment = (attachmentName || '').trim()
  if (attachment && !files.includes(attachment)) {
    files.unshift(attachment)
  }
  if (!normalized && !files.length) {
    return <p className="today-result-preview-status">Пустой результат</p>
  }
  return (
    <div className="today-result-preview-doc today-result-report today-result-doc-prose">
      {normalized ? <DocumentMarkdown text={normalized} onOpenFile={onOpenFile || undefined} /> : null}
      <DocumentFilesSummary files={files} onOpenFile={onOpenFile || undefined} />
    </div>
  )
}
