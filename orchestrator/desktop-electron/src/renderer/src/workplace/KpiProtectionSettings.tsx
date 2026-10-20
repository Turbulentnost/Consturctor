import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { ApiError } from '../api/types'
import { useKpiProtection, writeKpiUnlock } from './kpiProtection'

export function KpiProtectionSettings({ userId }: { userId: string }): React.JSX.Element {
  const protection = useKpiProtection(userId)
  const [enabled, setEnabled] = useState(false)
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<{ text: string; error: boolean } | null>(null)

  useEffect(() => {
    if (protection.loaded) setEnabled(protection.enabled)
  }, [protection.loaded, protection.enabled])

  const dirty = enabled !== protection.enabled || Boolean(next)

  const save = async (): Promise<void> => {
    if (busy) return
    if (next !== repeat) {
      setNote({ text: 'Новый пароль и повтор не совпадают', error: true })
      return
    }
    if (enabled && !protection.hasPassword && !next) {
      setNote({ text: 'Задайте пароль, чтобы включить защиту', error: true })
      return
    }
    if (protection.hasPassword && !current) {
      setNote({ text: 'Введите текущий пароль KPI', error: true })
      return
    }
    setBusy(true)
    setNote(null)
    try {
      await api.updateKpiProtection({ enabled, password: next || undefined, currentPassword: current || undefined })
      writeKpiUnlock(userId, null)
      setCurrent('')
      setNext('')
      setRepeat('')
      setNote({ text: enabled ? 'Защита KPI включена' : 'Защита KPI выключена', error: false })
    } catch (err: unknown) {
      setNote({ text: err instanceof ApiError ? err.message : 'Не удалось сохранить защиту KPI', error: true })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="set-card kpi-protect-card">
      <h2>Защита данных KPI</h2>
      <p className="set-muted">
        При входе во вкладку KPI будет спрашиваться пароль. После ввода пароля форма премирования выгружается в рублях:
        оклад и база премии берутся из 1С:ЗУП. Без пароля форма остаётся в процентах.
      </p>
      <label className="kpi-protect-toggle">
        <span className="set-switch">
          <input
            type="checkbox"
            checked={enabled}
            disabled={!protection.loaded || busy}
            onChange={(event) => setEnabled(event.target.checked)}
            aria-label="Требовать пароль при входе в KPI"
          />
          <span className="set-switch-track" aria-hidden>
            <span className="set-switch-thumb" />
          </span>
        </span>
        <span>Требовать пароль при входе в KPI</span>
      </label>
      <div className="kpi-protect-fields">
        {protection.hasPassword ? (
          <input
            className="wp-search"
            type="password"
            autoComplete="current-password"
            placeholder="Текущий пароль KPI"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
          />
        ) : null}
        <input
          className="wp-search"
          type="password"
          autoComplete="new-password"
          placeholder={protection.hasPassword ? 'Новый пароль (если меняете)' : 'Пароль KPI, не короче 4 символов'}
          value={next}
          onChange={(event) => setNext(event.target.value)}
        />
        {next ? (
          <input
            className="wp-search"
            type="password"
            autoComplete="new-password"
            placeholder="Повторите пароль"
            value={repeat}
            onChange={(event) => setRepeat(event.target.value)}
          />
        ) : null}
      </div>
      {note ? <p className={`kpi-protect-note${note.error ? ' is-error' : ''}`}>{note.text}</p> : null}
      <div className="wp-actions set-widget-actions">
        <button className="btn-primary" type="button" disabled={busy || !dirty} onClick={() => void save()}>
          {busy ? 'Сохраняю…' : 'Сохранить защиту'}
        </button>
      </div>
    </section>
  )
}
