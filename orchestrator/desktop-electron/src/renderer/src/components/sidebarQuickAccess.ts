export const QUICK_ACCESS_STORAGE_KEY = 'orch-sidebar-quick-v1'
export const SIDEBAR_COLLAPSED_STORAGE_KEY = 'orch-sidebar-collapsed-v1'
export const DEFAULT_QUICK_ACCESS = ['today', 'docflow', 'extensions', 'settings']

function userSlot(userId: string): string {
  return userId.trim() || 'default'
}

export function quickAccessStorageKey(userId: string): string {
  return `${QUICK_ACCESS_STORAGE_KEY}:${userSlot(userId)}`
}

export function sidebarCollapsedStorageKey(userId: string): string {
  return `${SIDEBAR_COLLAPSED_STORAGE_KEY}:${userSlot(userId)}`
}

/** Порядок на панели всегда как в общем меню — закреплённые вкладки не «прыгают». */
export function normalizeQuickAccess(raw: unknown, availableKeys: string[]): string[] {
  const source = Array.isArray(raw) ? raw : DEFAULT_QUICK_ACCESS
  const picked = new Set(source.filter((key): key is string => typeof key === 'string'))
  return [...new Set(availableKeys)].filter((key) => picked.has(key))
}

/** Меняет сохранённый выбор, не трогая вкладки, которые сейчас недоступны (выключенное расширение вернётся само). */
export function toggleQuickAccess(stored: string[], key: string): string[] {
  return stored.includes(key) ? stored.filter((item) => item !== key) : [...stored, key]
}

export function loadQuickAccess(userId: string): string[] {
  const fallback = [...DEFAULT_QUICK_ACCESS]
  if (typeof window === 'undefined') return fallback
  try {
    const raw = window.localStorage.getItem(quickAccessStorageKey(userId))
    const parsed = raw ? (JSON.parse(raw) as unknown) : null
    if (!Array.isArray(parsed)) return fallback
    return [...new Set(parsed.filter((key): key is string => typeof key === 'string'))]
  } catch {
    return fallback
  }
}

export function saveQuickAccess(userId: string, keys: string[]): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(quickAccessStorageKey(userId), JSON.stringify(keys))
  } catch {
    /* Ignore unavailable or full renderer storage. */
  }
}

export function loadSidebarCollapsed(userId: string, fallback: boolean): boolean {
  if (typeof window === 'undefined') return fallback
  try {
    const raw = window.localStorage.getItem(sidebarCollapsedStorageKey(userId))
    return raw === null ? fallback : raw === '1'
  } catch {
    return fallback
  }
}

export function saveSidebarCollapsed(userId: string, collapsed: boolean): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(sidebarCollapsedStorageKey(userId), collapsed ? '1' : '0')
  } catch {
    /* Ignore unavailable or full renderer storage. */
  }
}
