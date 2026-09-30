export const SIDEBAR_LAYOUT_STORAGE_KEY = 'orch-sidebar-layout-v1'

export type SidebarScope = 'user' | `admin:${string}`

export type SidebarFolder = {
  id: string
  name: string
  expanded: boolean
  tabKeys: string[]
}

export type SidebarLayout = {
  version: 1
  root: string[]
  folders: SidebarFolder[]
}

const TAB_PREFIX = 'tab:'
const FOLDER_PREFIX = 'folder:'

export function tabNodeId(key: string): string {
  return `${TAB_PREFIX}${key}`
}

export function folderNodeId(id: string): string {
  return `${FOLDER_PREFIX}${id}`
}

export function tabKeyFromNode(nodeId: string): string | null {
  return nodeId.startsWith(TAB_PREFIX) ? nodeId.slice(TAB_PREFIX.length) : null
}

export function folderIdFromNode(nodeId: string): string | null {
  return nodeId.startsWith(FOLDER_PREFIX) ? nodeId.slice(FOLDER_PREFIX.length) : null
}

export function sidebarLayoutStorageKey(userId: string, scope: SidebarScope): string {
  return `${SIDEBAR_LAYOUT_STORAGE_KEY}:${userId.trim() || 'default'}:${scope}`
}

export function defaultSidebarLayout(availableKeys: string[]): SidebarLayout {
  return {
    version: 1,
    root: [...new Set(availableKeys)].map(tabNodeId),
    folders: []
  }
}

export function normalizeSidebarLayout(raw: unknown, availableKeys: string[]): SidebarLayout {
  const available = [...new Set(availableKeys)]
  const allowed = new Set(available)
  if (!raw || typeof raw !== 'object') return defaultSidebarLayout(available)

  const record = raw as Record<string, unknown>
  const rawFolders = Array.isArray(record.folders) ? record.folders : []
  const folders: SidebarFolder[] = []
  const folderIds = new Set<string>()
  const assignedTabs = new Set<string>()

  for (const value of rawFolders) {
    if (!value || typeof value !== 'object') continue
    const folder = value as Record<string, unknown>
    const id = String(folder.id || '').trim()
    const name = String(folder.name || '').trim()
    if (!id || !name || folderIds.has(id)) continue
    folderIds.add(id)
    const tabKeys: string[] = []
    if (Array.isArray(folder.tabKeys)) {
      for (const keyValue of folder.tabKeys) {
        const key = typeof keyValue === 'string' ? keyValue : ''
        if (!allowed.has(key) || assignedTabs.has(key)) continue
        assignedTabs.add(key)
        tabKeys.push(key)
      }
    }
    folders.push({ id, name, expanded: folder.expanded !== false, tabKeys })
  }

  const root: string[] = []
  const seenNodes = new Set<string>()
  const rawRoot = Array.isArray(record.root) ? record.root : []
  for (const value of rawRoot) {
    if (typeof value !== 'string' || seenNodes.has(value)) continue
    const tabKey = tabKeyFromNode(value)
    if (tabKey !== null) {
      if (!allowed.has(tabKey) || assignedTabs.has(tabKey)) continue
      assignedTabs.add(tabKey)
      seenNodes.add(value)
      root.push(value)
      continue
    }
    const folderId = folderIdFromNode(value)
    if (folderId !== null && folderIds.has(folderId)) {
      seenNodes.add(value)
      root.push(value)
    }
  }

  for (const folder of folders) {
    const nodeId = folderNodeId(folder.id)
    if (!seenNodes.has(nodeId)) {
      seenNodes.add(nodeId)
      root.push(nodeId)
    }
  }
  for (const key of available) {
    if (!assignedTabs.has(key)) root.push(tabNodeId(key))
  }

  return { version: 1, root, folders }
}

export function loadSidebarLayout(
  userId: string,
  scope: SidebarScope,
  availableKeys: string[]
): SidebarLayout {
  if (typeof window === 'undefined') return defaultSidebarLayout(availableKeys)
  try {
    const raw = window.localStorage.getItem(sidebarLayoutStorageKey(userId, scope))
    return raw ? normalizeSidebarLayout(JSON.parse(raw) as unknown, availableKeys) : defaultSidebarLayout(availableKeys)
  } catch {
    return defaultSidebarLayout(availableKeys)
  }
}

export function saveSidebarLayout(userId: string, scope: SidebarScope, layout: SidebarLayout): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(sidebarLayoutStorageKey(userId, scope), JSON.stringify(layout))
  } catch {
    /* Ignore unavailable or full renderer storage. */
  }
}

export function createSidebarFolderId(): string {
  return `nav_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`
}

export function addSidebarFolder(layout: SidebarLayout, name: string, id = createSidebarFolderId()): SidebarLayout {
  const cleanName = name.trim()
  if (!cleanName || layout.folders.some((folder) => folder.id === id)) return layout
  return {
    ...layout,
    root: [...layout.root, folderNodeId(id)],
    folders: [...layout.folders, { id, name: cleanName, expanded: true, tabKeys: [] }]
  }
}

export function renameSidebarFolder(layout: SidebarLayout, id: string, name: string): SidebarLayout {
  const cleanName = name.trim()
  if (!cleanName) return layout
  return {
    ...layout,
    folders: layout.folders.map((folder) => (folder.id === id ? { ...folder, name: cleanName } : folder))
  }
}

export function toggleSidebarFolder(layout: SidebarLayout, id: string): SidebarLayout {
  return {
    ...layout,
    folders: layout.folders.map((folder) =>
      folder.id === id ? { ...folder, expanded: !folder.expanded } : folder
    )
  }
}

export function moveSidebarTab(layout: SidebarLayout, tabKey: string, targetFolderId: string | null): SidebarLayout {
  const tabNode = tabNodeId(tabKey)
  const targetExists = targetFolderId === null || layout.folders.some((folder) => folder.id === targetFolderId)
  if (!targetExists) return layout
  const root = layout.root.filter((nodeId) => nodeId !== tabNode)
  const folders = layout.folders.map((folder) => ({
    ...folder,
    tabKeys: folder.tabKeys.filter((key) => key !== tabKey)
  }))
  if (targetFolderId === null) {
    root.push(tabNode)
  } else {
    const target = folders.find((folder) => folder.id === targetFolderId)
    if (target) target.tabKeys.push(tabKey)
  }
  return { ...layout, root, folders }
}

export type SidebarDropTarget = {
  /** `null` — корневой список; иначе id папки (папки внутрь папок не кладутся). */
  folderId: string | null
  /** Узел, относительно которого вставляем; `null` — в конец списка. */
  anchor: string | null
  position: 'before' | 'after'
}

export function moveSidebarNode(layout: SidebarLayout, nodeId: string, target: SidebarDropTarget): SidebarLayout {
  const tabKey = tabKeyFromNode(nodeId)
  const folderId = folderIdFromNode(nodeId)
  if (tabKey === null && folderId === null) return layout
  if (target.anchor === nodeId) return layout
  if (folderId !== null) {
    if (target.folderId !== null || !layout.folders.some((folder) => folder.id === folderId)) return layout
  } else {
    const known =
      layout.root.includes(nodeId) || layout.folders.some((folder) => folder.tabKeys.includes(tabKey as string))
    if (!known) return layout
  }
  if (target.folderId !== null && !layout.folders.some((folder) => folder.id === target.folderId)) return layout

  const insert = (list: string[]): string[] => {
    const next = list.filter((item) => item !== nodeId)
    const anchorIdx = target.anchor === null ? -1 : next.indexOf(target.anchor)
    if (anchorIdx < 0) next.push(nodeId)
    else next.splice(target.position === 'before' ? anchorIdx : anchorIdx + 1, 0, nodeId)
    return next
  }

  const root = layout.root.filter((item) => item !== nodeId)
  const folders = layout.folders.map((folder) => ({
    ...folder,
    tabKeys: tabKey === null ? folder.tabKeys : folder.tabKeys.filter((key) => key !== tabKey)
  }))
  if (target.folderId === null) {
    return { ...layout, root: insert(root), folders }
  }
  return {
    ...layout,
    root,
    folders: folders.map((folder) =>
      folder.id === target.folderId
        ? {
            ...folder,
            expanded: true,
            tabKeys: insert(folder.tabKeys.map(tabNodeId)).map((node) => tabKeyFromNode(node) as string)
          }
        : folder
    )
  }
}

export function deleteSidebarFolder(layout: SidebarLayout, id: string): SidebarLayout {
  const folder = layout.folders.find((item) => item.id === id)
  if (!folder) return layout
  const nodeId = folderNodeId(id)
  const root: string[] = []
  for (const node of layout.root) {
    if (node === nodeId) root.push(...folder.tabKeys.map(tabNodeId))
    else root.push(node)
  }
  return {
    ...layout,
    root,
    folders: layout.folders.filter((item) => item.id !== id)
  }
}
