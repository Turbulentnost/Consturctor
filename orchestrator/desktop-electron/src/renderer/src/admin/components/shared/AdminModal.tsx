import { useEffect } from 'react'

interface AdminModalProps {
  title: string
  open: boolean
  onClose: () => void
  children: React.ReactNode
  footer?: React.ReactNode
  className?: string
}

export function AdminModal({
  title,
  open,
  onClose,
  children,
  footer,
  className
}: AdminModalProps): React.JSX.Element | null {
  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="admin-modal-backdrop" onClick={onClose}>
      <div className={className ? `admin-modal ${className}` : 'admin-modal'} role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        <div className="admin-modal__head">
          <h3>{title}</h3>
          <button type="button" className="admin-modal__close" aria-label="Закрыть" onClick={onClose}>×</button>
        </div>
        <div className="admin-modal__body">{children}</div>
        {footer ? <div className="admin-modal__footer">{footer}</div> : null}
      </div>
    </div>
  )
}
