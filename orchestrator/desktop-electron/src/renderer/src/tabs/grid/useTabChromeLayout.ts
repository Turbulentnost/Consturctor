import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Layout, LayoutItem } from 'react-grid-layout/legacy'
import { resolveLayoutOverlaps } from './gridReflow'
import { VISUAL_CHANGED_EVENT } from './visualTabs'
import {
  AGENT_LIBRARY_TAB_GRID_COLS,
  AGENT_LIBRARY_TAB_GRID_ROWS,
  DEFAULT_AGENT_LIBRARY_LAYOUT,
  DEFAULT_ASSIGNMENTS_REGISTRY_LAYOUT,
  DEFAULT_DECISIONS_LAYOUT,
  DEFAULT_KPI_LAYOUT,
  DEFAULT_MEETINGS_LAYOUT,
  DEFAULT_PROCESS_LAYOUT,
  DEFAULT_STANDARD_LAYOUT,
  DEFAULT_WIDE_MAIN_LAYOUT,
  KPI_TAB_GRID_COLS,
  KPI_TAB_GRID_ROWS,
  REGISTRY_TAB_GRID_COLS,
  REGISTRY_TAB_GRID_ROWS,
  TAB_CHROME_COLS,
  TAB_CHROME_MAX_ROWS,
  scaleLayoutItems,
  tabChromeGridDimensions,
  tabChromeLayoutMigration,
  tabUsesSnapGrid
} from './tabLayouts'

export const TAB_CHROME_STORAGE_KEY = 'orch-tab-chrome-v11'
export {
  AGENT_LIBRARY_TAB_GRID_COLS,
  AGENT_LIBRARY_TAB_GRID_ROWS,
  DEFAULT_AGENT_LIBRARY_LAYOUT,
  DEFAULT_ASSIGNMENTS_REGISTRY_LAYOUT,
  DEFAULT_DECISIONS_LAYOUT,
  DEFAULT_KPI_LAYOUT,
  DEFAULT_MEETINGS_LAYOUT,
  DEFAULT_PROCESS_LAYOUT,
  DEFAULT_STANDARD_LAYOUT,
  DEFAULT_WIDE_MAIN_LAYOUT,
  KPI_TAB_GRID_COLS,
  KPI_TAB_GRID_ROWS,
  REGISTRY_TAB_GRID_COLS,
  REGISTRY_TAB_GRID_ROWS,
  TAB_CHROME_COLS,
  TAB_CHROME_MAX_ROWS,
  tabChromeGridDimensions,
  tabUsesSnapGrid
}
export const TAB_CHROME_MARGIN: [number, number] = [5, 5]
export const TAB_CHROME_MIN_ROW = 48
/** Floor cell size: below this, overflow widgets go to the basket. */
export const TAB_CHROME_MIN_ROW_HARD = 28
export const TAB_CHROME_MIN_COL_PX = 36

export const TILE_WIDGET_PREFIX = 'tile:'

export function tileWidgetId(tileId: string): string {
  return `${TILE_WIDGET_PREFIX}${tileId}`
}

export function isTileWidgetId(id: string): boolean {
  return id.startsWith(TILE_WIDGET_PREFIX)
}

/** Split the old single `tiles` row into one widget per tile, equal columns. */
export function withTileWidgets(body: LayoutItem[], tileIds: string[]): LayoutItem[] {
  const rest = body.filter((item) => item.i !== 'tiles' && !isTileWidgetId(item.i))
  const ids = tileIds.length ? tileIds : []
  if (!ids.length) return rest
  const n = ids.length
  const baseW = Math.max(1, Math.floor(TAB_CHROME_COLS / n))
  const extra = TAB_CHROME_COLS - baseW * n
  let x = 0
  const tiles = ids.map((id, index) => {
    const w = Math.max(1, baseW + (index >= n - extra ? 1 : 0))
    const item: LayoutItem = {
      i: tileWidgetId(id),
      x,
      y: 0,
      w,
      h: 1,
      minW: 2,
      minH: 1,
      maxW: TAB_CHROME_COLS,
      maxH: 3
    }
    x += w
    return item
  })
  if (tiles.length) {
    const last = tiles[tiles.length - 1]
    last.w = Math.max(last.minW ?? 1, TAB_CHROME_COLS - last.x)
  }
  return [...tiles, ...rest]
}

export const STANDARD_TAB_WIDGET_IDS = ['tiles', 'filters', 'main', 'side'] as const
export type StandardTabWidgetId = (typeof STANDARD_TAB_WIDGET_IDS)[number]

export const STANDARD_TAB_LABELS: Record<string, string> = {
  tiles: 'Плитки',
  filters: 'Фильтры',
  main: 'Таблица',
  side: 'Карточка',
  botA: 'Нижний блок A',
  botB: 'Нижний блок B',
  botC: 'Нижний блок C',
  calendar: 'Календарь',
  rail: 'Период и календари'
}

export type TabChromeMeta = {
  visible: boolean
  color: string
  locked: boolean
  /** Auto-moved off the canvas because it could not shrink further. */
  binned?: boolean
}

export type TabChromePersist = {
  layout: LayoutItem[]
  meta: Record<string, TabChromeMeta>
}

function storageKey(tabId: string, userId: string): string {
  const uid = userId.trim() || 'default'
  if (tabId === 'assignments_registry') {
    return `${TAB_CHROME_STORAGE_KEY}:assignments_registry-v3:${uid}`
  }
  if (tabId === 'agent_library') {
    return `${TAB_CHROME_STORAGE_KEY}:agent_library-v2:${uid}`
  }
  if (tabId === 'meetings') {
    // v3 — правая карточка уехала во всплывающее окно, сетка заняла её место.
    return `${TAB_CHROME_STORAGE_KEY}:meetings-v3:${uid}`
  }
  if (tabId === 'kpi') {
    return `${TAB_CHROME_STORAGE_KEY}:kpi-v5:${uid}`
  }
  return `${TAB_CHROME_STORAGE_KEY}:${tabId}:${uid}`
}

function defaultMeta(ids: string[]): Record<string, TabChromeMeta> {
  return Object.fromEntries(ids.map((id) => [id, { visible: true, color: '', locked: false, binned: false }]))
}

function widgetBinPriority(id: string): number {
  if (id.startsWith('bot')) return 0
  if (id === 'side') return 1
  if (id === 'main') return 2
  if (id === 'filters') return 3
  if (isTileWidgetId(id) || id === 'tiles') return 4
  return 1
}

export function viewportFitCells(
  containerHeight: number,
  containerWidth: number,
  grid = tabChromeGridDimensions('')
): { rows: number; cols: number } {
  const [marginX, marginY] = TAB_CHROME_MARGIN
  const rows = Math.max(
    1,
    Math.min(
      grid.maxRows,
      Math.floor((Math.max(0, containerHeight) + marginY) / (TAB_CHROME_MIN_ROW_HARD + marginY))
    )
  )
  const cols = Math.max(
    1,
    Math.min(
      grid.cols,
      Math.floor((Math.max(0, containerWidth) + marginX) / (TAB_CHROME_MIN_COL_PX + marginX))
    )
  )
  return { rows, cols }
}

export function isWidgetOnCanvas(meta: TabChromeMeta | undefined): boolean {
  return meta?.visible !== false && !meta?.binned
}

/** Shrink widgets to min size, then list those that still sit past the visible cells. */
export function pickOverflowWidgetIds(
  layout: LayoutItem[],
  meta: Record<string, TabChromeMeta>,
  fitRows: number,
  fitCols: number
): string[] {
  const candidates = layout
    .filter((item) => isWidgetOnCanvas(meta[item.i]) && !meta[item.i]?.locked)
    .sort((left, right) => {
      const rank = widgetBinPriority(left.i) - widgetBinPriority(right.i)
      if (rank) return rank
      const bottom = right.y + right.h - (left.y + left.h)
      if (bottom) return bottom
      return right.x + right.w - (left.x + left.w)
    })

  const hidden = new Set<string>()
  const remaining = (): LayoutItem[] =>
    layout.filter((item) => isWidgetOnCanvas(meta[item.i]) && !hidden.has(item.i))

  const overflows = (items: LayoutItem[]): boolean => {
    if (!items.length) return false
    return items.some((item) => {
      const minW = item.minW ?? 1
      const minH = item.minH ?? 1
      const pastBottom = item.y >= fitRows || item.y + minH > fitRows
      const pastRight = item.x >= fitCols || item.x + minW > fitCols
      return pastBottom || pastRight
    })
  }

  for (const item of candidates) {
    if (!overflows(remaining())) break
    const next = remaining().filter((row) => row.i !== item.i)
    if (!next.length) break
    hidden.add(item.i)
  }
  return [...hidden]
}

export function applyViewportShrink(
  layout: LayoutItem[],
  fitRows: number,
  fitCols: number
): LayoutItem[] {
  return layout.map((item) => {
    const minW = item.minW ?? 1
    const minH = item.minH ?? 1
    let { x, y, w, h } = item
    if (x >= fitCols) x = Math.max(0, fitCols - minW)
    if (y >= fitRows) y = Math.max(0, fitRows - minH)
    w = Math.max(minW, Math.min(w, fitCols - x))
    h = Math.max(minH, Math.min(h, fitRows - y))
    return { ...item, x, y, w, h }
  })
}

function mergeLayout(
  raw: LayoutItem[] | undefined,
  defaults: LayoutItem[],
  grid: { cols: number; maxRows: number }
): LayoutItem[] {
  const list = raw ? [...raw] : []
  const byId = new Map(list.filter((item) => item?.i).map((item) => [item.i, item]))
  return defaults.map((base) => {
    const saved = byId.get(base.i)
    if (!saved) return { ...base }
    const maxW = Math.min(base.maxW ?? grid.cols, grid.cols)
    const maxH = Math.min(base.maxH ?? grid.maxRows, grid.maxRows)
    const minW = base.minW ?? 1
    const minH = base.minH ?? 1
    const w = Math.max(minW, Math.min(maxW, Math.round(saved.w || base.w)))
    const h = Math.max(minH, Math.min(maxH, Math.round(saved.h || base.h)))
    const x = Math.max(0, Math.min(grid.cols - w, Math.round(saved.x ?? base.x)))
    const y = Math.max(0, Math.min(grid.maxRows - h, Math.round(saved.y ?? base.y)))
    return { ...base, x, y, w, h }
  })
}

function sanitizeLayout(
  raw: LayoutItem[] | undefined,
  defaults: LayoutItem[],
  grid: { cols: number; maxRows: number }
): LayoutItem[] {
  return mergeLayout(raw, defaults, grid)
}

function sanitizeLayoutFromStorage(
  raw: LayoutItem[] | undefined,
  defaults: LayoutItem[],
  grid: { cols: number; maxRows: number }
): LayoutItem[] {
  return resolveLayoutOverlaps(mergeLayout(raw, defaults, grid), grid.cols, grid.maxRows)
}

function sanitizeMeta(
  raw: Record<string, Partial<TabChromeMeta>> | undefined,
  ids: string[]
): Record<string, TabChromeMeta> {
  const next = defaultMeta(ids)
  if (!raw) return next
  for (const id of ids) {
    const saved = raw[id]
    if (!saved) continue
    next[id] = {
      visible: saved.visible !== false,
      color: typeof saved.color === 'string' ? saved.color : '',
      locked: Boolean(saved.locked),
      binned: Boolean(saved.binned)
    }
  }
  return next
}

function kpiEnsureAllWidgetsVisible(
  meta: Record<string, TabChromeMeta>,
  ids: string[]
): Record<string, TabChromeMeta> {
  const next = { ...meta }
  for (const id of ids) {
    const cur = next[id] || { visible: true, color: '', locked: false, binned: false }
    next[id] = { ...cur, visible: true, binned: false }
  }
  return next
}

function readStoredChrome(tabId: string, userId: string): TabChromePersist | null {
  const uid = userId.trim() || 'default'
  const current = localStorage.getItem(storageKey(tabId, userId))
  if (current) return JSON.parse(current) as TabChromePersist
  const migration = tabChromeLayoutMigration(tabId)
  if (!migration) return null
  const legacy = localStorage.getItem(`${TAB_CHROME_STORAGE_KEY}:${migration.legacySuffix}:${uid}`)
  if (!legacy) return null
  const parsed = JSON.parse(legacy) as TabChromePersist
  return { ...parsed, layout: scaleLayoutItems(parsed.layout || [], migration.sx, migration.sy) }
}

function readPersist(tabId: string, userId: string, defaults: LayoutItem[], ids: string[]): TabChromePersist {
  const grid = tabChromeGridDimensions(tabId)
  try {
    const parsed = readStoredChrome(tabId, userId)
    if (!parsed) {
      return {
        layout: defaults.map((item) => ({ ...item })),
        meta:
          tabId === 'kpi' || tabId === 'assignments_registry'
            ? kpiEnsureAllWidgetsVisible(defaultMeta(ids), ids)
            : defaultMeta(ids)
      }
    }
    const meta = sanitizeMeta(parsed.meta, ids)
    return {
      layout: sanitizeLayoutFromStorage(parsed.layout, defaults, grid),
      meta:
        tabId === 'kpi' || tabId === 'assignments_registry'
          ? kpiEnsureAllWidgetsVisible(meta, ids)
          : meta
    }
  } catch {
    return {
      layout: defaults.map((item) => ({ ...item })),
      meta:
        tabId === 'kpi' || tabId === 'assignments_registry'
          ? kpiEnsureAllWidgetsVisible(defaultMeta(ids), ids)
          : defaultMeta(ids)
    }
  }
}

function writePersist(tabId: string, userId: string, state: TabChromePersist): void {
  try {
    localStorage.setItem(storageKey(tabId, userId), JSON.stringify(state))
  } catch {
    /* ignore */
  }
}

function layoutGeomEqual(left: LayoutItem[], right: LayoutItem[]): boolean {
  if (left.length !== right.length) return false
  const rightById = new Map(right.map((item) => [item.i, item]))
  return left.every((item) => {
    const other = rightById.get(item.i)
    return Boolean(
      other && item.x === other.x && item.y === other.y && item.w === other.w && item.h === other.h
    )
  })
}

/** Min row height for 8×6 snap grids (KPI) — same floor as «Сегодня». */
export const TAB_CHROME_SNAP_MIN_ROW = 44

export type TabChromeMetricsOptions = {
  cols?: number
  /** Stretch rows to exactly fill containerHeight (Today / KPI 8×6). */
  fillHeight?: boolean
  minRowHeight?: number
}

export function computeTabChromeMetrics(
  containerHeight: number,
  containerWidth: number,
  usedRows = TAB_CHROME_MAX_ROWS,
  options?: TabChromeMetricsOptions
): {
  rowHeight: number
  canvasHeight: number
  containerWidth: number
  colWidth: number
  marginX: number
  marginY: number
} {
  const [marginX, marginY] = TAB_CHROME_MARGIN
  const rows = Math.max(1, Math.min(TAB_CHROME_MAX_ROWS, usedRows))
  const cols = Math.max(1, options?.cols ?? TAB_CHROME_COLS)
  const innerH = Math.max(0, containerHeight)
  const innerW = Math.max(0, containerWidth)
  const minRow = options?.minRowHeight ?? TAB_CHROME_MIN_ROW_HARD
  const slack = Math.max(0, innerH - (rows - 1) * marginY)
  const rowHeight = options?.fillHeight
    ? Math.max(minRow, slack / rows)
    : Math.max(minRow, Math.floor(slack / rows))
  const canvasHeight = options?.fillHeight
    ? innerH
    : rows * rowHeight + (rows - 1) * marginY
  const colWidth = Math.max(0, (innerW - marginX * (cols - 1)) / cols)
  return {
    rowHeight,
    canvasHeight,
    containerWidth: innerW,
    colWidth,
    marginX,
    marginY
  }
}

export function useTabChromeLayout(
  tabId: string,
  userId: string,
  defaults: LayoutItem[]
): {
  widgetIds: string[]
  layoutWithStatic: LayoutItem[]
  meta: Record<string, TabChromeMeta>
  basketIds: string[]
  editMode: boolean
  setEditMode: (value: boolean | ((prev: boolean) => boolean)) => void
  onLayoutChange: (next: Layout) => void
  toggleVisible: (id: string) => void
  toggleLocked: (id: string) => void
  setColor: (id: string, color: string) => void
  restoreFromBasket: (id: string) => void
  syncViewport: (containerHeight: number, containerWidth: number) => void
  resetLayout: () => void
} {
  const widgetIds = useMemo(() => defaults.map((item) => item.i), [defaults])
  const [persist, setPersist] = useState(() => readPersist(tabId, userId, defaults, widgetIds))
  const [editMode, setEditMode] = useState(false)
  const persistRef = useRef(persist)
  persistRef.current = persist

  useEffect(() => {
    setPersist(readPersist(tabId, userId, defaults, widgetIds))
    setEditMode(false)
  }, [tabId, userId, defaults, widgetIds])

  useEffect(() => {
    const reload = (): void => {
      if (editMode) return
      setPersist(readPersist(tabId, userId, defaults, widgetIds))
    }
    window.addEventListener(VISUAL_CHANGED_EVENT, reload)
    return () => window.removeEventListener(VISUAL_CHANGED_EVENT, reload)
  }, [defaults, editMode, tabId, userId, widgetIds])

  const save = useCallback(
    (next: TabChromePersist) => {
      setPersist(next)
      writePersist(tabId, userId, next)
    },
    [tabId, userId]
  )

  const grid = useMemo(() => tabChromeGridDimensions(tabId), [tabId])

  const onLayoutChange = useCallback(
    (next: Layout) => {
      const proposed = sanitizeLayout([...next], defaults, grid)
      if (layoutGeomEqual(proposed, persist.layout)) return
      save({ layout: proposed, meta: persist.meta })
    },
    [defaults, grid, persist.layout, persist.meta, save]
  )

  const patchMeta = useCallback(
    (id: string, patch: Partial<TabChromeMeta>) => {
      save({
        layout: persist.layout,
        meta: { ...persist.meta, [id]: { ...persist.meta[id], ...patch } }
      })
    },
    [persist.layout, persist.meta, save]
  )

  const toggleVisible = useCallback(
    (id: string) => {
      patchMeta(id, { visible: !persist.meta[id]?.visible })
    },
    [patchMeta, persist.meta]
  )

  const toggleLocked = useCallback(
    (id: string) => {
      patchMeta(id, { locked: !persist.meta[id]?.locked })
    },
    [patchMeta, persist.meta]
  )

  const setColor = useCallback(
    (id: string, color: string) => {
      patchMeta(id, { color })
    },
    [patchMeta]
  )

  const resetLayout = useCallback(() => {
    const meta = defaultMeta(widgetIds)
    save({
      layout: defaults.map((item) => ({ ...item })),
      meta: tabId === 'kpi' ? kpiEnsureAllWidgetsVisible(meta, widgetIds) : meta
    })
  }, [defaults, save, tabId, widgetIds])

  const restoreFromBasket = useCallback(
    (id: string) => {
      patchMeta(id, { binned: false, visible: true })
    },
    [patchMeta]
  )

  const syncViewport = useCallback(
    (containerHeight: number, containerWidth: number) => {
      if (containerHeight < 8 || containerWidth < 8) return
      // Виджеты больше не уезжают в корзину сами: узкое окно, свёрнутая вкладка
      // или нулевой размер при замере прятали блоки без возможности вернуть их.
      // Корзина остаётся только для того, что пользователь скрыл сам.
      const { layout, meta: prevMeta } = persistRef.current
      const stuck = widgetIds.filter((id) => prevMeta[id]?.binned)
      if (!stuck.length) return
      const meta = { ...prevMeta }
      for (const id of stuck) {
        meta[id] = { ...meta[id], binned: false, visible: true }
      }
      save({ layout, meta })
    },
    [save, widgetIds]
  )

  const basketIds = useMemo(
    () => widgetIds.filter((id) => persist.meta[id]?.binned || persist.meta[id]?.visible === false),
    [persist.meta, widgetIds]
  )

  const layoutWithStatic = useMemo(() => {
    const visibleIds = new Set(widgetIds.filter((id) => isWidgetOnCanvas(persist.meta[id])))
    return persist.layout
      .filter((item) => visibleIds.has(item.i))
      .map((item) => ({
        ...item,
        static: !editMode || Boolean(persist.meta[item.i]?.locked)
      }))
  }, [editMode, persist.layout, persist.meta, widgetIds])

  return {
    widgetIds,
    layoutWithStatic,
    meta: persist.meta,
    basketIds,
    editMode,
    setEditMode,
    onLayoutChange,
    toggleVisible,
    toggleLocked,
    setColor,
    restoreFromBasket,
    syncViewport,
    resetLayout
  }
}
