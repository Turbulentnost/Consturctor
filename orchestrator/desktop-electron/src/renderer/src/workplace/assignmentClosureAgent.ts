import { api } from '../api/client'
import { adoptAgentFromLibrary, fetchAgentLibrary } from './agentLibraryApi'

export const CLOSURE_SOURCE_WORKFLOW_ID = '068a363f-c394-4e33-b349-79e09946eb44'
export const CLOSURE_AGENT_TITLE = 'Проверка поручений к закрытию'

/** The user's own copy of the agent, without adopting it from the library. */
export async function findClosureAgentWorkflowId(): Promise<string> {
  const workflows = await api.listWorkflows()
  return workflows.find((item) => item.title.trim() === CLOSURE_AGENT_TITLE)?.id || ''
}

/**
 * Resolve the workflow id of the assignment closure check agent:
 * adopted copy by title → catalog source (adopt if needed) → listWorkflows by title.
 */
export async function resolveClosureAgentWorkflowId(): Promise<string> {
  const library = await fetchAgentLibrary({ force: true })

  const adopted = library.adopted.find((entry) => entry.title.trim() === CLOSURE_AGENT_TITLE)
  const adoptedId = (adopted?.adoptedWorkflowId || adopted?.workflowId || '').trim()
  if (adoptedId) return adoptedId

  const catalog = library.catalog.find(
    (entry) => entry.workflowId === CLOSURE_SOURCE_WORKFLOW_ID || entry.title.trim() === CLOSURE_AGENT_TITLE
  )
  if (catalog?.workflowId) {
    if (catalog.alreadyAdded && catalog.adoptedWorkflowId?.trim()) {
      return catalog.adoptedWorkflowId.trim()
    }
    const adoptedCopy = await adoptAgentFromLibrary(catalog.workflowId)
    const id = (adoptedCopy.workflowId || '').trim()
    if (id) return id
  }

  const workflows = await api.listWorkflows()
  const byTitle = workflows.find((item) => item.title.trim() === CLOSURE_AGENT_TITLE)
  if (byTitle?.id) return byTitle.id

  throw new Error(
    `Агент «${CLOSURE_AGENT_TITLE}» не найден в библиотеке. Добавьте его из каталога или обратитесь к администратору.`
  )
}

/**
 * The registry reads per-task verdicts saved by report.closure_check; the sidecar appends the block.
 * Writing the whole JSON in the final message took longer than the run limit.
 */
export const CLOSURE_CHECK_LINE =
  'Выводы для реестра сохраняй инструментом report.closure_check по 2–3 поручения сразу после того, как дописал их в Word, по формату шага 8 регламента: все проверенные поручения и все их задачи ДО (tasks). По каждой задаче вердикт: «Можно закрывать», «Вернуть на доработку» или «Не выполнено». В comment всегда напиши почему можно или почему нельзя закрыть. Блок ```closure-check в ответ не пиши.'

function ruDate(iso: string): string {
  const [y, m, d] = iso.split('-')
  return y && m && d ? `${d}.${m}.${y}` : iso
}

/** Task message for the closure check. Selected numbers limit the check to those assignments. */
export function buildClosureCheckMessage(
  dateFrom: string,
  dateTo: string,
  numbers: string[] = []
): string {
  const period =
    dateFrom && dateTo
      ? `за период ${ruDate(dateFrom)} — ${ruDate(dateTo)} (date_from=${dateFrom}, date_to=${dateTo})`
      : 'все открытые, без ограничения периода'
  const picked = numbers.map((item) => item.trim()).filter(Boolean)
  const scope = picked.length
    ? `Только поручения с номерами: ${picked.join(', ')}.`
    : 'Если номера не перечислены, проверь все открытые за период.'
  return [
    'Проверь все поручения журнала АСТ00 в 1С ERP: открытые и закрытые, которых ещё нет в БД.',
    `Период: ${period}.`,
    scope,
    'Сначала onec.erp_assignments action=reviewed — эти номера не проверяй повторно. Затем action=list only_open=false.',
    'По каждому новому поручению прочитай файлы вкладки «Файлы».',
    'Задачи поручения в 1С:Документооборот бери из onec.erp_assignments с include_tasks=true (docflow_tasks). С мероприятиями задачи не связаны: мероприятия — только справка, что поручали.',
    'По каждой задаче ДО дай вердикт: «Можно закрывать», «Вернуть на доработку» или «Не выполнено». В comment всегда напиши почему можно закрыть или почему нельзя (чего нет, у кого задача, что приложить).',
    'Общий вывод «можно закрыть» — только если автор принял все задачи поручения; иначе «нельзя закрыть» и в обосновании почему, у кого задачи открыты и чего не хватает.',
    'Сохрани отчёт Word «Проверка артефактов по незакрытым поручениям АСТ00» через report.export_document — частями (append), чтобы раздел задач вошёл целиком.',
    'В чате — только короткий итог: сколько проверено, какие можно закрыть и по строке «<номер> — <вывод> (принято N из M задач)» на поручение; задачи по отдельности в чат не выписывай.',
    CLOSURE_CHECK_LINE
  ].join('\n')
}
