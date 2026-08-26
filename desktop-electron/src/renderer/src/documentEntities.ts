import type {
  FragmentEntityTag,
  RegulationEntityLegendItem,
  RegulationFragment,
  RegulationParseResult
} from './api/types'

export interface EntityColor {
  fill: string
  border: string
  text: string
}

const ROLE_COLORS: EntityColor[] = [
  { fill: 'rgba(8, 116, 95, 0.12)', border: '#08745F', text: '#06483D' },
  { fill: 'rgba(36, 89, 168, 0.12)', border: '#2459A8', text: '#1B3F78' },
  { fill: 'rgba(178, 106, 0, 0.14)', border: '#B26A00', text: '#7A4800' },
  { fill: 'rgba(124, 58, 237, 0.12)', border: '#7C3AED', text: '#4C1D95' },
  { fill: 'rgba(190, 24, 93, 0.12)', border: '#BE185D', text: '#831843' },
  { fill: 'rgba(14, 116, 144, 0.12)', border: '#0E7490', text: '#155E75' }
]

const PROCESS_COLORS: EntityColor[] = [
  { fill: 'rgba(15, 118, 110, 0.10)', border: '#0F766E', text: '#115E59' },
  { fill: 'rgba(67, 56, 202, 0.10)', border: '#4338CA', text: '#312E81' },
  { fill: 'rgba(180, 83, 9, 0.12)', border: '#B45309', text: '#7C2D12' },
  { fill: 'rgba(22, 163, 74, 0.10)', border: '#16A34A', text: '#166534' },
  { fill: 'rgba(79, 70, 229, 0.10)', border: '#4F46E5', text: '#3730A3' }
]

const ROLE_MARKERS = [
  'руководитель',
  'инженер',
  'заказчик',
  'владелец',
  'пользователь',
  'администратор',
  'специалист',
  'менеджер',
  'директор',
  'исполнитель'
]
const PROCESS_MARKERS = ['этап', 'процесс', 'порядок', 'жизненный цикл', 'согласование']

export function isRunningHeader(fragment: RegulationFragment): boolean {
  const blob = `${fragment.text} ${tableBlob(fragment)}`.replace(/\s+/g, ' ')
  const isTitle = /система менеджмента/i.test(blob) || /всего листов/i.test(blob)
  if (isTitle && fragment.page <= 1) return false
  const hasHeader = /версия\s+\d+/i.test(blob) && /лист\s+\d+/i.test(blob)
  if (!hasHeader) return false
  const leftover = blob
    .replace(/рг-\d+/gi, '')
    .replace(/версия\s+\d+/gi, '')
    .replace(/лист\s+\d+/gi, '')
    .replace(/регламент внедрения решений на базе искусственного интеллекта/gi, '')
    .replace(/на базе искусственного интеллекта/gi, '')
    .replace(/\s+/g, ' ')
    .trim()
  return leftover.length < 18
}

export function isTocLine(text: string): boolean {
  return /\.{4,}\s*\d+\s*$/.test(text.replace(/\s+/g, ' ').trim())
}

export function parseTocLine(text: string): { title: string; page: string } | null {
  const compact = text.replace(/\s+/g, ' ').trim()
  const match = compact.match(/^(.*?)(?:\s*\.{4,}\s*)(\d+)\s*$/)
  if (!match) return null
  return { title: match[1].trim(), page: match[2] }
}

export function primaryEntity(fragment: RegulationFragment): FragmentEntityTag | null {
  if (fragment.entities[0]) return fragment.entities[0]
  return inferEntity(fragment.section || fragment.text.split('\n')[0] || '')
}

export function buildLegend(result: RegulationParseResult): RegulationEntityLegendItem[] {
  if (result.entityLegend.length) return result.entityLegend
  const items = new Map<string, RegulationEntityLegendItem>()
  for (const fragment of result.fragments) {
    if (isRunningHeader(fragment) || fragment.blockType === 'table_row') continue
    const entity = primaryEntity(fragment)
    if (!entity) continue
    const current = items.get(entity.entityId)
    if (!current) {
      items.set(entity.entityId, {
        ...entity,
        fragmentIds: [fragment.fragmentId]
      })
    } else if (!current.fragmentIds.includes(fragment.fragmentId)) {
      current.fragmentIds.push(fragment.fragmentId)
    }
  }
  return [...items.values()]
}

export function entityColor(entity: FragmentEntityTag | RegulationEntityLegendItem): EntityColor {
  const palette = entity.kind === 'process' ? PROCESS_COLORS : ROLE_COLORS
  let hash = 0
  for (const char of entity.entityId) hash = (hash * 31 + char.charCodeAt(0)) >>> 0
  return palette[hash % palette.length]
}

export function groupFragments(fragments: RegulationFragment[]): Array<{
  entity: FragmentEntityTag | null
  items: RegulationFragment[]
}> {
  const groups: Array<{ entity: FragmentEntityTag | null; items: RegulationFragment[] }> = []
  for (const fragment of fragments) {
    if (fragment.blockType === 'table_row' || isRunningHeader(fragment)) continue
    const entity = primaryEntity(fragment)
    const last = groups[groups.length - 1]
    if (last && (last.entity?.entityId || '') === (entity?.entityId || '')) {
      last.items.push(fragment)
      continue
    }
    groups.push({ entity, items: [fragment] })
  }
  return groups
}

function inferEntity(title: string): FragmentEntityTag | null {
  const clean = title.replace(/\.{4,}\s*\d+\s*$/, '').trim()
  if (!clean || clean.length > 140) return null
  const lower = clean.toLowerCase()
  const numbered = /^\d+(?:\.\d+)+/.test(clean)
  if (ROLE_MARKERS.some((marker) => lower.includes(marker))) {
    return { entityId: `role:${lower}`, kind: 'role', title: clean, shortTitle: clean.replace(/^\d+(?:\.\d+)*\s+/, '') }
  }
  if (numbered && PROCESS_MARKERS.some((marker) => lower.includes(marker))) {
    return {
      entityId: `process:${lower}`,
      kind: 'process',
      title: clean,
      shortTitle: clean.replace(/^\d+(?:\.\d+)*\s+/, '')
    }
  }
  return null
}

function tableBlob(fragment: RegulationFragment): string {
  if (!fragment.table) return ''
  return [...fragment.table.headers, ...fragment.table.rows.flat()].join(' ')
}
