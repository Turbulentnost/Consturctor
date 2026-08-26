import type { ReactNode } from 'react'

const TABLE_ROW = /^\s*\|.+\|\s*$/
const TABLE_SEP = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/
const HEADING = /^(#{1,3})\s+(.+)$/
const UL = /^[-*•]\s+(.+)$/
const OL = /^(\d+)[.)]\s+(.+)$/
const FENCE = /^```/

function splitRow(line: string): string[] {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim())
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
  return Boolean(lines[index + 1] && TABLE_ROW.test(lines[index]) && TABLE_SEP.test(lines[index + 1]))
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
      i += 2
      while (i < lines.length && TABLE_ROW.test(lines[i]) && !TABLE_SEP.test(lines[i])) {
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
    if (heading) {
      const level = heading[1].length
      const title = inline(heading[2])
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
