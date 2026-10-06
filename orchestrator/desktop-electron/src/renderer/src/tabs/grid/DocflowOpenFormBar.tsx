import { SquarePen } from 'lucide-react'

const GUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** Над карточкой журнала: открыть документ в форме 1С — изменить, создать на основании, скопировать, файлы. */
export function DocflowOpenFormBar({
  refKey,
  onOpen
}: {
  refKey: string
  onOpen?: () => void
}): React.JSX.Element | null {
  if (!onOpen || !GUID_RE.test(refKey || '')) return null
  return (
    <div className="docflow-open-form">
      <button type="button" className="docflow-edit-btn is-primary" onClick={onOpen}>
        <SquarePen size={14} aria-hidden /> Открыть форму
      </button>
      <span>Изменить, создать на основании, скопировать, файлы · или двойной щелчок по строке</span>
    </div>
  )
}
