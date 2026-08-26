import { presentAgentText } from './agentfeed/formatAgentText'

interface FormationBannerProps {
  title: string
  output: string
  running: boolean
  awaiting: boolean
  onOpen: () => void
}

/** Strip markdown/formatting to a compact single-ish line for the banner. */
function plainPreview(text: string): string {
  const cleaned = presentAgentText(text || '')
    .replace(/[`*_>#]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  return cleaned
}

export function FormationBanner({
  title,
  output,
  running,
  awaiting,
  onOpen
}: FormationBannerProps): React.JSX.Element {
  const preview = plainPreview(output)
  const statusLabel = awaiting
    ? 'Ждёт ваш ответ'
    : running
      ? 'Формируется'
      : 'В работе'
  return (
    <div className="formation-banner">
      <span className={`formation-banner-dot${running ? ' busy' : awaiting ? ' wait' : ''}`} />
      <div className="formation-banner-copy">
        <div className="formation-banner-title">
          <span className="formation-banner-name">{title || 'ИИ-агент'}</span>
          <span className="formation-banner-status">{statusLabel}</span>
        </div>
        <div className="formation-banner-text">
          {preview || 'Агент формируется…'}
        </div>
      </div>
      <button className="formation-banner-open" onClick={onOpen}>
        Перейти
      </button>
    </div>
  )
}
