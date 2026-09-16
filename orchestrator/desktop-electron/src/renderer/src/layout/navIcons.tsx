import {
  BarChart3,
  BookOpen,
  Bot,
  CalendarClock,
  CalendarDays,
  ClipboardCheck,
  FolderKanban,
  History,
  LayoutDashboard,
  Library,
  ListTodo,
  Mail,
  Rocket,
  Settings,
  Users,
  Workflow,
  type LucideIcon
} from 'lucide-react'
import type { PageKey } from '../components/Sidebar'

const NAV_ICON_PROPS = {
  className: 'nav-icon-svg',
  size: 16,
  strokeWidth: 1.8,
  absoluteStrokeWidth: true,
  'aria-hidden': true
} as const

const PAGE_ICONS: Record<PageKey, LucideIcon> = {
  today: CalendarDays,
  processes: Workflow,
  tasks: ListTodo,
  projects: FolderKanban,
  mail: Mail,
  meetings: CalendarClock,
  decisions: ClipboardCheck,
  kpi: BarChart3,
  history: History,
  knowledge: BookOpen,
  settings: Settings,
  overview: LayoutDashboard,
  launch_calendar: Rocket,
  users: Users,
  ai_agents: Bot,
  knowledge_base: Library
}

export function NavIcon({ page }: { page: PageKey }): React.JSX.Element {
  const Icon = PAGE_ICONS[page] ?? Settings
  return <Icon {...NAV_ICON_PROPS} />
}
