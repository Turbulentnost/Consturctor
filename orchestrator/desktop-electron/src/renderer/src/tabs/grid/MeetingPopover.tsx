import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import './meetingPopover.css'

/** Зазор до блока и до краёв окна. */
const GAP = 10
const EDGE = 12
/** Окна поверх карточки (диалоги протокола, список ФИО) рисуются порталом в body.
 *  Их клики, прокрутка и Escape не должны закрывать карточку: иначе вместе с ней пропадает и сама форма. */
const OVERLAY_SELECTOR = '.modal-overlay, .tc-combo-list'

function insideOverlay(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest(OVERLAY_SELECTOR))
}

/** Ширина карточки в CSS. Её и берём для решения «влезет справа или нет»:
 *  измеренный прямоугольник во время анимации уже уменьшен масштабом. */
const CARD_W = 380

type Place = {
  left: number
  top: number
  ready: boolean
  /** Откуда карточка вырастает: сторона, обращённая к совещанию. */
  origin: string
  shiftX: number
  shiftY: number
}

/**
 * Ставим карточку справа от блока, а если справа не помещается — слева.
 * По вертикали равняем по верху блока и не даём уехать за края окна.
 * origin и сдвиг задают вылет: карточка появляется из самого совещания.
 */
function place(anchor: DOMRect, width: number, height: number): Place {
  const view = {
    w: document.documentElement.clientWidth || window.innerWidth,
    h: window.innerHeight
  }
  const cardW = Math.max(width, CARD_W)
  // Справа от совещания, а если до края страницы не хватает — целиком слева от него.
  const fitsRight = anchor.right + GAP + cardW <= view.w - EDGE
  const rawLeft = fitsRight ? anchor.right + GAP : anchor.left - GAP - cardW
  const left = Math.max(EDGE, Math.min(rawLeft, view.w - cardW - EDGE))
  const top = Math.max(EDGE, Math.min(anchor.top, view.h - height - EDGE))
  const originX = fitsRight ? 'left' : 'right'
  const rel = height > 0 ? (anchor.top + anchor.height / 2 - top) / height : 0.5
  const originY = Math.round(Math.max(8, Math.min(92, rel * 100)))
  return {
    left,
    top,
    ready: true,
    origin: `${originX} ${originY}%`,
    shiftX: originX === 'left' ? -18 : originX === 'right' ? 18 : 0,
    shiftY: rel < 0.3 ? -14 : rel > 0.7 ? 14 : 0
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
  const [pos, setPos] = useState<Place>({
    left: 0,
    top: 0,
    ready: false,
    origin: 'left center',
    shiftX: -18,
    shiftY: 0
  })

  // Место считаем по реальному размеру карточки, поэтому первый кадр её прячем.
  useLayoutEffect(() => {
    const node = cardRef.current
    if (!node) return
    const measure = (): void => {
      // offsetWidth не сжимается анимацией scale, иначе карточка считает, что влезает справа.
      setPos(place(anchor, node.offsetWidth, node.offsetHeight))
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
      // Escape в открытой поверх форме закрывает только её.
      if (event.key === 'Escape' && !insideOverlay(event.target)) onClose()
    }
    const onDown = (event: MouseEvent): void => {
      const target = event.target as HTMLElement | null
      if (!target || cardRef.current?.contains(target)) return
      // Диалоги протокола открываются в портале рядом с карточкой, а не внутри неё:
      // закрыть карточку по клику в них — значит закрыть и сам диалог.
      if (insideOverlay(target)) return
      onClose()
    }
    // Карточка привязана к месту блока на экране, поэтому прокрутка сетки её закрывает.
    // Первый кадр пропускаем: открытие само может докрутить сетку до совещания.
    let armed = false
    const arm = window.setTimeout(() => {
      armed = true
    }, 0)
    const onScroll = (event: Event): void => {
      // Прокрутка внутри формы или списка ФИО — это не сдвиг сетки: карточку не трогаем.
      if (!armed || cardRef.current?.contains(event.target as Node) || insideOverlay(event.target)) return
      onClose()
    }
    window.addEventListener('keydown', onKey)
    // capture: иначе клик по другому совещанию сначала закроет карточку.
    window.addEventListener('mousedown', onDown, true)
    window.addEventListener('scroll', onScroll, true)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onDown, true)
      window.removeEventListener('scroll', onScroll, true)
      window.clearTimeout(arm)
    }
  }, [onClose])

  return createPortal(
    <div
      ref={cardRef}
      className={pos.ready ? 'meet-pop is-shown' : 'meet-pop'}
      role="dialog"
      aria-modal="false"
      style={{
        left: pos.left,
        top: pos.top,
        visibility: pos.ready ? 'visible' : 'hidden',
        ['--meet-pop-origin' as string]: pos.origin,
        ['--meet-pop-shift-x' as string]: `${pos.shiftX}px`,
        ['--meet-pop-shift-y' as string]: `${pos.shiftY}px`
      }}
    >
      <button type="button" className="meet-pop-close" aria-label="Закрыть" onClick={onClose}>
        <X size={16} aria-hidden />
      </button>
      <div className="meet-pop-body">{children}</div>
    </div>,
    document.body
  )
}
