import { createContext, useContext, useMemo, type ReactNode } from 'react'
import type { UserProfile } from '../api/types'
import type { PageKey, SidebarNavItem } from '../components/Sidebar'
import { buildPinnedExtensionNav } from './extensionRegistry'
import { listAccessibleExtensions, type ExtensionModule } from './extensionModules'
import { useUserExtensions } from './useUserExtensions'

type ExtensionsContextValue = {
  modules: ExtensionModule[]
  pinned: string[]
  pinnedNav: SidebarNavItem[]
  isPinned: (id: string) => boolean
  togglePin: (id: string) => void
  pin: (id: string) => void
  unpin: (id: string) => void
}

const ExtensionsContext = createContext<ExtensionsContextValue | null>(null)

export function ExtensionsProvider({
  user,
  children
}: {
  user: UserProfile
  children: ReactNode
}): React.JSX.Element {
  const userId = user.id || ''
  const { pinned, isPinned, pin, unpin, togglePin } = useUserExtensions(userId)
  const modules = useMemo(() => listAccessibleExtensions(user), [user])
  const pinnedNav = useMemo(() => buildPinnedExtensionNav(user, pinned), [user, pinned])

  const value = useMemo(
    (): ExtensionsContextValue => ({
      modules,
      pinned,
      pinnedNav,
      isPinned,
      pin,
      unpin,
      togglePin
    }),
    [modules, pinned, pinnedNav, isPinned, pin, unpin, togglePin]
  )

  return <ExtensionsContext.Provider value={value}>{children}</ExtensionsContext.Provider>
}

export function useExtensions(): ExtensionsContextValue {
  const ctx = useContext(ExtensionsContext)
  if (!ctx) {
    throw new Error('useExtensions requires ExtensionsProvider')
  }
  return ctx
}

export function useExtensionsOptional(): ExtensionsContextValue | null {
  return useContext(ExtensionsContext)
}

export function navigateToExtensionPage(onNavigate: (key: PageKey) => void, pageKey: PageKey): void {
  onNavigate(pageKey)
}
