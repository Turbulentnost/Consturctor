import { createContext, useContext } from 'react'
import { Briefcase, ChevronRight, ClipboardList, Gavel, LayoutList, ScrollText } from 'lucide-react'
import '../inDevelopment/inDevelopment.css'

export const EXTERNAL_ORDER_DOCK = [
  { id: 'desk', label: 'Рабочий стол', Icon: LayoutList },
  { id: 'registry', label: 'Реестр', Icon: ClipboardList },
  { id: 'reconcile', label: 'Сверка', Icon: ScrollText },
  { id: 'committee', label: 'Комитет', Icon: Gavel },
  { id: 'audit', label: 'Журнал', Icon: Briefcase }
] as const

export type ExternalOrderDockId = (typeof EXTERNAL_ORDER_DOCK)[number]['id']

const ExternalOrderDockContext = createContext<ExternalOrderDockId>('desk')

export function ExternalOrderDockProvider({
  active,
  children
}: {
  active: ExternalOrderDockId
  children: React.ReactNode
}): React.JSX.Element {
  return <ExternalOrderDockContext.Provider value={active}>{children}</ExternalOrderDockContext.Provider>
}

export function useExternalOrderDock(): ExternalOrderDockId {
  return useContext(ExternalOrderDockContext)
}

export function ExternalOrderDock({
  labeled,
  active,
  onSelect
}: {
  labeled: boolean
  active: ExternalOrderDockId
  onSelect: (id: ExternalOrderDockId) => void
}): React.JSX.Element {
  return (
    <aside className={labeled ? 'child-dock child-dock--labeled' : 'child-dock'} aria-label="Внешний заказ">
      <div className="child-dock-head">
        <span className="child-dock-mark">
          <Briefcase size={16} strokeWidth={1.8} aria-hidden />
        </span>
        <span className="child-dock-head-text">
          <strong>Внешний заказ</strong>
          <small>Дело, сверка и Комитет</small>
        </span>
      </div>
      <nav className="child-dock-nav">
        {EXTERNAL_ORDER_DOCK.map((item) => {
          const Icon = item.Icon
          return (
            <button
              key={item.id}
              type="button"
              className={active === item.id ? 'child-dock-item is-active' : 'child-dock-item'}
              title={item.label}
              aria-label={item.label}
              aria-current={active === item.id ? 'page' : undefined}
              onClick={() => onSelect(item.id)}
            >
              <Icon size={16} strokeWidth={1.8} aria-hidden />
              <span className="child-dock-label">{item.label}</span>
              <ChevronRight className="child-dock-chevron" size={14} strokeWidth={1.8} aria-hidden />
            </button>
          )
        })}
      </nav>
    </aside>
  )
}
