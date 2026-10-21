import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'

const ErrorToastContext = createContext<(message: string) => void>(() => undefined)

export function useErrorToast(): (message: string) => void {
  return useContext(ErrorToastContext)
}

/** Показать текст ошибки тем же верхним блоком, если он ещё не на экране. */
export function useReportError(message: string | undefined | null): void {
  const report = useErrorToast()
  const shown = useRef('')
  useEffect(() => {
    const text = (message || '').trim()
    if (!text) {
      shown.current = ''
      return
    }
    if (text === shown.current) return
    shown.current = text
    report(text)
  }, [message, report])
}

export function ErrorToastProvider({ children }: { children: ReactNode }): React.JSX.Element {
  const [message, setMessage] = useState('')
  const [leaving, setLeaving] = useState(false)
  const [copied, setCopied] = useState(false)

  const report = useCallback((text: string) => {
    const next = text.trim()
    if (!next) return
    setMessage((current) => (current === next ? current : next))
    setLeaving(false)
    setCopied(false)
  }, [])

  useEffect(() => {
    if (!message) return
    const hide = window.setTimeout(() => setLeaving(true), 5200)
    const gone = window.setTimeout(() => setMessage(''), 5600)
    return () => {
      window.clearTimeout(hide)
      window.clearTimeout(gone)
    }
  }, [message])

  async function copyError(): Promise<void> {
    if (!message) return
    try {
      await navigator.clipboard.writeText(message)
    } catch {
      const area = document.createElement('textarea')
      area.value = message
      document.body.appendChild(area)
      area.select()
      document.execCommand('copy')
      area.remove()
    }
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1400)
  }

  return (
    <ErrorToastContext.Provider value={report}>
      {children}
      {message ? (
        <div className={leaving ? 'login-toast is-leaving' : 'login-toast'} role="alert">
          <p>{message}</p>
          <button type="button" className="login-toast-copy" onClick={() => void copyError()} title="Скопировать">
            {copied ? (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
                <path d="M5 12.5l4.2 4.2L19 7.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
                <rect x="8" y="8" width="11" height="11" rx="2" stroke="currentColor" strokeWidth="1.7" />
                <path d="M6 16V6.5A1.5 1.5 0 017.5 5H16" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              </svg>
            )}
          </button>
        </div>
      ) : null}
    </ErrorToastContext.Provider>
  )
}
