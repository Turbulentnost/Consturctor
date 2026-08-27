import type { ReactNode } from 'react'

const TABLE_SEP = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/
const HEADING = /^(#{1,3})\s+(.+)$/
const BOLD_HEAD = /^\*\*(.+?)\*\*$/
const UL = /^[-*•]\s+(.+)$/
const OL = /^(\d+)[.)]\s+(.+)$/
const FENCE = /^```/

function splitRow(line: string): string[] {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim())
}

function isTableRow(line: string): boolean {
  const trimmed = line.trim()
  if (!trimmed || FENCE.test(trimmed) || TABLE_SEP.test(trimmed)) return false
  return trimmed.includes('|') && splitRow(trimmed).length >= 2
}

function inline(text: string): ReactNode[] {
  const nodes: ReactNode[] = []
  const pattern = /(\*\*(.+?)\*\*|`([^`]+)`)/g
  let last = 0
  let match: RegExpExecArray | null
  let key = 0
  while ((match = pattern.exec(text))) {
    if (match.index > last) nodes.push(text.slice(last, match.index))
    if (match[2]) nodes.push(<strong key={`b-${key}`}>{match[2]}</strong>)
    else if (match[3]) nodes.push(<code key={`c-${key}`}>{match[3]}</code>)
    last = match.index + match[0].length
    key += 1
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

function isTableStart(lines: string[], index: number): boolean {
  if (!isTableRow(lines[index])) return false
  const next = lines[index + 1] || ''
  if (TABLE_SEP.test(next)) return true
  return isTableRow(next)
}

export function MarkdownBody({ text }: { text: string }): React.JSX.Element {
  const raw = (text || '').replace(/\r\n/g, '\n')
  if (!raw.trim()) return <></>
  const lines = raw.split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  let key = 0

  while (i < lines.length) {
    const line = lines[i]
    if (FENCE.test(line.trim())) {
      i += 1
      const code: string[] = []
      while (i < lines.length && !FENCE.test(lines[i].trim())) {
        code.push(lines[i])
        i += 1
      }
      if (i < lines.length) i += 1
      blocks.push(
        <pre key={`pre-${key}`} className="md-pre">
          <code>{code.join('\n')}</code>
        </pre>
      )
      key += 1
      continue
    }
    if (isTableStart(lines, i)) {
      const header = splitRow(lines[i])
      const rows: string[][] = []
      i += 1
      if (TABLE_SEP.test(lines[i] || '')) i += 1
      while (i < lines.length && isTableRow(lines[i])) {
        rows.push(splitRow(lines[i]))
        i += 1
      }
      blocks.push(
        <div key={`tbl-${key}`} className="md-table-wrap">
          <table className="md-table">
            <thead>
              <tr>
                {header.map((cell) => (
                  <th key={cell}>{inline(cell)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {header.map((_, col) => (
                    <td key={col}>{inline(row[col] || '')}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
      key += 1
      continue
    }
    const stripped = line.trim()
    if (!stripped) {
      i += 1
      continue
    }
    const heading = HEADING.exec(stripped)
    const boldHead = !heading ? BOLD_HEAD.exec(stripped) : null
    if (heading || boldHead) {
      const level = heading ? heading[1].length : 3
      const title = inline(heading ? heading[2] : boldHead![1])
      blocks.push(
        level === 1 ? (
          <h1 key={`h-${key}`} className="md-h md-h1">
            {title}
          </h1>
        ) : level === 2 ? (
          <h2 key={`h-${key}`} className="md-h md-h2">
            {title}
          </h2>
        ) : (
          <h3 key={`h-${key}`} className="md-h md-h3">
            {title}
          </h3>
        )
      )
      key += 1
      i += 1
      continue
    }
    const ul = UL.exec(stripped)
    if (ul) {
      const items: string[] = []
      while (i < lines.length) {
        const next = UL.exec(lines[i].trim())
        if (!next) break
        items.push(next[1])
        i += 1
      }
      blocks.push(
        <ul key={`ul-${key}`} className="md-list">
          {items.map((item, idx) => (
            <li key={idx}>{inline(item)}</li>
          ))}
        </ul>
      )
      key += 1
      continue
    }
    const ol = OL.exec(stripped)
    if (ol) {
      const items: string[] = []
      while (i < lines.length) {
        const next = OL.exec(lines[i].trim())
        if (!next) break
        items.push(next[2])
        i += 1
      }
      blocks.push(
        <ol key={`ol-${key}`} className="md-list">
          {items.map((item, idx) => (
            <li key={idx}>{inline(item)}</li>
          ))}
        </ol>
      )
      key += 1
      continue
    }
    blocks.push(
      <p key={`p-${key}`} className="md-p">
        {inline(stripped)}
      </p>
    )
    key += 1
    i += 1
  }

  return <div className="md-body">{blocks}</div>
}
