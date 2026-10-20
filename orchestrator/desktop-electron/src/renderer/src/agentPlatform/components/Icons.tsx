import type { ReactNode } from 'react'

interface IconProps {
  size?: number
}

function Svg({ size = 18, children }: IconProps & { children: ReactNode }): React.JSX.Element {
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
      {children}
    </svg>
  )
}

export function HomeIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M3.5 10.5 12 3.5l8.5 7" />
      <path d="M5.5 9v11h13V9" />
      <path d="M10 20v-5h4v5" />
    </Svg>
  )
}

export function ChecklistIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="m3.5 6.5 1.8 1.8L8.5 5" />
      <path d="m3.5 16.5 1.8 1.8L8.5 15" />
      <path d="M12 6.5h8.5" />
      <path d="M12 12h8.5" />
      <path d="M12 17.5h8.5" />
    </Svg>
  )
}

export function ChartIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M3.5 20.5h17" />
      <path d="M6.5 17v-6" />
      <path d="M12 17V5.5" />
      <path d="M17.5 17v-9" />
    </Svg>
  )
}

export function SlidersIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M4 6.5h9" />
      <path d="M17 6.5h3" />
      <circle cx="15" cy="6.5" r="2" />
      <path d="M4 12h3" />
      <path d="M11 12h9" />
      <circle cx="9" cy="12" r="2" />
      <path d="M4 17.5h11" />
      <path d="M19 17.5h1" />
      <circle cx="17" cy="17.5" r="2" />
    </Svg>
  )
}

export function SunIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4" />
    </Svg>
  )
}

export function MoonIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" />
    </Svg>
  )
}

export function ChevronRightIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="m9 6 6 6-6 6" />
    </Svg>
  )
}

export function ChevronLeftIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="m15 6-6 6 6 6" />
    </Svg>
  )
}

export function ChevronDownIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="m6 9 6 6 6-6" />
    </Svg>
  )
}

export function PlusIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M12 5v14M5 12h14" />
    </Svg>
  )
}

export function ArrowUpIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M12 19V5" />
      <path d="m5.5 11.5 6.5-6.5 6.5 6.5" />
    </Svg>
  )
}

export function BotIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <rect x="4" y="8" width="16" height="12" rx="3.5" />
      <path d="M12 4v4" />
      <circle cx="12" cy="3.5" r="0.5" />
      <path d="M9 13.5v1M15 13.5v1" />
    </Svg>
  )
}

export function WrenchIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9l-3.8 3.8Z" />
    </Svg>
  )
}

export function FlaskIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M9.5 3h5" />
      <path d="M10 3v6.2L4.8 18.1A2 2 0 0 0 6.5 21h11a2 2 0 0 0 1.7-2.9L14 9.2V3" />
      <path d="M7.2 15h9.6" />
    </Svg>
  )
}

export function ClockIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </Svg>
  )
}

export function SparklesIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="m11 3.5 1.7 4.3 4.3 1.7-4.3 1.7L11 15.5l-1.7-4.3L5 9.5l4.3-1.7Z" />
      <path d="m18.5 14 .8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8Z" />
    </Svg>
  )
}

export function PlugIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M9 3.5v4M15 3.5v4" />
      <path d="M6.5 7.5h11V11a5.5 5.5 0 0 1-11 0Z" />
      <path d="M12 16.5v4" />
    </Svg>
  )
}

export function RefreshIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M20 11.5A8 8 0 0 0 6.2 6.3L4 8.5" />
      <path d="M4 4v4.5h4.5" />
      <path d="M4 12.5a8 8 0 0 0 13.8 5.2l2.2-2.2" />
      <path d="M20 20v-4.5h-4.5" />
    </Svg>
  )
}

export function CloseIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M6 6l12 12" />
      <path d="M18 6 6 18" />
    </Svg>
  )
}

export function PlayIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M8 5.5v13l10.5-6.5Z" />
    </Svg>
  )
}

export function StopIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <rect x="7" y="7" width="10" height="10" rx="2" />
    </Svg>
  )
}

export function TerminalIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <rect x="3.5" y="4.5" width="17" height="15" rx="3" />
      <path d="m7.5 10 2.5 2-2.5 2" />
      <path d="M12.5 14.5h4" />
    </Svg>
  )
}

export function LayersIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="m12 3.5 8.5 4.5-8.5 4.5L3.5 8Z" />
      <path d="m3.5 12 8.5 4.5 8.5-4.5" />
      <path d="m3.5 16 8.5 4.5 8.5-4.5" />
    </Svg>
  )
}

export function FileIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M13.5 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9Z" />
      <path d="M13.5 3.5V9H19" />
    </Svg>
  )
}

export function SearchIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <circle cx="10.5" cy="10.5" r="6" />
      <path d="m15 15 5 5" />
    </Svg>
  )
}

export function FolderIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M3.5 7a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z" />
    </Svg>
  )
}

export function GlobeIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17" />
      <path d="M12 3.5c2.3 2.4 3.5 5.2 3.5 8.5s-1.2 6.1-3.5 8.5c-2.3-2.4-3.5-5.2-3.5-8.5S9.7 5.9 12 3.5Z" />
    </Svg>
  )
}

export function TrashIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M4.5 7h15" />
      <path d="M9.5 7V4.5h5V7" />
      <path d="M6.5 7l1 12.5h9l1-12.5" />
    </Svg>
  )
}

export function CheckIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="m5.5 12.5 4 4 9-9" />
    </Svg>
  )
}

export function PaperclipIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="m19.5 11.5-7.4 7.4a4.6 4.6 0 0 1-6.5-6.5l7.8-7.8a3.1 3.1 0 0 1 4.4 4.4l-7.6 7.6a1.5 1.5 0 0 1-2.2-2.2l7-7" />
    </Svg>
  )
}

export function ImageIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <rect x="3.5" y="4.5" width="17" height="15" rx="3" />
      <circle cx="9" cy="10" r="1.6" />
      <path d="m20.5 16-4.5-4.5-8.5 8" />
    </Svg>
  )
}

export function QuestionIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M9.6 9.5a2.5 2.5 0 0 1 4.8 1c0 1.7-2.4 2.2-2.4 3.5" />
      <path d="M12 17h.01" />
    </Svg>
  )
}

export function UsersIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20a6.5 6.5 0 0 1 13 0" />
      <path d="M16 4.7a3.5 3.5 0 0 1 0 6.6" />
      <path d="M18 14.2a6.5 6.5 0 0 1 3.5 5.8" />
    </Svg>
  )
}

export function InfoIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 11v5" />
      <path d="M12 8h.01" />
    </Svg>
  )
}

export function TargetIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="4.5" />
      <circle cx="12" cy="12" r="0.8" />
    </Svg>
  )
}

export function BoltIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M13 3.5 5.5 13.5H12l-1 7 7.5-10H12z" />
    </Svg>
  )
}

export function InboxIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M3.5 13.5h5l1.5 2.5h4l1.5-2.5h5" />
      <path d="M6 5.5h12l2.5 8v5h-17v-5z" />
    </Svg>
  )
}

export function BranchIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <circle cx="6" cy="5.5" r="2" />
      <circle cx="18" cy="5.5" r="2" />
      <circle cx="12" cy="18.5" r="2" />
      <path d="M6 7.5v1a4 4 0 0 0 4 4h4a4 4 0 0 0 4-4v-1" />
      <path d="M12 12.5v4" />
    </Svg>
  )
}

export function CircleCheckIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="m8.5 12 2.5 2.5 4.5-5" />
    </Svg>
  )
}

export function UserCheckIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <circle cx="9.5" cy="8" r="3.5" />
      <path d="M3.5 19.5a6 6 0 0 1 12 0" />
      <path d="m15.5 11 2 2 3.5-4" />
    </Svg>
  )
}

export function BanIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="m6 6 12 12" />
    </Svg>
  )
}

export function FlagIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="M5.5 20.5V4" />
      <path d="M5.5 4.5h11l-2 4 2 4h-11" />
    </Svg>
  )
}

export function TableIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M3.5 9.5h17M3.5 14.5h17M9.5 9.5v10" />
    </Svg>
  )
}

export function WindowIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M3.5 9h17" />
      <path d="M7 6.7h.01M10 6.7h.01" />
    </Svg>
  )
}

export function PointerIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <path d="m5.5 3.5 1.2 14 3.2-3.6 4.6 6 2.2-1.6-4.6-6H17Z" />
    </Svg>
  )
}

export function CalendarIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <rect x="3.5" y="5" width="17" height="15" rx="2" />
      <path d="M3.5 10h17M8 3.5V7M16 3.5V7" />
    </Svg>
  )
}

export function MailIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <rect x="3.5" y="5.5" width="17" height="13" rx="2" />
      <path d="m4.5 7 7.5 6 7.5-6" />
    </Svg>
  )
}

export function MonitorIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <rect x="3.5" y="4.5" width="17" height="11" rx="2" />
      <path d="M8.5 19.5h7M12 15.5v4" />
    </Svg>
  )
}

export function ServerIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <rect x="3.5" y="3.5" width="17" height="6" rx="2" />
      <rect x="3.5" y="14.5" width="17" height="6" rx="2" />
      <path d="M7 6.5h.01M7 17.5h.01" />
    </Svg>
  )
}

export function MeetingIcon(props: IconProps): React.JSX.Element {
  return (
    <Svg {...props}>
      <circle cx="8" cy="8" r="2.4" />
      <circle cx="16" cy="8" r="2.4" />
      <path d="M3.8 17.5a4.2 4.2 0 0 1 8.4 0M11.8 17.5a4.2 4.2 0 0 1 8.4 0" />
    </Svg>
  )
}
