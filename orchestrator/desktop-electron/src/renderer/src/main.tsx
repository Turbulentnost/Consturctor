import './browserApi'
import { Component, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { RunProvider } from './store/runs'
import './styles.css'
import './admin/admin-pages.css'
import './admin/admin-overview.css'
import './admin/admin-themes.css'
import './layout/orchGrid.css'
import './tabs/grid/todayGrid.css'
import { initAdminTheme } from './admin/theme/adminThemes'

const RUNS_RELOAD_KEY = 'orch-runs-provider-reload'

class RunsHotReloadBoundary extends Component<{ children: React.ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError(error: Error): { failed: boolean } {
    return { failed: String(error?.message || '').includes('useRuns must be used within a RunProvider') }
  }

  componentDidMount(): void {
    sessionStorage.removeItem(RUNS_RELOAD_KEY)
  }

  componentDidCatch(error: Error): void {
    if (!String(error?.message || '').includes('useRuns must be used within a RunProvider')) return
    if (sessionStorage.getItem(RUNS_RELOAD_KEY) === '1') return
    sessionStorage.setItem(RUNS_RELOAD_KEY, '1')
    window.location.reload()
  }

  render(): React.ReactNode {
    if (this.state.failed) return null
    return this.props.children
  }
}

initAdminTheme()

function preventWindowFileOpen(event: DragEvent): void {
  event.preventDefault()
}

window.addEventListener('dragover', preventWindowFileOpen)
window.addEventListener('drop', preventWindowFileOpen)

window.addEventListener('error', (event) => {
  const message = String(event.error?.message || event.message || '')
  const hmrFatal =
    message.includes('useRuns must be used within a RunProvider') ||
    message.includes('before initialization')
  if (!hmrFatal) return
  if (sessionStorage.getItem(RUNS_RELOAD_KEY) === '1') return
  sessionStorage.setItem(RUNS_RELOAD_KEY, '1')
  window.location.reload()
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RunsHotReloadBoundary>
      <RunProvider>
        <App />
      </RunProvider>
    </RunsHotReloadBoundary>
  </StrictMode>
)
