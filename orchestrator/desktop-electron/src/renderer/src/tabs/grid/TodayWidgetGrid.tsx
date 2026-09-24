import { GripVertical, Maximize2, Pin } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import GridLayout, { type Layout, type LayoutItem } from 'react-grid-layout/legacy'
import 'react-grid-layout/css/styles.css'
import { mergeTodayLayout, reflowTodayLayout } from './todayLayoutCompact'
import { TodayWidgetExpandContext, TodayWidgetRequestExpandContext } from './TodayWidgetExpandContext'
import {
  TODAY_GRID_COLS,
  TODAY_GRID_LAYOUT_MAX_ROWS,
  TODAY_GRID_MARGIN,
  TODAY_GRID_MAX_ROWS,
  TODAY_WIDGET_LABELS,
  computeTodayGridMetrics,
  todayGridMinCanvasHeight,
  todayLayoutExtentRows,
  type TodayWidgetId,
  useTodayWidgetLayout
} from './useTodayWidgetLayout'

const GRID_MIN_CANVAS_HEIGHT = todayGridMinCanvasHeight()

const TODAY_RESIZE_HANDLES = ['s', 'w', 'e', 'n', 'sw', 'nw', 'se', 'ne'] as const

function TodayWidgetExpandModal({
  widgetId,
  onClose,
  children
}: {
  widgetId: TodayWidgetId
  onClose: () => void
  children: React.ReactNode
}): React.JSX.Element | null {
  const title = TODAY_WIDGET_LABELS[widgetId]
  return createPortal(
    <div className="modal-overlay today-widget-expand-overlay" onClick={onClose} role="presentation">
      <div
        className="modal-card today-widget-expand-dialog"
        data-widget={widgetId}
        role="dialog"
        aria-modal="true"
        aria-labelledby="today-widget-expand-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="today-widget-expand-head">
          <h4 className="modal-title" id="today-widget-expand-title">
            {title}
          </h4>
          <button type="button" className="today-plan-detail-close" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </header>
        <div className="today-widget-expand-body">
          <TodayWidgetExpandContext.Provider value>{children}</TodayWidgetExpandContext.Provider>
        </div>
        {widgetId === 'outlook' ? null : (
          <div className="modal-actions">
            <button type="button" className="btn-light" onClick={onClose}>
              Закрыть
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}

function TodayWidgetChrome({
  id,
  editMode,
  locked,
  onToggleLock,
  onExpand
}: {
  id: TodayWidgetId
  editMode: boolean
  locked: boolean
  onToggleLock: () => void
  onExpand: () => void
}): React.JSX.Element {
  const label = TODAY_WIDGET_LABELS[id]
  return (
    <div
      className={[
        'today-widget-chrome',
        'today-widget-chrome-bar',
        editMode ? 'today-widget-chrome-bar--edit' : ''
      ]
        .filter(Boolean)
        .join(' ')}
      role="group"
      aria-label={label}
    >
      <span
        className="today-widget-drag-handle"
        aria-label={`Переместить: ${label}`}
        title="Перетащите для перемещения"
      >
        <GripVertical size={15} strokeWidth={2} aria-hidden />
      </span>
      <span className="today-widget-chrome-title">{label}</span>
      <button
        type="button"
        className="today-widget-expand-btn"
        aria-label={`Развернуть: ${label}`}
        title="Открыть в окне"
        onClick={(event) => {
          event.stopPropagation()
          onExpand()
        }}
      >
        <Maximize2 size={14} strokeWidth={2} aria-hidden />
      </button>
      {editMode ? (
        <button
          type="button"
          className={`today-widget-lock-btn${locked ? ' is-locked' : ''}`}
          aria-label={locked ? `Открепить: ${label}` : `Закрепить: ${label}`}
          aria-pressed={locked}
          title={locked ? 'Закреплено — не двигается' : 'Закрепить на месте'}
          onClick={(event) => {
            event.stopPropagation()
            onToggleLock()
          }}
        >
          <Pin size={14} strokeWidth={2} fill={locked ? 'currentColor' : 'none'} aria-hidden />
        </button>
      ) : null}
    </div>
  )
}

export function TodayWidgetGrid({
  userId,
  editMode,
  layoutWithStatic,
  fullLayout,
  locked,
  onLayoutChange,
  onToggleLock,
  onRequestEditMode,
  widgets,
  visibleWidgetIds,
  rightRail,
  kpiFocusWidgetIds
}: {
  userId: string
  editMode: boolean
  layoutWithStatic: LayoutItem[]
  fullLayout: LayoutItem[]
  locked: Partial<Record<TodayWidgetId, boolean>>
  onLayoutChange: (layout: Layout) => void
  onToggleLock: (id: TodayWidgetId) => void
  onRequestEditMode: () => void
  widgets: Record<TodayWidgetId, React.ReactNode>
  visibleWidgetIds: TodayWidgetId[]
  rightRail?: React.ReactNode
  /** Подсветка виджета после клика по KPI-плитке. */
  kpiFocusWidgetIds?: TodayWidgetId[]
}): React.JSX.Element {
  const canvasRef = useRef<HTMLDivElement>(null)
  const layoutRef = useRef(fullLayout)
  const layoutSessionRef = useRef(false)
  const layoutReadyRef = useRef(false)
  const [expandedWidgetId, setExpandedWidgetId] = useState<TodayWidgetId | null>(null)
  const [sessionLayout, setSessionLayout] = useState<LayoutItem[] | null>(null)

  const visibleLayout = useMemo(
    () => layoutWithStatic.filter((item) => visibleWidgetIds.includes(item.i as TodayWidgetId)),
    [layoutWithStatic, visibleWidgetIds]
  )
  const displayLayout = sessionLayout ?? visibleLayout

  const extentRows = useMemo(
    () => todayLayoutExtentRows(displayLayout),
    [displayLayout]
  )
  const [gridMetrics, setGridMetrics] = useState(() =>
    computeTodayGridMetrics(GRID_MIN_CANVAS_HEIGHT, 800, extentRows)
  )

  useEffect(() => {
    layoutRef.current = fullLayout
  }, [fullLayout])

  useEffect(() => {
    if (!layoutSessionRef.current) setSessionLayout(null)
  }, [visibleLayout])

  useEffect(() => {
    const node = canvasRef.current
    if (!node) return

    const measure = (): void => {
      const parentH = node.parentElement?.clientHeight ?? 0
      const selfH = node.clientHeight ?? 0
      const viewportHeight = parentH > 0 ? parentH : selfH
      const height =
        viewportHeight > 0 ? viewportHeight : Math.max(parentH, selfH, GRID_MIN_CANVAS_HEIGHT)
      const width = node.clientWidth
      const layoutRows = editMode
        ? Math.max(TODAY_GRID_MAX_ROWS, extentRows)
        : TODAY_GRID_MAX_ROWS
      setGridMetrics(computeTodayGridMetrics(height, width, layoutRows))
    }

    measure()
    const observer = new ResizeObserver(() => measure())
    observer.observe(node)
    return () => observer.disconnect()
  }, [editMode, extentRows])

  const { rowHeight, canvasHeight, containerWidth, colWidth, marginX, marginY, canvasRows } = gridMetrics
  const needsScroll = editMode

  const beginLayoutSession = useCallback(() => {
    layoutSessionRef.current = true
    if (!editMode) onRequestEditMode()
  }, [editMode, onRequestEditMode])

  const settleLayout = useCallback(
    (next: Layout, priorityIds: string[]) => {
      if (!layoutReadyRef.current) {
        layoutReadyRef.current = true
        return
      }
      layoutSessionRef.current = false
      const reflowed = reflowTodayLayout([...next], priorityIds, TODAY_GRID_COLS, locked)
      setSessionLayout(reflowed)
      onLayoutChange(mergeTodayLayout(layoutRef.current, visibleWidgetIds, reflowed))
    },
    [locked, onLayoutChange, visibleWidgetIds]
  )

  const handleVisibleLayoutChange = useCallback((next: Layout) => {
    if (!layoutReadyRef.current) {
      layoutReadyRef.current = true
      return
    }
    if (!layoutSessionRef.current) return
    setSessionLayout([...next])
  }, [])

  const canvasStyle = useMemo(
    () =>
      ({
        minHeight: editMode ? GRID_MIN_CANVAS_HEIGHT : 0,
        height: editMode ? undefined : '100%',
        maxHeight: editMode ? undefined : '100%',
        '--today-rgl-row-height': `${rowHeight}px`,
        '--today-rgl-col-width': `${colWidth}px`,
        '--today-rgl-margin-x': `${marginX}px`,
        '--today-rgl-margin-y': `${marginY}px`
      }) as React.CSSProperties,
    [colWidth, marginX, marginY, rowHeight]
  )

  const focusSet = useMemo(() => new Set(kpiFocusWidgetIds || []), [kpiFocusWidgetIds])

  const children = useMemo(() => {
    return visibleWidgetIds.map((id) => (
      <div key={id} className="today-widget-grid-item">
        <div
          className={[
            'today-widget-shell',
            editMode ? 'today-widget-shell--edit' : '',
            locked[id] ? 'today-widget-shell--locked' : '',
            focusSet.has(id) ? 'today-widget-shell--kpi-focus' : ''
          ]
            .filter(Boolean)
            .join(' ')}
          data-widget-id={id}
        >
          <TodayWidgetChrome
            id={id}
            editMode={editMode}
            locked={Boolean(locked[id])}
            onToggleLock={() => onToggleLock(id)}
            onExpand={() => setExpandedWidgetId(id)}
          />
          <div className="today-widget-content">
            <TodayWidgetRequestExpandContext.Provider value={() => setExpandedWidgetId(id)}>
              {widgets[id]}
            </TodayWidgetRequestExpandContext.Provider>
          </div>
        </div>
      </div>
    ))
  }, [editMode, focusSet, locked, onToggleLock, visibleWidgetIds, widgets])

  return (
    <>
      <div
        ref={canvasRef}
        className={[
          'today-widget-canvas',
          editMode ? 'today-widget-canvas--edit' : 'today-widget-canvas--view',
          'today-widget-grid-host',
          editMode ? 'today-widget-grid-host--edit' : '',
          needsScroll ? 'today-widget-canvas--scroll' : ''
        ]
          .filter(Boolean)
          .join(' ')}
        style={canvasStyle}
        data-user-id={userId || 'default'}
      >
        <GridLayout
          key={editMode ? 'today-grid-edit' : 'today-grid-view'}
          className="today-widget-grid"
          style={{
            height: editMode ? canvasHeight : '100%',
            minHeight: editMode ? canvasHeight : 0,
            maxHeight: editMode ? undefined : '100%'
          }}
          width={Math.max(containerWidth, 1)}
          cols={TODAY_GRID_COLS}
          maxRows={
            editMode
              ? Math.max(TODAY_GRID_LAYOUT_MAX_ROWS, canvasRows, extentRows)
              : TODAY_GRID_MAX_ROWS
          }
          rowHeight={rowHeight}
          margin={TODAY_GRID_MARGIN}
          containerPadding={[0, 0]}
          layout={displayLayout}
          onLayoutChange={handleVisibleLayoutChange}
          onDragStart={(_layout, _oldItem, newItem) => {
            beginLayoutSession()
            if (newItem?.i) setSessionLayout((current) => current ?? [...visibleLayout])
          }}
          onResizeStart={(_layout, _oldItem, newItem) => {
            beginLayoutSession()
            if (newItem?.i) setSessionLayout((current) => current ?? [...visibleLayout])
          }}
          onDragStop={(layout, _oldItem, newItem) => {
            settleLayout(layout, newItem?.i ? [newItem.i] : [])
          }}
          onResizeStop={(layout, _oldItem, newItem) => {
            settleLayout(layout, newItem?.i ? [newItem.i] : [])
          }}
          draggableHandle=".today-widget-chrome-bar--edit, .today-widget-drag-handle"
          draggableCancel=".today-widget-expand-btn, .today-widget-lock-btn"
          isDraggable={editMode}
          isResizable={editMode}
          isBounded
          compactType={null}
          preventCollision={false}
          allowOverlap={false}
          useCSSTransforms
          resizeHandles={[...TODAY_RESIZE_HANDLES]}
        >
          {children}
        </GridLayout>
        {rightRail ? <div className="today-widget-right-rail">{rightRail}</div> : null}
      </div>
      {expandedWidgetId ? (
        <TodayWidgetExpandModal widgetId={expandedWidgetId} onClose={() => setExpandedWidgetId(null)}>
          <div className="today-widget-expand-content" data-widget={expandedWidgetId}>
            {widgets[expandedWidgetId]}
          </div>
        </TodayWidgetExpandModal>
      ) : null}
    </>
  )
}

export { useTodayWidgetLayout }
