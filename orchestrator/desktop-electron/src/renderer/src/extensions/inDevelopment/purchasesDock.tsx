import { createContext, useContext } from 'react'
import { ChevronRight, Clock, Factory, ShoppingCart } from 'lucide-react'
import './inDevelopment.css'

export const PURCHASES_DOCK_ITEMS = [
  { id: 'by_period', label: 'По периоду', Icon: Clock },
  { id: 'by_site', label: 'По площадкам', Icon: Factory }
] as const

export type PurchasesDockId = (typeof PURCHASES_DOCK_ITEMS)[number]['id']

type PurchasesDockValue = {
  active: PurchasesDockId
}

const PurchasesDockContext = createContext<PurchasesDockValue | null>(null)

export function PurchasesDockProvider({
  active,
  children
}: {
  active: PurchasesDockId
  children: React.ReactNode
}): React.JSX.Element {
  return <PurchasesDockContext.Provider value={{ active }}>{children}</PurchasesDockContext.Provider>
}

export function usePurchasesDock(): PurchasesDockValue {
  return useContext(PurchasesDockContext) ?? { active: 'by_period' }
}

export function PurchasesDock({
  labeled,
  active,
  onSelect
}: {
  labeled: boolean
  active: PurchasesDockId
  onSelect: (id: PurchasesDockId) => void
}): React.JSX.Element {
  return (
    <aside
      className={labeled ? 'child-dock child-dock--labeled' : 'child-dock'}
      aria-label="Вид закупок"
    >
      <div className="child-dock-head">
        <span className="child-dock-mark">
          <ShoppingCart size={16} strokeWidth={1.8} aria-hidden />
        </span>
        <span className="child-dock-head-text">
          <strong>Закупки</strong>
          <small>Планирование и анализ закупок</small>
        </span>
      </div>
      <nav className="child-dock-nav">
        {PURCHASES_DOCK_ITEMS.map((item) => {
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
