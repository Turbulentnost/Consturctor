export function KpiPage(): React.JSX.Element {
  return (
    <div>
      <h1 className="page-title">KPI</h1>
      <p className="page-subtitle">Показатели эффективности ИИ-агентов</p>
      <div className="placeholder-card">
        Раздел KPI будет перенесён на следующем шаге миграции.
      </div>
    </div>
  )
}

export function DashboardPage(): React.JSX.Element {
  return (
    <div>
      <h1 className="page-title">Мой дашборд</h1>
      <p className="page-subtitle">Сводка по вашим агентам и задачам</p>
      <div className="placeholder-card">
        Раздел дашборда будет перенесён на следующем шаге миграции.
      </div>
    </div>
  )
}

export function RegulationResultView({
  fileName,
  pageCount,
  sectionCount,
  onBack
}: {
  fileName: string
  pageCount: number
  sectionCount: number
  onBack: () => void
}): React.JSX.Element {
  return (
    <div>
      <h1 className="page-title">Регламент распознан</h1>
      <p className="page-subtitle">{fileName}</p>
      <div className="placeholder-card" style={{ textAlign: 'left' }}>
        <div>
          Страниц: <b>{pageCount}</b>
        </div>
        <div>
          Разделов: <b>{sectionCount}</b>
        </div>
        <p style={{ marginTop: 16, color: 'var(--content-muted)' }}>
          Следующие шаги конструктора (проверка регламента, подбор функций по должности,
          готовность, паспорт агента, формирование и пробный прогон) переносятся поэтапно.
        </p>
      </div>
      <button className="btn-primary" style={{ maxWidth: 200, marginTop: 20 }} onClick={onBack}>
        Назад
      </button>
    </div>
  )
}
