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
    'Проверь незакрытые поручения журнала АСТ00 в 1С ERP к закрытию.',
    `Период: ${period}.`,
    scope,
    'По каждому поручению прочитай файлы вкладки «Файлы».',
    'Свяжи поручение с задачами 1С:Документооборот (onec.docflow_tasks) по теме и номеру.',
    'Если по файлам и задачам документооборота есть основания закрыть поручение, в отчёте напиши «можно закрыть» и коротко почему.',
    'Сохрани отчёт Word «Проверка артефактов по незакрытым поручениям АСТ00» через report.export_document.'
  ].join('\n')
}
