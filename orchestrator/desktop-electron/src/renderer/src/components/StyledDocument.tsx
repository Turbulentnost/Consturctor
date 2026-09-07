import { useEffect, type CSSProperties } from 'react'
import type {
  FragmentEntityTag,
  RegulationFragment,
  RegulationStyleRun,
  RegulationTable
} from '../api/types'
import { entityColor, groupFragments, isTocLine, parseTocLine } from '../documentEntities'

interface StyledDocumentProps {
  fragments: RegulationFragment[]
  highlightFragmentId?: string
}

function numberFromLocation(location: Record<string, unknown>, key: string): number {
  const value = location[key]
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function cssColor(color?: number): string | undefined {
  if (color == null || color === 0) return undefined
  return `#${color.toString(16).padStart(6, '0')}`
}

function cssFontFamily(fontName?: string): string | undefined {
  const name = (fontName || '').trim()
  if (!name) return undefined
  const marker = name.toLowerCase()
  if (marker.includes('times') || marker.includes('georgia') || marker.includes('cambria')) {
    return `"${name}", "Times New Roman", Times, serif`
  }
  if (marker.includes('courier') || marker.includes('consolas') || marker.includes('mono')) {
    return `"${name}", Consolas, "Courier New", monospace`
  }
  return `"${name}", Calibri, Arial, sans-serif`
}

function alignmentValue(value: unknown): CSSProperties['textAlign'] {
  const name = String(value || '').toLowerCase()
  if (name === 'center') return 'center'
  if (name === 'right') return 'right'
  if (name === 'justify') return 'justify'
  return 'left'
}

function headingLevel(fragment: RegulationFragment): 1 | 2 | 3 {
  const style = fragment.style.toLowerCase()
  if (style.includes('heading 1') || style.includes('заголовок 1')) return 1
  if (style.includes('heading 3') || style.includes('заголовок 3')) return 3
  const dots = (fragment.numbering || '').split('.').filter(Boolean).length
  if (dots >= 3) return 3
  if (dots === 1) return 1
  return 2
}

function blockStyle(fragment: RegulationFragment): CSSProperties {
  const indent = numberFromLocation(fragment.location, 'indentPt')
  const firstLine = numberFromLocation(fragment.location, 'firstLineIndentPt')
  const spaceBefore = numberFromLocation(fragment.location, 'spaceBeforePt')
  const spaceAfter = numberFromLocation(fragment.location, 'spaceAfterPt')
  const hanging = firstLine < 0 ? Math.abs(firstLine) : 0
  const fontSize = fragment.fontSize && fragment.fontSize > 0 ? fragment.fontSize : 12
  const isHeading = fragment.blockType === 'heading'
  const isList = fragment.blockType === 'list_item' || fragment.kind === 'list'
  const isContents = /^\s*содержание\s*$/i.test(fragment.text)
  return {
    marginTop: spaceBefore > 0 ? spaceBefore : isHeading ? 16 : 8,
    marginBottom: spaceAfter > 0 ? spaceAfter : isHeading ? 10 : 8,
    marginLeft: indent + hanging + (isList && indent <= 0 ? 18 : 0),
    textIndent: firstLine,
    textAlign: isContents ? 'center' : alignmentValue(fragment.location.alignment),
    fontSize: `${isHeading ? Math.max(fontSize, headingLevel(fragment) === 1 ? 16 : 14) : fontSize}pt`,
    fontWeight: fragment.isBold || isHeading || isContents ? 700 : 400,
    lineHeight: 1.45
  }
}

function StyleRunView({ run }: { run: RegulationStyleRun }): React.JSX.Element {
  const size = run.fontSize && run.fontSize > 0 ? run.fontSize : undefined
  return (
    <span
      style={{
        fontFamily: cssFontFamily(run.fontName),
        fontSize: size ? `${size}pt` : undefined,
        fontWeight: run.isBold ? 700 : undefined,
        fontStyle: run.isItalic ? 'italic' : undefined,
        textDecoration: run.underline ? 'underline' : undefined,
        color: cssColor(run.color)
      }}
    >
      {run.text}
    </span>
  )
}

function TableView({ table }: { table: RegulationTable }): React.JSX.Element {
  const blob = [...table.headers, ...table.rows.flat()].join(' ')
  const isTitleTable = /версия/i.test(blob) && (/лист/i.test(blob) || /листов/i.test(blob))
  const hasHeaders = table.headers.some((header) => header.trim()) && !isTitleTable
  const columns = Math.max(table.headers.length, ...table.rows.map((row) => row.length), 1)
  const labels = Array.from({ length: columns }, (_, index) => table.headers[index] || '')
  const rows = table.rows.length ? table.rows : [Array.from({ length: columns }, () => '')]
  return (
    <div className="review-table-wrap">
      <table className={isTitleTable ? 'review-table review-title-table' : 'review-table'}>
        {hasHeaders && (
          <thead>
            <tr>
              {labels.map((header, index) => (
                <th key={index}>{header}</th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {isTitleTable && !table.rows.length ? (
            <tr>
              {labels.map((header, index) => (
                <td key={index}>{header}</td>
              ))}
            </tr>
          ) : (
            rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {Array.from({ length: columns }, (_, col) => (
                  <td key={col}>{row[col] || ''}</td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

function TocView({ text }: { text: string }): React.JSX.Element {
  const parsed = parseTocLine(text)
  if (!parsed) {
    return <p className="review-frag">{text}</p>
  }
  return (
    <div className="review-toc-row">
      <span className="review-toc-title">{parsed.title}</span>
      <span className="review-toc-dots" />
      <span className="review-toc-page">{parsed.page}</span>
    </div>
  )
}

function FragmentView({ fragment }: { fragment: RegulationFragment }): React.JSX.Element | null {
  if (fragment.blockType === 'table_row') return null
  if (isTocLine(fragment.text)) return <TocView text={fragment.text} />
  if ((fragment.kind === 'table' || fragment.blockType === 'table') && fragment.table) {
    return <TableView table={fragment.table} />
  }

  const runs = fragment.styleRuns.filter((run) => (run.text || '').length > 0)
  const content = runs.length ? (
    runs.map((run, index) => <StyleRunView key={index} run={run} />)
  ) : (
    fragment.text
  )
  const className = [
    'review-frag',
    fragment.blockType === 'heading' ? `review-heading review-heading-${headingLevel(fragment)}` : '',
    fragment.blockType === 'list_item' || fragment.kind === 'list' ? 'review-list' : ''
  ]
    .filter(Boolean)
    .join(' ')

  if (fragment.blockType === 'heading') {
    const Tag = headingLevel(fragment) === 1 ? 'h2' : headingLevel(fragment) === 3 ? 'h4' : 'h3'
    return (
      <Tag className={className} style={blockStyle(fragment)}>
        {content}
      </Tag>
    )
  }

  return (
    <p className={className} style={blockStyle(fragment)}>
      {content}
    </p>
  )
}

function GroupView({
  entity,
  items,
  lastPage,
  highlightFragmentId
}: {
  entity: FragmentEntityTag | null
  items: RegulationFragment[]
  lastPage: number
  highlightFragmentId?: string
}): React.JSX.Element {
  let pageCursor = lastPage
  const body = items.map((fragment, index) => {
    const showPage = fragment.page > 0 && fragment.page !== pageCursor
    pageCursor = fragment.page || pageCursor
    const highlighted = Boolean(highlightFragmentId && fragment.fragmentId === highlightFragmentId)
    return (
      <div
        key={fragment.fragmentId || index}
        id={fragment.fragmentId ? `fragment-${fragment.fragmentId}` : undefined}
        data-fragment-id={fragment.fragmentId || undefined}
        className={highlighted ? 'review-frag-highlight' : undefined}
      >
        {showPage && <div className="review-page-break">Страница {fragment.page}</div>}
        <FragmentView fragment={fragment} />
      </div>
    )
  })
  if (!entity) {
    return <div className="review-plain-group">{body}</div>
  }
  const color = entityColor(entity)
  return (
    <div
      className="review-entity-group"
      style={{
        background: color.fill,
        borderLeftColor: color.border
      }}
    >
      {body}
    </div>
  )
}

export function StyledDocument({ fragments, highlightFragmentId }: StyledDocumentProps): React.JSX.Element {
  const groups = groupFragments(fragments)
  let lastPage = 0

  useEffect(() => {
    if (!highlightFragmentId) return
    const node = document.getElementById(`fragment-${highlightFragmentId}`)
    node?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [highlightFragmentId])

  return (
    <div className="review-paper">
      {groups.length === 0 && <div className="chat-hint">Текст регламента не распознан.</div>}
      {groups.map((group, index) => {
        const startPage = lastPage
        lastPage = group.items[group.items.length - 1]?.page || lastPage
        return (
          <GroupView
            key={`${group.entity?.entityId || 'plain'}-${index}`}
            entity={group.entity}
            items={group.items}
            lastPage={startPage}
            highlightFragmentId={highlightFragmentId}
          />
        )
      })}
    </div>
  )
}
