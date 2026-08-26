export interface Stage {
  id: string
  label: string
}

export const FORMATION_STAGES: Stage[] = [
  { id: 'document', label: 'Материалы' },
  { id: 'designed', label: 'Черновик' },
  { id: 'executing', label: 'Пробный прогон' },
  { id: 'tested', label: 'Инструкция' },
  { id: 'done', label: 'Готово' }
]

interface StageStepperProps {
  stages?: Stage[]
  currentIndex: number
}

export function StageStepper({
  stages = FORMATION_STAGES,
  currentIndex
}: StageStepperProps): React.JSX.Element {
  return (
    <div className="stage-stepper">
      {stages.map((stage, index) => {
        const state =
          index < currentIndex ? 'done' : index === currentIndex ? 'active' : 'pending'
        return (
          <div key={stage.id} className={`stage-step ${state}`}>
            <span className="stage-dot">{index < currentIndex ? '✓' : index + 1}</span>
            <span className="stage-label">{stage.label}</span>
            {index < stages.length - 1 && <span className="stage-line" />}
          </div>
        )
      })}
    </div>
  )
}
