import { useEffect, useRef, useState } from 'react'
import { ChevronDownIcon } from '../components/Icons'

interface ProgressBarProps {
  running: boolean
  text: string
  /** Агент стоит на вопросе или разрешении — без анимации «работает». */
  waiting: boolean
  shown: boolean
  always: boolean
  onOnce: (show: boolean) => void
  onAlways: (show: boolean) => void
}

// Строка под конфигурацией: пока агент работает — анимированный статус, по клику — выбор,
// показывать ли ход работы один раз (в этом окне) или всегда (общая настройка).
export function ProgressBar({ running, text, waiting, shown, always, onOnce, onAlways }: ProgressBarProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent): void => {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onDown)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  const pick = (apply: () => void): void => {
    apply()
    setOpen(false)
  }

  const label = running ? text : shown ? 'Ход работы показан' : 'Ход работы скрыт'
  const live = running && !waiting

  return (
    <div className="sess-progress" ref={boxRef}>
      <button
        type="button"
        className={['sess-progress-toggle', running ? 'running' : '', live ? 'live' : ''].join(' ')}
        aria-haspopup="menu"
        aria-expanded={open}
        title="Показать или скрыть ход работы агента"
        onClick={() => setOpen((value) => !value)}
      >
        {running ? <span className={live ? 'sess-spinner' : 'sess-dot'} /> : null}
        <span className={live ? 'sess-shimmer' : ''}>{label}</span>
        <ChevronDownIcon size={12} />
      </button>
      {open ? (
        <div className="picker-menu agent-menu sess-progress-menu" role="menu">
          <span className="picker-label">Ход работы агента</span>
          <button type="button" role="menuitem" className="picker-option" onClick={() => pick(() => onOnce(!shown))}>
            {shown ? 'Скрыть' : 'Показать'} один раз
            <small>только в этом окне</small>
          </button>
          <button type="button" role="menuitem" className="picker-option" onClick={() => pick(() => onAlways(!always))}>
            {always ? 'Скрывать всегда' : 'Показывать всегда'}
            <small>меняет общую настройку</small>
          </button>
        </div>
      ) : null}
    </div>
  )
}
