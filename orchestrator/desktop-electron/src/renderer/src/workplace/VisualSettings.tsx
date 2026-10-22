import { Pin, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { LayoutItem } from 'react-grid-layout/legacy'
import type { UserProfile } from '../api/types'
import { isIlchenkoAccount } from './boardReportReadiness'
import {
  readTodayTileOrder,
  readTodayTileVisibility,
  readTodayWidgetVisibility,
  TODAY_TILE_LABELS,
  TODAY_WIDGET_IDS,
  TODAY_WIDGET_LABELS,
  type TodayTileId,
  type TodayWidgetId,
  writeTodayTileOrder,
  writeTodayTileVisibility,
  writeTodayWidgetVisibility
} from '../tabs/grid/todayWidgetSettings'
import { reflowTodayLayout } from '../tabs/grid/todayLayoutCompact'
import {
  DEFAULT_TODAY_WIDGET_LAYOUT,
  readTodayWidgetLayoutSettings,
  readTodayWidgetLockSettings,
  writeTodayWidgetLayoutSettings,
  writeTodayWidgetLockSettings
} from '../tabs/grid/useTodayWidgetLayout'
import { tabChromeGridDimensions } from '../tabs/grid/tabLayouts'
import {
  readVisualDraft,
  VISUAL_CHANGED_EVENT,
  VISUAL_TABS,
  VISUAL_TAB_TILES,
  visualWidgetLabel,
  writeVisualDraft,
  type VisualDraft,
  type VisualTab
} from '../tabs/grid/visualTabs'

type VisualDrafts = Record<string, VisualDraft>

function cloneDrafts(userId: string): VisualDrafts {
  return Object.fromEntries(VISUAL_TABS.map((tab) => [tab.id, readVisualDraft(tab, userId)]))
}

function draftChanged(left: VisualDraft, right: VisualDraft): boolean {
  return JSON.stringify(left) !== JSON.stringify(right)
}

/** Перенесённый и закреплённые остаются, остальные видимые занимают свободные клетки сверху-слева. */
function reflowAfterMove(
  layout: LayoutItem[],
  visible: (item: LayoutItem) => boolean,
  movedId: string,
  isLocked: (id: string) => boolean,
  cols: number,
  maxRows: number
): LayoutItem[] {
  const shown = layout.filter(visible)
  const locked: Partial<Record<TodayWidgetId, boolean>> = {}
  for (const item of shown) {
    if (isLocked(item.i)) locked[item.i as TodayWidgetId] = true
  }
  const packed = reflowTodayLayout(shown, [movedId], cols, locked, maxRows)
  const byId = new Map(packed.map((item) => [item.i, item]))
  return layout.map((item) => byId.get(item.i) ?? item)
}

export function VisualSettings({ user }: { user: UserProfile }): React.JSX.Element {
  const [tabId, setTabId] = useState(VISUAL_TABS[0].id)
  const [saved, setSaved] = useState<VisualDrafts>(() => cloneDrafts(user.id))
  const [drafts, setDrafts] = useState<VisualDrafts>(() => cloneDrafts(user.id))
  const [widgetVisibility, setWidgetVisibility] = useState(() => readTodayWidgetVisibility(user.id))
  const [widgetDraft, setWidgetDraft] = useState(() => readTodayWidgetVisibility(user.id))
  const [tileVisibility, setTileVisibility] = useState(() => readTodayTileVisibility(user.id))
  const [tileDraft, setTileDraft] = useState(() => readTodayTileVisibility(user.id))
  const [tileOrder, setTileOrder] = useState(() => readTodayTileOrder(user.id))
  const [tileOrderDraft, setTileOrderDraft] = useState(() => readTodayTileOrder(user.id))
  const [todayLayout, setTodayLayout] = useState(() => readTodayWidgetLayoutSettings(user.id))
  const [todayLayoutSaved, setTodayLayoutSaved] = useState(() => readTodayWidgetLayoutSettings(user.id))
  const [todayLocked, setTodayLocked] = useState(() => readTodayWidgetLockSettings(user.id))
  const [todayLockedSaved, setTodayLockedSaved] = useState(() => readTodayWidgetLockSettings(user.id))
  const [note, setNote] = useState('')

  useEffect(() => {
    const next = cloneDrafts(user.id)
    setSaved(next)
    setDrafts(next)
    const widgets = readTodayWidgetVisibility(user.id)
    setWidgetVisibility(widgets)
    setWidgetDraft(widgets)
    const tiles = readTodayTileVisibility(user.id)
    setTileVisibility(tiles)
    setTileDraft(tiles)
    const order = readTodayTileOrder(user.id)
    setTileOrder(order)
    setTileOrderDraft(order)
    const layout = readTodayWidgetLayoutSettings(user.id)
    setTodayLayout(layout)
    setTodayLayoutSaved(layout)
    const locked = readTodayWidgetLockSettings(user.id)
    setTodayLocked(locked)
    setTodayLockedSaved(locked)
  }, [user.id])

  useEffect(() => {
    if (!note) return
    const timer = window.setTimeout(() => setNote(''), 2500)
    return () => window.clearTimeout(timer)
  }, [note])

  const tab = VISUAL_TABS.find((item) => item.id === tabId) || VISUAL_TABS[0]
  const draft = drafts[tab.id]

  const dirty = useMemo(() => {
    const tabsDirty = VISUAL_TABS.some((item) => draftChanged(drafts[item.id], saved[item.id]))
    return (
      tabsDirty ||
      JSON.stringify(widgetDraft) !== JSON.stringify(widgetVisibility) ||
      JSON.stringify(tileDraft) !== JSON.stringify(tileVisibility) ||
      JSON.stringify(tileOrderDraft) !== JSON.stringify(tileOrder) ||
      JSON.stringify(todayLayout) !== JSON.stringify(todayLayoutSaved) ||
      JSON.stringify(todayLocked) !== JSON.stringify(todayLockedSaved)
    )
  }, [
    drafts,
    saved,
    widgetDraft,
    widgetVisibility,
    tileDraft,
    tileVisibility,
    tileOrderDraft,
    tileOrder,
    todayLayout,
    todayLayoutSaved,
    todayLocked,
    todayLockedSaved
  ])

  function patchDraft(tabKey: string, next: VisualDraft): void {
    setDrafts((prev) => ({ ...prev, [tabKey]: next }))
  }

  function placeWidget(id: string, x: number, y: number, w?: number, h?: number): void {
    if (!draft || draft.meta[id]?.locked) return
    const { cols, maxRows } = tabChromeGridDimensions(tab.id)
    const moved = draft.layout.map((item) => {
      if (item.i !== id) return item
      const nextW = Math.max(item.minW ?? 1, Math.min(item.maxW ?? cols, w ?? item.w))
      const nextH = Math.max(item.minH ?? 1, Math.min(item.maxH ?? maxRows, h ?? item.h))
      return {
        ...item,
        w: nextW,
        h: nextH,
        x: Math.max(0, Math.min(cols - nextW, x)),
        y: Math.max(0, Math.min(maxRows - nextH, y))
      }
    })
    const resizing = w !== undefined || h !== undefined
    const layout = resizing
      ? moved
      : reflowAfterMove(
          moved,
          (item) => draft.meta[item.i]?.visible !== false,
          id,
          (widgetId) => Boolean(draft.meta[widgetId]?.locked),
          cols,
          maxRows
        )
    patchDraft(tab.id, { ...draft, layout })
  }

  function toggleWidget(id: string): void {
    const current = draft.meta[id]
    patchDraft(tab.id, {
      ...draft,
      meta: { ...draft.meta, [id]: { ...current, visible: current?.visible === false, binned: false } }
    })
  }

  function toggleLock(id: string): void {
    const current = draft.meta[id]
    patchDraft(tab.id, {
      ...draft,
      meta: { ...draft.meta, [id]: { ...current, locked: !current?.locked } }
    })
  }

  function placeToday(id: string, x: number, y: number, w?: number, h?: number): void {
    if (todayLocked[id as TodayWidgetId]) return
    const { cols, maxRows } = tabChromeGridDimensions('today')
    setTodayLayout((current) => {
      const moved = current.map((item) => {
        if (item.i !== id) return item
        const nextW = Math.max(item.minW ?? 1, Math.min(item.maxW ?? cols, w ?? item.w))
        const nextH = Math.max(item.minH ?? 1, Math.min(item.maxH ?? maxRows, h ?? item.h))
        return {
          ...item,
          w: nextW,
          h: nextH,
          x: Math.max(0, Math.min(cols - nextW, x)),
          y: Math.max(0, Math.min(maxRows - nextH, y))
        }
      })
      if (w !== undefined || h !== undefined) return moved
      return reflowAfterMove(
        moved,
        (item) => widgetDraft[item.i as TodayWidgetId] !== false,
        id,
        (widgetId) => Boolean(todayLocked[widgetId as TodayWidgetId]),
        cols,
        maxRows
      )
    })
  }

  function toggleTodayLock(id: TodayWidgetId): void {
    setTodayLocked((current) => {
      const next = { ...current, [id]: !current[id] }
      if (!next[id]) delete next[id]
      return next
    })
  }

  function resetTab(): void {
    if (tabId === 'today') {
      setTodayLayout(DEFAULT_TODAY_WIDGET_LAYOUT.map((item) => ({ ...item })))
      setTodayLocked({})
      return
    }
    patchDraft(tab.id, {
      layout: tab.defaults.map((item) => ({ ...item })),
      meta: Object.fromEntries(
        tab.defaults.map((item) => [item.i, { visible: true, color: '', locked: false, binned: false }])
      )
    })
  }

  function save(): void {
    const nextSaved: VisualDrafts = {}
    for (const item of VISUAL_TABS) {
      const value = drafts[item.id]
      if (draftChanged(value, saved[item.id])) writeVisualDraft(item, user.id, value)
      nextSaved[item.id] = value
    }
    setSaved(nextSaved)
    writeTodayWidgetLayoutSettings(user.id, todayLayout)
    setTodayLayoutSaved(todayLayout.map((item) => ({ ...item })))
    writeTodayWidgetLockSettings(user.id, todayLocked)
    setTodayLockedSaved({ ...todayLocked })
    writeTodayWidgetVisibility(user.id, widgetDraft)
    setWidgetVisibility(widgetDraft)
    writeTodayTileVisibility(user.id, tileDraft)
    setTileVisibility(tileDraft)
    writeTodayTileOrder(user.id, tileOrderDraft)
    setTileOrder(tileOrderDraft)
    window.dispatchEvent(new CustomEvent(VISUAL_CHANGED_EVENT))
    setNote('Внешний вид сохранён')
  }

  const ordered = [...(draft?.layout ?? [])].sort((left, right) => left.y - right.y || left.x - right.x)
  const showAssignments = isIlchenkoAccount(user)

  return (
    <div className="set-body set-body-visual">
      <header className="set-head">
        <div>
          <h1 className="page-title">Визуал</h1>
          <p className="set-sub">Превью вкладок без данных: видимость, порядок, размер и закрепление виджетов</p>
        </div>
        <div className="wp-actions">
          <button className="btn-primary" type="button" onClick={save} disabled={!dirty}>
            Сохранить
          </button>
          <button className="btn-ghost" type="button" onClick={resetTab}>
            Сбросить вкладку
          </button>
        </div>
      </header>
      {note ? <div className="set-toast">{note}</div> : null}

      <div className="set-visual-tabs" role="tablist" aria-label="Вкладки">
        {VISUAL_TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={item.id === tab.id}
            className={item.id === tab.id ? 'is-active' : ''}
            onClick={() => setTabId(item.id)}
          >
            {item.label}
          </button>
        ))}
        <button
          type="button"
          role="tab"
          aria-selected={tabId === 'today'}
          className={tabId === 'today' ? 'is-active' : ''}
          onClick={() => setTabId('today')}
        >
          Сегодня
        </button>
      </div>

      {tabId === 'today' ? (
        <TodayVisual
          layout={todayLayout}
          locked={todayLocked}
          widgetDraft={widgetDraft}
          tileDraft={tileDraft}
          tileOrderDraft={tileOrderDraft}
          showAssignments={showAssignments}
          onMove={placeToday}
          onToggleLock={toggleTodayLock}
          onToggleWidget={(id) => setWidgetDraft((prev) => ({ ...prev, [id]: prev[id] === false }))}
          onToggleTile={(id) => setTileDraft((prev) => ({ ...prev, [id]: prev[id] === false }))}
          onReorderTiles={(from, to) =>
            setTileOrderDraft((current) => {
              const next = [...current]
              const [moved] = next.splice(from, 1)
              next.splice(to, 0, moved)
              return next
            })
          }
        />
      ) : (
        <section className="set-card set-visual-card set-visual-fill">
          <h2>{tab.label}</h2>
          <p className="set-muted">
            Сетка как на вкладке. После переноса незакреплённые виджеты занимают свободные клетки. Булавка
            фиксирует блок на месте.
          </p>
          <TabPreview
            tab={tab}
            draft={draft}
            onMove={placeWidget}
            onHide={toggleWidget}
            onToggleLock={toggleLock}
            tileRow={visualTileRow(VISUAL_TAB_TILES[tab.id])}
          />
          <InactiveTray
            label="Выключенные виджеты"
            items={ordered
              .filter((item) => draft.meta[item.i]?.visible === false)
              .map((item) => ({ id: item.i, label: visualWidgetLabel(tab, item.i) }))}
            onEnable={toggleWidget}
          />
        </section>
      )}
    </div>
  )
}

type DragState = {
  id: string
  mode: 'move' | 'resize'
  x: number
  y: number
  w: number
  h: number
  pointerX: number
  pointerY: number
}

function visualTileRow(labels: string[] | undefined): React.ReactNode | false {
  if (!labels?.length) return false
  return labels.map((label) => <span key={label}>{label}</span>)
}

const TODAY_VISUAL_TAB: VisualTab = {
  id: 'today',
  label: 'Сегодня',
  defaults: DEFAULT_TODAY_WIDGET_LAYOUT,
  labels: { ...TODAY_WIDGET_LABELS }
}

function TabPreview({
  tab,
  draft,
  onMove,
  onHide,
  onToggleLock,
  tileRow
}: {
  tab: VisualTab
  draft: VisualDraft
  onMove: (id: string, x: number, y: number, w?: number, h?: number) => void
  onHide: (id: string) => void
  onToggleLock: (id: string) => void
  /** false — у вкладки нет полосы плиток, заглушки не рисуем. */
  tileRow?: React.ReactNode | false
}): React.JSX.Element {
  const boardRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<DragState | null>(null)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [hiddenPlaceholders, setHiddenPlaceholders] = useState<number[]>([])
  const { cols, maxRows } = tabChromeGridDimensions(tab.id)
  const visible = draft.layout.filter((item) => draft.meta[item.i]?.visible !== false)

  function cellSize(): { cellW: number; cellH: number } | null {
    const board = boardRef.current
    if (!board) return null
    const style = getComputedStyle(board)
    const padX = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight)
    const padY = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom)
    const cellW = (board.clientWidth - padX) / cols
    const cellH = (board.clientHeight - padY) / maxRows
    if (cellW < 1 || cellH < 1) return null
    return { cellW, cellH }
  }

  function startDrag(event: React.PointerEvent<HTMLElement>, item: LayoutItem, mode: 'move' | 'resize'): void {
    setActiveId(item.i)
    if (draft.meta[item.i]?.locked) return
    event.stopPropagation()
    dragRef.current = {
      id: item.i,
      mode,
      x: item.x,
      y: item.y,
      w: item.w,
      h: item.h,
      pointerX: event.clientX,
      pointerY: event.clientY
    }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function moveDrag(event: React.PointerEvent<HTMLElement>): void {
    const drag = dragRef.current
    const size = cellSize()
    if (!drag || !size) return
    const item = draft.layout.find((row) => row.i === drag.id)
    if (!item) return
    const dx = Math.round((event.clientX - drag.pointerX) / size.cellW)
    const dy = Math.round((event.clientY - drag.pointerY) / size.cellH)
    if (drag.mode === 'resize') {
      const w = Math.max(item.minW ?? 1, Math.min(item.maxW ?? cols, drag.w + dx, cols - drag.x))
      const h = Math.max(item.minH ?? 1, Math.min(item.maxH ?? maxRows, drag.h + dy, maxRows - drag.y))
      if (w !== item.w || h !== item.h) onMove(item.i, drag.x, drag.y, w, h)
      return
    }
    const x = Math.max(0, Math.min(cols - item.w, drag.x + dx))
    const y = Math.max(0, Math.min(maxRows - item.h, drag.y + dy))
    if (x !== item.x || y !== item.y) onMove(item.i, x, y)
  }

  function endDrag(event: React.PointerEvent<HTMLElement>): void {
    dragRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  return (
    <div className="set-visual-stage">
      {tileRow === false ? null : (
      <div className="set-visual-tiles" aria-hidden={tileRow ? undefined : true}>
        {tileRow ??
          Array.from({ length: cols }, (_, index) => (
            <span key={index} className={hiddenPlaceholders.includes(index) ? 'is-empty' : ''}>
              {hiddenPlaceholders.includes(index) ? null : (
                <>
                  <button
                    type="button"
                    className="set-visual-tile-trash"
                    aria-label="Убрать плитку"
                    title="Убрать плитку"
                    onClick={() => setHiddenPlaceholders((current) => [...current, index])}
                  >
                    <Trash2 size={12} strokeWidth={2} aria-hidden />
                  </button>
                  Плитка
                </>
              )}
            </span>
          ))}
      </div>
      )}
      <div className="set-visual-filters" aria-hidden>
        <span>Фильтры</span>
        <span>Период</span>
        <span>Поиск</span>
      </div>
      <div
        ref={boardRef}
        className="set-visual-preview"
        onPointerDown={(event) => {
          if (event.target === event.currentTarget) setActiveId(null)
        }}
        style={{
          gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
          gridTemplateRows: `repeat(${maxRows}, minmax(0, 1fr))`,
          ['--visual-cols' as string]: String(cols),
          ['--visual-rows' as string]: String(maxRows)
        }}
      >
        {visible.map((item) => {
          const locked = Boolean(draft.meta[item.i]?.locked)
          const active = item.i === activeId
          return (
            <div
              key={item.i}
              className={active ? 'set-visual-block is-editing' : 'set-visual-block'}
              style={blockStyle(item, draft.meta[item.i]?.color || '')}
              title={`${visualWidgetLabel(tab, item.i)} · ${item.w}×${item.h}, минимум ${item.minW ?? 1}×${item.minH ?? 1}`}
              onPointerDown={(event) => startDrag(event, item, 'move')}
              onPointerMove={moveDrag}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
            >
              {active || locked ? (
                <button
                  type="button"
                  className={locked ? 'set-visual-pin is-locked' : 'set-visual-pin'}
                  aria-label={locked ? `Открепить: ${visualWidgetLabel(tab, item.i)}` : `Закрепить: ${visualWidgetLabel(tab, item.i)}`}
                  aria-pressed={locked}
                  title={locked ? 'Закреплено — не двигается' : 'Закрепить на месте'}
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={(event) => {
                    event.stopPropagation()
                    onToggleLock(item.i)
                  }}
                >
                  <Pin size={14} strokeWidth={2} fill={locked ? 'currentColor' : 'none'} aria-hidden />
                </button>
              ) : null}
              {active ? (
                <button
                  type="button"
                  className="set-visual-trash"
                  aria-label={`Убрать с отображения: ${visualWidgetLabel(tab, item.i)}`}
                  title="Убрать с отображения"
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={(event) => {
                    event.stopPropagation()
                    setActiveId(null)
                    onHide(item.i)
                  }}
                >
                  <Trash2 size={14} strokeWidth={2} aria-hidden />
                </button>
              ) : null}
              <strong>{visualWidgetLabel(tab, item.i)}</strong>
              <em>
                {item.w}×{item.h} · мин {item.minW ?? 1}×{item.minH ?? 1}
              </em>
              <span
                className="set-visual-resize"
                role="separator"
                aria-label="Изменить размер"
                onPointerDown={(event) => startDrag(event, item, 'resize')}
              />
            </div>
          )
        })}
      </div>
    </div>
  )
}

function InactiveTray({
  label,
  items,
  onEnable
}: {
  label: string
  items: { id: string; label: string; enable?: () => void }[]
  onEnable?: (id: string) => void
}): React.JSX.Element {
  return (
    <div className="set-visual-inactive">
      <span className="set-visual-inactive-label">{label}</span>
      {items.length ? (
        <div className="set-visual-presence" role="group" aria-label={label}>
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              className="today-filter-layout-btn"
              onClick={() => (item.enable ? item.enable() : onEnable?.(item.id))}
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : (
        <p className="set-muted">Все включены</p>
      )}
    </div>
  )
}

function blockStyle(item: LayoutItem, color: string): React.CSSProperties {
  return {
    gridColumn: `${item.x + 1} / span ${item.w}`,
    gridRow: `${item.y + 1} / span ${item.h}`,
    background: color || undefined
  }
}

function TodayVisual({
  layout,
  locked,
  widgetDraft,
  tileDraft,
  tileOrderDraft,
  showAssignments,
  onMove,
  onToggleLock,
  onToggleWidget,
  onToggleTile,
  onReorderTiles
}: {
  layout: LayoutItem[]
  locked: Partial<Record<TodayWidgetId, boolean>>
  widgetDraft: Record<TodayWidgetId, boolean>
  tileDraft: Record<TodayTileId, boolean>
  tileOrderDraft: TodayTileId[]
  showAssignments: boolean
  onMove: (id: string, x: number, y: number, w?: number, h?: number) => void
  onToggleLock: (id: TodayWidgetId) => void
  onToggleWidget: (id: TodayWidgetId) => void
  onToggleTile: (id: TodayTileId) => void
  onReorderTiles: (from: number, to: number) => void
}): React.JSX.Element {
  const tiles = tileOrderDraft.filter((id) => id !== 'assignments' || showAssignments)
  const tileDrag = useRef<number | null>(null)
  const draft: VisualDraft = {
    layout,
    meta: Object.fromEntries(
      TODAY_WIDGET_IDS.map((id) => [
        id,
        { visible: widgetDraft[id] !== false, color: '', locked: Boolean(locked[id]), binned: false }
      ])
    )
  }
  return (
    <section className="set-card set-visual-card set-visual-fill">
      <h2>Сегодня</h2>
      <p className="set-muted">
        Та же сетка 16×12. После переноса незакреплённые виджеты сами занимают свободные клетки.
      </p>
      <TabPreview
        tab={TODAY_VISUAL_TAB}
        draft={draft}
        onMove={onMove}
        onHide={(id) => onToggleWidget(id as TodayWidgetId)}
        onToggleLock={(id) => onToggleLock(id as TodayWidgetId)}
        tileRow={tiles.map((id, index) =>
          tileDraft[id] === false ? null : (
            <span
              key={id}
              draggable
              onDragStart={() => {
                tileDrag.current = index
              }}
              onDragOver={(event) => event.preventDefault()}
              onDrop={() => {
                const from = tileDrag.current
                tileDrag.current = null
                if (from === null || from === index) return
                onReorderTiles(from, index)
              }}
            >
              <button
                type="button"
                className="set-visual-tile-trash"
                draggable={false}
                aria-label={`Убрать плитку: ${TODAY_TILE_LABELS[id]}`}
                title="Убрать с отображения"
                onPointerDown={(event) => event.stopPropagation()}
                onClick={(event) => {
                  event.stopPropagation()
                  event.preventDefault()
                  onToggleTile(id)
                }}
              >
                <Trash2 size={12} strokeWidth={2} aria-hidden />
              </button>
              {TODAY_TILE_LABELS[id]}
            </span>
          )
        )}
      />
      <InactiveTray
        label="Выключенные плитки и виджеты"
        items={[
          ...tiles
            .filter((id) => tileDraft[id] === false)
            .map((id) => ({ id, label: TODAY_TILE_LABELS[id], enable: () => onToggleTile(id) })),
          ...TODAY_WIDGET_IDS.filter((id) => widgetDraft[id] === false).map((id) => ({
            id,
            label: TODAY_WIDGET_LABELS[id],
            enable: () => onToggleWidget(id)
          }))
        ]}
      />
    </section>
  )
}
