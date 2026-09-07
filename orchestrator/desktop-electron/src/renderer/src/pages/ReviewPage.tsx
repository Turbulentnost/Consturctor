import { StyledDocument } from '../components/StyledDocument'
import { buildLegend, entityColor } from '../documentEntities'
import type { RegulationParseResult } from '../api/types'

interface ReviewPageProps {
  result: RegulationParseResult
  onBack: () => void
  onContinue: () => void
  continueBusy?: boolean
}

export function ReviewPage({
  result,
  onBack,
  onContinue,
  continueBusy
}: ReviewPageProps): React.JSX.Element {
  const legend = buildLegend(result)
  const roles = legend.filter((item) => item.kind === 'role')
  const processes = legend.filter((item) => item.kind === 'process')

  return (
    <div className="page-with-footer">
      <div className="page-scroll">
        <div className="chat-head">
          <button className="btn-ghost" onClick={onBack}>
            {'\u2039'} Назад
          </button>
          <h1 className="page-title" style={{ fontSize: 24 }}>
            Проверьте распознанный регламент
          </h1>
        </div>
        <p className="page-subtitle">{result.fileName}</p>

        <div className="review-stats">
          <div className="stat">
            <div className="stat-value">{result.pageCount}</div>
            <div className="stat-label">страниц</div>
          </div>
          <div className="stat">
            <div className="stat-value">{result.sectionCount}</div>
            <div className="stat-label">разделов</div>
          </div>
          <div className="stat">
            <div className="stat-value">{result.tableCount}</div>
            <div className="stat-label">таблиц</div>
          </div>
          <div className="stat">
            <div className="stat-value">{Math.round(result.recognitionQuality * 100)}%</div>
            <div className="stat-label">качество</div>
          </div>
        </div>

        <div className="review-layout">
          <aside className="review-outline">
            <div className="review-outline-title">Легенда</div>
            {legend.length === 0 && (
              <div className="review-outline-empty">Должности и процессы в тексте не выделены.</div>
            )}
            {roles.length > 0 && <div className="review-legend-caption">Должности</div>}
            {roles.map((item) => {
              const color = entityColor(item)
              return (
                <div key={item.entityId} className="review-legend-item">
                  <span className="review-legend-swatch" style={{ background: color.fill, borderColor: color.border }} />
                  <div>
                    <div className="review-legend-name" style={{ color: color.text }}>
                      {item.shortTitle || item.title}
                    </div>
                    {item.shortTitle && item.shortTitle !== item.title && (
                      <div className="review-legend-note">{item.title}</div>
                    )}
                  </div>
                </div>
              )
            })}
            {processes.length > 0 && <div className="review-legend-caption">Процессы</div>}
            {processes.map((item) => {
              const color = entityColor(item)
              return (
                <div key={item.entityId} className="review-legend-item">
                  <span className="review-legend-swatch" style={{ background: color.fill, borderColor: color.border }} />
                  <div>
                    <div className="review-legend-name" style={{ color: color.text }}>
                      {item.shortTitle || item.title}
                    </div>
                    {item.shortTitle && item.shortTitle !== item.title && (
                      <div className="review-legend-note">{item.title}</div>
                    )}
                  </div>
                </div>
              )
            })}
          </aside>
          <div className="review-doc">
            <StyledDocument fragments={result.fragments} />
          </div>
        </div>
      </div>

      <div className="page-footer">
        <button className="btn-ghost-dark" onClick={onBack}>
          Назад
        </button>
        <div className="page-footer-actions">
          <button className="btn-primary" style={{ maxWidth: 260 }} onClick={onContinue} disabled={continueBusy}>
            {continueBusy ? 'Анализируем...' : 'Продолжить'}
          </button>
        </div>
      </div>
    </div>
  )
}
