import { useCallback, useEffect, useState } from 'react'

export const TRACKED_CALENDARS_EVENT = 'orchestrator:tracked-calendars-changed'
export const CALENDAR_STATUS_EVENT = 'orchestrator:calendar-status-changed'
/** Порядок — чистое оформление, перечитывать Outlook из-за него не нужно. */
export const CALENDAR_ORDER_EVENT = 'orchestrator:calendar-order-changed'

export type CalendarReadStatus = { person: string; count: number; hint?: string }

const STATUS_KEY = 'orch-calendar-status-v1'

function orderKey(fio: string): string {
  return `orch-calendar-order-v1:${fio.trim().toLocaleLowerCase('ru') || 'default'}`
}

/** Порядок календарей = приоритет показа в пересечениях: первый виден поверх. */
export function readCalendarOrder(fio: string): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(orderKey(fio)) || '[]') as unknown
    return Array.isArray(parsed) ? parsed.map((item) => String(item || '').trim()).filter(Boolean) : []
  } catch {
    return []
  }
}

export function writeCalendarOrder(fio: string, order: string[]): void {
  try {
    localStorage.setItem(orderKey(fio), JSON.stringify(order))
  } catch {
    /* ignore quota */
  }
  window.dispatchEvent(new CustomEvent(CALENDAR_ORDER_EVENT))
}

function storageKey(fio: string): string {
  return `orch-tracked-calendars-v1:${fio.trim().toLocaleLowerCase('ru') || 'default'}`
}

/** Слот цвета, закреплённый за человеком. Слот 0 всегда у своего календаря. */
export type CalendarColorSlot = { person: string; slot: number }

function colorsKey(fio: string): string {
  return `orch-calendar-colors-v1:${fio.trim().toLocaleLowerCase('ru') || 'default'}`
}

export function readCalendarColorSlots(fio: string): CalendarColorSlot[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(colorsKey(fio)) || '[]') as unknown
    if (!Array.isArray(parsed)) return []
    return parsed
      .map((item) => ({
        person: String((item as CalendarColorSlot)?.person || '').trim(),
        slot: Number((item as CalendarColorSlot)?.slot)
      }))
      .filter((item) => item.person && Number.isInteger(item.slot) && item.slot >= 0)
  } catch {
    return []
  }
}

function writeCalendarColorSlots(fio: string, slots: CalendarColorSlot[]): void {
  try {
    localStorage.setItem(colorsKey(fio), JSON.stringify(slots))
  } catch {
    /* ignore quota */
  }
  window.dispatchEvent(new CustomEvent(CALENDAR_ORDER_EVENT))
}

function personParts(value: string): { surname: string; initials: string[] } {
  const parts = String(value || '')
    .replace(/\./g, ' ')
    .trim()
    .toLocaleLowerCase('ru')
    .split(/\s+/)
    .filter(Boolean)
  return { surname: parts[0] || '', initials: parts.slice(1, 3).map((part) => part[0]) }
}

/**
 * «Амураль» ≡ «Амураль И.Б.» ≡ «Амураль Игорь Борисович».
 * Сверяем фамилию и те инициалы, которые известны обеим записям: человека часто
 * добавляют одной фамилией, и такой календарь не должен встать вторым в список.
 */
export function samePersonFio(left: string, right: string): boolean {
  const first = personParts(left)
  const second = personParts(right)
  if (!first.surname || first.surname !== second.surname) return false
  const depth = Math.min(first.initials.length, second.initials.length)
  for (let index = 0; index < depth; index += 1) {
    if (first.initials[index] !== second.initials[index]) return false
  }
  return true
}

function samePerson(left: string, right: string): boolean {
  return samePersonFio(left, right)
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
  order: string[]
  colorSlots: CalendarColorSlot[]
  add: (person: string) => void
  remove: (person: string) => void
  setOrder: (order: string[]) => void
  setColor: (person: string, slot: number) => void
} {
  const [people, setPeople] = useState(() => readTrackedCalendars(fio))
  const [statuses, setStatuses] = useState(readCalendarStatus)
  const [order, setOrderState] = useState(() => readCalendarOrder(fio))
  const [colorSlots, setColorSlots] = useState(() => readCalendarColorSlots(fio))

  useEffect(() => {
    const syncOrder = (): void => {
      setOrderState(readCalendarOrder(fio))
      setColorSlots(readCalendarColorSlots(fio))
    }
    const sync = (): void => {
      setPeople(readTrackedCalendars(fio))
      syncOrder()
    }
    const syncStatus = (): void => setStatuses(readCalendarStatus())
    sync()
    window.addEventListener(TRACKED_CALENDARS_EVENT, sync)
    window.addEventListener(CALENDAR_ORDER_EVENT, syncOrder)
    window.addEventListener(CALENDAR_STATUS_EVENT, syncStatus)
    return () => {
      window.removeEventListener(TRACKED_CALENDARS_EVENT, sync)
      window.removeEventListener(CALENDAR_ORDER_EVENT, syncOrder)
      window.removeEventListener(CALENDAR_STATUS_EVENT, syncStatus)
    }
  }, [fio])

  // Календари, добавленные до появления слотов, закрепляем по их текущим позициям —
  // иначе удаление соседа перекрашивало бы оставшиеся.
  useEffect(() => {
    if (!people.length || colorSlots.length) return
    writeCalendarColorSlots(
      fio,
      people.map((person, index) => ({ person, slot: index + 1 }))
    )
  }, [fio, people, colorSlots.length])

  const add = useCallback(
    (person: string) => {
      const name = person.trim().replace(/\s+/g, ' ')
      if (!name || samePerson(name, fio)) return
      const current = readTrackedCalendars(fio)
      if (current.some((item) => samePerson(item, name))) return
      writeTrackedCalendars(fio, [...current, name])
      // Занимаем самый младший свободный слот цвета и держим его за человеком.
      const slots = readCalendarColorSlots(fio)
      if (!slots.some((item) => samePerson(item.person, name))) {
        const taken = new Set(slots.map((item) => item.slot))
        let slot = 1
        while (taken.has(slot)) slot += 1
        writeCalendarColorSlots(fio, [...slots, { person: name, slot }])
      }
    },
    [fio]
  )

  const remove = useCallback(
    (person: string) => {
      writeTrackedCalendars(
        fio,
        readTrackedCalendars(fio).filter((item) => !samePerson(item, person))
      )
      writeCalendarOrder(
        fio,
        readCalendarOrder(fio).filter((item) => !samePerson(item, person))
      )
      // Слот освобождаем, чтобы следующий добавленный календарь его переиспользовал.
      writeCalendarColorSlots(
        fio,
        readCalendarColorSlots(fio).filter((item) => !samePerson(item.person, person))
      )
    },
    [fio]
  )

  const setOrder = useCallback((next: string[]) => writeCalendarOrder(fio, next), [fio])

  const setColor = useCallback(
    (person: string, slot: number) => {
      const name = person.trim()
      if (!name || !Number.isInteger(slot) || slot < 0) return
      const slots = readCalendarColorSlots(fio).filter((item) => !samePerson(item.person, name))
      writeCalendarColorSlots(fio, [...slots, { person: name, slot }])
    },
    [fio]
  )

  return { people, statuses, order, colorSlots, add, remove, setOrder, setColor }
}
