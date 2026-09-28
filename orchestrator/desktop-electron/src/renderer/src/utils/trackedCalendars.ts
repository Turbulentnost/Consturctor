import { useCallback, useEffect, useState } from 'react'

export const TRACKED_CALENDARS_EVENT = 'orchestrator:tracked-calendars-changed'
export const CALENDAR_STATUS_EVENT = 'orchestrator:calendar-status-changed'

export type CalendarReadStatus = { person: string; count: number; hint?: string }

const STATUS_KEY = 'orch-calendar-status-v1'

function storageKey(fio: string): string {
  return `orch-tracked-calendars-v1:${fio.trim().toLocaleLowerCase('ru') || 'default'}`
}

function samePerson(left: string, right: string): boolean {
  return left.trim().toLocaleLowerCase('ru') === right.trim().toLocaleLowerCase('ru')
}

export function readTrackedCalendars(fio: string): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey(fio)) || '[]') as unknown
    return Array.isArray(parsed) ? parsed.map((item) => String(item || '').trim()).filter(Boolean) : []
  } catch {
    return []
  }
}

function writeTrackedCalendars(fio: string, people: string[]): void {
  try {
    localStorage.setItem(storageKey(fio), JSON.stringify(people))
  } catch {
    /* ignore quota */
  }
  window.dispatchEvent(new CustomEvent(TRACKED_CALENDARS_EVENT))
}

export function readCalendarStatus(): CalendarReadStatus[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(STATUS_KEY) || '[]') as unknown
    return Array.isArray(parsed) ? (parsed as CalendarReadStatus[]) : []
  } catch {
    return []
  }
}

export function publishCalendarStatus(calendars: CalendarReadStatus[]): void {
  try {
    localStorage.setItem(STATUS_KEY, JSON.stringify(calendars))
  } catch {
    /* ignore quota */
  }
  window.dispatchEvent(new CustomEvent(CALENDAR_STATUS_EVENT))
}

export function calendarStatusFor(person: string, statuses: CalendarReadStatus[]): CalendarReadStatus | undefined {
  return statuses.find((item) => samePerson(item.person, person))
}

/** Bumps when the tracked list changes, so calendar loaders can refetch. */
export function useTrackedCalendarsVersion(): number {
  const [version, setVersion] = useState(0)
  useEffect(() => {
    const bump = (): void => setVersion((value) => value + 1)
    window.addEventListener(TRACKED_CALENDARS_EVENT, bump)
    return () => window.removeEventListener(TRACKED_CALENDARS_EVENT, bump)
  }, [])
  return version
}

export function useTrackedCalendars(fio: string): {
  people: string[]
  statuses: CalendarReadStatus[]
  add: (person: string) => void
  remove: (person: string) => void
} {
  const [people, setPeople] = useState(() => readTrackedCalendars(fio))
  const [statuses, setStatuses] = useState(readCalendarStatus)

  useEffect(() => {
    const sync = (): void => setPeople(readTrackedCalendars(fio))
    const syncStatus = (): void => setStatuses(readCalendarStatus())
    sync()
    window.addEventListener(TRACKED_CALENDARS_EVENT, sync)
    window.addEventListener(CALENDAR_STATUS_EVENT, syncStatus)
    return () => {
      window.removeEventListener(TRACKED_CALENDARS_EVENT, sync)
      window.removeEventListener(CALENDAR_STATUS_EVENT, syncStatus)
    }
  }, [fio])

  const add = useCallback(
    (person: string) => {
      const name = person.trim().replace(/\s+/g, ' ')
      if (!name || samePerson(name, fio)) return
      const current = readTrackedCalendars(fio)
      if (current.some((item) => samePerson(item, name))) return
      writeTrackedCalendars(fio, [...current, name])
    },
    [fio]
  )

  const remove = useCallback(
    (person: string) => {
      writeTrackedCalendars(
        fio,
        readTrackedCalendars(fio).filter((item) => !samePerson(item, person))
      )
    },
    [fio]
  )

  return { people, statuses, add, remove }
}
