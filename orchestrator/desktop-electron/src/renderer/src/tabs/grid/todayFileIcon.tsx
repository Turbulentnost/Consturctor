import { fileTypeIconSrc } from '../../utils/fileTypeIcon'

export type TodayFileKind = 'doc' | 'pdf' | 'xls' | 'csv'

export function fileKindFromName(name: string): TodayFileKind {
  const lower = (name || '').toLowerCase()
  if (/\.pdf$/.test(lower)) return 'pdf'
  if (/\.csv$/.test(lower)) return 'csv'
  if (/\.(xlsx?|xlsm)$/.test(lower)) return 'xls'
  return 'doc'
}

export function TodayFileIcon({
  name,
  kind,
  size = 28
}: {
  name: string
  kind?: TodayFileKind
  size?: number
}): React.JSX.Element {
  const label = kind ? `${kind} file` : name
  return (
    <img
      className="today-file-ico"
      src={fileTypeIconSrc(name)}
      alt=""
      title={name}
      aria-label={label}
      width={size}
      height={size}
      loading="lazy"
      decoding="async"
    />
  )
}
