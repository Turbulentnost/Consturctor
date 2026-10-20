/**
 * День, который нужно открыть во вкладке совещаний при переходе из «Сегодня».
 * Вкладка монтируется заново при переходе, поэтому передаём через модульное значение.
 */
let requestedDay: Date | null = null

export function requestMeetingsDay(day: Date): void {
  requestedDay = new Date(day.getFullYear(), day.getMonth(), day.getDate())
}

export function peekRequestedMeetingsDay(): Date | null {
  return requestedDay
}

export function clearRequestedMeetingsDay(): void {
  requestedDay = null
}
