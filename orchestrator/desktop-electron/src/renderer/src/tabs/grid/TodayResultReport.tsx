import { Bell, CheckCircle2, FileSpreadsheet, Info } from 'lucide-react'
import { MarkdownBody } from '../../components/agentfeed/MarkdownBody'
import { isBrokenResultText } from '../../utils/cleanRunResult'

const SECTION_HEAD =
  /(?:^|\n)[ \t]*(?:#{1,6}[ \t]*|\*\*)?(FILES|ACTIONS|NOTIFICATIONS|SCHEDULE|CLARIFY|RESULT|ФАЙЛЫ|ДЕЙСТВИЯ|УВЕДОМЛЕНИЯ|РЕЗУЛЬТАТ)\*?\*?[ \t]*:?[ \t]*(?:\n|$)/gi

const SECTION_TITLE: Record<string, string> = {
  files: 'Результат',
  actions: 'Что сделано',
  notifications: 'Кому сообщить',
  schedule: 'Расписание',
  clarify: 'Нужно уточнить',
  result: 'Итог',
  файлы: 'Результат',
  действия: 'Что сделано',
  уведомления: 'Кому сообщить',
  результат: 'Итог'
}

const INLINE_RE = /(\bACT\d{3}-\d{4,}\b|[A-Za-z0-9._-]+\.(?:xlsx|xls|csv|docx|pdf)\b|IN PROGRESS)/gi

function ticketCodes(text: string): string[] {
  return text.match(/\bACT\d{3}-\d{4,}\b/gi) || []
}

type ReportSection = {
  key: string
  title: string
  items: string[]
}

type ReportBlock =
  | { kind: 'paragraphs'; texts: string[] }
  | { kind: 'group'; title: string; items: string[]; tone: 'alert' | 'warn' | 'neutral' }
  | { kind: 'markdown'; text: string }

function sectionTitle(raw: string): string {
  return SECTION_TITLE[raw.toLowerCase()] || raw
}

function splitSentences(text: string): string[] {
  const compact = text.replace(/[ \t]+/g, ' ').replace(/\n+/g, ' ').trim()
  if (!compact) return []
  const out: string[] = []
  let current = ''
  for (let i = 0; i < compact.length; i += 1) {
    current += compact[i]
    if (compact[i] !== '.') continue
    if (compact[i + 1] !== ' ') continue
    const next = compact[i + 2] || ''
    const prev = compact[i - 1] || ''
    if (!/[А-ЯЁA-Z«]/.test(next) || !/[а-яёa-z)…»]/.test(prev)) continue
    out.push(current.trim())
    current = ''
    i += 1
  }
  if (current.trim()) out.push(current.trim())
  return out.length ? out : [compact]
}

function peelListTail(items: string[]): { items: string[]; tail: string[] } {
  const last = items[items.length - 1] || ''
  const sentences = splitSentences(last)
  if (sentences.length < 2) return { items, tail: [] }
  const kept = [sentences[0], ...sentences.slice(1).filter((item) => ticketCodes(item).length)]
  const tail = sentences.slice(1).filter((item) => !ticketCodes(item).length)
  if (!tail.length) return { items, tail: [] }
  return { items: [...items.slice(0, -1), kept.join(' ')], tail }
}

function asNamedList(text: string): { title: string; items: string[]; tail: string[] } | null {
  const codes = ticketCodes(text)
  if (codes.length < 2) return null
  const start = text.search(/\bACT\d{3}-\d/i)
  if (start < 0) return null
  const prefix = text.slice(0, start).replace(/[:—-]\s*$/, '').trim()
  const labeled = /^(.*?):\s*(.*)$/.exec(prefix)
  const title = (labeled?.[1] || prefix).trim()
  const extra = (labeled?.[2] || '').trim()
  const body = `${extra ? `${extra} ` : ''}${text.slice(start).trim()}`
  const items = body
    .split(/\s*;\s*/)
    .map((item) => item.replace(/^[—-]\s*/, '').trim())
    .filter(Boolean)
  if (items.length < 2 || title.length > 80) return null
  const peeled = peelListTail(items)
  return { title, items: peeled.items, tail: peeled.tail }
}

function groupTone(title: string): 'alert' | 'warn' | 'neutral' {
  const value = title.toLowerCase()
  if (value.includes('просроч')) return 'alert'
  if (value.includes('без владель') || value.includes('ближайш')) return 'warn'
  return 'neutral'
}

function listItems(body: string): string[] {
  const lines = body
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  if (!lines.length) return []
  const bullets = lines.filter((line) => /^[-*•]\s+/.test(line) || /^\d+[.)]\s+/.test(line))
  if (bullets.length >= 1 && bullets.length === lines.length) {
    return lines.map((line) => line.replace(/^[-*•]\s+/, '').replace(/^\d+[.)]\s+/, '').trim())
  }
  const named = asNamedList(body)
  if (named) return named.items
  return [body.trim()]
}

function parseSections(text: string): { lead: string; sections: ReportSection[] } {
  const raw = (text || '').replace(/\r\n/g, '\n').trim()
  const head = new RegExp(SECTION_HEAD.source, SECTION_HEAD.flags)
  const matches = [...raw.matchAll(head)]
  if (!matches.length) return { lead: raw, sections: [] }
  const first = matches[0]
  const lead = raw.slice(0, first.index).trim()
  const sections: ReportSection[] = []
  for (let i = 0; i < matches.length; i += 1) {
    const match = matches[i]
    const start = (match.index || 0) + match[0].length
    const end = i + 1 < matches.length ? matches[i + 1].index || raw.length : raw.length
    const key = (match[1] || '').toLowerCase()
    const body = raw.slice(start, end).trim()
    if (!body) continue
    const title = sectionTitle(match[1] || '')
    if (key === 'result' || key === 'результат') {
      continue
    }
    sections.push({ key, title, items: listItems(body) })
  }
  const resultMatch = matches.find((item) => /^(result|результат)$/i.test(item[1] || ''))
  if (resultMatch) {
    const idx = matches.indexOf(resultMatch)
    const start = (resultMatch.index || 0) + resultMatch[0].length
    const end = idx + 1 < matches.length ? matches[idx + 1].index || raw.length : raw.length
    const resultBody = raw.slice(start, end).trim()
    return { lead: [lead, resultBody].filter(Boolean).join('\n\n'), sections }
  }
  return { lead, sections }
}

function leadChunks(lead: string): string[] {
  const byBlank = lead
    .split(/\n{2,}/)
    .map((chunk) => chunk.trim())
    .filter(Boolean)
  if (byBlank.length > 1) return byBlank
  const byLine = lead
    .split('\n')
    .map((chunk) => chunk.trim())
    .filter(Boolean)
  return byLine.length ? byLine : [lead.trim()].filter(Boolean)
}

function leadBlocks(lead: string): ReportBlock[] {
  const chunks = leadChunks(lead)
  const blocks: ReportBlock[] = []
  for (const chunk of chunks) {
    const named = asNamedList(chunk)
    if (named) {
      blocks.push({ kind: 'group', title: named.title, items: named.items, tone: groupTone(named.title) })
      if (named.tail.length) blocks.push({ kind: 'paragraphs', texts: named.tail })
      continue
    }
    if (/^(#{1,3}\s+|\|.+\|)/m.test(chunk) || chunk.includes('```')) {
      blocks.push({ kind: 'markdown', text: chunk })
      continue
    }
    const sentences = splitSentences(chunk)
    const texts: string[] = []
    for (const sentence of sentences) {
      const nested = asNamedList(sentence)
      if (nested) {
        if (texts.length) {
          blocks.push({ kind: 'paragraphs', texts: [...texts] })
          texts.length = 0
        }
        blocks.push({ kind: 'group', title: nested.title, items: nested.items, tone: groupTone(nested.title) })
        if (nested.tail.length) blocks.push({ kind: 'paragraphs', texts: nested.tail })
        continue
      }
      texts.push(sentence)
    }
    if (texts.length) blocks.push({ kind: 'paragraphs', texts })
  }
  return blocks
}

function ResultInline({ text }: { text: string }): React.JSX.Element {
  const parts = text.split(INLINE_RE)
  return (
    <>
      {parts.map((part, index) => {
        if (!part) return null
        if (/^ACT\d{3}-\d{4,}$/i.test(part)) {
          return (
            <span key={`${part}:${index}`} className="today-result-code">
              {part}
            </span>
          )
        }
        if (/\.(xlsx|xls|csv|docx|pdf)$/i.test(part)) {
          return (
            <span key={`${part}:${index}`} className="today-result-file">
              {part}
            </span>
          )
        }
        if (/^IN PROGRESS$/i.test(part)) {
          return (
            <span key={`${part}:${index}`} className="today-result-pill">
              в работе
            </span>
          )
        }
        return <span key={`${part}:${index}`}>{part}</span>
      })}
    </>
  )
}

function SectionIcon({ title }: { title: string }): React.JSX.Element {
  if (title === 'Результат') return <FileSpreadsheet size={16} strokeWidth={2} aria-hidden />
  if (title === 'Что сделано') return <CheckCircle2 size={16} strokeWidth={2} aria-hidden />
  if (title === 'Кому сообщить') return <Bell size={16} strokeWidth={2} aria-hidden />
  return <Info size={16} strokeWidth={2} aria-hidden />
}

function BlockView({ block }: { block: ReportBlock }): React.JSX.Element {
  if (block.kind === 'markdown') {
    return (
      <div className="today-result-md">
        <MarkdownBody text={block.text} />
      </div>
    )
  }
  if (block.kind === 'group') {
    return (
      <div className={`today-result-group tone-${block.tone}`}>
        {block.title ? <h5>{block.title}</h5> : null}
        <ul>
          {block.items.map((item) => (
            <li key={item}>
              <ResultInline text={item} />
            </li>
          ))}
        </ul>
      </div>
    )
  }
  return (
    <div className="today-result-copy">
      {block.texts.map((text) => (
        <p key={text}>
          <ResultInline text={text} />
        </p>
      ))}
    </div>
  )
}

function renderedLength(lead: string, sections: ReportSection[]): number {
  return [lead, ...sections.flatMap((section) => section.items)].join(' ').replace(/\s+/g, ' ').trim()
    .length
}

export function TodayResultReport({ text }: { text: string }): React.JSX.Element {
  if (isBrokenResultText(text)) {
    return (
      <article className="today-result-preview-doc today-result-report">
        <p className="today-result-preview-plain">{text}</p>
      </article>
    )
  }
  const { lead, sections } = parseSections(text)
  const sourceLen = (text || '').replace(/\s+/g, ' ').trim().length
  const parsedLen = renderedLength(lead, sections)
  if (sourceLen && parsedLen < sourceLen * 0.5) {
    return (
      <article className="today-result-preview-doc today-result-report">
        <p className="today-result-preview-plain">{text}</p>
      </article>
    )
  }
  const blocks = leadBlocks(lead)
  if (!blocks.length && !sections.length) {
    return (
      <article className="today-result-preview-doc today-result-report">
        <p className="today-result-preview-plain">{text}</p>
      </article>
    )
  }
  return (
    <article className="today-result-preview-doc today-result-report">
      {blocks.map((block, index) => (
        <BlockView key={`lead:${index}`} block={block} />
      ))}
      {sections.map((section) => (
        <section key={section.key} className="today-result-section">
          <h5>
            <SectionIcon title={section.title} />
            {section.title}
          </h5>
          {section.items.length > 1 ? (
            <ul>
              {section.items.map((item) => (
                <li key={item}>
                  <ResultInline text={item} />
                </li>
              ))}
            </ul>
          ) : section.items[0] ? (
            <p>
              <ResultInline text={section.items[0]} />
            </p>
          ) : null}
        </section>
      ))}
    </article>
  )
}
