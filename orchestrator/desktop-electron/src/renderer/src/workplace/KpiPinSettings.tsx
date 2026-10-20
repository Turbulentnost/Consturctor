import { useState } from 'react'
import { PinWizard, type PinWizardFailure } from '../components/PinCode'
import { useKpiPin } from './useKpiPin'

export function KpiPinSettings(): React.JSX.Element {
  const pin = useKpiPin()
  const [round, setRound] = useState(0)
  const [note, setNote] = useState('')

  const changePin = async ([current, next, repeat]: string[]): Promise<PinWizardFailure | null> => {
    if (next !== repeat) return { message: 'Новые PIN-коды не совпадают', restartAt: 1 }
    if (next === current) return { message: 'Новый PIN-код совпадает со старым', restartAt: 1 }
    const failure = await pin.change(current, next, repeat)
    if (failure) return { message: failure, restartAt: /старый|попыток/i.test(failure) ? 0 : 1 }
    setNote('PIN-код изменён')
    setRound((value) => value + 1)
    return null
  }

  const createPin = async ([next, repeat]: string[]): Promise<PinWizardFailure | null> => {
    if (next !== repeat) return { message: 'PIN-коды не совпадают' }
    const failure = await pin.create(next, repeat)
    if (failure) return { message: failure }
    setNote('PIN-код задан')
    setRound((value) => value + 1)
    return null
  }

  return (
    <section className="set-card set-pin-card">
      <h2>PIN-код для зарплаты</h2>
      <p className="set-muted">
        Без него оклад и премия на странице KPI скрыты. Код знаете только вы: в базе хранится лишь его отпечаток.
      </p>
      {!pin.loaded ? (
        <p className="set-muted">Проверяем…</p>
      ) : pin.error ? (
        <p className="kpi-protect-note is-error">{pin.error}</p>
      ) : (
        <div className="set-pin-body" onFocus={() => setNote('')}>
          <PinWizard
            key={`${pin.hasPin ? 'change' : 'create'}-${round}`}
            steps={
              pin.hasPin
                ? ['Введите старый PIN-код', 'Придумайте новый PIN-код', 'Повторите новый PIN-код']
                : ['Придумайте PIN-код', 'Повторите PIN-код']
            }
            onDone={pin.hasPin ? changePin : createPin}
            autoFocus={false}
          />
          {note ? <p className="kpi-protect-note set-pin-done">{note}</p> : null}
        </div>
      )}
    </section>
  )
}
