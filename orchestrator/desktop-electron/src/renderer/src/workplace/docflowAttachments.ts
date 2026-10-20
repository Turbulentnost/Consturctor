import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { onecGatewayInvokeArgs } from './userContext'

export type DocflowAttachment = {
  id: string
  name: string
  extension: string
}

const GUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export const ATTACHED_FILES = {
  incoming: 'Catalog_ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы',
  outgoing: 'Catalog_ТД_ИсходящаяКорреспонденцияПрисоединенныеФайлы',
  memo: 'Catalog_ТД_СлужебнаяЗапискаПрисоединенныеФайлы',
  order: 'Catalog_ТД_ПриказПрисоединенныеФайлы',
  directive: 'Catalog_ТД_РаспоряжениеПрисоединенныеФайлы',
  payment: 'Catalog_ЗаявкаНаРасходованиеДенежныхСредствПрисоединенныеФайлы',
  forwarding: 'Catalog_ПоручениеЭкспедиторуПрисоединенныеФайлы'
} as const

function rowsFromResult(result: unknown): Record<string, unknown>[] {
  if (!result || typeof result !== 'object') return []
  const payload = result as Record<string, unknown>
  const value = payload.value
  if (Array.isArray(value)) {
    return value.filter((item) => item && typeof item === 'object') as Record<string, unknown>[]
  }
  const data = payload.data
  if (data && typeof data === 'object') {
    const nested = (data as Record<string, unknown>).value
    if (Array.isArray(nested)) {
      return nested.filter((item) => item && typeof item === 'object') as Record<string, unknown>[]
    }
  }
  return []
}

export function attachmentFileName(file: { name: string; extension?: string }): string {
  const name = (file.name || 'file').replace(/[\\/:*?"<>|]+/g, '_')
  const extension = (file.extension || '').replace(/^\./, '')
  if (!extension) return name
  if (name.toLowerCase().endsWith(`.${extension.toLowerCase()}`)) return name
  return `${name}.${extension}`
}

/** Присоединённые файлы документа ERP. Байты потом идут через hs/dtw/files, как у входящего письма. */
export async function loadDocflowAttachments(
  user: UserProfile | null,
  entity: string,
  ownerId: string
): Promise<DocflowAttachment[]> {
  if (!GUID_RE.test(ownerId)) throw new Error('У документа нет ссылки 1С')
  const res = await api.invokeServerTool(
    'onec.odata_get',
    onecGatewayInvokeArgs(user, {
      entity,
      filter: `ВладелецФайла_Key eq guid'${ownerId}' and DeletionMark eq false`,
      select: 'Ref_Key,Description,Расширение,ДатаСоздания',
      orderby: 'ДатаСоздания desc',
      top: 50
    }),
    60_000
  )
  if (!res.ok) throw new Error(res.error || 'Не удалось прочитать вложения в 1С')
  return rowsFromResult(res.result)
    .map((row) => ({
      id: String(row.Ref_Key || ''),
      name: String(row.Description || ''),
      extension: String(row.Расширение || '')
    }))
    .filter((file) => GUID_RE.test(file.id))
}

export async function openDocflowAttachment(file: { id: string; name: string; extension?: string }): Promise<void> {
  if (!GUID_RE.test(file.id)) throw new Error('У вложения нет ссылки 1С')
  const result = await window.api.download({
    url: `/api/v1/tools/onec-artifacts/${encodeURIComponent(file.id)}`,
    defaultName: attachmentFileName(file),
    token: api.getToken(),
    temporary: true,
    openAfter: true
  })
  if (!result.ok) throw new Error(result.error || 'Не удалось открыть вложение')
}
