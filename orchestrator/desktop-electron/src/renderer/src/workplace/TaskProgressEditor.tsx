import { useEffect, useState } from 'react'
import { stageProgressTone } from './specV04Shell'
import { getStoredTaskProgress, saveStoredTaskProgress } from './taskProgressStore'

export function TaskProgressEditor({
  rowId,
  baseProgress,
  onSaved
}: {
  rowId: string
  baseProgress: number
  onSaved?: (value: number) => void
}): React.JSX.Element {
  const [saved, setSaved] = useState(() => getStoredTaskProgress(rowId, baseProgress))
  const [draft, setDraft] = useState(saved)

  useEffect(() => {
    const next = getStoredTaskProgress(rowId, baseProgress)
    setSaved(next)
    setDraft(next)
  }, [rowId, baseProgress])

  const dirty = draft !== saved
  const tone = stageProgressTone(draft / 100)

  const persist = (): void => {
    const next = saveStoredTaskProgress(rowId, draft)
    setSaved(next)
    setDraft(next)
    onSaved?.(next)
  }

  return (
    <div className="task-progress-editor">
      <div className="task-progress-editor-head">
        <span className="task-progress-editor-label">Прогресс выполнения</span>
        <span className="task-progress-editor-value">{draft}%</span>
      </div>
      <input
        type="range"
        className="task-progress-slider"
        min={0}
        max={100}
        step={1}
        value={draft}
        onChange={(e) => setDraft(Number(e.target.value))}
        aria-label="Прогресс выполнения"
      />
      <div className={`spec-progress-bar tone-${tone} task-progress-slider-track`}>
        <i style={{ width: `${draft}%` }} />
      </div>
      {dirty ? (
        <button type="button" className="spec-btn-launch spec-btn-launch-block task-progress-save" onClick={persist}>
          Сохранить
        </button>
      ) : null}
    </div>
  )
}

/** Progress for table cells: stored override or base. */
export function displayTaskProgress(rowId: string, baseProgress: number): number {
  return getStoredTaskProgress(rowId, baseProgress)
}
