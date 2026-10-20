import type { LayoutItem } from 'react-grid-layout/legacy'

export const TAB_CHROME_COLS = 16
export const TAB_CHROME_MAX_ROWS = 12
/** KPI body widgets — same 8×6 snap as вкладка «Сегодня». */
export const KPI_TAB_GRID_COLS = 8
export const KPI_TAB_GRID_ROWS = 6
/** Реестр поручений: рабочее поле 8×6 (col×row). */
export const REGISTRY_TAB_GRID_COLS = 8
export const REGISTRY_TAB_GRID_ROWS = 6
/** Библиотека агентов: 8×8, низ 2×8 — «Мои агенты». */
export const AGENT_LIBRARY_TAB_GRID_COLS = 8
export const AGENT_LIBRARY_TAB_GRID_ROWS = 8

export function tabChromeGridDimensions(tabId: string): { cols: number; maxRows: number } {
  if (tabId === 'kpi') return { cols: KPI_TAB_GRID_COLS, maxRows: KPI_TAB_GRID_ROWS }
  if (tabId === 'assignments_registry') return { cols: REGISTRY_TAB_GRID_COLS, maxRows: REGISTRY_TAB_GRID_ROWS }
  if (tabId === 'agent_library') return { cols: AGENT_LIBRARY_TAB_GRID_COLS, maxRows: AGENT_LIBRARY_TAB_GRID_ROWS }
  return { cols: TAB_CHROME_COLS, maxRows: TAB_CHROME_MAX_ROWS }
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

/** 8×8: каталог 8×6, добавленные 8×2. */
export const DEFAULT_AGENT_LIBRARY_LAYOUT: LayoutItem[] = [
  {
    i: 'main',
    x: 0,
    y: 0,
    w: AGENT_LIBRARY_TAB_GRID_COLS,
    h: 6,
    minW: 4,
    minH: 3,
    maxW: AGENT_LIBRARY_TAB_GRID_COLS,
    maxH: AGENT_LIBRARY_TAB_GRID_ROWS
  },
  {
    i: 'botA',
    x: 0,
    y: 6,
    w: AGENT_LIBRARY_TAB_GRID_COLS,
    h: 2,
    minW: 4,
    minH: 2,
    maxW: AGENT_LIBRARY_TAB_GRID_COLS,
    maxH: 4
  }
]

/** 8×6: таблица 6×6, карточка поручения 2×6. */
export const DEFAULT_ASSIGNMENTS_REGISTRY_LAYOUT: LayoutItem[] = [
  {
    i: 'main',
    x: 0,
    y: 0,
    w: 6,
    h: 6,
    minW: 4,
    minH: 4,
    maxW: REGISTRY_TAB_GRID_COLS,
    maxH: REGISTRY_TAB_GRID_ROWS
  },
  {
    i: 'side',
    x: 6,
    y: 0,
    w: 2,
    h: 6,
    minW: 2,
    minH: 4,
    maxW: REGISTRY_TAB_GRID_COLS,
    maxH: REGISTRY_TAB_GRID_ROWS
  }
]

export const DEFAULT_PROCESS_LAYOUT: LayoutItem[] = [
  { i: 'main', x: 0, y: 0, w: 12, h: 7, minW: 6, minH: 3, maxW: 16, maxH: 12 },
  { i: 'side', x: 12, y: 0, w: 4, h: 7, minW: 4, minH: 3, maxW: 16, maxH: 12 },
  { i: 'botA', x: 0, y: 7, w: 8, h: 5, minW: 4, minH: 2, maxW: 16, maxH: 6 },
  { i: 'botB', x: 8, y: 7, w: 8, h: 5, minW: 4, minH: 2, maxW: 16, maxH: 6 }
]

/** KPI: таблица на всю ширину под двумя фиксированными рядами плиток. */
export const DEFAULT_KPI_LAYOUT: LayoutItem[] = [
  { i: 'main', x: 0, y: 0, w: 8, h: 6, minW: 4, minH: 2, maxW: KPI_TAB_GRID_COLS, maxH: KPI_TAB_GRID_ROWS }
]

export const DEFAULT_DECISIONS_LAYOUT: LayoutItem[] = [
  { i: 'main', x: 0, y: 0, w: 12, h: 10, minW: 6, minH: 4, maxW: 16, maxH: 12 },
  { i: 'side', x: 12, y: 0, w: 4, h: 10, minW: 4, minH: 4, maxW: 16, maxH: 12 },
  { i: 'botC', x: 0, y: 10, w: 16, h: 2, minW: 6, minH: 1, maxW: 16, maxH: 4 }
]
