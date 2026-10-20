import { useMemo, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { PeriodPicker } from './PeriodPicker'
import {
  buildPeriodColumns,
  defaultPeriod,
  eachDay,
  firstWeekInMonth,
  initialOpen,
  type DayRange,
  type PeriodColumn
} from './periodDates'

const PRODUCTS = [
  {
    id: 'k12',
    name: 'Корпус К-12',
    materials: [
      { id: 'k12-sheet', name: 'Лист стальной' },
      { id: 'k12-paint', name: 'Эмаль' }
    ]
  },
  {
    id: 'p4',
    name: 'Плата П-4',
    materials: [
      { id: 'p4-textolite', name: 'Текстолит' },
      { id: 'p4-chip', name: 'Микросхема' }
    ]
  },
  {
    id: 'kr1',
    name: 'Крышка КР-1',
    materials: [
      { id: 'kr1-plastic', name: 'Полиамид' },
      { id: 'kr1-seal', name: 'Уплотнитель' }
    ]
  },
  {
    id: 'sh2',
    name: 'Шасси Ш-2',
    materials: [
      { id: 'sh2-profile', name: 'Профиль' },
      { id: 'sh2-bolt', name: 'Крепёж' }
    ]
  }
]

const FILTERS = [
  { id: 'stock', label: 'Остатки' },
  { id: 'expected', label: 'Ожидаемое поступление' },
  { id: 'ordered', label: 'Заказано' }
] as const

type SupplyFilter = (typeof FILTERS)[number]['id']

function dayPair(productId: string, day: string, filter: SupplyFilter): { plan: number; fact: number } {
  const seed = [...productId].reduce((sum, char) => sum + char.charCodeAt(0), 0)
  const shift = filter === 'stock' ? 0 : filter === 'expected' ? 5 : 11
  const date = Number(day.slice(8, 10))
  const month = Number(day.slice(5, 7))
  const plan = 6 + ((seed + date * 3 + month + shift) % 9)
  if ((seed + date + shift) % 11 === 0) return { plan, fact: 0 }
  return { plan, fact: Math.max(0, plan - 3 + ((seed + date + shift) % 7)) }
}

function columnPair(
  productId: string,
  column: PeriodColumn,
  filter: SupplyFilter
): { plan: number; fact: number } {
  return column.days.reduce(
    (sum, day) => {
      const pair = dayPair(productId, day, filter)
      return { plan: sum.plan + pair.plan, fact: sum.fact + pair.fact }
    },
    { plan: 0, fact: 0 }
  )
}

function factTone(plan: number, fact: number): 'is-zero' | 'is-ok' | 'is-low' {
  if (fact === 0) return 'is-zero'
  return fact >= plan ? 'is-ok' : 'is-low'
}

export function SupplyPeriodReport(): React.JSX.Element {
  const [range, setRange] = useState<DayRange>(defaultPeriod)
  const [filter, setFilter] = useState<SupplyFilter>('stock')
  const [openProducts, setOpenProducts] = useState<Set<string>>(() => new Set())
  const days = useMemo(() => eachDay(range), [range])
  const fallback = useMemo(() => initialOpen(days), [days])
  const [openMonth, setOpenMonth] = useState(fallback.month)
  const [openWeek, setOpenWeek] = useState(fallback.week)
  const monthOpen = days.some((day) => day.startsWith(openMonth)) ? openMonth : fallback.month
  const weekOpen = openWeek.startsWith(`${monthOpen}:`) ? openWeek : firstWeekInMonth(days, monthOpen)
  const groups = useMemo(
    () => buildPeriodColumns(days, monthOpen, weekOpen),
    [days, monthOpen, weekOpen]
  )
  const columns = groups.flatMap((group) => group.columns)

  function chooseRange(next: DayRange): void {
    const nextDays = eachDay(next)
    const open = initialOpen(nextDays)
    setRange(next)
    setOpenMonth(open.month)
    setOpenWeek(open.week)
  }

  function chooseMonth(month: string): void {
    setOpenMonth(month)
    setOpenWeek(firstWeekInMonth(days, month))
  }

  function toggleProduct(id: string): void {
    setOpenProducts((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="supply-report">
      <div className="supply-toolbar">
        <PeriodPicker value={range} onChange={chooseRange} />
        <label className="supply-filter">
          <span>Показатель</span>
          <select value={filter} onChange={(event) => setFilter(event.target.value as SupplyFilter)}>
            {FILTERS.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <div className="supply-legend" aria-label="План слева сверху, факт справа снизу">
          <span className="supply-legend-cell">
            <span>План</span>
            <span>Факт</span>
          </span>
        </div>
      </div>
      <div className="supply-table-wrap">
        <table className="supply-table">
          <thead>
            <tr>
              <th className="supply-sticky supply-name" rowSpan={2}>
                Изделие
              </th>
              {groups.map((group) =>
                group.open ? (
                  <th key={group.id} colSpan={group.columns.length} className="is-open">
                    <button type="button" onClick={() => chooseMonth(group.month)}>
                      {group.title}
                    </button>
                  </th>
                ) : (
                  <th key={group.id} rowSpan={2}>
                    <button type="button" onClick={() => chooseMonth(group.month)}>
                      {group.title}
                    </button>
                  </th>
                )
              )}
            </tr>
            <tr>
              {groups.flatMap((group) =>
                group.open
                  ? group.columns.map((column) => (
                      <th key={column.id} className={column.kind === 'day' ? 'is-day' : 'is-week'}>
                        {column.kind === 'week' ? (
                          <button type="button" onClick={() => setOpenWeek(column.week)}>
                            {column.title}
                          </button>
                        ) : column.kind === 'day' ? (
                          <span className="supply-day">
                            <b>{column.title}</b>
                            <small>{column.weekday}</small>
                          </span>
                        ) : (
                          column.title
                        )}
                      </th>
                    ))
                  : null
              )}
            </tr>
          </thead>
          <tbody>
            {PRODUCTS.map((product) => {
              const opened = openProducts.has(product.id)
              const rows = [
                { id: product.id, name: product.name, material: false },
                ...(opened
                  ? product.materials.map((material) => ({
                      id: material.id,
                      name: material.name,
                      material: true
                    }))
                  : [])
              ]
              return rows.map((row) => (
                <tr key={row.id} className={row.material ? 'supply-row-material' : 'supply-row-product'}>
                  <th className="supply-sticky supply-name" scope="row">
                    {row.material ? (
                      <span className="supply-material-name">{row.name}</span>
                    ) : (
                      <button
                        type="button"
                        className={opened ? 'supply-product is-open' : 'supply-product'}
                        aria-expanded={opened}
                        onClick={() => toggleProduct(product.id)}
                      >
                        <ChevronRight size={16} strokeWidth={2.2} aria-hidden />
                        {row.name}
                      </button>
                    )}
                  </th>
                  {columns.map((column) => {
                    const pair = columnPair(row.id, column, filter)
                    return (
                      <td key={column.id} className="supply-split">
                        <span className="supply-plan">{pair.plan}</span>
                        <span className={`supply-fact ${factTone(pair.plan, pair.fact)}`}>{pair.fact}</span>
                      </td>
                    )
                  })}
                </tr>
              ))
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
