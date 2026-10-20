import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { apiGet } from '../../agentPlatform/api/client'
import type { PlatformConfig } from '../../agentPlatform/api/types'
import { AgentSession } from '../../agentPlatform/pages/AgentSession'
import '../../agentPlatform/styles/index.css'
import './platformRunDialog.css'

/** Ход работы запуска платформы агентов поверх карточки: вопросы, разрешения, шаги и ответ агента. */
export function PlatformRunDialog({
  sessionId,
  onClose
}: {
  sessionId: string
  onClose: () => void
}): React.JSX.Element {
  const [configs, setConfigs] = useState<PlatformConfig[]>([])
  const [showProgress, setShowProgress] = useState(false)

  useEffect(() => {
    let alive = true
    void apiGet<{ items: PlatformConfig[] }>('/api/v1/platform/configs')
      .then((data) => {
        if (alive) setConfigs(data.items)
      })
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return createPortal(
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal-card platform-run-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Ход работы агента"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="tt-root" data-theme="light">
          <AgentSession
            target={{ kind: 'session', sessionId }}
            configs={configs}
            backLabel="Закрыть"
            showProgress={showProgress}
            onShowProgress={setShowProgress}
            onBack={onClose}
            onOpened={() => undefined}
          />
        </div>
      </div>
    </div>,
    document.body
  )
}
