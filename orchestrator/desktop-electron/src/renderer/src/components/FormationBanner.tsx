import { presentAgentText } from './agentfeed/formatAgentText'

interface FormationBannerProps {
  title: string
  output: string
  running: boolean
  awaiting: boolean
  mode?: 'formation' | 'run'
  onOpen: () => void
}

/** Strip markdown/formatting to a compact single-ish line for the banner. */
function plainPreview(text: string): string {
  let cleaned = presentAgentText(text || '')
    .replace(/[`*_>#]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  // Never dump raw verdict JSON into the top run banner.
  const jsonMatch = cleaned.match(/\{[\s\S]*"verdict"[\s\S]*\}/i)
  if (jsonMatch) {
    try {
      const parsed = JSON.parse(jsonMatch[0]) as { verdict?: string; reason?: string }
      const verdict = String(parsed.verdict || '').toLowerCase()
      const reason = String(parsed.reason || '').trim()
      if (verdict === 'acceptable') return reason ? `Допустимо: ${reason}` : 'Допустимо'
      if (verdict === 'rejected' || verdict === 'escalate' || verdict === 'denied') {
        return reason ? `Отказано: ${reason}` : 'Отказано'
      }
    } catch {
      /* keep cleaned */
    }
  }
  return cleaned
}

export function FormationBanner({
  title,
  output,
  running,
  awaiting,
  mode = 'formation',
  onOpen
}: FormationBannerProps): React.JSX.Element {
  const preview = plainPreview(output)
  const statusLabel = awaiting
    ? 'Ждёт ваш ответ'
    : running
      ? mode === 'run'
        ? 'Выполняется'
        : 'Формируется'
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
          {preview || (mode === 'run' ? 'Агент выполняется…' : 'Агент формируется…')}
        </div>
      </div>
      <button className="formation-banner-open" onClick={onOpen}>
        Перейти
      </button>
    </div>
  )
}
