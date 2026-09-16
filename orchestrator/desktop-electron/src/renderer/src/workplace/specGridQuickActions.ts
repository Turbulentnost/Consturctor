import { invokeLocalAcTool } from '../utils/localAcTool'
import { openWorkplaceTab } from './workplaceNav'

export type SpecQuickActionTone = 'green' | 'orange' | 'blue' | 'yellow'

export type SpecQuickActionIcon = 'play' | 'onec' | 'calendar'

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

async function runPowerShell(command: string): Promise<void> {
  await invokeLocalAcTool('workspace.powershell_run', {
    command,
    runtime_context: { agent_id: 'orch-grid' }
  })
}

/** Открыть Outlook на виде календаря (shell) или поднять окно Outlook. */
export async function openOutlookCalendarView(): Promise<void> {
  await runPowerShell(
    '$ol = New-Object -ComObject Outlook.Application -ErrorAction SilentlyContinue; if ($ol) { $ol.ActiveExplorer().ShowFolder($ol.Session.GetDefaultFolder(9)) } else { Start-Process outlook }'
  )
}

/** Подключение к базе 1С через COM (открывает клиент при необходимости). */
export async function launch1cClient(): Promise<void> {
  await invokeLocalAcTool('onec.search_tasks', { mine_only: true, limit: 1 })
}

/** Создание задачи: COM-сессия 1С (форма задачи — в клиенте). */
export async function open1cTaskCreation(): Promise<void> {
  const res = await invokeLocalAcTool('onec.search_tasks', { mine_only: true, limit: 1 })
  if (!res.ok) {
    await launch1cClient()
  }
}

export function buildProcessesQuickActions(_handlers: Record<string, never> = {}): SpecQuickActionDef[] {
  return [
    {
      id: 'launch-process',
      label: 'Запустить новый процесс',
      tone: 'green',
      icon: 'play',
      run: () => {
        triggerHeaderQuickLaunch()
      }
    },
    {
      id: 'create-1c-task',
      label: 'Создать задачу в 1С',
      tone: 'orange',
      icon: 'onec',
      run: () => void open1cTaskCreation()
    },
    {
      id: 'open-outlook-cal',
      label: 'Открыть календарь Outlook',
      tone: 'blue',
      icon: 'calendar',
      run: () => void openOutlookCalendarView()
    },
    {
      id: 'goto-1c',
      label: 'Перейти в 1С',
      tone: 'yellow',
      icon: 'onec',
      run: () => void launch1cClient()
    }
  ]
}
