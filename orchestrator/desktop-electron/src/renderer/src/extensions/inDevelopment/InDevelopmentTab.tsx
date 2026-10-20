import { useState } from 'react'
import { OrchSlotMain } from '../../layout/GridSlots'
import { SupplyPeriodReport } from './SupplyPeriodReport'
import { usePurchasesDock } from './purchasesDock'
import './inDevelopment.css'

const SECTIONS = [
  {
    id: 'supply_report',
    label: 'Отчет по обеспеченности',
    text: 'Макет раздела «Отчет по обеспеченности».'
  },
  {
    id: 'supply_forecast',
    label: 'Прогноз обеспеченности',
    text: 'Макет раздела «Прогноз обеспеченности».'
  },
  {
    id: 'shift_tasks',
    label: 'Сменные задания',
    text: 'Макет раздела «Сменные задания».'
  }
] as const

type SectionId = (typeof SECTIONS)[number]['id']

const DOCK_LABEL = {
  by_period: 'По периоду',
  by_site: 'По площадкам'
} as const

export function InDevelopmentTab(): React.JSX.Element {
  const [active, setActive] = useState<SectionId>('supply_report')
  const dock = usePurchasesDock()
  const section = SECTIONS.find((item) => item.id === active) ?? SECTIONS[0]
  const periodReport = active === 'supply_report' && dock.active === 'by_period'

  return (
    <OrchSlotMain spanAll heavyEmbed>
      <div className={periodReport ? 'purchases-page purchases-page--report' : 'purchases-page'}>
        <div className="purchases-nav" role="tablist" aria-label="Разделы закупок">
          {SECTIONS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={item.id === active}
              className={item.id === active ? 'is-active' : ''}
              onClick={() => setActive(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        {periodReport ? (
          <SupplyPeriodReport />
        ) : (
          <p className="purchases-mock">
            {section.text} {DOCK_LABEL[dock.active]}.
          </p>
        )}
      </div>
    </OrchSlotMain>
  )
}
