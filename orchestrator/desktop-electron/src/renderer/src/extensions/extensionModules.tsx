import type { ReactNode } from 'react'
import type { UserProfile } from '../api/types'
import type { PageKey } from '../components/Sidebar'
import type { PassportTab } from '../pages/AgentPassportPage'
import { AssignmentsRegistryGridTab } from '../tabs/grid/AssignmentsRegistryGridTab'
import { AgentLibraryGridTab } from '../tabs/grid/AgentLibraryGridTab'
import type { ExtensionPositionFilter } from './extensionAudience'
import {
  canUseAgentLibrary,
  canUseAssignmentsRegistry,
  isChairmanBoardAssistant,
  isPromptEngineer
} from './extensionAccess'

/** Контекст вкладки расширения (общие колбэки приложения). */
export type ExtensionTabContext = {
  user: UserProfile
  onAskOrchestrator: (message: string, appContext: string) => void
  onNavigate: (pageKey: PageKey) => void
  onOpenPassport: (workflowId: string, title: string, tab?: PassportTab) => void
}

/**
 * Модуль расширения — добавьте объект в EXTENSION_MODULES, pageKey в Sidebar UserPageKey
 * и иконку в navIcons (или общую Puzzle).
 */
export type ExtensionModule = {
  id: string
  pageKey: PageKey
  navLabel: string
  title: string
  description: string
  subtitle: string
  /** В каких фильтрах по должности показывать карточку в каталоге «Расширения». */
  positionGroups: ExtensionPositionFilter[]
  canAccess: (user: UserProfile) => boolean
  renderTab: (ctx: ExtensionTabContext) => ReactNode
}

export const EXTENSION_MODULES: ExtensionModule[] = [
  {
    id: 'assignments_registry',
    pageKey: 'assignments_registry',
    navLabel: 'Реестр поручений',
    title: 'Реестр поручений',
    subtitle: 'Журнал поручений АСТ00: контроль сроков, статусов и проверка закрытия через ИИ',
    description:
      'Журнал поручений АСТ00: плитки, фильтр по датам, таблица с сортировкой и проверка незакрытых поручений через ИИ-агента.',
    positionGroups: ['director_assistants'],
    canAccess: canUseAssignmentsRegistry,
    renderTab: ({ user, onAskOrchestrator }) => (
      <AssignmentsRegistryGridTab user={user} onAskOrchestrator={onAskOrchestrator} />
    )
  },
  {
    id: 'agent_library',
    pageKey: 'agent_library',
    navLabel: 'Библиотека агентов',
    title: 'Библиотека агентов',
    subtitle: 'Опубликованные ИИ-агенты всех сотрудников: добавьте к себе и откройте паспорт',
    description:
      'Сбор агентов со всех пользователей, карточки agent_card, добавление копии в ваши процессы и открытие паспорта.',
    positionGroups: ['all', 'director_assistants'],
    canAccess: canUseAgentLibrary,
    renderTab: ({ user, onOpenPassport }) => (
      <AgentLibraryGridTab user={user} onOpenPassport={onOpenPassport} />
    )
  }
]

export const EXTENSION_MODULE_BY_ID: Record<string, ExtensionModule> = Object.fromEntries(
  EXTENSION_MODULES.map((item) => [item.id, item])
)

export const EXTENSION_MODULE_BY_PAGE: Record<string, ExtensionModule> = Object.fromEntries(
  EXTENSION_MODULES.map((item) => [item.pageKey, item])
)

export function registeredExtensionIds(): string[] {
  return EXTENSION_MODULES.map((item) => item.id)
}

export function extensionModuleForPage(pageKey: string): ExtensionModule | undefined {
  return EXTENSION_MODULE_BY_PAGE[pageKey]
}

export function listAccessibleExtensions(user: UserProfile): ExtensionModule[] {
  return EXTENSION_MODULES.filter((item) => item.canAccess(user))
}

export { isPromptEngineer, isChairmanBoardAssistant }
