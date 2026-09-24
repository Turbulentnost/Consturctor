import type { ReactNode } from 'react'
import { PAGE_LABELS } from '../components/Sidebar'
import {
  SpecProcessMapButton,
  SpecQuickLaunchButton,
  SpecTodayQuickLaunchButton
} from '../workplace/specV04Components'
import { CreateTaskHeaderButton } from './CreateTaskHeaderButton'
import { KpiExportReportButton } from './KpiExportReportButton'

export type WorkplaceTabKey =
  | 'today'
  | 'processes'
  | 'tasks'
  | 'projects'
  | 'mail'
  | 'docflow'
  | 'meetings'
  | 'decisions'
  | 'kpi'
  | 'history'
  | 'knowledge'
  | 'extensions'
  | 'assignments_registry'
  | 'agent_library'
  | 'task_create'
  | 'platform_task_create'

export interface TabRegistryEntry {
  title: string
  subtitle: string
  headerActions?: ReactNode
  /** Логотип в шапке вкладки вместо стандартной иконки навигации */
  titleLogoSrc?: string
}

export const TAB_REGISTRY: Record<WorkplaceTabKey, TabRegistryEntry> = {
  today: {
    title: PAGE_LABELS.today,
    subtitle: 'Ваше рабочее место в Оркестраторе должности',
    headerActions: <SpecTodayQuickLaunchButton />
  },
  processes: {
    title: PAGE_LABELS.processes,
    subtitle: 'Все процессы вашей должности. Статус, задачи, регламенты и результаты.',
    headerActions: (
      <>
        <SpecQuickLaunchButton />
        <SpecProcessMapButton />
      </>
    )
  },
  tasks: {
    title: PAGE_LABELS.tasks,
    subtitle: 'Единый центр управления задачами сотрудника',
    headerActions: <CreateTaskHeaderButton />
  },
  projects: {
    title: PAGE_LABELS.projects,
    subtitle: 'Ваши проекты, роли, задачи, сроки и результаты',
    headerActions: <SpecQuickLaunchButton />
  },
  mail: {
    title: PAGE_LABELS.mail,
    subtitle: 'Ваши письма в Outlook и связанные процессы',
    headerActions: <SpecQuickLaunchButton />
  },
  docflow: {
    title: PAGE_LABELS.docflow,
    subtitle: 'Корреспонденция, служебные записки, приказы, поручения и протоколы'
  },
  meetings: {
    title: PAGE_LABELS.meetings,
    subtitle: 'Календарь, подготовка и материалы',
    headerActions: <SpecQuickLaunchButton />
  },
  decisions: {
    title: PAGE_LABELS.decisions,
    subtitle: 'Рекомендации ИИ и подтверждение решений по процессам',
    headerActions: <SpecQuickLaunchButton />
  },
  kpi: {
    title: PAGE_LABELS.kpi,
    subtitle: 'Ключевые показатели сотрудника и ИИ-агентов',
    headerActions: <KpiExportReportButton />
  },
  history: {
    title: PAGE_LABELS.history,
    subtitle: 'Журнал действий пользователя, процессов и ИИ-агентов',
    headerActions: <SpecQuickLaunchButton />
  },
  knowledge: {
    title: PAGE_LABELS.knowledge,
    subtitle: 'Регламенты, шаблоны, инструкции и связанные материалы',
    headerActions: <SpecQuickLaunchButton />
  },
  extensions: {
    title: 'Расширения',
    subtitle: 'Дополнительные вкладки для вашей панели навигации'
  },
  assignments_registry: {
    title: 'Реестр поручений',
    subtitle: 'Журнал поручений АСТ00: контроль сроков, статусов и проверка закрытия через ИИ'
  },
  task_create: {
    title: PAGE_LABELS.task_create,
    subtitle: 'Запуск задачи в 1С:Документооборот'
  },
  platform_task_create: {
    title: PAGE_LABELS.platform_task_create,
    subtitle: 'Постановка задачи сотруднику внутри Оркестратора'
  },
  agent_library: {
    title: 'Библиотека агентов',
    subtitle: 'Опубликованные ИИ-агенты всех сотрудников: добавьте к себе и откройте паспорт'
  }
}
