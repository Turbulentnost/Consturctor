import type { LayoutItem } from 'react-grid-layout/legacy'

export const TAB_CHROME_COLS = 16
export const TAB_CHROME_MAX_ROWS = 12
/** Все вкладки, включая KPI, реестр и «Сегодня», стоят на одной сетке 16×12. */
export const KPI_TAB_GRID_COLS = TAB_CHROME_COLS
export const KPI_TAB_GRID_ROWS = TAB_CHROME_MAX_ROWS
export const REGISTRY_TAB_GRID_COLS = TAB_CHROME_COLS
export const REGISTRY_TAB_GRID_ROWS = TAB_CHROME_MAX_ROWS
export const AGENT_LIBRARY_TAB_GRID_COLS = TAB_CHROME_COLS
export const AGENT_LIBRARY_TAB_GRID_ROWS = TAB_CHROME_MAX_ROWS

export function tabChromeGridDimensions(_tabId: string): { cols: number; maxRows: number } {
  return { cols: TAB_CHROME_COLS, maxRows: TAB_CHROME_MAX_ROWS }
}

/** Старые ключи вкладок, которые жили на сетке меньше 16×12. Координаты умножаются при чтении. */
export function tabChromeLayoutMigration(
  tabId: string
): { legacySuffix: string; sx: number; sy: number } | null {
  if (tabId === 'kpi') return { legacySuffix: 'kpi-v4', sx: 2, sy: 2 }
  if (tabId === 'assignments_registry') return { legacySuffix: 'assignments_registry-v2', sx: 2, sy: 2 }
  if (tabId === 'agent_library') return { legacySuffix: 'agent_library-v1', sx: 2, sy: 1.5 }
  return null
}

export function scaleLayoutItems(items: LayoutItem[], sx: number, sy: number): LayoutItem[] {
  return items.map((item) => ({
    ...item,
    x: Math.round((item.x ?? 0) * sx),
    y: Math.round((item.y ?? 0) * sy),
    w: Math.max(1, Math.round((item.w ?? 1) * sx)),
    h: Math.max(1, Math.round((item.h ?? 1) * sy))
  }))
}

export function tabUsesSnapGrid(tabId: string): boolean {
  return tabId === 'kpi' || tabId === 'assignments_registry' || tabId === 'agent_library'
}

export const DEFAULT_STANDARD_LAYOUT: LayoutItem[] = [
  { i: 'main', x: 0, y: 0, w: 12, h: 12, minW: 6, minH: 4, maxW: 16, maxH: 12 },
  { i: 'side', x: 12, y: 0, w: 4, h: 12, minW: 4, minH: 4, maxW: 16, maxH: 12 }
]

/**
 * Совещания: слева период и календари, справа сетка. Карточки совещания в раскладке
 * нет — она открывается рядом с блоком, как в Google Calendar.
 */
export const DEFAULT_MEETINGS_LAYOUT: LayoutItem[] = [
  { i: 'rail', x: 0, y: 0, w: 3, h: 12, minW: 2, minH: 6, maxW: 6, maxH: 12 },
  { i: 'main', x: 3, y: 0, w: 13, h: 12, minW: 5, minH: 4, maxW: 16, maxH: 12 }
]

export const DEFAULT_WIDE_MAIN_LAYOUT: LayoutItem[] = [
  { i: 'main', x: 0, y: 0, w: 16, h: 12, minW: 8, minH: 4, maxW: 16, maxH: 12 }
]

/** 16×12: каталог 16×9, добавленные 16×3. */
export const DEFAULT_AGENT_LIBRARY_LAYOUT: LayoutItem[] = [
  {
    i: 'main',
    x: 0,
    y: 0,
    w: 16,
    h: 9,
    minW: 8,
    minH: 4,
    maxW: 16,
    maxH: 12
  },
  {
    i: 'botA',
    x: 0,
    y: 9,
    w: 16,
    h: 3,
    minW: 8,
    minH: 2,
    maxW: 16,
    maxH: 6
  }
]

/** 16×12: таблица 12×12, карточка поручения 4×12. */
export const DEFAULT_ASSIGNMENTS_REGISTRY_LAYOUT: LayoutItem[] = [
  {
    i: 'main',
    x: 0,
    y: 0,
    w: 12,
    h: 12,
    minW: 8,
    minH: 6,
    maxW: 16,
    maxH: 12
  },
  {
    i: 'side',
    x: 12,
    y: 0,
    w: 4,
    h: 12,
    minW: 3,
    minH: 6,
    maxW: 16,
    maxH: 12
  }
]

export const DEFAULT_PROCESS_LAYOUT: LayoutItem[] = [
  { i: 'main', x: 0, y: 0, w: 12, h: 7, minW: 6, minH: 3, maxW: 16, maxH: 12 },
  { i: 'side', x: 12, y: 0, w: 4, h: 7, minW: 4, minH: 3, maxW: 16, maxH: 12 },
  { i: 'botA', x: 0, y: 7, w: 8, h: 5, minW: 4, minH: 2, maxW: 16, maxH: 6 },
  { i: 'botB', x: 8, y: 7, w: 8, h: 5, minW: 4, minH: 2, maxW: 16, maxH: 6 }
]

/** KPI: таблица на всю сетку 16×12 под двумя фиксированными рядами плиток. */
export const DEFAULT_KPI_LAYOUT: LayoutItem[] = [
  { i: 'main', x: 0, y: 0, w: 16, h: 12, minW: 8, minH: 4, maxW: 16, maxH: 12 }
]

export const DEFAULT_DECISIONS_LAYOUT: LayoutItem[] = [
  { i: 'main', x: 0, y: 0, w: 12, h: 10, minW: 6, minH: 4, maxW: 16, maxH: 12 },
  { i: 'side', x: 12, y: 0, w: 4, h: 10, minW: 4, minH: 4, maxW: 16, maxH: 12 },
  { i: 'botC', x: 0, y: 10, w: 16, h: 2, minW: 6, minH: 1, maxW: 16, maxH: 4 }
]
