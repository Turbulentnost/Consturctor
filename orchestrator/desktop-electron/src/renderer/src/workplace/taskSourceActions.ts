import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { invokeLocalAcTool } from '../utils/localAcTool'
import { onecGatewayInvokeArgs } from './userContext'
import { turboProjectInvokeArgs } from './userContext'
import type { TaskActionContext } from './taskSourceKind'

export type DocflowUiAction =
  | 'acquaint'
  | 'execute'
  | 'reject'
  | 'consider'
  | 'approve'
  | 'open_card'

export type TurboUiAction = 'open_project' | 'mark_done' | 'refresh'

export type TaskActionResult = { ok: boolean; message: string }

function inferDocflowActions(step: string, title: string): DocflowUiAction[] {
  const blob = `${step} ${title}`.toLowerCase()
  if (/ознаком/i.test(blob)) return ['acquaint', 'reject']
  if (/рассмотр/i.test(blob)) return ['consider', 'reject']
  if (/соглас/i.test(blob)) return ['approve', 'reject']
  if (/исполн/i.test(blob)) return ['execute', 'reject']
  return ['execute', 'acquaint', 'reject']
}

export function docflowActionButtons(ctx: TaskActionContext): Array<{
  id: DocflowUiAction
  label: string
  tone?: 'primary' | 'outline' | 'danger'
}> {
  const step = (ctx.step || ctx.title || '').trim()
  const ids = inferDocflowActions(step, ctx.title)
  const labels: Record<DocflowUiAction, string> = {
    acquaint: 'Ознакомиться',
    execute: 'Исполнено',
    reject: 'Отказаться от исполнения',
    consider: 'Рассмотреть',
    approve: 'Согласовать',
    open_card: 'Карточка в 1С'
  }
  const tones: Partial<Record<DocflowUiAction, 'primary' | 'outline' | 'danger'>> = {
    execute: 'primary',
    acquaint: 'primary',
    reject: 'danger',
    consider: 'outline',
    approve: 'primary'
  }
  const buttons = ids.map((id) => ({
    id,
    label: labels[id],
    tone: tones[id]
  }))
  buttons.push({ id: 'open_card', label: labels.open_card, tone: 'outline' })
  return buttons
}

export function turboActionButtons(): Array<{
  id: TurboUiAction
  label: string
  tone?: 'primary' | 'outline'
}> {
  return [
    { id: 'open_project', label: 'Открыть в TurboProject', tone: 'outline' },
    { id: 'mark_done', label: 'Исполнено (100%)', tone: 'primary' }
  ]
}

const DOCFLOW_ACTION_API: Record<DocflowUiAction, string | null> = {
  acquaint: 'acquaint',
  execute: 'execute',
  reject: 'reject',
  consider: 'consider',
  approve: 'approve',
  open_card: null
}

export async function runDocflowAction(
  user: UserProfile,
  ctx: TaskActionContext,
  action: DocflowUiAction
): Promise<TaskActionResult> {
  const refKey = (ctx.refKey || ctx.taskNumber || '').trim()
  if (!refKey && action !== 'open_card') {
    return { ok: false, message: 'Нет идентификатора задачи 1С (ref_key).' }
  }
  if (action === 'open_card') {
    const number = (ctx.taskNumber || ctx.refKey || '').trim()
    if (!number) return { ok: false, message: 'Нет номера задачи для карточки.' }
    const com = await invokeLocalAcTool('onec.get_task_card', { number, task_ref: number }, 120_000, user)
    if (com.ok) {
      return { ok: true, message: 'Карточка задачи загружена через COM (только чтение).' }
    }
    const res = await api.invokeServerTool(
      'onec.docflow_task_action',
      onecGatewayInvokeArgs(user, {
        action: 'retrieve',
        task_id: ctx.refKey,
        number: ctx.taskNumber
      }),
      120_000
    )
    if (res.ok) return { ok: true, message: 'Данные задачи получены с сервера документооборота.' }
    return {
      ok: false,
      message: com.error || res.error || 'Не удалось открыть карточку задачи.'
    }
  }
  const apiAction = DOCFLOW_ACTION_API[action]
  const res = await api.invokeServerTool(
    'onec.docflow_task_action',
    onecGatewayInvokeArgs(user, {
      action: apiAction,
      task_id: ctx.refKey,
      number: ctx.taskNumber,
      target_id: ctx.targetId,
      step: ctx.step,
      title: ctx.title
    }),
    180_000
  )
  if (res.ok) {
    const payload = res.result && typeof res.result === 'object' ? (res.result as Record<string, unknown>) : {}
    const summary = String(payload.summary || payload.message || 'Действие отправлено в 1С:Документооборот.')
    return { ok: true, message: summary }
  }
  return { ok: false, message: res.error || 'Документооборот не принял действие.' }
}

export async function runTurboAction(
  user: UserProfile,
  ctx: TaskActionContext,
  action: TurboUiAction,
  opts?: { projectUrl?: string }
): Promise<TaskActionResult> {
  if (action === 'open_project') {
    if (opts?.projectUrl) {
      window.open(opts.projectUrl, '_blank', 'noopener,noreferrer')
      return { ok: true, message: 'Открываю проект в TurboProject.' }
    }
    if (!ctx.projectId) return { ok: false, message: 'Нет project_id для TurboProject.' }
    const res = await api.invokeServerTool(
      'turboproject.get_project',
      turboProjectInvokeArgs(user, { project_id: ctx.projectId, fields: ['identity', 'urls'] }),
      120_000
    )
    const url =
      res.result && typeof res.result === 'object'
        ? String((res.result as Record<string, unknown>).url || '').trim()
        : ''
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer')
      return { ok: true, message: 'Открываю карточку проекта.' }
    }
    return { ok: false, message: res.error || 'URL проекта не найден.' }
  }
  if (action === 'mark_done') {
    return {
      ok: true,
      message:
        'Прогресс 100% сохранён локально. Синхронизация с MPP через TurboProject API пока недоступна из оркестратора.'
    }
  }
  return { ok: true, message: 'Обновите список задач проекта.' }
}
