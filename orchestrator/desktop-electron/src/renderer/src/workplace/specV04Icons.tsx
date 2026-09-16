/** Inline SVG-иконки для v0.4 (без внешних ассетов). */

export function SpecIconReg(): React.JSX.Element {
  return (
    <svg className="spec-tile-ico" viewBox="0 0 24 24" aria-hidden>
      <path
        fill="currentColor"
        d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2V5a2 2 0 0 0-2-2H11a2 2 0 0 0-2 2v0zm2 0h2v2h-2V5zm-2 4h10v10H7V9zm2 2v2h6v-2H9zm0 4v2h4v-2H9z"
      />
    </svg>
  )
}

export function SpecIconOnec(): React.JSX.Element {
  return (
    <svg className="spec-tile-ico" viewBox="0 0 24 24" aria-hidden>
      <path
        fill="currentColor"
        d="M4 4h16v2H4V4zm0 5h10v2H4V9zm0 5h16v2H4v-2zm0 5h10v2H4v-2z"
      />
    </svg>
  )
}

export function SpecIconProject(): React.JSX.Element {
  return (
    <svg className="spec-tile-ico" viewBox="0 0 24 24" aria-hidden>
      <path
        fill="currentColor"
        d="M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2z"
      />
    </svg>
  )
}

export function SpecIconMail(): React.JSX.Element {
  return (
    <svg className="spec-tile-ico" viewBox="0 0 24 24" aria-hidden>
      <path
        fill="currentColor"
        d="M20 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zm0 4-8 5L4 8V6l8 5 8-5v2z"
      />
    </svg>
  )
}

export function SpecIconMeeting(): React.JSX.Element {
  return (
    <svg className="spec-tile-ico" viewBox="0 0 24 24" aria-hidden>
      <path
        fill="currentColor"
        d="M7 2h2v2h6V2h2v2h3a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h3V2zm13 8H4v10h16V10zM6 12h4v2H6v-2z"
      />
    </svg>
  )
}

export function SpecIconSearch(): React.JSX.Element {
  return (
    <svg className="spec-filter-ico" viewBox="0 0 24 24" aria-hidden>
      <path
        fill="currentColor"
        d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C8.01 14 6 11.99 6 9.5S8.01 5 10.5 5 15 7.01 15 9.5 12.99 14 10.5 14z"
      />
    </svg>
  )
}

export function SpecIconCalendar(): React.JSX.Element {
  return (
    <svg className="spec-filter-ico" viewBox="0 0 24 24" aria-hidden>
      <path
        fill="currentColor"
        d="M7 2h2v2h6V2h2v2h3a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h3V2zm13 8H4v10h16V10z"
      />
    </svg>
  )
}

export function SpecIconPlay(): React.JSX.Element {
  return (
    <svg className="spec-launch-play" viewBox="0 0 24 24" aria-hidden>
      <path fill="currentColor" d="M8 5v14l11-7L8 5z" />
    </svg>
  )
}

const TILE_ICON: Record<string, () => React.JSX.Element> = {
  day: SpecIconReg,
  reg: SpecIconReg,
  onec: SpecIconOnec,
  'onec-from-me': SpecIconOnec,
  proj: SpecIconProject,
  mail: SpecIconMail,
  meet: SpecIconMeeting,
  ev: SpecIconMeeting
}

export function SpecTileIcon({ id }: { id: string }): React.JSX.Element | null {
  const Icon = TILE_ICON[id]
  if (!Icon) return null
  const tone =
    id === 'meet' || id === 'ev'
      ? 'yellow'
      : id === 'day'
        ? 'orange'
        : id === 'proj'
          ? 'proj'
          : id === 'onec-from-me'
            ? 'onec'
            : id
  return (
    <span className={`spec-tile-icon-wrap tone-${tone}`} aria-hidden>
      <Icon />
    </span>
  )
}
