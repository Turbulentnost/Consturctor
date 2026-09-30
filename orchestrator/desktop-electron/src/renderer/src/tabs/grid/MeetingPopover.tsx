import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import './meetingPopover.css'

/** Зазор до блока и до краёв окна. */
const GAP = 10
const EDGE = 12

type Place = { left: number; top: number; ready: boolean }

/**
 * Ставим карточку справа от блока, а если справа не помещается — слева.
 * По вертикали равняем по верху блока и не даём уехать за края окна.
 */
function place(anchor: DOMRect, width: number, height: number): Place {
  const view = { w: window.innerWidth, h: window.innerHeight }
  const right = anchor.right + GAP
  const left = right + width <= view.w - EDGE ? right : anchor.left - GAP - width
  return {
    left: Math.max(EDGE, Math.min(left, view.w - width - EDGE)),
    top: Math.max(EDGE, Math.min(anchor.top, view.h - height - EDGE)),
    ready: true
  }
}

export function MeetingPopover({
  anchor,
  onClose,
  children
}: {
  anchor: DOMRect
  onClose: () => void
  children: React.ReactNode
}): React.JSX.Element {
  const cardRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<Place>({ left: 0, top: 0, ready: false })

  // Место считаем по реальному размеру карточки, поэтому первый кадр её прячем.
  useLayoutEffect(() => {
    const node = cardRef.current
    if (!node) return
    const measure = (): void => {
      const box = node.getBoundingClientRect()
      setPos(place(anchor, box.width, box.height))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    window.addEventListener('resize', measure)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', measure)
    }
  }, [anchor])

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    const onDown = (event: MouseEvent): void => {
      const target = event.target as HTMLElement | null
      if (!target || cardRef.current?.contains(target)) return
      // Диалоги протокола открываются в портале рядом с карточкой, а не внутри неё:
      // закрыть карточку по клику в них — значит закрыть и сам диалог.
      if (target.closest('.modal-overlay')) return
      onClose()
    }
    // Карточка привязана к месту блока на экране, поэтому прокрутка сетки её закрывает.
    const onScroll = (event: Event): void => {
      if (!cardRef.current?.contains(event.target as Node)) onClose()
    }
    window.addEventListener('keydown', onKey)
    // capture: иначе клик по другому совещанию сначала закроет карточку.
    window.addEventListener('mousedown', onDown, true)
    window.addEventListener('scroll', onScroll, true)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onDown, true)
      window.removeEventListener('scroll', onScroll, true)
    }
  }, [onClose])

  return createPortal(
    <div
      ref={cardRef}
      className="meet-pop"
      role="dialog"
      aria-modal="false"
      style={{ left: pos.left, top: pos.top, visibility: pos.ready ? 'visible' : 'hidden' }}
    >
      <button type="button" className="meet-pop-close" aria-label="Закрыть" onClick={onClose}>
        <X size={16} aria-hidden />
      </button>
      <div className="meet-pop-body">{children}</div>
    </div>,
    document.body
  )
}
