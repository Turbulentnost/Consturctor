import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'

export const DOCFLOW_REFRESH_EVENT = 'orch-docflow-refresh'
export const DOCFLOW_BUSY_EVENT = 'orch-docflow-busy'

export function requestDocflowRefresh(): void {
  window.dispatchEvent(new Event(DOCFLOW_REFRESH_EVENT))
}

export function publishDocflowBusy(busy: boolean): void {
  window.dispatchEvent(new CustomEvent(DOCFLOW_BUSY_EVENT, { detail: { busy } }))
}

/** Кнопка шапки «Документооборот»: заново читает открытый журнал из 1С. */
export function DocflowRefreshButton(): React.JSX.Element {
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const onBusy = (event: Event): void => {
      setBusy(Boolean((event as CustomEvent<{ busy?: boolean }>).detail?.busy))
    }
    window.addEventListener(DOCFLOW_BUSY_EVENT, onBusy)
    return () => window.removeEventListener(DOCFLOW_BUSY_EVENT, onBusy)
  }, [])

  return (
    <button
      type="button"
      className="spec-btn-outline spec-header-action-compact docflow-refresh-btn"
      title="Обновить данные из 1С"
      disabled={busy}
      onClick={() => {
        setBusy(true)
        requestDocflowRefresh()
      }}
    >
      <RefreshCw size={14} className={busy ? 'is-spinning' : ''} aria-hidden />
      Обновить
    </button>
  )
}
