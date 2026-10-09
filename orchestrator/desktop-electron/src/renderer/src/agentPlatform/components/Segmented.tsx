import { useLayoutEffect, useRef, useState } from 'react'

interface SegmentedProps<K extends string> {
  items: { key: K; label: string }[]
  value: K
  label: string
  className?: string
  onChange: (key: K) => void
}

export function Segmented<K extends string>({
  items,
  value,
  label,
  className,
  onChange
}: SegmentedProps<K>): React.JSX.Element {
  const listRef = useRef<HTMLDivElement>(null)
  const placed = useRef(false)
  const [motion, setMotion] = useState(false)
  const [indicator, setIndicator] = useState<{ x: number; y: number; width: number; height: number } | null>(
    null
  )

  useLayoutEffect(() => {
    const list = listRef.current
    if (!list) return
    const measure = (): void => {
      const active = list.querySelector<HTMLElement>('[aria-selected="true"]')
      if (!active) return
      setIndicator({
        x: active.offsetLeft,
        y: active.offsetTop,
        width: active.offsetWidth,
        height: active.offsetHeight
      })
    }
    measure()
    if (placed.current) setMotion(true)
    else placed.current = true
    const observer = new ResizeObserver(measure)
    observer.observe(list)
    return () => observer.disconnect()
  }, [value])

  return (
    <div
      ref={listRef}
      className={className ? `segmented sliding ${className}` : 'segmented sliding'}
      role="tablist"
      aria-label={label}
    >
      {indicator ? (
        <span
          className={motion ? 'segment-indicator motion' : 'segment-indicator'}
          style={{
            width: indicator.width,
            height: indicator.height,
            transform: `translate(${indicator.x}px, ${indicator.y}px)`
          }}
          aria-hidden="true"
        />
      ) : null}
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          role="tab"
          aria-selected={value === item.key}
          className={value === item.key ? 'segment active' : 'segment'}
          onClick={() => onChange(item.key)}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}
