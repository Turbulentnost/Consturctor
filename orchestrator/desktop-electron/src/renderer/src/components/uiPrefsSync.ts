import { api } from '../api/client'
import { ApiError } from '../api/types'

/** Совпадает с константами sidebarFolders / sidebarQuickAccess / today layout. */
const SIDEBAR_LAYOUT_PREFIX = 'orch-sidebar-layout-v1'
const SIDEBAR_QUICK_PREFIX = 'orch-sidebar-quick-v1'
const SIDEBAR_COLLAPSED_PREFIX = 'orch-sidebar-collapsed-v1'
const TODAY_LAYOUT_PREFIX = 'orch-today-layout-v6'
const TODAY_TILES_PREFIX = 'orch-today-tiles-v1'
const TODAY_TILE_ORDER_PREFIX = 'orch-today-tile-order-v1'

const UI_PREFS_EVENT = 'orchestrator:ui-prefs'
const TODAY_WIDGETS_EVENT = 'orchestrator:today-widgets-changed'
const TODAY_TILES_EVENT = 'orchestrator:today-tiles-changed'

type Section = 'sidebar' | 'today'

let userId = ''
let ready = false
let remoteEnabled = true
let applying = false
const pending = new Set<Section>()
let timer = 0

function slot(id: string): string {
  return id.trim() || 'default'
}

function readJson(key: string): unknown | undefined {
  if (typeof window === 'undefined') return undefined
  const raw = window.localStorage.getItem(key)
  if (raw == null) return undefined
  try {
    return JSON.parse(raw) as unknown
  } catch {
    return undefined
  }
}

function writeJson(key: string, value: unknown): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(key, JSON.stringify(value))
}

function collectSidebar(id: string): Record<string, unknown> | null {
  if (typeof window === 'undefined') return null
  const who = slot(id)
  const prefix = `${SIDEBAR_LAYOUT_PREFIX}:${who}:`
  const layouts: Record<string, unknown> = {}
  for (let index = 0; index < window.localStorage.length; index += 1) {
    const key = window.localStorage.key(index)
    if (!key?.startsWith(prefix)) continue
    const parsed = readJson(key)
    if (parsed && typeof parsed === 'object') layouts[key.slice(prefix.length)] = parsed
  }
  const quick = readJson(`${SIDEBAR_QUICK_PREFIX}:${who}`)
  const collapsedRaw = window.localStorage.getItem(`${SIDEBAR_COLLAPSED_PREFIX}:${who}`)
  if (!Object.keys(layouts).length && quick === undefined && collapsedRaw == null) return null
  const section: Record<string, unknown> = {}
  if (Object.keys(layouts).length) section.layouts = layouts
  if (Array.isArray(quick)) section.quick = quick
  if (collapsedRaw != null) section.collapsed = collapsedRaw === '1'
  return section
}

function collectToday(id: string): Record<string, unknown> | null {
  const who = slot(id)
  const widgets = readJson(`${TODAY_LAYOUT_PREFIX}:${who}`)
  const tilesHidden = readJson(`${TODAY_TILES_PREFIX}:${who}`)
  const tileOrder = readJson(`${TODAY_TILE_ORDER_PREFIX}:${who}`)
  if (widgets === undefined && tilesHidden === undefined && tileOrder === undefined) return null
  const section: Record<string, unknown> = {}
  if (widgets && typeof widgets === 'object') section.widgets = widgets
  if (tilesHidden && typeof tilesHidden === 'object' && !Array.isArray(tilesHidden)) section.tilesHidden = tilesHidden
  if (Array.isArray(tileOrder)) section.tileOrder = tileOrder
  return Object.keys(section).length ? section : null
}

function applySidebar(id: string, value: unknown): void {
  if (!value || typeof value !== 'object' || typeof window === 'undefined') return
  const section = value as Record<string, unknown>
  const who = slot(id)
  const layouts = section.layouts
  if (layouts && typeof layouts === 'object' && !Array.isArray(layouts)) {
    for (const [scope, layout] of Object.entries(layouts)) {
      if (!scope || !layout || typeof layout !== 'object') continue
      writeJson(`${SIDEBAR_LAYOUT_PREFIX}:${who}:${scope}`, layout)
    }
  }
  if (Array.isArray(section.quick)) writeJson(`${SIDEBAR_QUICK_PREFIX}:${who}`, section.quick)
  if (typeof section.collapsed === 'boolean') {
    window.localStorage.setItem(`${SIDEBAR_COLLAPSED_PREFIX}:${who}`, section.collapsed ? '1' : '0')
  }
}

function applyToday(id: string, value: unknown): void {
  if (!value || typeof value !== 'object') return
  const section = value as Record<string, unknown>
  const who = slot(id)
  if (section.widgets && typeof section.widgets === 'object') {
    writeJson(`${TODAY_LAYOUT_PREFIX}:${who}`, section.widgets)
  }
  if (section.tilesHidden && typeof section.tilesHidden === 'object' && !Array.isArray(section.tilesHidden)) {
    writeJson(`${TODAY_TILES_PREFIX}:${who}`, section.tilesHidden)
  }
  if (Array.isArray(section.tileOrder)) writeJson(`${TODAY_TILE_ORDER_PREFIX}:${who}`, section.tileOrder)
}

function notify(sections: Section[]): void {
  if (typeof window === 'undefined' || !sections.length) return
  if (sections.includes('sidebar')) window.dispatchEvent(new CustomEvent(UI_PREFS_EVENT))
  if (sections.includes('today')) {
    window.dispatchEvent(new CustomEvent(TODAY_WIDGETS_EVENT))
    window.dispatchEvent(new CustomEvent(TODAY_TILES_EVENT))
  }
}

async function flush(): Promise<void> {
  if (!ready || !remoteEnabled || !userId || !pending.size) return
  const sections = [...pending]
  pending.clear()
  const body: Record<string, unknown> = {}
  for (const section of sections) {
    const value = section === 'sidebar' ? collectSidebar(userId) : collectToday(userId)
    if (value) body[section] = value
  }
  if (!Object.keys(body).length) return
  try {
    await api.patchUiPrefs(body)
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 405)) remoteEnabled = false
  }
}

function schedule(): void {
  if (!ready || !remoteEnabled) return
  window.clearTimeout(timer)
  timer = window.setTimeout(() => void flush(), 400)
}

/** Вызывать после записи в localStorage. До первой загрузки с сервера правка не затирается ответом. */
export function scheduleUiSync(id: string, section: Section): void {
  if (applying || slot(id) !== slot(userId) || !userId) return
  pending.add(section)
  schedule()
}

export function resetUiPrefsSync(): void {
  window.clearTimeout(timer)
  userId = ''
  ready = false
  remoteEnabled = true
  pending.clear()
}

export async function startUiPrefsSync(id: string): Promise<void> {
  const who = id.trim()
  if (!who) return
  if (userId !== who) {
    window.clearTimeout(timer)
    pending.clear()
    ready = false
    remoteEnabled = true
  }
  userId = who
  let remote: Record<string, unknown> = {}
  try {
    remote = await api.getUiPrefs()
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 405)) remoteEnabled = false
    ready = true
    return
  }
  if (userId !== who) return
  const applied: Section[] = []
  applying = true
  try {
    for (const section of ['sidebar', 'today'] as const) {
      if (pending.has(section)) continue
      const value = remote[section]
      if (value && typeof value === 'object') {
        if (section === 'sidebar') applySidebar(who, value)
        else applyToday(who, value)
        applied.push(section)
        continue
      }
      const local = section === 'sidebar' ? collectSidebar(who) : collectToday(who)
      if (local) pending.add(section)
    }
  } finally {
    applying = false
  }
  ready = true
  notify(applied)
  void flush()
}
