import type { UserProfile } from '../api/types'
import { invokeLocalAcTool } from '../utils/localAcTool'
import { onecComInvokeArgs } from './userContext'
import { openHttpUrl } from './workplaceNav'

/** Журнал поручений АСТ00 — форма списка в толстом клиенте 1С. */
export const ONEC_ASSIGNMENT_LIST_FORM = 'Документ.ТД_Поручения.Форма.ФормаСписка'

export type OpenAssignmentFormResult = {
  ok: boolean
  error?: string
  method?: string
}

function erpWebListUrl(): string {
  const raw = (import.meta.env.VITE_1C_ERP_WEB_URL || import.meta.env.VITE_ODATA_WEB_BASE || '').trim()
  if (!raw) return ''
  const base = raw.replace(/\/+$/, '')
  if (base.includes('#')) return base
  return `${base}#e1cib/list/Document.ТД_Поручения`
}

/** Открыть форму списка поручений в 1С (создание — кнопка «Создать» в форме 1С). */
export async function openAssignmentListFormIn1C(
  user: UserProfile | null
): Promise<OpenAssignmentFormResult> {
  const res = await invokeLocalAcTool(
    'onec.open_form',
    onecComInvokeArgs(
      {
        form: ONEC_ASSIGNMENT_LIST_FORM,
        metadata: 'Document.ТД_Поручения',
        form_name: 'ФормаСписка'
      },
      user
    ),
    120_000,
    user
  )
  if (res.ok) {
    return { ok: true, method: String(res.result?.method || 'onec.open_form') }
  }
  const web = erpWebListUrl()
  if (web && openHttpUrl(web)) {
    return { ok: true, method: 'web_client' }
  }
  const raw = res.error || ''
  const comHint =
    /ONEC_COM_SERVER|ONEC_COM_REF|ONEC_ENTERPRISE_DB/i.test(raw)
      ? ' Задайте ONEC_COM_SERVER и ONEC_COM_REF в orchestrator/desktop/.env (или перезапустите приложение после настройки).'
      : ''
  return {
    ok: false,
    error:
      raw ||
      `Не удалось открыть 1С.${comHint} Либо запустите erp_pm вручную.`
  }
}
