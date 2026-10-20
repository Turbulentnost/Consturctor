import { useEffect, useState } from 'react'

type UpdateState = 'idle' | 'available' | 'downloading' | 'installing' | 'error'

interface UpdateStatus {
  state: UpdateState
  currentVersion: string
  availableVersion: string
  percent: number
  error: string
  source: string
  devMode: boolean
}

const IDLE_UPDATE: UpdateStatus = {
  state: 'idle',
  currentVersion: '',
  availableVersion: '',
  percent: 0,
  error: '',
  source: '',
  devMode: false
}

export function AppUpdatePanel({ collapsed = false }: { collapsed?: boolean }): React.JSX.Element {
  const [update, setUpdate] = useState<UpdateStatus>(IDLE_UPDATE)
  const [checking, setChecking] = useState(false)

  const runCheck = (): void => {
    if (checking) return
    setChecking(true)
    void window.api
      .checkUpdate?.()
      .then((payload) => {
        if (payload) setUpdate(payload)
      })
      .finally(() => setChecking(false))
  }

  useEffect(() => {
    let alive = true
    void window.api.getUpdateStatus?.().then((payload) => {
      if (alive && payload) setUpdate(payload)
    })
    const unsubscribe = window.api.onUpdateStatus?.((payload) => {
      setUpdate(payload)
    })
    return () => {
      alive = false
      unsubscribe?.()
    }
  }, [])

  return (
    <div className="sidebar-update">
      {!collapsed ? (
        <p className="sidebar-update-meta">
          {update.currentVersion ? `v${update.currentVersion}` : 'Версия —'}
          {update.availableVersion && update.availableVersion !== update.currentVersion
            ? ` → ${update.availableVersion}`
            : ''}
        </p>
      ) : null}
      {update.error && !collapsed ? <p className="sidebar-update-error">{update.error}</p> : null}
      {update.state === 'downloading' || update.state === 'installing' ? (
        <div
          className={update.percent > 0 ? 'sidebar-update-progress' : 'sidebar-update-progress indeterminate'}
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={update.percent}
        >
          <i className="sidebar-update-progress-bar" style={update.percent > 0 ? { width: `${update.percent}%` } : undefined} />
          {!collapsed && (
            <span className="sidebar-update-progress-label">
              {update.state === 'installing' ? 'Установка...' : update.percent > 0 ? `${update.percent}%` : 'Загрузка...'}
            </span>
          )}
        </div>
      ) : update.state === 'available' && !update.devMode ? (
        <button
          type="button"
          className="sidebar-update-btn"
          title={update.error || 'Установить обновление Конструктора и Оркестратора'}
          onClick={() => void window.api.installUpdate?.()}
        >
          {!collapsed && <span>Обновить обе программы</span>}
          {collapsed && <span className="sidebar-update-mark">!</span>}
        </button>
      ) : null}
      <button
        type="button"
        className="sidebar-update-check"
        disabled={checking || update.state === 'downloading' || update.state === 'installing'}
        title="Проверить обновление приложения (не перезагрузка данных сеток)"
        onClick={runCheck}
      >
        {collapsed ? '↻' : checking ? 'Проверяем…' : 'Проверить обновление'}
      </button>
    </div>
  )
}
