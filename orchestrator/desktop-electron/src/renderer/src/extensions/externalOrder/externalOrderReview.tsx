import type { ExternalOrderReview } from './externalOrderTypes'

const VERDICT: Record<string, string> = {
  done: 'Выполнено',
  gap: 'Нет источника',
  wait: 'Ждёт владельца',
  skip: 'Не применимо'
}

export function HelperPanel({
  review,
  log
}: {
  review: ExternalOrderReview
  log: string[]
}): React.JSX.Element {
  const checks = review.checks.filter((item) => item.verdict !== 'done' && item.verdict !== 'skip')
  const diffs = review.diffs.filter((item) => item.verdict !== 'done' && item.verdict !== 'skip')
  return (
    <section className="eo-window eo-window-work">
      <h3>Помощник</h3>
      {review.summary ? <p>{review.summary}</p> : null}
      {log.map((line, index) => <p key={index}>{line}</p>)}
      {checks.length ? (
        <div className="eo-form">
          <h3>Открытые пункты</h3>
          {checks.map((item) => (
            <article key={item.id} className="eo-check">
              <span>{item.text}<br /><small className="eo-muted">{item.owner_label}. {item.note}</small></span>
              <span className="eo-tag is-stop">{VERDICT[item.verdict] || item.verdict}</span>
            </article>
          ))}
        </div>
      ) : null}
      {diffs.length ? (
        <table className="eo-table">
          <thead>
            <tr><th>Код</th><th>Сверка</th><th>Владелец</th><th></th></tr>
          </thead>
          <tbody>
            {diffs.map((item) => (
              <tr key={item.code}>
                <td>{item.code}</td>
                <td>{item.title}</td>
                <td>{item.owner_label}</td>
                <td><span className="eo-tag is-stop">{VERDICT[item.verdict] || item.verdict}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  )
}
