import { useEffect, type ReactNode } from 'react'
import { PAGE_SEARCH_PLACEHOLDER, usePageSearch } from './pageSearchContext'
import { Sidebar, type PageKey, type SidebarNavItem } from '../components/Sidebar'
import { PAGE_LABELS } from '../components/Sidebar'
import type { ChatThread } from '../api/types'
import { UserMenu } from '../components/UserMenu'
import type { UserProfile } from '../api/types'
import { NavIcon } from './navIcons'
import { TAB_REGISTRY, type WorkplaceTabKey } from './tabRegistry'
import { userGivenName } from '../workplace/userContext'
import type { GlobalSearchTarget } from './globalSearch'

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
  onOpenSettings: () => void
  searchTarget?: GlobalSearchTarget | null
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
  onOpenSettings,
  searchTarget = null,
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
  const pageSearch = usePageSearch()
  const searchPlaceholder =
    PAGE_SEARCH_PLACEHOLDER[activeKey] || 'Поиск на открытой странице…'

  useEffect(() => {
    if (!searchTarget || searchTarget.pageKey !== activeKey) return
    const selector = `[data-search-id="${CSS.escape(searchTarget.targetId)}"]`
    if (searchTarget.sectionId) {
      document
        .querySelector<HTMLElement>(`[data-search-id="${CSS.escape(searchTarget.sectionId)}"]`)
        ?.click()
    }
    let timeout = 0
    let highlightTimeout = 0
    let firstFrame = 0
    let secondFrame = 0
    let observer: MutationObserver | null = null
    const focusTarget = (): boolean => {
      const node = document.querySelector<HTMLElement>(selector)
      if (!node) return false
      node.click()
      observer?.disconnect()
      firstFrame = window.requestAnimationFrame(() => {
        secondFrame = window.requestAnimationFrame(() => {
          const renderedNode = document.querySelector<HTMLElement>(selector)
          if (!renderedNode) return
          renderedNode.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' })
          renderedNode.classList.add('global-search-highlight')
          highlightTimeout = window.setTimeout(
            () => renderedNode.classList.remove('global-search-highlight'),
            1000
          )
        })
      })
      return true
    }
    if (!focusTarget()) {
      observer = new MutationObserver(() => focusTarget())
      observer.observe(document.body, { childList: true, subtree: true })
      timeout = window.setTimeout(() => observer?.disconnect(), 5000)
    }
    return () => {
      observer?.disconnect()
      if (timeout) window.clearTimeout(timeout)
      if (highlightTimeout) window.clearTimeout(highlightTimeout)
      if (firstFrame) window.cancelAnimationFrame(firstFrame)
      if (secondFrame) window.cancelAnimationFrame(secondFrame)
    }
  }, [activeKey, searchTarget])

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
          refreshAt={chatRefreshAt}
          pinnedExtensionNav={pinnedExtensionNav}
        />
      </div>

      <div className={`orch-grid${gridMods ? ` ${gridMods}` : ''}`}>
      {subpage ? null : (
        <>
          <header
            className={`orch-grid-title${isToday ? ' orch-grid-title-today' : ''}`}
            data-search-id={`page:${activeKey}`}
          >
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

          {activeKey === 'kpi' ? null : (
            <div className="orch-grid-search" role="search">
              <div className="global-search">
                <span className="global-search-icon" aria-hidden />
                <input
                  type="search"
                  value={pageSearch.query}
                  placeholder={searchPlaceholder}
                  aria-label="Поиск на странице"
                  onChange={(event) => pageSearch.setQuery(event.target.value)}
                />
              </div>
            </div>
          )}
        </>
      )}

      <div className="orch-grid-util">
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
