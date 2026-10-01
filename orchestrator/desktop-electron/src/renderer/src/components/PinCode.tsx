import { useEffect, useRef, useState } from 'react'
import './pinCode.css'

export const PIN_LENGTH = 4

export function PinEntry({
  value,
  onChange,
  onComplete,
  label,
  disabled = false,
  invalid = false,
  shakeKey = 0,
  autoFocus = false
}: {
  value: string
  onChange: (value: string) => void
  onComplete?: (value: string) => void
  label: string
  disabled?: boolean
  invalid?: boolean
  /** Меняется при каждой ошибке — точки заново встряхиваются. */
  shakeKey?: number
  autoFocus?: boolean
}): React.JSX.Element {
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (autoFocus && !disabled) inputRef.current?.focus()
  }, [autoFocus, disabled, shakeKey])

  return (
    <label className={`pin-entry${invalid ? ' is-invalid' : ''}${disabled ? ' is-disabled' : ''}`}>
      <input
        ref={inputRef}
        className="pin-entry-input"
        type="password"
        inputMode="numeric"
        autoComplete="off"
        maxLength={PIN_LENGTH}
        value={value}
        disabled={disabled}
        aria-label={label}
        onChange={(event) => {
          const next = event.target.value.replace(/\D/g, '').slice(0, PIN_LENGTH)
          onChange(next)
          if (next.length === PIN_LENGTH) onComplete?.(next)
        }}
      />
      <span key={shakeKey} className="pin-entry-dots" aria-hidden>
        {Array.from({ length: PIN_LENGTH }, (_, index) => (
          <i key={index} className={index < value.length ? 'is-filled' : ''} />
        ))}
      </span>
    </label>
  )
}

export interface PinWizardFailure {
  message: string
  /** С какого шага начать заново (по умолчанию с первого). */
  restartAt?: number
}

/** Ввод нескольких PIN подряд: «придумайте → повторите» или «старый → новый → ещё раз». */
export function PinWizard({
  steps,
  onDone,
  autoFocus = true,
  footer
}: {
  steps: string[]
  onDone: (values: string[]) => Promise<PinWizardFailure | null>
  autoFocus?: boolean
  footer?: React.ReactNode
}): React.JSX.Element {
  const [index, setIndex] = useState(0)
  const [values, setValues] = useState<string[]>([])
  const [current, setCurrent] = useState('')
  const [error, setError] = useState('')
  const [shakeKey, setShakeKey] = useState(0)
  const [busy, setBusy] = useState(false)

  const complete = async (pin: string): Promise<void> => {
    const collected = [...values.slice(0, index), pin]
    if (index < steps.length - 1) {
      setValues(collected)
      setIndex(index + 1)
      setCurrent('')
      setError('')
      return
    }
    setBusy(true)
    const failure = await onDone(collected)
    setBusy(false)
    if (!failure) return
    const restartAt = Math.max(0, Math.min(failure.restartAt ?? 0, steps.length - 1))
    setError(failure.message)
    setShakeKey((key) => key + 1)
    setValues(collected.slice(0, restartAt))
    setIndex(restartAt)
    setCurrent('')
  }

  return (
    <div className="pin-wizard">
      {steps.length > 1 ? (
        <ol className="pin-wizard-steps" aria-hidden>
          {steps.map((step, stepIndex) => (
            <li key={step} className={stepIndex === index ? 'is-current' : stepIndex < index ? 'is-done' : ''} />
          ))}
        </ol>
      ) : null}
      <p className="pin-wizard-label">{busy ? 'Проверяем…' : steps[index]}</p>
      <PinEntry
        value={current}
        onChange={(next) => {
          setCurrent(next)
          if (next) setError('')
        }}
        onComplete={(pin) => void complete(pin)}
        label={steps[index]}
        disabled={busy}
        invalid={Boolean(error)}
        shakeKey={shakeKey}
        autoFocus={autoFocus}
      />
      <p className={`pin-wizard-error${error ? ' is-shown' : ''}`} role="alert">
        {error || ' '}
      </p>
      {index > 0 && !busy ? (
        <button
          type="button"
          className="pin-wizard-restart"
          onClick={() => {
            setIndex(0)
            setValues([])
            setCurrent('')
            setError('')
          }}
        >
          Начать заново
        </button>
      ) : null}
      {footer}
    </div>
  )
}
