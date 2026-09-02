export interface Stage {
  id: string
  label: string
  doneHint: string
  activeHint: string
}

/** Formation stages, ported from desktop workflow_page._STAGES. */
export const FORMATION_STAGES: Stage[] = [
  { id: 'document', label: 'Материалы', doneHint: 'Файлы загружены', activeHint: 'Добавляем материалы' },
  {
    id: 'designed',
    label: 'Черновик',
    doneHint: 'Черновик готов',
    activeHint: 'Проектируем инструкцию по регламенту'
  },
  {
    id: 'executing',
    label: 'Пробный прогон',
    doneHint: 'Задача выполнена',
    activeHint: 'Агент делает задачу как Cursor'
  },
  {
    id: 'tested',
    label: 'Инструкция',
    doneHint: 'Инструкция готова',
    activeHint: 'Пишем правило для следующих запусков'
  },
  { id: 'done', label: 'Готово', doneHint: 'Агент сохранён', activeHint: 'Можно запускать агента' }
]

/** Phase -> stage rank, ported from desktop workflow_page._PHASE_RANK. */
export const PHASE_RANK: Record<string, number> = {
  document: 0,
  designing: 1,
  designed: 1,
  clarify: 1,
  plan: 2,
  ready: 2,
  executing: 2,
  tested: 3,
  done: 4
}

interface StageStepperProps {
  phase: string
  busy?: boolean
}

export function StageStepper({ phase, busy = false }: StageStepperProps): React.JSX.Element {
  const total = FORMATION_STAGES.length
  let rank = PHASE_RANK[phase] ?? 0
  if (phase === 'done') rank = total - 1
  const current = phase === 'done' ? total : Math.min(total, rank + 1)
  const pct = phase === 'done' ? 100 : Math.round((rank / Math.max(1, total - 1)) * 100)

  return (
    <div className="wf-stages">
      <div className="wf-stages-head">Создание агента</div>
      <div className="wf-stages-meta">
        Этап {current} из {total} · {pct}%
      </div>
      <div className="wf-progress">
        <span className="wf-progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="wf-stage-list">
        {FORMATION_STAGES.map((stage, index) => {
          const state = index < rank ? 'done' : index === rank ? 'active' : 'pending'
          return (
            <div key={stage.id} className={`wf-stage ${state}`}>
              <div className="wf-stage-rail">
                <span className="wf-stage-dot">{state === 'done' ? '\u2713' : ''}</span>
              </div>
              <div className="wf-stage-body">
                <div className="wf-stage-title">{stage.label}</div>
                <div className="wf-stage-hint">
                  {state === 'done' ? stage.doneHint : stage.activeHint}
                </div>
                {state === 'active' && (
                  <span className="wf-stage-badge">{busy ? 'Выполняется…' : 'Текущий этап'}</span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
