import type { ReactNode } from 'react'

export type SpecSummaryTone = 'green' | 'blue' | 'purple' | 'orange' | 'lilac' | 'yellow' | 'red' | 'neutral'

export type SpecPillTone = 'green' | 'blue' | 'orange' | 'red' | 'purple' | 'gray' | 'yellow'

export interface SpecSummaryTile {
  id: string
  label: string
  value: string
  hint?: string
  /** Подсказка при наведении на плитку (если не задана — label + hint). */
  tooltip?: string
  tone?: SpecSummaryTone
  progress?: number
  ring?: boolean
}

interface SpecV04ShellProps {
  title: string
  subtitle: string
  badge?: string
  tiles: SpecSummaryTile[]
  filters?: ReactNode
  children: ReactNode
  onAskOrchestrator?: (message: string) => void
}

export function stageProgressTone(ratio: number): 'red' | 'yellow' | 'green' {
  const percent = Math.max(0, Math.min(1, ratio)) * 100
  if (percent < 33) return 'red'
  if (percent < 66) return 'yellow'
  return 'green'
}

export function SpecV04Shell({
  title,
  subtitle,
  badge,
  tiles,
  filters,
  children,
  onAskOrchestrator
}: SpecV04ShellProps): React.JSX.Element {
  return (
    <div className="wp-page spec-v04-page">
      <div className="wp-head spec-v04-head">
        <div>
          <div className="wp-head-title-row">
            <h1 className="page-title">{title}</h1>
            {badge ? <span className="orch-badge">{badge}</span> : null}
          </div>
          <div className="wp-sub">{subtitle}</div>
        </div>
      </div>

      <div className="spec-v04-tiles">
        {tiles.map((tile) => (
          <article key={tile.id} className={`spec-v04-tile tone-${tile.tone || 'neutral'}`}>
            <span className="spec-v04-tile-label">{tile.label}</span>
            <strong className="spec-v04-tile-value">{tile.value}</strong>
            {tile.hint ? <small>{tile.hint}</small> : null}
          </article>
        ))}
      </div>

      {filters ? <div className="spec-v04-filters">{filters}</div> : null}

      <div className="spec-v04-body">{children}</div>

      {onAskOrchestrator ? (
        <SpecAskOrchestrator onSubmit={onAskOrchestrator} />
      ) : null}
    </div>
  )
}

function SpecAskOrchestrator({ onSubmit }: { onSubmit: (message: string) => void }): React.JSX.Element {
  return (
    <section className="spec-ask-orch wp-card">
      <h2 className="spec-ask-orch-title">Спросить Оркестратора</h2>
      <p className="spec-ask-orch-hint">Вопрос отправляется в контексте текущей вкладки.</p>
      <form
        className="spec-ask-orch-form"
        onSubmit={(event) => {
          event.preventDefault()
          const form = event.currentTarget
          const input = form.elements.namedItem('q') as HTMLInputElement | null
          const text = (input?.value || '').trim()
          if (!text) return
          onSubmit(text)
          if (input) input.value = ''
        }}
      >
        <input name="q" type="text" placeholder="Сформулируйте вопрос…" autoComplete="off" />
        <button type="submit" className="btn-primary">
          Отправить
        </button>
      </form>
    </section>
  )
}
