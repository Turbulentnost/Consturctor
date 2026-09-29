import type { UserProfile } from '../api/types'
import type { PageKey, SidebarNavItem } from '../components/Sidebar'
import {
  EXTENSION_MODULE_BY_ID,
  EXTENSION_MODULES,
  registeredExtensionIds,
  type ExtensionModule
} from './extensionModules'

export type ExtensionId = string

export type ExtensionDefinition = Pick<
  ExtensionModule,
  'id' | 'navLabel' | 'title' | 'description' | 'pageKey' | 'positionGroups'
>

export const EXTENSIONS: ExtensionDefinition[] = EXTENSION_MODULES.map((item) => ({
  id: item.id,
  navLabel: item.navLabel,
  title: item.title,
  description: item.description,
  pageKey: item.pageKey,
  positionGroups: item.positionGroups
}))

export const EXTENSION_BY_ID = EXTENSION_MODULE_BY_ID

export function canUseExtension(user: UserProfile, id: ExtensionId): boolean {
  const mod = EXTENSION_MODULE_BY_ID[id]
  return mod ? mod.canAccess(user) : false
}

export function extensionPageKey(id: ExtensionId): PageKey {
  return EXTENSION_MODULE_BY_ID[id]?.pageKey || 'extensions'
}

export function buildPinnedExtensionNav(user: UserProfile, pinned: ExtensionId[]): SidebarNavItem[] {
  return pinned
    .map((id) => EXTENSION_MODULE_BY_ID[id])
    .filter((item): item is ExtensionModule => Boolean(item))
    .filter((item) => item.canAccess(user))
    .map((item) => ({ key: item.pageKey, label: item.navLabel, extension: true as const }))
}

export { registeredExtensionIds }
