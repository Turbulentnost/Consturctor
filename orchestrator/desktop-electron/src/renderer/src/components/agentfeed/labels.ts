/** RU tool labels ported from desktop agent_run_page._TOOL_LABELS. */
export const TOOL_LABELS: Record<string, string> = {
  askQuestion: 'Уточняющий вопрос',
  web_search: 'Поиск в интернете',
  site_browser: 'Просмотр сайта',
  'outlook.search_mail': 'Поиск писем Outlook',
  'outlook.read_calendar': 'Календарь Outlook',
  'outlook.create_event': 'Встреча в Outlook',
  'calendar.show_meetings': 'Совещания на календаре',
  'browser.list_installed_browsers': 'Список браузеров',
  'browser.open_browser': 'Открытие браузера',
  'browser.search_web': 'Поиск в интернете',
  'browser.open_page': 'Чтение страницы',
  'browser.extract_table': 'Таблицы со страницы',
  'browser.scroll_page': 'Прокрутка страницы',
  'browser.click_link': 'Переход по ссылке',
  'browser.navigate': 'Открытие страницы',
  'browser.screenshot': 'Скриншот браузера',
  'browser.get_page_html': 'HTML страницы',
  'browser.dump_page_source': 'Выгрузка HTML страницы',
  'browser.click': 'Клик в браузере',
  'browser.type_text': 'Ввод в браузере',
  'browser.press_key': 'Клавиша в браузере',
  'browser.scroll': 'Прокрутка браузера',
  'onec.search_documents': 'Поиск документов 1С',
  'onec.get_document_card': 'Карточка документа 1С',
  'onec.search_tasks': 'Поиск задач 1С',
  'onec.get_task_card': 'Карточка задачи 1С',
  'onec.meeting_service_notes': 'Служебные записки на совещания',
  'onec.erp_tasks_current': 'Текущие задачи 1С',
  'onec.erp_tasks_period': 'Задачи 1С за период',
  'onec.erp_subordinate_tasks': 'Задачи подчинённых 1С',
  'onec.docflow_tasks': 'Задачи документооборота',
  'excel.list_files': 'Файлы агента',
  'excel.read_workbook': 'Чтение Excel',
  'excel.create_workbook': 'Создание Excel',
  'excel.edit_workbook': 'Изменение Excel',
  'workspace.powershell_run': 'PowerShell в папке агента',
  'code.write_python': 'Запись Python-кода',
  'code.run_python': 'Запуск Python-кода',
  'agent.wait': 'Пауза',
  'report.build_task_report': 'Отчёт по поручениям',
  'report.build_meeting_summary': 'Сводка совещания',
  'report.build_schedule_recommendations': 'Рекомендации по графику',
  turboproject: 'Проекты TurboProject',
  'users.current': 'Текущий пользователь',
  'users.list': 'Список пользователей',
  'users.subordinates': 'Подчинённые из erp_pm',
  'notify.send': 'Уведомление',
  'agent.schedule': 'Расписание агента',
  'agent.schedule.cancel': 'Отмена расписания'
}

const SDK_TOOL_LABELS: Record<string, string> = {
  Read: 'Чтение файла',
  read: 'Чтение файла',
  write: 'Запись файла',
  Write: 'Запись файла',
  Edit: 'Правка файла',
  edit: 'Правка файла',
  Grep: 'Поиск в файлах',
  grep: 'Поиск в файлах',
  Glob: 'Поиск файлов',
  glob: 'Поиск файлов',
  LS: 'Список файлов',
  ls: 'Список файлов',
  Shell: 'Команда в терминале',
  shell: 'Команда в терминале',
  SemanticSearch: 'Семантический поиск',
  semSearch: 'Семантический поиск',
  Delete: 'Удаление файла',
  Task: 'Вложенный агент',
  task: 'Вложенный агент',
  Agent: 'Вложенный агент',
  explore: 'Исследование',
  mcp: 'MCP инструмент'
}

export function resolveToolName(tool: string, args?: Record<string, unknown>): string {
  const name = (tool || '').trim()
  if (name.toLowerCase() === 'mcp' && args) {
    for (const key of ['toolName', 'tool', 'name']) {
      const value = args[key]
      if (typeof value === 'string' && value.trim()) return value.trim()
    }
  }
  return name
}

export function isTaskTool(tool: string): boolean {
  const name = (tool || '').toLowerCase()
  return name === 'task' || name === 'agent' || name === 'explore' || name === 'generalpurpose'
}

export function toolLabel(tool: string): string {
  if (!tool) return 'внешний источник'
  return TOOL_LABELS[tool] || SDK_TOOL_LABELS[tool] || tool
}

export function toolArgHint(args: Record<string, unknown> | undefined): string {
  if (!args) return ''
  for (const key of [
    'path',
    'file_path',
    'target_file',
    'targetFile',
    'globPattern',
    'target_directory',
    'targetDirectory',
    'query',
    'pattern',
    'glob',
    'command',
    'url',
    'description',
    'title',
    'name',
    'subagent_type',
    'prompt'
  ]) {
    const value = args[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

export function toolCardTitle(tool: string, args?: Record<string, unknown>): string {
  const name = resolveToolName(tool, args)
  if (isTaskTool(name) || isTaskTool(tool)) {
    const description =
      (typeof args?.description === 'string' && args.description.trim()) ||
      (typeof args?.title === 'string' && args.title.trim()) ||
      (typeof args?.subagent_type === 'string' && args.subagent_type.trim()) ||
      ''
    return description ? `Агент: ${description}` : 'Вложенный агент'
  }
  return `Инструмент: ${toolLabel(name)}`
}
