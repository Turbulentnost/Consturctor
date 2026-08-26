interface StatTileProps {
  icon: string
  text: string
}

export function StatTile({ icon, text }: StatTileProps): React.JSX.Element {
  return (
    <div className="stat-tile">
      <img className="stat-tile-icon" src={icon} alt="" />
      <span className="stat-tile-text">{text}</span>
    </div>
  )
}
