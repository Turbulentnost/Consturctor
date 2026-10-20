import { useMemo } from 'react'
import type { AgentPassport } from '../api/types'
import {
  BanIcon,
  BoltIcon,
  BranchIcon,
  CircleCheckIcon,
  FlagIcon,
  InboxIcon,
  SearchIcon,
  TargetIcon,
  UserCheckIcon
} from '../components/Icons'

type PassportField = Exclude<keyof AgentPassport, 'name'>

const PASSPORT_ROWS: { key: PassportField; label: string; Icon: (props: { size?: number }) => React.JSX.Element }[] = [
  { key: 'goal', label: 'Цель', Icon: TargetIcon },
  { key: 'trigger', label: 'Триггер', Icon: BoltIcon },
  { key: 'receives', label: 'Получает', Icon: InboxIcon },
  { key: 'checks', label: 'Проверяет', Icon: SearchIcon },
  { key: 'decisions', label: 'Принимает решения', Icon: BranchIcon },
  { key: 'can_autonomous', label: 'Может самостоятельно', Icon: CircleCheckIcon },
  { key: 'needs_human_approval', label: 'Требует подтверждения человека', Icon: UserCheckIcon },
  { key: 'forbidden', label: 'Не может', Icon: BanIcon },
  { key: 'result', label: 'Результат', Icon: FlagIcon }
]

// Сервер уже оставил в SVG только фигуры с геометрией; здесь — тот же список ещё раз,
// чтобы строку из базы нельзя было превратить в разметку с обработчиками.
const SHAPES: Record<string, string[]> = {
  path: ['d'],
  circle: ['cx', 'cy', 'r'],
  ellipse: ['cx', 'cy', 'rx', 'ry'],
  rect: ['x', 'y', 'width', 'height', 'rx', 'ry'],
  line: ['x1', 'y1', 'x2', 'y2'],
  polyline: ['points'],
  polygon: ['points']
}

type Shape = { tag: string; attrs: Record<string, string> }

function iconShapes(svg: string): Shape[] {
  if (!svg) return []
  const doc = new DOMParser().parseFromString(svg, 'image/svg+xml')
  const shapes: Shape[] = []
  for (const node of Array.from(doc.documentElement.querySelectorAll('*'))) {
    const allowed = SHAPES[node.localName]
    if (!allowed) continue
    const attrs: Record<string, string> = {}
    for (const name of allowed) {
      const value = node.getAttribute(name)
      if (value) attrs[name] = value
    }
    if (Object.keys(attrs).length) shapes.push({ tag: node.localName, attrs })
  }
  return shapes
}

export function AgentIcon({ svg, size = 16 }: { svg: string; size?: number }): React.JSX.Element | null {
  const shapes = useMemo(() => iconShapes(svg), [svg])
  if (!shapes.length) return null
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {shapes.map((shape, index) => {
        const Tag = shape.tag as 'path'
        return <Tag key={index} {...shape.attrs} />
      })}
    </svg>
  )
}

export function AgentPassportView({ passport }: { passport: AgentPassport }): React.JSX.Element {
  return (
    <ul className="agent-passport" aria-label="Паспорт агента">
      {PASSPORT_ROWS.filter(({ key }) => passport[key]).map(({ key, label, Icon }) => (
        <li key={key} className="agent-passport-field">
          <span className="agent-passport-field-icon">
            <Icon size={16} />
          </span>
          <div>
            <span className="agent-passport-label">{label}</span>
            <p>{passport[key]}</p>
          </div>
        </li>
      ))}
    </ul>
  )
}
