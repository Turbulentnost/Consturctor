import type { UserProfile } from '../api/types'
import { invokeLocalAcTool } from '../utils/localAcTool'
import { openAssignmentListFormIn1C } from './assignmentRegistryOneCForm'
import { openWorkplaceTab } from './workplaceNav'

export type SpecQuickActionTone = 'green' | 'orange' | 'blue' | 'yellow'

export type SpecQuickActionIcon = 'plus' | 'play' | 'onec' | 'calendar' | 'mail' | 'book'

export interface SpecQuickActionDef {
  id: string
  label: string
  tone: SpecQuickActionTone
  icon: SpecQuickActionIcon
  run: () => void | Promise<void>
}

/** Клик по «Запустить процесс» в шапке сетки — вкладка «Решения». */
export function triggerHeaderQuickLaunch(): void {
  openWorkplaceTab('decisions')
}

async function runPowerShell(command: string): Promise<boolean> {
  const res = await invokeLocalAcTool('workspace.powershell_run', {
    command,
    runtime_context: { agent_id: 'orch-grid' }
  })
  return res.ok
}

function outlookCreateItemScript(itemType: 0 | 1 | 3): string {
  return [
    'try {',
    '  $ol = New-Object -ComObject Outlook.Application',
    `  $item = $ol.CreateItem(${itemType})`,
    '  $item.Display()',
    '} catch {',
    '  Start-Process outlook',
    '}'
  ].join('; ')
}

/** Новое письмо Outlook. */
export async function openOutlookCompose(): Promise<void> {
  await runPowerShell(outlookCreateItemScript(0))
}

/** Новая встреча в календаре Outlook (форма создания). */
export async function openOutlookCalendarCreate(): Promise<void> {
  const ok = await runPowerShell(outlookCreateItemScript(1))
  if (!ok) {
    await runPowerShell(outlookCreateItemScript(3))
  }
}

/** Открыть Outlook на виде календаря. */
export async function openOutlookCalendarView(): Promise<void> {
  await runPowerShell(
    '$ol = New-Object -ComObject Outlook.Application -ErrorAction SilentlyContinue; if ($ol) { $ol.ActiveExplorer().ShowFolder($ol.Session.GetDefaultFolder(9)) } else { Start-Process outlook }'
  )
}

/** Открыть клиент 1С (форма списка поручений или запуск 1cv8c). */
export async function launch1cClient(user: UserProfile | null = null): Promise<void> {
  const opened = await openAssignmentListFormIn1C(user)
  if (opened.ok) return
  await runPowerShell(
    [
      "$roots = @('C:\\Program Files\\1cv8','C:\\Program Files (x86)\\1cv8')",
      '$exe = Get-ChildItem -Path $roots -Recurse -Filter 1cv8c.exe -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1',
      'if ($exe) { Start-Process -FilePath $exe.FullName } else { Start-Process 1cv8c }'
    ].join('; ')
  )
}

export async function open1cTaskCreation(user: UserProfile | null = null): Promise<void> {
  await launch1cClient(user)
}

export function buildProcessesQuickActions(user: UserProfile | null = null): SpecQuickActionDef[] {
  return [
    {
      id: 'launch-process',
      label: 'Запустить новый процесс',
      tone: 'green',
      icon: 'plus',
      run: () => {
        triggerHeaderQuickLaunch()
      }
    },
    {
      id: 'calendar-task',
      label: 'Создать задачу в календаре',
      tone: 'blue',
      icon: 'calendar',
      run: () => void openOutlookCalendarCreate()
    },
    {
      id: 'create-mail',
      label: 'Создать письмо',
      tone: 'orange',
      icon: 'mail',
      run: () => void openOutlookCompose()
    },
    {
      id: 'goto-1c',
      label: 'Перейти в 1С',
      tone: 'yellow',
      icon: 'onec',
      run: () => void launch1cClient(user)
    },
    {
      id: 'open-regulation',
      label: 'Открыть регламент',
      tone: 'orange',
      icon: 'book',
      run: () => {
        openWorkplaceTab('knowledge')
      }
    }
  ]
}
