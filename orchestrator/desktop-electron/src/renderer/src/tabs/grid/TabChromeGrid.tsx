import { useEffect, useMemo, useRef, useState } from 'react'
import GridLayout, { type Layout, type LayoutItem } from 'react-grid-layout/legacy'
import 'react-grid-layout/css/styles.css'
import { SpecSummaryTiles } from '../../workplace/specV04Components'
import type { SpecSummaryTile } from '../../workplace/specV04Shell'
import {
  STANDARD_TAB_LABELS,
  TAB_CHROME_COLS,
  TAB_CHROME_MARGIN,
  TAB_CHROME_MAX_ROWS,
  tabChromeGridDimensions,
  computeTabChromeMetrics,
  TAB_CHROME_SNAP_MIN_ROW,
  isTileWidgetId,
  tileWidgetId,
  type TabChromeMeta,
  useTabChromeLayout
} from './useTabChromeLayout'
import './tabChrome.css'

const RESIZE_HANDLES = ['s', 'w', 'e', 'n', 'sw', 'nw', 'se', 'ne'] as const

function EyeIcon({ hidden }: { hidden: boolean }): React.JSX.Element {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
      {hidden ? (
        <path
          d="M4 4l16 16M9.9 9.9A3 3 0 0014 14M3 12s3.5-6 9-6c1.4 0 2.7.3 3.8.9M21 12s-1.2 2-3.2 3.7"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
      ) : (
        <>
          <path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6z" stroke="currentColor" strokeWidth="1.6" />
          <circle cx="12" cy="12" r="2.4" stroke="currentColor" strokeWidth="1.6" />
        </>
      )}
    </svg>
  )
}

export function TabChromeToolbar({
  editMode,
  onToggleEdit,
  onReset,
  basketIds,
  labels,
  onRestore
}: {
  editMode: boolean
  onToggleEdit: () => void
  onReset: () => void
  basketIds?: string[]
  labels?: Record<string, string>
  onRestore?: (id: string) => void
}): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const basket = basketIds || []
  return (
    <div className="tab-chrome-toolbar">
      {basket.length ? (
        <div className="tab-chrome-basket">
          <button
            type="button"
            className={`tab-chrome-basket-btn${open ? ' is-open' : ''}`}
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            Корзина ({basket.length})
          </button>
          {open ? (
            <ul className="tab-chrome-basket-list">
              {basket.map((id) => (
                <li key={id}>
                  <span>{labels?.[id] || id}</span>
                  <button type="button" onClick={() => onRestore?.(id)}>
                    Вернуть
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      <button
        type="button"
        className={`today-filter-layout-btn${editMode ? ' is-active' : ''}`}
        aria-pressed={editMode}
        onClick={onToggleEdit}
      >
        {editMode ? 'Готово' : 'Редактировать виджеты'}
      </button>
      {editMode ? (
        <button type="button" className="today-filter-layout-reset" onClick={onReset}>
          Сбросить раскладку
        </button>
      ) : null}
    </div>
  )
}

export function ChromeFitRoot({
  widgetId,
  className,
  baseWidth = 180,
  baseHeight = 78,
  children
}: {
  widgetId: string
  className?: string
  baseWidth?: number
  baseHeight?: number
  children: React.ReactNode
}): React.JSX.Element {
  const { ref, fit } = useChromeFit(baseWidth, baseHeight)
  return (
    <div
      ref={ref}
      className={['chrome-fit-root', className].filter(Boolean).join(' ')}
      data-widget-id={widgetId}
      style={{ ['--chrome-fit' as string]: String(fit) }}
    >
      <div className="chrome-fit-body">{children}</div>
    </div>
  )
}

function useChromeFit(baseWidth: number, baseHeight: number): {
  ref: React.RefObject<HTMLDivElement | null>
  fit: number
} {
  const ref = useRef<HTMLDivElement>(null)
  const [fit, setFit] = useState(1)
  useEffect(() => {
    const node = ref.current
    if (!node) return
    const measure = (): void => {
      const width = node.clientWidth
      const height = node.clientHeight
      if (width < 8 || height < 8) return
      const next = Math.max(
        0.42,
        Math.min(1.85, Math.min(width / baseWidth, height / baseHeight))
      )
      setFit((prev) => (Math.abs(prev - next) < 0.015 ? prev : next))
    }
    measure()
    const observer = new ResizeObserver(() => measure())
    observer.observe(node)
    return () => observer.disconnect()
  }, [baseHeight, baseWidth])
  return { ref, fit }
}

function WidgetChrome({
  id,
  label,
  editMode,
  meta,
  onToggleVisible,
  onToggleLocked,
  onSetColor,
  children
}: {
  id: string
  label: string
  editMode: boolean
  meta: TabChromeMeta
  onToggleVisible: () => void
  onToggleLocked: () => void
  onSetColor: (color: string) => void
  children: React.ReactNode
}): React.JSX.Element {
  const hidden = meta.visible === false
  const tile = id.startsWith('tile:') || id === 'tiles'
  const { ref, fit } = useChromeFit(tile ? 180 : id === 'filters' ? 720 : 360, tile ? 78 : id === 'filters' ? 40 : 180)
  return (
    <div
      ref={ref}
      className={[
        'tab-chrome-shell',
        editMode ? 'tab-chrome-shell--edit' : '',
        hidden ? 'tab-chrome-shell--hidden' : '',
        meta.locked ? 'tab-chrome-shell--locked' : ''
      ]
        .filter(Boolean)
        .join(' ')}
      style={{
        background: meta.color || 'var(--card, #fff)',
        ['--tab-chrome-color' as string]: meta.color || 'transparent',
        ['--chrome-fit' as string]: String(fit)
      }}
      data-widget-id={id}
    >
      {editMode ? (
        <div className="tab-chrome-bar tab-chrome-drag-handle" role="group" aria-label={`Переместить: ${label}`}>
          <span className="today-widget-drag-grip" aria-hidden>
            ⋮⋮
          </span>
          <span className="today-widget-chrome-title">{label}</span>
          <label className="tab-chrome-color" title="Цвет виджета">
            <input
              type="color"
              value={meta.color || '#ffffff'}
              onChange={(event) => onSetColor(event.target.value)}
              onClick={(event) => event.stopPropagation()}
            />
          </label>
          <button
            type="button"
            className="tab-chrome-color-reset"
            title="Белый / как карточка"
            onClick={(event) => {
              event.stopPropagation()
              onSetColor('')
            }}
          >
            Сброс цвета
          </button>
          <button
            type="button"
            className={`today-widget-lock-btn${hidden ? ' is-locked' : ''}`}
            aria-label={hidden ? `Показать: ${label}` : `Скрыть: ${label}`}
            onClick={(event) => {
              event.stopPropagation()
              onToggleVisible()
            }}
          >
            <EyeIcon hidden={hidden} />
          </button>
          <button
            type="button"
            className={`today-widget-lock-btn${meta.locked ? ' is-locked' : ''}`}
            aria-label={meta.locked ? `Открепить: ${label}` : `Закрепить: ${label}`}
            onClick={(event) => {
              event.stopPropagation()
              onToggleLocked()
            }}
          >
            {meta.locked ? '📌' : '📍'}
          </button>
        </div>
      ) : null}
      <div className="tab-chrome-content">{children}</div>
    </div>
  )
}

export function TabChromeGrid({
  tabId,
  userId,
  defaults,
  labels = STANDARD_TAB_LABELS,
  widgets,
  editMode,
  layoutWithStatic,
  meta,
  onLayoutChange,
  toggleVisible,
  toggleLocked,
  setColor,
  syncViewport
}: {
  tabId: string
  userId: string
  defaults: LayoutItem[]
  labels?: Record<string, string>
  widgets: Record<string, React.ReactNode>
  editMode: boolean
  layoutWithStatic: LayoutItem[]
  meta: Record<string, TabChromeMeta>
  onLayoutChange: (layout: Layout) => void
  toggleVisible: (id: string) => void
  toggleLocked: (id: string) => void
  setColor: (id: string, color: string) => void
  syncViewport?: (height: number, width: number) => void
}): React.JSX.Element {
  const canvasRef = useRef<HTMLDivElement>(null)
  const { cols: gridCols, maxRows: gridMaxRows } = tabChromeGridDimensions(tabId)
  const layoutRows = Math.max(1, ...layoutWithStatic.map((item) => item.y + item.h), 1)
  const usedRows = tabId === 'kpi' ? gridMaxRows : Math.min(gridMaxRows, layoutRows)
  const snapGrid = tabId === 'kpi'
  const metricsOptions = useMemo(
    () =>
      snapGrid
        ? {
            cols: gridCols,
            fillHeight: true as const,
            minRowHeight: TAB_CHROME_SNAP_MIN_ROW
          }
        : undefined,
    [gridCols, snapGrid]
  )
  const [metrics, setMetrics] = useState(() =>
    computeTabChromeMetrics(320, 800, usedRows, metricsOptions)
  )

  useEffect(() => {
    const node = canvasRef.current
    if (!node) return
    const measure = (): void => {
      const height = Math.max(node.clientHeight, 200)
      const width = node.clientWidth
      const next = computeTabChromeMetrics(height, width, usedRows, metricsOptions)
      setMetrics((prev) =>
        prev.rowHeight === next.rowHeight &&
        prev.canvasHeight === next.canvasHeight &&
        prev.containerWidth === next.containerWidth &&
        prev.colWidth === next.colWidth
          ? prev
          : next
      )
      syncViewport?.(height, width)
    }
    measure()
    const observer = new ResizeObserver(() => measure())
    observer.observe(node)
    return () => observer.disconnect()
  }, [syncViewport, usedRows, metricsOptions])

  const canvasStyle = useMemo(
    () =>
      snapGrid
        ? ({
            height: '100%',
            minHeight: 0,
            '--kpi-rgl-row-height': `${metrics.rowHeight}px`,
            '--kpi-rgl-col-width': `${metrics.colWidth}px`,
            '--kpi-rgl-margin-x': `${metrics.marginX}px`,
            '--kpi-rgl-margin-y': `${metrics.marginY}px`
          } as React.CSSProperties)
        : undefined,
    [metrics.colWidth, metrics.marginX, metrics.marginY, metrics.rowHeight, snapGrid]
  )

  const gridLayoutStyle = useMemo(
    () =>
      snapGrid
        ? { height: metrics.canvasHeight, minHeight: metrics.canvasHeight }
        : undefined,
    [metrics.canvasHeight, snapGrid]
  )

  const ids = useMemo(() => defaults.map((item) => item.i), [defaults])
  const children = useMemo(
    () =>
      ids
        .filter((id) => {
          if (meta[id]?.visible === false && !editMode) return false
          if (meta[id]?.binned && !editMode) return false
          return true
        })
        .map((id) => (
          <div key={id} className="tab-chrome-grid-item">
            <WidgetChrome
              id={id}
              label={labels[id] || id}
              editMode={editMode}
              meta={meta[id] || { visible: true, color: '', locked: false }}
              onToggleVisible={() => toggleVisible(id)}
              onToggleLocked={() => toggleLocked(id)}
              onSetColor={(color) => setColor(id, color)}
            >
              {widgets[id]}
            </WidgetChrome>
          </div>
        )),
    [editMode, ids, labels, meta, setColor, toggleLocked, toggleVisible, widgets]
  )

  return (
    <div
      ref={canvasRef}
      className={[
        'tab-chrome-canvas',
        snapGrid ? 'tab-chrome-canvas--snap' : '',
        editMode ? 'tab-chrome-canvas--edit' : 'tab-chrome-canvas--view'
      ]
        .filter(Boolean)
        .join(' ')}
      style={canvasStyle}
      data-tab={tabId}
      data-grid-cols={gridCols}
      data-grid-rows={gridMaxRows}
      data-user-id={userId || 'default'}
    >
      <GridLayout
        className="tab-chrome-grid"
        style={gridLayoutStyle}
        width={Math.max(metrics.containerWidth, 1)}
        cols={gridCols}
        maxRows={gridMaxRows}
        rowHeight={metrics.rowHeight}
        margin={TAB_CHROME_MARGIN}
        containerPadding={[0, 0]}
        layout={layoutWithStatic}
        onLayoutChange={onLayoutChange}
        draggableHandle=".tab-chrome-drag-handle"
        draggableCancel=".today-widget-lock-btn, .tab-chrome-color, .tab-chrome-color-reset"
        isDraggable={editMode}
        isResizable={editMode}
        isBounded
        compactType={null}
        preventCollision
        allowOverlap={false}
        useCSSTransforms
        resizeHandles={[...RESIZE_HANDLES]}
      >
        {children}
      </GridLayout>
    </div>
  )
}

export type ChromeTileSpec = {
  id: string
  label: string
  node: React.ReactNode
}

export function summaryTilesAsChrome(
  tiles: SpecSummaryTile[],
  activeId?: string | string[] | null,
  onSelect?: (id: string) => void
): ChromeTileSpec[] {
  return tiles.map((tile) => ({
    id: tile.id,
    label: tile.label,
    node: (
      <SpecSummaryTiles
        tiles={[tile]}
        activeId={activeId}
        onSelect={onSelect}
        className="spec-v04-tile-solo"
      />
    )
  }))
}

export function StandardTabChrome({
  tabId,
  userId,
  defaults,
  labels,
  widgets,
  chromeTiles
}: {
  tabId: string
  userId: string
  defaults: LayoutItem[]
  labels?: Record<string, string>
  widgets: Record<string, React.ReactNode>
  chromeTiles?: ChromeTileSpec[]
}): React.JSX.Element {
  const layoutDefaults = useMemo(
    () => defaults.filter((item) => item.i !== 'tiles' && item.i !== 'filters' && !isTileWidgetId(item.i)),
    [defaults]
  )
  const chrome = useTabChromeLayout(tabId, userId, layoutDefaults)
  const filterNode = widgets.filters
  const mergedLabels = useMemo(() => {
    const next = { ...STANDARD_TAB_LABELS, ...labels }
    for (const tile of chromeTiles || []) {
      next[tileWidgetId(tile.id)] = tile.label
    }
    return next
  }, [chromeTiles, labels])
  const widgetsWithToolbar = {
    ...widgets,
    tiles: undefined,
    filters: undefined
  }
  return (
    <div className="orch-slot-tab-canvas">
      {chromeTiles?.length || widgets.tiles ? (
        <div className="tab-chrome-tiles-bar">
          {chromeTiles?.length
            ? chromeTiles.map((tile) => (
                <ChromeFitRoot
                  key={tile.id}
                  widgetId={tileWidgetId(tile.id)}
                  className="tab-chrome-shell tab-chrome-tile-fixed"
                >
                  {tile.node}
                </ChromeFitRoot>
              ))
            : widgets.tiles}
        </div>
      ) : null}
      <div className="tab-chrome-filters-bar">
        <div className="tab-chrome-filters-wrap">
          {filterNode}
          <TabChromeToolbar
            editMode={chrome.editMode}
            onToggleEdit={() => chrome.setEditMode((value) => !value)}
            onReset={chrome.resetLayout}
            basketIds={chrome.basketIds}
            labels={mergedLabels}
            onRestore={chrome.restoreFromBasket}
          />
        </div>
      </div>
      <TabChromeGrid
        tabId={tabId}
        userId={userId}
        defaults={layoutDefaults}
        labels={mergedLabels}
        widgets={widgetsWithToolbar}
        editMode={chrome.editMode}
        layoutWithStatic={chrome.layoutWithStatic}
        meta={chrome.meta}
        onLayoutChange={chrome.onLayoutChange}
        toggleVisible={chrome.toggleVisible}
        toggleLocked={chrome.toggleLocked}
        setColor={chrome.setColor}
        syncViewport={chrome.syncViewport}
      />
    </div>
  )
}
