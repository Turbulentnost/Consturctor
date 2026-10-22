import type { LayoutItem } from 'react-grid-layout/legacy'
import {
  DEFAULT_AGENT_LIBRARY_LAYOUT,
  DEFAULT_ASSIGNMENTS_REGISTRY_LAYOUT,
  DEFAULT_DECISIONS_LAYOUT,
  DEFAULT_KPI_LAYOUT,
  DEFAULT_MEETINGS_LAYOUT,
  DEFAULT_PROCESS_LAYOUT,
  DEFAULT_STANDARD_LAYOUT,
  DEFAULT_WIDE_MAIN_LAYOUT,
  scaleLayoutItems,
  tabChromeGridDimensions,
  tabChromeLayoutMigration
} from './tabLayouts'
import type { TabChromeMeta, TabChromePersist } from './useTabChromeLayout'

const TAB_WIDGET_LABELS: Record<string, string> = {
  tiles: 'Плитки',
  filters: 'Фильтры',
  main: 'Таблица',
  side: 'Карточка',
  botA: 'Нижний блок',
  botB: 'Нижний блок B',
  botC: 'Лента решений',
  calendar: 'Календарь',
  rail: 'Период и календари'
}

export type VisualTab = {
  id: string
  label: string
  defaults: LayoutItem[]
  labels: Record<string, string>
}

/** Вкладки с настраиваемой раскладкой виджетов — те же id, что у рабочих вкладок. */
export const VISUAL_TABS: VisualTab[] = [
  { id: 'tasks', label: 'Задачи', defaults: DEFAULT_STANDARD_LAYOUT, labels: TAB_WIDGET_LABELS },
  { id: 'mail', label: 'Почта', defaults: DEFAULT_STANDARD_LAYOUT, labels: TAB_WIDGET_LABELS },
  { id: 'docflow', label: 'Документооборот', defaults: DEFAULT_STANDARD_LAYOUT, labels: TAB_WIDGET_LABELS },
  { id: 'meetings', label: 'Совещания', defaults: DEFAULT_MEETINGS_LAYOUT, labels: TAB_WIDGET_LABELS },
  { id: 'decisions', label: 'Решения', defaults: DEFAULT_DECISIONS_LAYOUT, labels: TAB_WIDGET_LABELS },
  { id: 'kpi', label: 'KPI', defaults: DEFAULT_KPI_LAYOUT, labels: TAB_WIDGET_LABELS },
  { id: 'processes', label: 'Процессы', defaults: DEFAULT_PROCESS_LAYOUT, labels: TAB_WIDGET_LABELS },
  { id: 'projects', label: 'Проекты', defaults: DEFAULT_STANDARD_LAYOUT, labels: TAB_WIDGET_LABELS },
  { id: 'knowledge', label: 'База знаний', defaults: DEFAULT_STANDARD_LAYOUT, labels: TAB_WIDGET_LABELS },
  { id: 'agent_library', label: 'Библиотека агентов', defaults: DEFAULT_AGENT_LIBRARY_LAYOUT, labels: TAB_WIDGET_LABELS },
  {
    id: 'assignments_registry',
    label: 'Реестр поручений',
    defaults: DEFAULT_ASSIGNMENTS_REGISTRY_LAYOUT,
    labels: TAB_WIDGET_LABELS
  },
  { id: 'history', label: 'История', defaults: DEFAULT_WIDE_MAIN_LAYOUT, labels: TAB_WIDGET_LABELS }
]

export function visualTabById(tabId: string): VisualTab | undefined {
  return VISUAL_TABS.find((tab) => tab.id === tabId)
}

/** Названия плиток как на рабочей вкладке. Пустой список — полосы плиток нет. */
export const VISUAL_TAB_TILES: Record<string, string[]> = {
  tasks: ['Все задачи', 'Задачи из 1С', '1С от меня', 'Платформа', 'Turbo мне', 'Turbo РП', 'Регламентные', 'Просроченные'],
  mail: ['Входящие', 'Исходящие', 'Высокий приоритет', 'Проектные'],
  meetings: ['Совещания за период', 'Сегодня', 'Прошло', 'Дальше'],
  decisions: ['Ожидают меня', 'На рассмотрении', 'Подтверждено сегодня', 'Возвращено'],
  kpi: ['Выполнение задач', 'SLA', 'Загрузка', 'Эффективность ИИ', 'Доля автоматизации', 'Качество'],
  processes: ['Регламентные процессы', 'Задачи из 1С', 'Проекты', 'Письма', 'Совещания'],
  projects: ['Активные проекты', 'Открытые задачи', 'С риском', 'Выполнено (выбранный)', 'Загрузка'],
  knowledge: ['Документов (агенты)', 'Регламенты', 'Шаблоны', 'Статьи', 'Обновлено'],
  assignments_registry: ['Все', 'Просроченные', 'Подходит срок', 'В работе', 'Выполненные'],
  history: ['События за период', 'Действия сотрудника', 'Действия ИИ', 'Ошибки / возвраты', 'Подтверждённые решения']
}

export function visualWidgetLabel(tab: VisualTab, id: string): string {
  return tab.labels[id] || TAB_WIDGET_LABELS[id] || id
}

/** Ключ хранения совпадает с рабочими вкладками, чтобы превью и вкладка делили одну раскладку. */
export function visualStorageKey(tabId: string, userId: string): string {
  const uid = userId.trim() || 'default'
  if (tabId === 'assignments_registry') return `orch-tab-chrome-v11:assignments_registry-v3:${uid}`
  if (tabId === 'agent_library') return `orch-tab-chrome-v11:agent_library-v2:${uid}`
  if (tabId === 'meetings') return `orch-tab-chrome-v11:meetings-v3:${uid}`
  if (tabId === 'kpi') return `orch-tab-chrome-v11:kpi-v5:${uid}`
  return `orch-tab-chrome-v11:${tabId}:${uid}`
}

export type VisualDraft = {
  layout: LayoutItem[]
  meta: Record<string, TabChromeMeta>
}

function defaultMeta(ids: string[]): Record<string, TabChromeMeta> {
  return Object.fromEntries(ids.map((id) => [id, { visible: true, color: '', locked: false, binned: false }]))
}

export function readVisualDraft(tab: VisualTab, userId: string): VisualDraft {
  const ids = tab.defaults.map((item) => item.i)
  const meta = defaultMeta(ids)
  const layout = tab.defaults.map((item) => ({ ...item }))
  try {
    const uid = userId.trim() || 'default'
    let raw = localStorage.getItem(visualStorageKey(tab.id, userId))
    let legacyScale: { sx: number; sy: number } | null = null
    if (!raw) {
      const migration = tabChromeLayoutMigration(tab.id)
      if (migration) {
        raw = localStorage.getItem(`orch-tab-chrome-v11:${migration.legacySuffix}:${uid}`)
        legacyScale = migration
      }
    }
    if (!raw) return { layout, meta }
    const parsed = JSON.parse(raw) as Partial<TabChromePersist>
    const storedLayout = legacyScale
      ? scaleLayoutItems(parsed.layout || [], legacyScale.sx, legacyScale.sy)
      : parsed.layout || []
    const saved = new Map(storedLayout.map((item) => [item.i, item]))
    const { cols, maxRows } = tabChromeGridDimensions(tab.id)
    for (const item of layout) {
      const found = saved.get(item.i)
      if (!found) continue
      const w = Math.max(item.minW ?? 1, Math.min(item.maxW ?? cols, Math.round(found.w || item.w)))
      const h = Math.max(item.minH ?? 1, Math.min(item.maxH ?? maxRows, Math.round(found.h || item.h)))
      item.x = Math.max(0, Math.min(cols - w, Math.round(found.x ?? item.x)))
      item.y = Math.max(0, Math.min(maxRows - h, Math.round(found.y ?? item.y)))
      item.w = w
      item.h = h
    }
    for (const id of ids) {
      const savedMeta = parsed.meta?.[id]
      if (!savedMeta) continue
      meta[id] = {
        visible: savedMeta.visible !== false && !savedMeta.binned,
        color: typeof savedMeta.color === 'string' ? savedMeta.color : '',
        locked: Boolean(savedMeta.locked),
        binned: false
      }
    }
  } catch {
    /* повреждённая запись — показываем раскладку по умолчанию */
  }
  return { layout, meta }
}

export function writeVisualDraft(tab: VisualTab, userId: string, draft: VisualDraft): void {
  const ids = new Set(tab.defaults.map((item) => item.i))
  const payload: TabChromePersist = {
    layout: draft.layout.filter((item) => ids.has(item.i)),
    meta: Object.fromEntries(
      [...ids].map((id) => [
        id,
        {
          visible: draft.meta[id]?.visible !== false,
          color: draft.meta[id]?.color || '',
          locked: Boolean(draft.meta[id]?.locked),
          binned: false
        }
      ])
    )
  }
  localStorage.setItem(visualStorageKey(tab.id, userId), JSON.stringify(payload))
}

export const VISUAL_CHANGED_EVENT = 'orchestrator:tab-visual-changed'
