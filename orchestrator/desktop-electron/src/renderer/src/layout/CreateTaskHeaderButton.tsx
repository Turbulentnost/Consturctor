import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  CREATE_TASK_CHANNEL_LABEL,
  requestCreateTask,
  type CreateTaskChannel
} from '../workplace/workplaceNav'

const CHANNELS: CreateTaskChannel[] = ['onec', 'turbo', 'draft']

export function CreateTaskHeaderButton(): React.JSX.Element {
  const buttonRef = useRef<HTMLButtonElement | null>(null)
  const popRef = useRef<HTMLDivElement | null>(null)
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState({ top: 0, left: 0 })

  const place = (): void => {
    const box = buttonRef.current?.getBoundingClientRect()
    if (!box) return
    const width = 220
    setPos({
      top: box.bottom + 6,
      left: Math.min(Math.max(8, box.right - width), window.innerWidth - width - 8)
    })
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
    if (!open) return
    const onDoc = (event: MouseEvent): void => {
      const target = event.target as Node | null
      if (!target) return
      if (buttonRef.current?.contains(target) || popRef.current?.contains(target)) return
      setOpen(false)
    }
    const timer = window.setTimeout(() => document.addEventListener('mousedown', onDoc), 0)
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('mousedown', onDoc)
    }
  }, [open])

  const pick = (channel: CreateTaskChannel): void => {
    setOpen(false)
    requestCreateTask(channel)
  }

  return (
    <div className="orch-header-menu">
      <button
        ref={buttonRef}
        type="button"
        className="spec-btn-launch"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span>+ Создать задачу</span>
        <span className="spec-btn-launch-caret" aria-hidden>
          ▾
        </span>
      </button>
      {open
        ? createPortal(
            <div
              ref={popRef}
              className="orch-header-menu-pop"
              role="menu"
              style={{ top: pos.top, left: pos.left }}
            >
              {CHANNELS.map((channel) => (
                <button key={channel} type="button" role="menuitem" onClick={() => pick(channel)}>
                  {CREATE_TASK_CHANNEL_LABEL[channel]}
                </button>
              ))}
            </div>,
            document.body
          )
        : null}
    </div>
  )
}
