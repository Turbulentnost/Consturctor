import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { downloadTableExport } from '../admin/utils/exportTable'
import { getKpiExportSnapshot } from '../workplace/kpiExportSnapshot'

function buildKpiExportRows(): { filename: string; headers: string[]; rows: string[][] } {
  const snap = getKpiExportSnapshot()
  const from = snap.from || snap.data?.periodFrom || ''
  const to = snap.to || snap.data?.periodTo || ''
  const cards = snap.data?.cards ?? []
  const agents = snap.data?.agents ?? []
  const rows: string[][] = [
    ...cards.map((card) => [
      'Карточка',
      card.label,
      card.id,
      '',
      card.displayValue,
      '',
      '',
      '',
      card.trend || ''
    ]),
    ...agents.map((row) => [
      'Агент',
      row.name,
      row.code,
      row.process,
      String(row.completionPct),
      String(row.slaPct),
      String(row.loadPct),
      String(row.automationPct),
      row.status
    ])
  ]
  return {
    filename: `kpi-${from || 'period'}-${to || 'now'}`,
    headers: [
      'Раздел',
      'Название',
      'Код / id',
      'Процесс',
      'Значение / выполнение %',
      'SLA %',
      'Загрузка %',
      'Автоматизация %',
      'Статус / тренд'
    ],
    rows
  }
}

export function KpiExportReportButton(): React.JSX.Element {
  const buttonRef = useRef<HTMLButtonElement | null>(null)
  const popRef = useRef<HTMLDivElement | null>(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [pos, setPos] = useState({ top: 0, left: 0 })

  const place = (): void => {
    const box = buttonRef.current?.getBoundingClientRect()
    if (!box) return
    const width = 220
    setPos({
      top: box.bottom + 6,
      left: Math.min(Math.max(8, box.right - width), window.innerWidth - width - 8)
    })
  }

  useEffect(() => {
    if (!open) return
    place()
    const onMove = (): void => place()
    window.addEventListener('resize', onMove)
    document.addEventListener('scroll', onMove, true)
    return () => {
      window.removeEventListener('resize', onMove)
      document.removeEventListener('scroll', onMove, true)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onDoc = (event: MouseEvent): void => {
      const target = event.target as Node | null
      if (!target) return
      if (buttonRef.current?.contains(target) || popRef.current?.contains(target)) return
      setOpen(false)
    }
    const timer = window.setTimeout(() => document.addEventListener('mousedown', onDoc), 0)
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('mousedown', onDoc)
    }
  }, [open])

  const runExport = async (format: string): Promise<void> => {
    setBusy(true)
    try {
      await downloadTableExport(format, buildKpiExportRows())
    } finally {
      setBusy(false)
      setOpen(false)
    }
  }

  return (
    <div className="kpi-export orch-header-menu">
      <button
        ref={buttonRef}
        type="button"
        className="spec-btn-outline"
        disabled={busy}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {busy ? 'Экспорт…' : 'Экспорт отчёта ▾'}
      </button>
      {open
        ? createPortal(
            <div
              ref={popRef}
              className="kpi-export-menu"
              role="menu"
              style={{ top: pos.top, left: pos.left, position: 'fixed' }}
            >
              <button type="button" role="menuitem" onClick={() => void runExport('CSV')}>
                <span>CSV</span>
              </button>
              <button type="button" role="menuitem" onClick={() => void runExport('Excel')}>
                <span>XLSX</span>
              </button>
            </div>,
            document.body
          )
        : null}
    </div>
  )
}
