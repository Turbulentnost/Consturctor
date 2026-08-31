import { useEffect, useState } from 'react'
import { FormationBanner } from './FormationBanner'

export interface BannerEntry {
  id: string
  title: string
  output: string
  running: boolean
  awaiting: boolean
  mode?: 'formation' | 'run'
  onOpen: () => void
}

/**
 * Unified top widget for every agent that is currently working: agents in
 * formation and running published agents. When more than one is active it turns
 * into a left/right slider so the user can page through them.
 */
export function RunBannerCarousel({ entries }: { entries: BannerEntry[] }): React.JSX.Element | null {
  const [index, setIndex] = useState(0)

  useEffect(() => {
    if (index > entries.length - 1) setIndex(Math.max(0, entries.length - 1))
  }, [entries.length, index])

  if (entries.length === 0) return null
  const safeIndex = Math.min(index, entries.length - 1)
  const entry = entries[safeIndex]
  const multi = entries.length > 1

  return (
    <div className={multi ? 'run-banner-carousel multi' : 'run-banner-carousel'}>
      {multi && (
        <>
          <button
            className="run-banner-nav prev"
            title="Предыдущий агент"
            onClick={() => setIndex((i) => (i - 1 + entries.length) % entries.length)}
          >
            {'\u2039'}
          </button>
          <span className="run-banner-count">
            {safeIndex + 1}/{entries.length}
          </span>
        </>
      )}
      <FormationBanner
        key={entry.id}
        title={entry.title}
        output={entry.output}
        running={entry.running}
        awaiting={entry.awaiting}
        mode={entry.mode}
        onOpen={entry.onOpen}
      />
      {multi && (
        <button
          className="run-banner-nav next"
          title="Следующий агент"
          onClick={() => setIndex((i) => (i + 1) % entries.length)}
        >
          {'\u203A'}
        </button>
      )}
    </div>
  )
}
