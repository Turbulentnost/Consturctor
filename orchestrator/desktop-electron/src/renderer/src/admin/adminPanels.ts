import type { UserProfile } from '../api/types'
import type { PageKey } from '../components/Sidebar'

export type AdminPanelKey = 'default' | 'finance'

export interface AdminPanelDefinition {
  key: AdminPanelKey
  title: string
  defaultTab: PageKey
  pages: PageKey[]
}

export const ADMIN_PANELS: Record<AdminPanelKey, AdminPanelDefinition> = {
  default: {
    key: 'default',
    title: 'Администрирование',
    defaultTab: 'overview',
    pages: ['overview', 'history', 'launch_calendar', 'kpi', 'users', 'ai_agents', 'knowledge_base', 'settings']
  },
  finance: {
    key: 'finance',
    title: 'Финансы',
    defaultTab: 'finance_employees',
    pages: ['finance_employees', 'finance_upload', 'finance_import_history']
  }
}

export function resolveAdminPanel(user: UserProfile | null): AdminPanelDefinition | null {
  if (!user?.isAdmin || !user.adminPanel) return null
  const definition = ADMIN_PANELS[user.adminPanel as AdminPanelKey]
  if (!definition) return null
  const serverPages = new Set(user.adminPages)
  const pages = definition.pages.filter((page) => serverPages.has(page))
  if (!pages.length) return null
  return {
    ...definition,
    pages,
    defaultTab: pages.includes(definition.defaultTab) ? definition.defaultTab : pages[0]
  }
}
