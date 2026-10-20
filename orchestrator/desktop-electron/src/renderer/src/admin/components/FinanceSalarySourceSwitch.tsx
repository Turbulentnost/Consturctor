import { useEffect, useState } from 'react'
import { api } from '../../api/client'

type SalarySourceMode = 'file' | 'onec'

interface SalarySourceState {
  mode: SalarySourceMode
  canUseFile: boolean
}

function parseState(value: unknown): SalarySourceState {
  const source = value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
  const mode = source.mode === 'file' ? 'file' : 'onec'
  return { mode, canUseFile: source.can_use_file === true }
}

export function FinanceSalarySourceSwitch(): React.JSX.Element {
  const [state, setState] = useState<SalarySourceState>({ mode: 'onec', canUseFile: false })
  const [ready, setReady] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let active = true
    void api
      .adminFinanceSalarySource()
      .then((payload) => {
        if (active) setState(parseState(payload))
      })
      .catch(() => {
        if (active) setState({ mode: 'onec', canUseFile: false })
      })
      .finally(() => {
        if (active) setReady(true)
      })
    return () => {
      active = false
    }
  }, [])

  async function choose(mode: SalarySourceMode): Promise<void> {
    if (saving || mode === state.mode) return
    if (mode === 'file' && !state.canUseFile) return
    setSaving(true)
    try {
      setState(parseState(await api.updateAdminFinanceSalarySource(mode)))
    } catch {
      /* keep the previous source */
    } finally {
      setSaving(false)
    }
  }

  const fileLocked = !state.canUseFile
  return (
    <div className="finance-source-switch" role="group" aria-label="Источник зарплаты">
      <button
        type="button"
        aria-pressed={state.mode === 'file'}
        disabled={!ready || saving || fileLocked}
        title={fileLocked ? 'Пока не загружен ни один файл зарплат' : 'Оклад из загруженного файла'}
        onClick={() => void choose('file')}
      >
        Файл
      </button>
      <button
        type="button"
        aria-pressed={state.mode === 'onec'}
        disabled={!ready || saving}
        title="Оклад из 1С"
        onClick={() => void choose('onec')}
      >
        1С
      </button>
    </div>
  )
}
