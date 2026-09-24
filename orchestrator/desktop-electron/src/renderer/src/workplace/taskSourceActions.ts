import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { onecGatewayInvokeArgs } from './userContext'
import { turboProjectInvokeArgs } from './userContext'
import type { TaskActionContext } from './taskSourceKind'
import {
  docflowKindActions,
  docflowTaskKind,
  type DocflowActionId,
  type DocflowActionSpec,
  type DocflowTaskKind
} from './docflowTaskKind'

export type DocflowUiAction = DocflowActionId | 'open_card'

export type TurboUiAction = 'open_project' | 'mark_done' | 'refresh'

export type TaskActionResult = { ok: boolean; message: string }

export function docflowKindOfContext(ctx: TaskActionContext): DocflowTaskKind {
  return ctx.docflowKind ?? docflowTaskKind(ctx.step, ctx.taskName)
}

/** Задачи «от меня» завершает исполнитель, у автора остаётся только карточка. */
export function canActOnDocflowTask(ctx: TaskActionContext): boolean {
  return String(ctx.role || '').trim().toLowerCase() !== 'author'
}

export function docflowActionButtons(ctx: TaskActionContext): DocflowActionSpec[] {
  return canActOnDocflowTask(ctx) ? docflowKindActions(docflowKindOfContext(ctx)) : []
}

export function turboActionButtons(opts?: { taskUid?: string }): Array<{
  id: TurboUiAction
  label: string
  tone?: 'primary' | 'outline'
}> {
  const buttons: Array<{ id: TurboUiAction; label: string; tone?: 'primary' | 'outline' }> = [
    { id: 'open_project', label: 'Открыть в TurboProject', tone: 'outline' }
  ]
  // «Исполнено» только у задачи проекта, не у карточки самого проекта.
  if ((opts?.taskUid || '').trim()) {
    buttons.push({ id: 'mark_done', label: 'Исполнено (100%)', tone: 'primary' })
  }
  return buttons
}

export async function runDocflowAction(
  user: UserProfile,
  ctx: TaskActionContext,
  action: DocflowUiAction,
  comment = ''
): Promise<TaskActionResult> {
  const refKey = (ctx.refKey || '').trim()
  if (!refKey) {
    return { ok: false, message: 'Нет идентификатора задачи 1С (ref_key).' }
  }
  if (action === 'open_card') {
    const res = await api.invokeServerTool(
      'onec.docflow_task_action',
      onecGatewayInvokeArgs(user, { action: 'web_url', task_id: refKey }),
      60_000
    )
    const url =
      res.ok && res.result && typeof res.result === 'object'
        ? String((res.result as Record<string, unknown>).web_url || '').trim()
        : ''
    if (!url) return { ok: false, message: res.error || 'Не удалось открыть карточку задачи.' }
    window.open(url, '_blank', 'noopener,noreferrer')
    return { ok: true, message: 'Карточка задачи открыта в веб-клиенте 1С:Документооборот.' }
  }
  const res = await api.invokeServerTool(
    'onec.docflow_task_action',
    onecGatewayInvokeArgs(user, {
      action,
      task_id: refKey,
      number: ctx.taskNumber,
      target_id: ctx.targetId,
      step: ctx.step,
      title: ctx.title,
      comment: comment.trim()
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
