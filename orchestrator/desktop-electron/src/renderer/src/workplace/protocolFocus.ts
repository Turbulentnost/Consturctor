/**
 * Протокол, который нужно открыть в документообороте при переходе из «Сегодня».
 * Вкладка монтируется заново, поэтому ссылка передаётся через модульное значение.
 */
export type ProtocolFocus = {
  id: string
  date: string
  number: string
}

let requested: ProtocolFocus | null = null

export function requestProtocolFocus(focus: ProtocolFocus): void {
  const id = focus.id.trim()
  if (!id) {
    requested = null
    return
  }
  requested = { id, date: focus.date.slice(0, 10), number: focus.number.trim() }
}

export function peekProtocolFocus(): ProtocolFocus | null {
  return requested
}

export function clearProtocolFocus(): void {
  requested = null
}
