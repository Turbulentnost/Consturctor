import {
  isOutlookFolderOwner,
  meetingInstanceKey,
  sharedMeetingCalendarFor,
  type MeetingEvent
} from '../utils/outlookMeetings'
import { overlappingMeetingKeys } from '../utils/meetingOverlap'
import { samePersonFio } from '../utils/trackedCalendars'
import { meetingMatchesTile } from './tileFilters'

export type CalendarPalette = {
  /** Точка в легенде и подписи — самый насыщенный тон. */
  dot: string
  /** Заливка блока совещания: тот же тон, только светлый. */
  fill: string
  border: string
  text: string
}

/**
 * Цвет календаря берём по позиции в списке панели: им закрашен и кружок в легенде,
 * и сам блок совещания. Оттенки держим на одной светлоте, чтобы рядом стоящие
 * колонки не спорили друг с другом, а тёмный текст читался на любой заливке.
 */
const CALENDAR_PALETTES: CalendarPalette[] = [
  { dot: '#2F6BD8', fill: '#E7EFFC', border: '#A8C3F2', text: '#17325F' },
  { dot: '#7B57D6', fill: '#EFE9FB', border: '#C4B3F0', text: '#3A2870' },
  { dot: '#1F9A78', fill: '#E3F5EF', border: '#A3DCCA', text: '#0F4A39' },
  { dot: '#D08324', fill: '#FCF1E1', border: '#F0CE9F', text: '#6B3F0C' },
  { dot: '#1188A8', fill: '#E2F2F8', border: '#9FD3E4', text: '#0A4658' },
  { dot: '#C64B8C', fill: '#FBEAF3', border: '#EDB2D0', text: '#6B2049' }
]

export function calendarPalette(index: number): CalendarPalette {
  return CALENDAR_PALETTES[Math.max(0, index) % CALENDAR_PALETTES.length]
}

export function calendarColor(index: number): string {
  return calendarPalette(index).dot
}

function personKey(value: string): string {
  return String(value || '').trim().toLocaleLowerCase('ru')
}

export const samePersonName = samePersonFio

/**
 * Календари, которые реально читаются из Outlook: свой (или общий) плюс отслеживаемые.
 * Одного человека, записанного по-разному («Амураль» и «Амураль Игорь Борисович»),
 * сводим в одну строку и оставляем самую полную запись.
 */
/** Ярлык своего календаря: у части сотрудников совещания лежат в общем календаре руководителя. */
export function meetingSelfLabel(fio: string): string {
  return sharedMeetingCalendarFor(fio) || String(fio || '').trim()
}

export function meetingCalendarOwners(fio: string, tracked: string[], order: string[] = []): string[] {
  const self = meetingSelfLabel(fio)
  const owners: string[] = []
  for (const person of [self, ...tracked.map((item) => item.trim())].filter(Boolean)) {
    const at = owners.findIndex((item) => samePersonName(item, person))
    if (at < 0) {
      owners.push(person)
      continue
    }
    if (at > 0 && person.length > owners[at].length) owners[at] = person
  }
  if (!order.length) return owners
  // Сохранённый порядок = приоритет показа; незнакомые календари уходят в конец.
  const rank = (person: string): number => {
    const at = order.findIndex((item) => samePersonName(item, person))
    return at < 0 ? order.length + owners.indexOf(person) : at
  }
  return [...owners].sort((left, right) => rank(left) - rank(right))
}

/** Чей это календарь. Своя папка Outlook приходит без владельца («Календарь»). */
export function meetingOwnerName(meeting: MeetingEvent, selfLabel: string): string {
  if (meeting.ownCalendar || isOutlookFolderOwner(meeting.owner)) return selfLabel
  return meeting.owner.trim() || selfLabel
}

/** Фамилия человека встречается среди организатора или участников. */
export function meetingMentionsPerson(meeting: MeetingEvent, person: string): boolean {
  const surname = personKey(person).replace(/\./g, ' ').split(/\s+/).filter(Boolean)[0] || ''
  if (surname.length < 3) return false
  return `${meeting.organizer} ${meeting.attendees}`.toLocaleLowerCase('ru').includes(surname)
}

export type MeetingQuickFilters = {
  mineOnly: boolean
  withSelected: boolean
  noConflicts: boolean
  importantOnly: boolean
}

export const EMPTY_MEETING_QUICK_FILTERS: MeetingQuickFilters = {
  mineOnly: false,
  withSelected: false,
  noConflicts: false,
  importantOnly: false
}

export function hasMeetingQuickFilters(filters: MeetingQuickFilters): boolean {
  return filters.mineOnly || filters.withSelected || filters.noConflicts || filters.importantOnly
}

export function applyMeetingQuickFilters(
  meetings: MeetingEvent[],
  filters: MeetingQuickFilters,
  options: { selfLabel: string; others: string[] }
): MeetingEvent[] {
  if (!hasMeetingQuickFilters(filters)) return meetings
  const conflicts = filters.noConflicts ? overlappingMeetingKeys(meetings) : null
  const others = options.others.filter((person) => !samePersonName(person, options.selfLabel))
  return meetings.filter((meeting) => {
    const owner = meetingOwnerName(meeting, options.selfLabel)
    if (filters.mineOnly && !samePersonName(owner, options.selfLabel)) return false
    if (filters.importantOnly && (meeting.importance ?? 1) < 2) return false
    if (conflicts?.has(meetingInstanceKey(meeting))) return false
    if (filters.withSelected && others.length) {
      if (!others.some((person) => meetingMentionsPerson(meeting, person))) return false
    }
    return true
  })
}

/** Значения плитки по каждому календарю: плитка показывает сумму, окно под ней — разбивку. */
export function meetingOwnerCounts(
  meetings: MeetingEvent[],
  tileId: string,
  owners: string[],
  selfLabel: string,
  now = new Date()
): { person: string; count: number }[] {
  return owners.map((person) => ({
    person,
    count: meetings.filter(
      (meeting) =>
        samePersonName(meetingOwnerName(meeting, selfLabel), person) &&
        meetingMatchesTile(meeting, tileId, now)
    ).length
  }))
}
