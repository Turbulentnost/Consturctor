import type { LayoutItem } from 'react-grid-layout/legacy'
import { TODAY_GRID_COLS, TODAY_GRID_LAYOUT_MAX_ROWS, type TodayWidgetId } from './useTodayWidgetLayout'

function cloneItems(items: LayoutItem[]): LayoutItem[] {
  return items.map((item) => ({ ...item }))
}

function collides(a: LayoutItem, b: LayoutItem): boolean {
  if (a.i === b.i) return false
  if (a.x + a.w <= b.x) return false
  if (a.x >= b.x + b.w) return false
  if (a.y + a.h <= b.y) return false
  if (a.y >= b.y + b.h) return false
  return true
}

function hasCollision(placed: LayoutItem[], item: LayoutItem): boolean {
  return placed.some((other) => collides(item, other))
}

function clampItem(item: LayoutItem, cols: number, maxRows: number): LayoutItem {
  const w = Math.max(1, Math.min(item.w, cols))
  const h = Math.max(1, Math.min(item.h, maxRows))
  return {
    ...item,
    w,
    h,
    x: Math.max(0, Math.min(item.x, cols - w)),
    y: Math.max(0, Math.min(item.y, maxRows - h))
  }
}

function findFirstFit(
  placed: LayoutItem[],
  item: LayoutItem,
  cols: number,
  maxRows: number
): LayoutItem {
  const base = clampItem(item, cols, maxRows)
  for (let y = 0; y <= maxRows - base.h; y++) {
    for (let x = 0; x <= cols - base.w; x++) {
      const candidate = { ...base, x, y }
      if (!hasCollision(placed, candidate)) return candidate
    }
  }
  return base
}

/**
 * Якорные виджеты (перемещённый + закреплённые) остаются на месте.
 * Остальные перераскладываются сверху-слева, заполняя пустоты.
 */
export function reflowTodayLayout(
  layout: LayoutItem[],
  priorityIds: string[] = [],
  cols = TODAY_GRID_COLS,
  locked: Partial<Record<TodayWidgetId, boolean>> = {},
  maxRows = TODAY_GRID_LAYOUT_MAX_ROWS
): LayoutItem[] {
  if (!layout.length) return layout

  const anchorIds = new Set<string>(priorityIds)
  for (const id of Object.keys(locked)) {
    if (locked[id as TodayWidgetId]) anchorIds.add(id)
  }

  const source = layout.map((item) => clampItem(item, cols, maxRows))
  const anchors = source.filter((item) => anchorIds.has(item.i))
  const movable = source.filter((item) => !anchorIds.has(item.i))

  movable.sort((left, right) => {
    const areaDiff = right.w * right.h - left.w * left.h
    if (areaDiff !== 0) return areaDiff
    return left.y - right.y || left.x - right.x
  })

  const placed: LayoutItem[] = anchors.map((item) => ({ ...item }))

  for (const item of movable) {
    placed.push(findFirstFit(placed, item, cols, maxRows))
  }

  const byId = new Map(placed.map((item) => [item.i, item]))
  return layout.map((item) => byId.get(item.i) ?? item)
}

/** @deprecated используйте reflowTodayLayout */
export function compactTodayLayout(
  layout: LayoutItem[],
  cols = TODAY_GRID_COLS,
  locked: Partial<Record<TodayWidgetId, boolean>> = {}
): LayoutItem[] {
  return reflowTodayLayout(layout, [], cols, locked)
}

export function mergeTodayLayout(
  fullLayout: LayoutItem[],
  visibleIds: TodayWidgetId[],
  visibleLayout: LayoutItem[]
): LayoutItem[] {
  const visibleSet = new Set<string>(visibleIds)
  const visibleMap = new Map(visibleLayout.map((item) => [item.i, item]))

  let stackY = visibleLayout.reduce((max, item) => Math.max(max, item.y + item.h), 0)

  return fullLayout.map((item) => {
    if (visibleSet.has(item.i as TodayWidgetId)) {
      const next = visibleMap.get(item.i)
      return next ? { ...item, ...next } : item
    }
    const next = { ...item, x: 0, y: stackY }
    stackY += item.h
    return next
  })
}

export function layoutsEqual(left: LayoutItem[], right: LayoutItem[]): boolean {
  if (left.length !== right.length) return false
  const rightById = new Map(right.map((item) => [item.i, item]))
  return left.every((item) => {
    const other = rightById.get(item.i)
    if (!other) return false
    return item.x === other.x && item.y === other.y && item.w === other.w && item.h === other.h
  })
}
