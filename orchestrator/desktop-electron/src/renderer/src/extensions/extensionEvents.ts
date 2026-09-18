export const ORCH_EXTENSIONS_CHANGED = 'orch:extensions-changed'

export function notifyExtensionsChanged(userId: string): void {
  window.dispatchEvent(
    new CustomEvent(ORCH_EXTENSIONS_CHANGED, { detail: { userId: userId.trim() || 'default' } })
  )
}
