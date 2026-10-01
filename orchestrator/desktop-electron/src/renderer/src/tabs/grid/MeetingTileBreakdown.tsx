import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { SpecSummaryTiles } from '../../workplace/specV04Components'
import type { SpecSummaryTile } from '../../workplace/specV04Shell'
import { formatSurnameInitials } from '../../workplace/tileFilters'
import './meetingsPanel.css'

const POP_GAP = 6
const POP_MIN_WIDTH = 210

export type MeetingBreakdownRow = { person: string; count: number; color: string }

/**
 * Плитка совещаний: значение на плитке — сумма по всем календарям, а по клику
 * под ней раскрывается разбивка по каждому человеку. Панель в портале, потому
 * что полоса плиток режет overflow.
 */
export function MeetingTileBreakdown({
  tile,
  active,
  rows,
  onSelect
}: {
  tile: SpecSummaryTile
  active: boolean
  rows: MeetingBreakdownRow[]
  onSelect: (id: string) => void
}): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const popRef = useRef<HTMLDivElement>(null)
  const splitable = rows.length > 1

  useEffect(() => {
    if (!splitable) setOpen(false)
  }, [splitable])

  useLayoutEffect(() => {
    if (!open) return
    const place = (): void => {
      const rect = rootRef.current?.getBoundingClientRect()
      if (!rect) return
      const width = Math.max(POP_MIN_WIDTH, Math.min(rect.width, window.innerWidth - 16))
      const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))
      setPos({ top: rect.bottom + POP_GAP, left, width })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent): void => {
      const target = event.target as Node
      if (rootRef.current?.contains(target) || popRef.current?.contains(target)) return
      setOpen(false)
    }
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const total = rows.reduce((sum, row) => sum + row.count, 0)

  return (
    <div className="meet-tile-wrap" ref={rootRef}>
      <SpecSummaryTiles
        tiles={[tile]}
        activeId={active ? tile.id : null}
        onSelect={(id) => {
          onSelect(id)
          if (splitable) setOpen((value) => !value)
        }}
        className="spec-v04-tile-solo"
      />
      {open && pos
        ? createPortal(
            <div
              ref={popRef}
              className="meet-tile-pop"
              role="dialog"
              aria-label={`${tile.label}: по календарям`}
              style={{ top: pos.top, left: pos.left, width: pos.width }}
            >
              <p className="meet-tile-pop-head">{tile.label} · по календарям</p>
              <ul className="meet-tile-pop-list">
                {rows.map((row) => (
                  <li key={row.person}>
                    <span className="meet-tile-pop-dot" style={{ background: row.color }} aria-hidden />
                    <span className="meet-tile-pop-name" title={row.person}>
                      {formatSurnameInitials(row.person)}
                    </span>
                    <span className="meet-tile-pop-count">{row.count}</span>
                  </li>
                ))}
              </ul>
              <p className="meet-tile-pop-total">
                <span>Всего</span>
                <span>{total}</span>
              </p>
            </div>,
            document.body
          )
        : null}
    </div>
  )
}
