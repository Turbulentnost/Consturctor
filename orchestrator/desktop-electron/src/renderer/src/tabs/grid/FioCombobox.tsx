import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

const LIST_MAX_HEIGHT = 280

/** Поле ФИО с прокручиваемым списком подсказок (datalist не даёт задать высоту). */
export function FioCombobox({
  value,
  hints,
  placeholder,
  onChange
}: {
  value: string
  hints: string[]
  placeholder?: string
  onChange: (value: string) => void
}): React.JSX.Element {
  const listId = useId()
  const inputRef = useRef<HTMLInputElement | null>(null)
  const listRef = useRef<HTMLUListElement | null>(null)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [pos, setPos] = useState({ top: 0, left: 0, width: 0, up: false })

  const items = useMemo(() => {
    const words = value.trim().toLowerCase().replace(/ё/g, 'е').split(/\s+/).filter(Boolean)
    if (!words.length) return hints
    return hints.filter((fio) => {
      const key = fio.toLowerCase().replace(/ё/g, 'е')
      return words.every((word) => key.includes(word))
    })
  }, [hints, value])

  const place = (): void => {
    const box = inputRef.current?.getBoundingClientRect()
    if (!box) return
    const up = window.innerHeight - box.bottom < LIST_MAX_HEIGHT + 16 && box.top > LIST_MAX_HEIGHT + 16
    setPos({ top: up ? box.top - 4 : box.bottom + 4, left: box.left, width: box.width, up })
  }

  useEffect(() => {
    if (!open) return
    place()
    const onMove = (): void => place()
    window.addEventListener('resize', onMove)
    document.addEventListener('scroll', onMove, true)
    return () => {
      window.removeEventListener('resize', onMove)
      document.removeEventListener('scroll', onMove, true)
    }
  }, [open])

  useEffect(() => {
    setActive(-1)
  }, [items])

  useEffect(() => {
    if (active < 0) return
    const node = listRef.current?.children[active] as HTMLElement | undefined
    node?.scrollIntoView({ block: 'nearest' })
  }, [active])

  const pick = (fio: string): void => {
    onChange(fio)
    setOpen(false)
  }

  return (
    <>
      <input
        ref={inputRef}
        className="onec-reconnect-input"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        autoComplete="off"
        value={value}
        placeholder={placeholder}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onChange={(event) => {
          onChange(event.target.value)
          setOpen(true)
        }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown') {
            event.preventDefault()
            setOpen(true)
            setActive((current) => Math.min(items.length - 1, current + 1))
          } else if (event.key === 'ArrowUp') {
            event.preventDefault()
            setActive((current) => Math.max(0, current - 1))
          } else if (event.key === 'Enter' && open && active >= 0 && items[active]) {
            event.preventDefault()
            pick(items[active])
          } else if (event.key === 'Escape') {
            setOpen(false)
          }
        }}
      />
      {open && items.length
        ? createPortal(
            <ul
              ref={listRef}
              id={listId}
              role="listbox"
              className="tc-combo-list"
              style={{
                top: pos.top,
                left: pos.left,
                width: pos.width,
                maxHeight: LIST_MAX_HEIGHT,
                transform: pos.up ? 'translateY(-100%)' : undefined
              }}
            >
              {items.map((fio, index) => (
                <li
                  key={fio}
                  role="option"
                  aria-selected={index === active}
                  className={index === active ? 'is-active' : undefined}
                  onMouseDown={(event) => {
                    event.preventDefault()
                    pick(fio)
                  }}
                  onMouseEnter={() => setActive(index)}
                >
                  {fio}
                </li>
              ))}
            </ul>,
            document.body
          )
        : null}
    </>
  )
}
