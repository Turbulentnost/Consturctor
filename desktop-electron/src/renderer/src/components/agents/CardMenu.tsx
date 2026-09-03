import { useEffect, useRef, useState } from 'react'

export interface MenuItem {
  label: string
  onClick: () => void
  danger?: boolean
  separatorBefore?: boolean
}

interface CardMenuProps {
  items: MenuItem[]
  openSignal?: number
}

export function CardMenu({ items, openSignal = 0 }: CardMenuProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const hostRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (openSignal) setOpen(true)
  }, [openSignal])

  useEffect(() => {
    if (!open) return
    function onDocClick(evt: MouseEvent): void {
      if (hostRef.current && !hostRef.current.contains(evt.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  return (
    <div className="card-menu" ref={hostRef}>
      <button
        className="card-menu-btn"
        onClick={(e) => {
          e.stopPropagation()
          setOpen((prev) => !prev)
        }}
        aria-label="Меню"
      >
        &#8942;
      </button>
      {open && (
        <div className="card-menu-popover" onClick={(e) => e.stopPropagation()}>
          {items.map((item, index) => (
            <div key={`${item.label}-${index}`}>
              {item.separatorBefore && <div className="card-menu-sep" />}
              <button
                className={item.danger ? 'card-menu-item danger' : 'card-menu-item'}
                onClick={() => {
                  setOpen(false)
                  item.onClick()
                }}
              >
                {item.label}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
