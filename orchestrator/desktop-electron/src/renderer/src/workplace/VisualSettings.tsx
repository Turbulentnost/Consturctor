import { useEffect, useMemo, useState } from 'react'
import type { LayoutItem } from 'react-grid-layout/legacy'
import type { UserProfile } from '../api/types'
import { isIlchenkoAccount } from './boardReportReadiness'
import {
  defaultTodayTileVisibility,
  defaultTodayWidgetVisibility,
  readTodayTileOrder,
  readTodayTileVisibility,
  readTodayWidgetVisibility,
  TODAY_TILE_IDS,
  TODAY_TILE_LABELS,
  TODAY_WIDGET_IDS,
  TODAY_WIDGET_LABELS,
  type TodayTileId,
  type TodayWidgetId,
  writeTodayTileOrder,
  writeTodayTileVisibility,
  writeTodayWidgetVisibility
} from '../tabs/grid/todayWidgetSettings'
import { tabChromeGridDimensions } from '../tabs/grid/tabLayouts'
import {
  readVisualDraft,
  VISUAL_CHANGED_EVENT,
  VISUAL_TABS,
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
      JSON.stringify(tileOrderDraft) !== JSON.stringify(tileOrder)
    )
  }, [drafts, saved, widgetDraft, widgetVisibility, tileDraft, tileVisibility, tileOrderDraft, tileOrder])

  function patchDraft(tabKey: string, next: VisualDraft): void {
    setDrafts((prev) => ({ ...prev, [tabKey]: next }))
  }

  function moveWidget(id: string, direction: -1 | 1): void {
    const order = [...draft.layout].sort((left, right) => left.y - right.y || left.x - right.x)
    const index = order.findIndex((item) => item.i === id)
    const target = index + direction
    if (index < 0 || target < 0 || target >= order.length) return
    const current = order[index]
    const other = order[target]
    order[index] = { ...current, x: other.x, y: other.y }
    order[target] = { ...other, x: current.x, y: current.y }
    patchDraft(tab.id, { ...draft, layout: order })
  }

  function resizeWidget(id: string, axis: 'w' | 'h', delta: number): void {
    const { cols, maxRows } = tabChromeGridDimensions(tab.id)
    const layout = draft.layout.map((item) => {
      if (item.i !== id) return item
      const limit = axis === 'w' ? cols - item.x : maxRows - item.y
      const min = axis === 'w' ? item.minW ?? 1 : item.minH ?? 1
      const max = Math.min(axis === 'w' ? item.maxW ?? cols : item.maxH ?? maxRows, limit)
      return { ...item, [axis]: Math.max(min, Math.min(max, item[axis] + delta)) }
    })
    patchDraft(tab.id, { ...draft, layout })
  }

  function toggleWidget(id: string): void {
    const current = draft.meta[id]
    patchDraft(tab.id, {
      ...draft,
      meta: { ...draft.meta, [id]: { ...current, visible: current?.visible === false, binned: false } }
    })
  }

  function setColor(id: string, color: string): void {
    const current = draft.meta[id]
    patchDraft(tab.id, {
      ...draft,
      meta: { ...draft.meta, [id]: { ...current, color } }
    })
  }

  function resetTab(): void {
    patchDraft(tab.id, {
      layout: tab.defaults.map((item) => ({ ...item })),
      meta: Object.fromEntries(
        tab.defaults.map((item) => [item.i, { visible: true, color: '', locked: false, binned: false }])
      )
    })
  }

  function moveTile(id: TodayTileId, direction: -1 | 1): void {
    setTileOrderDraft((current) => {
      const index = current.indexOf(id)
      const next = index + direction
      if (index < 0 || next < 0 || next >= current.length) return current
      const copy = [...current]
      const swapped = copy[index]
      copy[index] = copy[next]
      copy[next] = swapped
      return copy
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
    writeTodayWidgetVisibility(user.id, widgetDraft)
    setWidgetVisibility(widgetDraft)
    writeTodayTileVisibility(user.id, tileDraft)
    setTileVisibility(tileDraft)
    writeTodayTileOrder(user.id, tileOrderDraft)
    setTileOrder(tileOrderDraft)
    window.dispatchEvent(new CustomEvent(VISUAL_CHANGED_EVENT))
    setNote('Внешний вид сохранён')
  }

  const ordered = [...draft.layout].sort((left, right) => left.y - right.y || left.x - right.x)
  const showAssignments = isIlchenkoAccount(user)

  return (
    <div className="set-body">
      <header className="set-head">
        <div>
          <h1 className="page-title">Визуал</h1>
          <p className="set-sub">Превью вкладок без данных: видимость, порядок, размер и цвет виджетов</p>
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
          widgetDraft={widgetDraft}
          tileDraft={tileDraft}
          tileOrderDraft={tileOrderDraft}
          showAssignments={showAssignments}
          onToggleWidget={(id) => setWidgetDraft((prev) => ({ ...prev, [id]: prev[id] === false }))}
          onToggleTile={(id) => setTileDraft((prev) => ({ ...prev, [id]: prev[id] === false }))}
          onMoveTile={moveTile}
          onReset={() => {
            setWidgetDraft(defaultTodayWidgetVisibility())
            setTileDraft(defaultTodayTileVisibility())
            setTileOrderDraft([...TODAY_TILE_IDS])
          }}
        />
      ) : (
        <section className="set-card set-visual-card">
          <h2>{tab.label}</h2>
          <p className="set-muted">Пустые блоки показывают, как встанут виджеты. Данные на превью не загружаются.</p>
          <TabPreview tab={tab} draft={draft} onPick={toggleWidget} />
          <div className="set-visual-rows">
            {ordered.map((item, index) => {
              const on = draft.meta[item.i]?.visible !== false
              const color = draft.meta[item.i]?.color || ''
              return (
                <div key={item.i} className={`set-visual-row${on ? '' : ' is-off'}`}>
                  <button type="button" aria-label="Выше" disabled={index === 0} onClick={() => moveWidget(item.i, -1)}>
                    ↑
                  </button>
                  <button
                    type="button"
                    aria-label="Ниже"
                    disabled={index === ordered.length - 1}
                    onClick={() => moveWidget(item.i, 1)}
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    className={`set-widget-toggle${on ? ' is-on' : ''}`}
                    aria-pressed={on}
                    onClick={() => toggleWidget(item.i)}
                  >
                    {visualWidgetLabel(tab, item.i)}
                  </button>
                  <span className="set-visual-size">
                    <button type="button" onClick={() => resizeWidget(item.i, 'w', -1)} aria-label="Уже">
                      −
                    </button>
                    <em>
                      {item.w}×{item.h}
                    </em>
                    <button type="button" onClick={() => resizeWidget(item.i, 'w', 1)} aria-label="Шире">
                      +
                    </button>
                    <button type="button" onClick={() => resizeWidget(item.i, 'h', -1)} aria-label="Ниже">
                      −
                    </button>
                    <button type="button" onClick={() => resizeWidget(item.i, 'h', 1)} aria-label="Выше по высоте">
                      +
                    </button>
                  </span>
                  <label className="set-visual-color" title="Цвет виджета">
                    <input
                      type="color"
                      value={color || '#ffffff'}
                      onChange={(event) => setColor(item.i, event.target.value)}
                    />
                  </label>
                  {color ? (
                    <button type="button" className="set-visual-color-reset" onClick={() => setColor(item.i, '')}>
                      Без цвета
                    </button>
                  ) : null}
                </div>
              )
            })}
          </div>
        </section>
      )}
    </div>
  )
}

function TabPreview({
  tab,
  draft,
  onPick
}: {
  tab: VisualTab
  draft: VisualDraft
  onPick: (id: string) => void
}): React.JSX.Element {
  const { cols, maxRows } = tabChromeGridDimensions(tab.id)
  const visible = draft.layout.filter((item) => draft.meta[item.i]?.visible !== false)
  return (
    <div
      className="set-visual-preview"
      style={{ gridTemplateColumns: `repeat(${cols}, 1fr)`, gridTemplateRows: `repeat(${maxRows}, 1fr)` }}
      aria-hidden
    >
      {visible.map((item) => (
        <button
          key={item.i}
          type="button"
          className="set-visual-block"
          style={blockStyle(item, draft.meta[item.i]?.color || '')}
          onClick={() => onPick(item.i)}
        >
          {visualWidgetLabel(tab, item.i)}
        </button>
      ))}
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
  widgetDraft,
  tileDraft,
  tileOrderDraft,
  showAssignments,
  onToggleWidget,
  onToggleTile,
  onMoveTile,
  onReset
}: {
  widgetDraft: Record<TodayWidgetId, boolean>
  tileDraft: Record<TodayTileId, boolean>
  tileOrderDraft: TodayTileId[]
  showAssignments: boolean
  onToggleWidget: (id: TodayWidgetId) => void
  onToggleTile: (id: TodayTileId) => void
  onMoveTile: (id: TodayTileId, direction: -1 | 1) => void
  onReset: () => void
}): React.JSX.Element {
  const tiles = tileOrderDraft.filter((id) => id !== 'assignments' || showAssignments)
  return (
    <>
      <section className="set-card">
        <h2>Плитки «Сегодня»</h2>
        <div className="set-visual-preview set-visual-preview--tiles" aria-hidden>
          {tiles
            .filter((id) => tileDraft[id] !== false)
            .map((id) => (
              <span key={id} className="set-visual-block">
                {TODAY_TILE_LABELS[id]}
              </span>
            ))}
        </div>
        <div className="set-tile-order">
          {tiles.map((id) => {
            const on = tileDraft[id] !== false
            const index = tileOrderDraft.indexOf(id)
            return (
              <div key={id} className="set-tile-order-row">
                <button type="button" className="set-tile-order-move" disabled={index === 0} onClick={() => onMoveTile(id, -1)}>
                  ↑
                </button>
                <button
                  type="button"
                  className="set-tile-order-move"
                  disabled={index === tileOrderDraft.length - 1}
                  onClick={() => onMoveTile(id, 1)}
                >
                  ↓
                </button>
                <button
                  type="button"
                  className={`set-widget-toggle${on ? ' is-on' : ''}`}
                  aria-pressed={on}
                  onClick={() => onToggleTile(id)}
                >
                  {TODAY_TILE_LABELS[id]}
                </button>
              </div>
            )
          })}
        </div>
      </section>
      <section className="set-card">
        <h2>Виджеты «Сегодня»</h2>
        <div className="set-visual-preview set-visual-preview--tiles" aria-hidden>
          {TODAY_WIDGET_IDS.filter((id) => widgetDraft[id] !== false).map((id) => (
            <span key={id} className="set-visual-block">
              {TODAY_WIDGET_LABELS[id]}
            </span>
          ))}
        </div>
        <div className="set-widget-grid-9">
          {TODAY_WIDGET_IDS.map((id) => {
            const on = widgetDraft[id] !== false
            return (
              <button
                key={id}
                type="button"
                className={`set-widget-toggle${on ? ' is-on' : ''}`}
                aria-pressed={on}
                onClick={() => onToggleWidget(id)}
              >
                {TODAY_WIDGET_LABELS[id]}
              </button>
            )
          })}
        </div>
        <button className="btn-ghost" type="button" onClick={onReset}>
          Все плитки и виджеты
        </button>
      </section>
    </>
  )
}
