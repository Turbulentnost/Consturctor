import type { LayoutItem } from 'react-grid-layout/legacy'

type Rect = { x: number; y: number; w: number; h: number }

function overlaps(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
}

function sameBandY(a: Rect, b: Rect): boolean {
  return a.y < b.y + b.h && b.y < a.y + a.h
}

function sameBandX(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w
}

function area(item: Rect): number {
  return Math.max(0, item.w) * Math.max(0, item.h)
}

export function findResizedWidgetId(prev: LayoutItem[], next: LayoutItem[]): string | null {
  const prevById = new Map(prev.map((item) => [item.i, item]))
  let bestId: string | null = null
  let bestDelta = 0
  for (const item of next) {
    const old = prevById.get(item.i)
    if (!old) continue
    const sizeChanged = old.w !== item.w || old.h !== item.h
    if (!sizeChanged) continue
    const delta = Math.abs(area(item) - area(old)) + Math.abs(item.x - old.x) + Math.abs(item.y - old.y)
    if (delta > bestDelta) {
      bestDelta = delta
      bestId = item.i
    }
  }
  return bestId
}

function clampItem(item: LayoutItem, cols: number, rows: number): LayoutItem {
  const minW = item.minW ?? 1
  const minH = item.minH ?? 1
  const maxW = Math.min(item.maxW ?? cols, cols)
  const maxH = Math.min(item.maxH ?? rows, rows)
  const w = Math.max(minW, Math.min(maxW, item.w))
  const h = Math.max(minH, Math.min(maxH, item.h))
  const x = Math.max(0, Math.min(cols - w, item.x))
  const y = Math.max(0, Math.min(rows - h, item.y))
  return { ...item, x, y, w, h }
}

function clampAgainstLocked(
  item: LayoutItem,
  others: LayoutItem[],
  lockedIds: Set<string>,
  cols: number,
  rows: number
): LayoutItem {
  let next = clampItem(item, cols, rows)
  for (const other of others) {
    if (other.i === next.i || !lockedIds.has(other.i)) continue
    if (!overlaps(next, other)) continue
    if (next.x < other.x && next.x + next.w > other.x) {
      next = { ...next, w: Math.max(next.minW ?? 1, other.x - next.x) }
    } else if (other.x < next.x && other.x + other.w > next.x) {
      const x = other.x + other.w
      next = { ...next, x, w: Math.max(next.minW ?? 1, next.x + next.w - x) }
    }
    if (next.y < other.y && next.y + next.h > other.y) {
      next = { ...next, h: Math.max(next.minH ?? 1, other.y - next.y) }
    } else if (other.y < next.y && other.y + other.h > next.y) {
      const y = other.y + other.h
      next = { ...next, y, h: Math.max(next.minH ?? 1, next.y + next.h - y) }
    }
    next = clampItem(next, cols, rows)
  }
  return next
}

/**
 * When one widget is resized, shrink or grow neighbors on the moved edges.
 * Neighbors that cannot shrink past minW/minH are returned as overflowIds (basket).
 */
export function resizeWithNeighbors(
  prev: LayoutItem[],
  proposed: LayoutItem[],
  changedId: string,
  cols: number,
  rows: number,
  lockedIds: Set<string>
): { layout: LayoutItem[]; overflowIds: string[] } {
  const oldItem = prev.find((item) => item.i === changedId)
  const rawNew = proposed.find((item) => item.i === changedId)
  if (!oldItem || !rawNew) return { layout: proposed.map((item) => ({ ...item })), overflowIds: [] }

  const byId = new Map(prev.map((item) => [item.i, { ...item }]))
  for (const item of proposed) {
    if (!byId.has(item.i)) byId.set(item.i, { ...item })
  }
  const lockedItem = clampAgainstLocked(
    rawNew,
    [...byId.values()],
    lockedIds,
    cols,
    rows
  )
  byId.set(changedId, lockedItem)

  const overflowIds: string[] = []
  const dLeft = lockedItem.x - oldItem.x
  const dRight = lockedItem.x + lockedItem.w - (oldItem.x + oldItem.w)
  const dTop = lockedItem.y - oldItem.y
  const dBottom = lockedItem.y + lockedItem.h - (oldItem.y + oldItem.h)

  const tryAdjust = (
    item: LayoutItem,
    patch: { x?: number; y?: number; w?: number; h?: number }
  ): boolean => {
    const minW = item.minW ?? 1
    const minH = item.minH ?? 1
    const next = clampItem({ ...item, ...patch }, cols, rows)
    if (next.w < minW || next.h < minH) return false
    if (next.x < 0 || next.y < 0 || next.x + next.w > cols || next.y + next.h > rows) return false
    byId.set(item.i, next)
    return true
  }

  for (const item of [...byId.values()]) {
    if (item.i === changedId || lockedIds.has(item.i)) continue

    if (dRight !== 0 && sameBandY(item, lockedItem)) {
      const oldRight = oldItem.x + oldItem.w
      const touches =
        (dRight > 0 && item.x < lockedItem.x + lockedItem.w && item.x + item.w > oldRight) ||
        (dRight < 0 && Math.abs(item.x - oldRight) <= 1)
      if (touches) {
        const ok = tryAdjust(item, { x: item.x + dRight, w: item.w - dRight })
        if (!ok && dRight > 0) overflowIds.push(item.i)
      }
    }

    if (dLeft !== 0 && sameBandY(item, lockedItem)) {
      const touches =
        (dLeft < 0 && item.x < oldItem.x && item.x + item.w > lockedItem.x) ||
        (dLeft > 0 && Math.abs(item.x + item.w - oldItem.x) <= 1)
      if (touches) {
        const ok = tryAdjust(item, { w: item.w + dLeft })
        if (!ok && dLeft < 0) overflowIds.push(item.i)
      }
    }

    if (dBottom !== 0 && sameBandX(item, lockedItem)) {
      const oldBottom = oldItem.y + oldItem.h
      const touches =
        (dBottom > 0 && item.y < lockedItem.y + lockedItem.h && item.y + item.h > oldBottom) ||
        (dBottom < 0 && Math.abs(item.y - oldBottom) <= 1)
      if (touches) {
        const ok = tryAdjust(item, { y: item.y + dBottom, h: item.h - dBottom })
        if (!ok && dBottom > 0) overflowIds.push(item.i)
      }
    }

    if (dTop !== 0 && sameBandX(item, lockedItem)) {
      const touches =
        (dTop < 0 && item.y < oldItem.y && item.y + item.h > lockedItem.y) ||
        (dTop > 0 && Math.abs(item.y + item.h - oldItem.y) <= 1)
      if (touches) {
        const ok = tryAdjust(item, { h: item.h + dTop })
        if (!ok && dTop < 0) overflowIds.push(item.i)
      }
    }
  }

  const overflow = new Set(overflowIds)
  const layout = [...byId.values()].map((item) => clampItem(item, cols, rows))
  return { layout, overflowIds: [...overflow] }
}

/** Push overlapping items apart (vertical compact) — fixes bad persisted layouts. */
export function resolveLayoutOverlaps(items: LayoutItem[], cols: number, maxRows: number): LayoutItem[] {
  if (!items.length) return items

  const byId = new Map(items.map((item) => [item.i, { ...item }]))
  const order = [...items].sort((left, right) => {
    if (left.y !== right.y) return left.y - right.y
    if (left.x !== right.x) return left.x - right.x
    return left.i.localeCompare(right.i)
  })

  const settled: LayoutItem[] = []

  for (const raw of order) {
    let item = clampItem(raw, cols, maxRows)

    for (let attempt = 0; attempt < 64; attempt++) {
      const hit = settled.find((other) => overlaps(item, other))
      if (!hit) break

      const belowY = hit.y + hit.h
      const rightX = hit.x + hit.w
      if (belowY + item.h <= maxRows) {
        item = clampItem({ ...item, y: belowY }, cols, maxRows)
        continue
      }
      if (rightX + item.w <= cols) {
        item = clampItem({ ...item, x: rightX, y: hit.y }, cols, maxRows)
        continue
      }
      item = clampItem({ ...item, x: 0, y: belowY }, cols, maxRows)
    }

    settled.push(item)
    byId.set(item.i, item)
  }

  return items.map((item) => byId.get(item.i) ?? item)
}
