import type { ReactNode } from 'react'
import { Sidebar, type PageKey, type SidebarNavItem } from '../components/Sidebar'
import { PAGE_LABELS } from '../components/Sidebar'
import type { ChatThread, DirectoryUser } from '../api/types'
import { UserMenu } from '../components/UserMenu'
import type { UserProfile } from '../api/types'
import { NavIcon } from './navIcons'
import { TAB_REGISTRY, type WorkplaceTabKey } from './tabRegistry'
import { userGivenName } from '../workplace/userContext'

function todayGreeting(fio: string): string {
  const hour = new Date().getHours()
  const lead = hour < 12 ? 'Доброе утро' : hour < 18 ? 'Добрый день' : 'Добрый вечер'
  return `${lead}, ${userGivenName(fio)}!`
}

interface OrchGridShellProps {
  activeKey: WorkplaceTabKey
  user: UserProfile
  avatarUrl: string | null
  unread: number
  onUnreadChange: (count: number) => void
  onLogout: () => void
  showLogout: boolean
  lightSidebar?: boolean
  activeThreadId?: string
  chatRefreshAt?: number
  onNavigate: (key: PageKey) => void
  onOpenThread: (thread: ChatThread) => void
  onOpenFio: (fio: string, user?: DirectoryUser) => void
  onOpenSettings: () => void
  onOpenAgent?: (workflowId: string, runId: string, title?: string, body?: string) => void
  onStopRun?: (workflowId: string, runId?: string) => void
  isRunLive?: (workflowId: string, runId?: string) => boolean
  canSwitchAdminView?: boolean
  onSwitchAdminView?: (mode: 'admin' | 'user') => void
  toast?: ReactNode
  gridClassName?: string
  /** Hide workplace title/search — used for agent run/history overlays. */
  subpage?: boolean
  pinnedExtensionNav?: SidebarNavItem[]
  children: ReactNode
}

export function OrchGridShell({
  activeKey,
  user,
  avatarUrl,
  unread,
  onUnreadChange,
  onLogout,
  showLogout,
  lightSidebar = false,
  activeThreadId = '',
  chatRefreshAt = 0,
  onNavigate,
  onOpenThread,
  onOpenFio,
  onOpenSettings,
  onOpenAgent,
  onStopRun,
  isRunLive,
  canSwitchAdminView = false,
  onSwitchAdminView,
  toast,
  gridClassName = '',
  subpage = false,
  pinnedExtensionNav = [],
  children
}: OrchGridShellProps): React.JSX.Element {
  const meta = TAB_REGISTRY[activeKey]
  const title = meta?.title || PAGE_LABELS[activeKey]
  const isToday = activeKey === 'today'
  const displayTitle = isToday ? todayGreeting(user.fio || '') : title
  const displaySub = isToday ? meta?.subtitle || '' : meta?.subtitle || ''
  const gridMods = [gridClassName, subpage ? 'orch-grid-subpage' : ''].filter(Boolean).join(' ')

  return (
    <div className="orch-grid-frame">
      <div className="orch-grid-nav">
        <Sidebar
          active={activeKey}
          light={lightSidebar || activeKey === 'today'}
          activeThreadId={activeThreadId}
          currentUserId={user.id || ''}
          onNavigate={onNavigate}
          onOpenThread={onOpenThread}
          onOpenFio={onOpenFio}
          refreshAt={chatRefreshAt}
          pinnedExtensionNav={pinnedExtensionNav}
        />
      </div>

      <div className={`orch-grid${gridMods ? ` ${gridMods}` : ''}`}>
      {subpage ? null : (
        <>
          <header className={`orch-grid-title${isToday ? ' orch-grid-title-today' : ''}`}>
            <span className="orch-grid-title-icon" aria-hidden>
              {meta?.titleLogoSrc ? (
                <img className="orch-grid-title-logo" src={meta.titleLogoSrc} alt="" />
              ) : (
                <NavIcon page={activeKey} />
              )}
            </span>
            <div>
              <h1 className="page-title">{displayTitle}</h1>
              {displaySub ? <p className="orch-grid-sub">{displaySub}</p> : null}
            </div>
          </header>

          <div className="orch-grid-header-actions">{meta?.headerActions}</div>

          <div className="orch-grid-search" role="search">
            <div className="global-search">
              <span className="global-search-icon" aria-hidden />
              <input placeholder="Поиск по процессам, документам, задачам, проектам…" aria-label="Поиск" />
            </div>
          </div>
        </>
      )}

      <div className="orch-grid-util">
        <button
          type="button"
          className="icon-btn-help"
          title="Помощь"
          onClick={() => {
            window.open('https://wiki.turbo-don.ru', '_blank', 'noopener,noreferrer')
          }}
        >
          ?
        </button>
        <UserMenu
          user={user}
          avatarUrl={avatarUrl}
          unread={unread}
          onUnreadChange={onUnreadChange}
          onLogout={onLogout}
          showLogout={showLogout}
          onOpenAgent={onOpenAgent}
          onStopRun={onStopRun}
          isRunLive={isRunLive}
          onOpenSettings={onOpenSettings}
          canSwitchAdminView={canSwitchAdminView}
          onSwitchAdminView={onSwitchAdminView}
        />
      </div>

      {toast ? <div className="orch-grid-toast">{toast}</div> : null}

      {children}
      </div>
    </div>
  )
}
