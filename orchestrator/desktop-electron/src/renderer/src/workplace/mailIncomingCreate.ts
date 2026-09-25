import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { invokeLocalAcTool } from '../utils/localAcTool'
import { hasOutlookEntryId } from '../utils/outlookMailActions'
import type { SpecMailRow } from './specV04DemoData'
import { onecComInvokeArgs } from './userContext'
import { decodeMimeHeader } from '../utils/mimeHeader'

export type IncomingDepartmentOption = {
  code: string
  name: string
}

export type IncomingOrganizationOption = {
  code: string
  name: string
}

export type IncomingPayerOption = {
  code: string
  name: string
}

/** enum 1С «ТД_ПлательщикНаправление» → отображаемое имя (data/pochta display map). */
export const INCOMING_PAYERS: IncomingPayerOption[] = [
  { code: 'ТурбулентностьДОНКС', name: 'ООО НПО «Турбулентность-ДОН» КС' },
  { code: 'ТурбулентностьДОНПроизводство1', name: 'ООО НПО «Турбулентность-ДОН» пр-во1' },
  { code: 'ТурбулентностьДОНСС', name: 'ООО НПО «Турбулентность-ДОН» СС' },
  { code: 'ТурбулентностьДОНМС', name: 'ООО НПО «Турбулентность-ДОН» МС' },
  { code: 'ТурбулентностьДОНРУ', name: 'ООО НПО «Турбулентность-ДОН» РУ' },
  { code: 'АЛМАЗ', name: 'ООО «Алмаз»' },
  { code: 'Метрогазсервис', name: 'ООО «Метрогазсервис»' },
  { code: 'АмурскаяЛегенда', name: 'ООО «Амурская легенда»' },
  { code: 'БМИ', name: 'БМИ (блочно-модульные изделия)' }
]

/** Подразделения из «Код.docx». В форме только названия. */
export const INCOMING_DEPARTMENTS: IncomingDepartmentOption[] = [
  { code: '00-000001', name: 'Председатель Совета Директоров' },
  { code: '00-000002', name: 'Бухгалтерия' },
  { code: '00-000003', name: 'Административно-управленческий аппарат' },
  { code: '00-000006', name: 'ПРОИЗВОДСТВО НПО' },
  { code: '00-000007', name: 'ГЛАВНЫЙ КОНСТРУКТОР' },
  { code: '00-000010', name: 'Участок переповерки приборов' },
  { code: '00-000011', name: 'Отдел по работе с рекламациями' },
  { code: '00-000012', name: 'Конструкторское бюро' },
  { code: '00-000013', name: 'ДИРЕКТОР ПО РАЗВИТИЮ' },
  { code: '00-000015', name: 'Отдел внешнеэкономической деятельности' },
  { code: '00-000019', name: 'Отдел продаж Амурской легенды' },
  { code: '00-000020', name: 'Производство АКВАГЕН' },
  { code: '00-000021', name: 'Семикаракорское подразделение' },
  { code: '00-000022', name: 'Электрик/энергетик' },
  { code: '00-000023', name: 'Специалист по процессному управлению' },
  { code: '00-000024', name: 'Монтажный участок №2' },
  { code: '00-000025', name: 'Отдел метрологии и сертификации' },
  { code: '00-000028', name: 'Отдел сервисного обслуживания' },
  { code: '00-000029', name: 'Служба ремонта и обслуживания оборудования' },
  { code: '00-000031', name: 'Планово-диспетчерская служба' },
  { code: '00-000033', name: 'Участок ремонта пром.оборудования производственного цеха №1' },
  { code: '00-000035', name: 'ДИРЕКТОР МИЛАКА' },
  { code: '00-000036', name: 'Сальское подразделение' },
  { code: '00-000038', name: 'Эксплуатационная служба' },
  { code: '00-000040', name: 'Зам. технического директора по качеству' },
  { code: '00-000042', name: 'Отдел по работе с ключевыми клиентами' },
  { code: '00-000044', name: 'Юридический отдел' },
  { code: '00-000046', name: 'АХО' },
  { code: '00-000047', name: 'Производственный цех №1' },
  { code: '00-000048', name: 'Складской комплекс' },
  { code: '00-000049', name: 'ФИНАНСОВЫЙ ДИРЕКТОР' },
  { code: '00-000050', name: 'ЗАМЕСТИТЕЛЬ ДИРЕКТОРА ПО КАЧЕСТВУ' },
  { code: '00-000051', name: 'Конструкторско-технологический отдел' },
  { code: '00-000053', name: 'Производственный цех №2' },
  { code: '00-000054', name: 'Тендерный офис' },
  { code: '00-000056', name: 'Метрологическая служба' },
  { code: '00-000057', name: 'Отдел информационных технологий' },
  { code: '00-000058', name: 'КОММЕРЧЕСКИЙ ДИРЕКТОР' },
  { code: '00-000059', name: 'ЗАМ. ДИРЕКТОРА ПО ЭКОНОМИЧЕСКОЙ БЕЗОПАСНОСТИ' },
  { code: '00-000060', name: 'Механический участок №1' },
  { code: '00-000061', name: 'Служба безопасности' },
  { code: '00-000062', name: 'Служба развития' },
  { code: '00-000063', name: 'Служба управления персоналом' },
  { code: '00-000064', name: 'Отдел сопровождения 1С' },
  { code: '00-000065', name: 'Отдел МТО' },
  { code: '00-000066', name: 'Управление делами' },
  { code: '00-000068', name: 'НАЧАЛЬНИК СЛУЖБЫ ЛОГИСТИКИ' },
  { code: '00-000069', name: 'Ремонтный участок стендов' },
  { code: '00-000071', name: 'Участок ремонта гарантийных приборов' },
  { code: '00-000072', name: 'Участок Гранд SPI' },
  { code: '00-000073', name: 'Механический цех' },
  { code: '00-000074', name: 'Отдел продаж эталонного оборудования и услуг' },
  { code: '00-000076', name: 'Отдел по работе с ПАО Газпром' },
  { code: '00-000078', name: 'Заместитель главного конструктора по проектной деятельности' },
  { code: '00-000080', name: 'ДИРЕКТОР МЕТРОГАЗСЕРВИСА' },
  { code: '00-000082', name: 'Основное подразделение (Промзона)' },
  { code: '00-000083', name: 'Батайское подразделение' },
  { code: '00-000084', name: 'Новочеркасское подразделение' },
  { code: '00-000085', name: 'Таганрогское подразделение' },
  { code: '00-000087', name: 'Шахтинское подразделение' },
  { code: '00-000088', name: 'Каменск-Шахтинское подразделение' },
  { code: '00-000090', name: 'Ростов СЦ (Нагибина)' },
  { code: '00-000091', name: 'Азовское подразделение' },
  { code: '00-000092', name: 'Склад ремонтных приборов' },
  { code: '00-000093', name: 'Волгодонское подразделение' },
  { code: '00-000094', name: 'Сборочный участок №1' },
  { code: '00-000096', name: 'Участок сборки счетчиков' },
  { code: '00-000097', name: 'Участок СПУ-5 (АЛМАЗ)' },
  { code: '00-000098', name: 'Участок упаковки' },
  { code: '00-000099', name: 'Отдел технической поддержки' },
  { code: '00-000100', name: 'ОТК-1' },
  { code: '00-000101', name: 'ОТК-2' },
  { code: '00-000102', name: 'ПРОИЗВОДСТВО АЛМАЗ' },
  { code: '00-000103', name: 'Экономический отдел' },
  { code: '00-000104', name: 'Сервисная служба' },
  { code: '00-000106', name: 'ДИРЕКТОР АМУРСКОЙ ЛЕГЕНДЫ' },
  { code: '00-000107', name: 'Сборочный участок №2' },
  { code: '00-000110', name: 'Участок ремонта гарантийных плат' },
  { code: '00-000111', name: 'Транспортная служба' },
  { code: '00-000112', name: 'Участок ультразвуковых датчиков' },
  { code: '00-000113', name: 'ГСПП' },
  { code: '00-000116', name: 'Миллеровское подразделение' },
  { code: '00-000117', name: 'Зерноградское подразделение' },
  { code: '00-000118', name: 'Новошахтинское подразделение' },
  { code: '00-000119', name: 'Сектор разработки ПО и АСУ' },
  { code: '00-000122', name: 'Производственный цех №3' },
  { code: '00-000123', name: 'Лаборатория неразрушающего контроля' },
  { code: '00-000127', name: 'Cектор рекламы и PR' },
  { code: '00-000128', name: 'Отдел продаж БМИ' },
  { code: '00-000129', name: 'Сектор по развитию новых продуктов' },
  { code: '00-000130', name: 'Заместитель директора' },
  { code: '00-000134', name: 'Отдел ценообразования' },
  { code: '00-000135', name: 'Отдел снабжения' },
  { code: '00-000136', name: 'ДИРЕКТОР ПО ПРОДАЖАМ КЛЮЧЕВЫМ КЛИЕНТАМ' },
  { code: '00-000143', name: 'Сектор по внедрению искусственного интеллекта' },
  { code: '00-000145', name: 'Служба подготовки производства' },
  { code: '00-000146', name: 'Экспериментальный производственный цех' },
  { code: '00-000148', name: 'Отдел внедрения' },
  { code: '00-000149', name: 'ГЛАВНЫЙ МЕТРОЛОГ' },
  { code: '00-000150', name: 'Специалист по товарным запасам' },
  { code: '00-000152', name: 'ОПЕРАЦИОННЫЙ ДИРЕКТОР' },
  { code: '00-000153', name: 'Вёшенское подразделение' },
  { code: '00-000154', name: 'Ревизионная комиссия' },
  { code: '00-000155', name: 'Отдел дилерских продаж' },
  { code: '00-000156', name: 'Зам. технического директора по сервису' },
  { code: '00-000157', name: 'Сектор обучения и развития' },
  { code: '00-000158', name: 'Сектор сопровождения продаж' },
  { code: '00-000159', name: 'Сектор сопровождения производства и продаж' },
  { code: '00-000160', name: 'Сектор доработки и улучшения продукции' },
  { code: '00-000161', name: 'Инспекционная группа' },
  { code: '00-000162', name: 'Сектор постановки на производство несерийной продукции' },
  { code: '00-000163', name: 'ТЕХНИЧЕСКИЙ ДИРЕКТОР' },
  { code: '00-000164', name: 'Проектный офис' },
  { code: '00-000165', name: 'Помощник операционного директора' },
  { code: '00-000166', name: 'Производство несерийных изделий' },
  { code: '00-000167', name: 'Зам. директора по производству' },
  { code: '00-000168', name: 'Служба технического директора' },
  { code: '00-000169', name: 'Сектор качества разработки' },
  { code: '00-000170', name: 'Сектор разработки тех. решений' },
  { code: '00-000171', name: 'Сектор промышленной безопасности' },
  { code: '00-000172', name: 'Зам. директора по перспективным проектам' },
  { code: '00-000173', name: 'Зам. коммерческого директора по развитию продаж' },
  { code: '00-000174', name: 'Цех БМИ' },
  { code: '00-000175', name: 'Отдел управления несоответствиями' },
  { code: '00-000176', name: 'Участок сборки UFG-FC' },
  { code: '00-000177', name: 'Участок производства СПУ-3М' },
  { code: '00-000178', name: 'Заготовительный участок (Монтажный)' },
  { code: '00-000179', name: 'Заготовительный участок (Механический)' },
  { code: '00-000180', name: 'Заготовительный участок (Сборочный)' },
  { code: '00-000181', name: 'Участок сборки UFG-H' },
  { code: '00-000182', name: 'Помощник зам. операционного директора' },
  { code: '00-000183', name: 'Заготовительный участок' }
]

export const INCOMING_ORGANIZATIONS: IncomingOrganizationOption[] = [
  { code: 'НП', name: 'НПО «Турбулентность-ДОН»' },
  { code: 'АЛ', name: 'ООО «Алмаз»' },
  { code: 'МГ', name: 'ООО «Метрогазсервис»' },
  { code: 'АМ', name: 'ООО «Амурская легенда»' },
  { code: 'МИ', name: 'ООО «МИЛАКА»' },
  { code: 'БМ', name: 'БМИ (блочно-модульные изделия)' }
]

export function organizationLabel(codeOrName: string): string {
  const text = codeOrName.trim()
  const byCode = INCOMING_ORGANIZATIONS.find((item) => item.code === text)
  if (byCode) return byCode.name
  return text
}

export type IncomingCreateDraft = {
  departmentId: string
  departmentName: string
  theme: string
  partner: string
  organization: string
  /** enum-код «ТД_ПлательщикНаправление»; пусто = backend вычислит по организации. */
  payerDirection: string
  emailSender: string
  emailRecipient: string
  content: string
}

export type IncomingCreateResult = {
  ok: boolean
  number?: string
  refKey?: string
  summary?: string
  attachmentWarning?: string
  error?: string
}

function entryIdOf(row: { entryId?: string; id: string }): string {
  const explicit = String(row.entryId || '').trim()
  if (explicit && !explicit.toLowerCase().startsWith('imap:')) return explicit
  return String(row.id || '').trim()
}

/** Ящик agent-pochta: письмо разбирает ИИ и создаёт входящую. */
export const INCOMING_AI_MAILBOX = 'info@turbo-don.ru'

export async function forwardIncomingMailToAi(
  mail: SpecMailRow
): Promise<{ ok: boolean; error?: string }> {
  if (!hasOutlookEntryId(mail)) {
    return { ok: false, error: 'Переадресация доступна для писем Outlook (COM).' }
  }
  const response = await invokeLocalAcTool(
    'outlook.display_message',
    {
      entry_id: entryIdOf(mail),
      mode: 'forward',
      to: INCOMING_AI_MAILBOX,
      send: true
    },
    60_000
  )
  if (!response.ok) {
    return { ok: false, error: response.error || 'Не удалось переслать письмо' }
  }
  if (response.result?.sent !== true) {
    return {
      ok: false,
      error:
        'Outlook не подтвердил отправку. Полностью перезапустите Orchestrator и повторите переадресацию.'
    }
  }
  return { ok: true }
}

/** Первый e-mail из строки вида «Иванов Иван <ivanov@example.ru>» или пусто. */
export function extractEmailAddress(text: string | undefined): string {
  const match = String(text || '').match(/[\w.+-]+@[\w.-]+\.[\wа-яё-]+/i)
  return match ? match[0] : ''
}

export function emptyIncomingCreateDraft(
  mail?: SpecMailRow,
  detail?: {
    subject?: string
    sender?: string
    senderEmail?: string
    bodyPreview?: string
    recipient?: string
  }
): IncomingCreateDraft {
  // «Почта отправителя» — именно e-mail (Outlook sender — display name, не адрес).
  const senderText = decodeMimeHeader(detail?.sender || mail?.sender || '')
  const senderEmail =
    (detail?.senderEmail || '').trim() ||
    extractEmailAddress(senderText)
  return {
    departmentId: '',
    departmentName: '',
    theme: decodeMimeHeader(detail?.subject || mail?.subject || '').trim(),
    partner: '',
    organization: 'НП',
    payerDirection: '',
    emailSender: senderEmail,
    emailRecipient: (detail?.recipient || '').trim(),
    content: (detail?.bodyPreview || '').trim()
  }
}

function parseNamedOptions(rows: unknown): IncomingDepartmentOption[] {
  if (!Array.isArray(rows)) return []
  return rows
    .map((row) => {
      if (!row || typeof row !== 'object') return null
      const item = row as Record<string, unknown>
      const code = String(item.code || '').trim()
      const name = String(item.name || '').trim()
      if (!code || !name || name === code) return null
      return { code, name }
    })
    .filter((item): item is IncomingDepartmentOption => Boolean(item))
}

export async function fetchIncomingCatalog(): Promise<{
  departments: IncomingDepartmentOption[]
  organizations: IncomingOrganizationOption[]
  payers: IncomingPayerOption[]
}> {
  const response = await api.invokeServerTool(
    'onec.incoming_correspondence',
    { action: 'departments' },
    60_000
  )
  if (!response.ok) {
    return {
      departments: INCOMING_DEPARTMENTS,
      organizations: INCOMING_ORGANIZATIONS,
      payers: INCOMING_PAYERS
    }
  }
  const result = response.result as Record<string, unknown> | undefined
  const organizations = parseNamedOptions(result?.organizations)
  const departments = parseNamedOptions(result?.departments)
  const payers = parseNamedOptions(result?.payers)
  return {
    departments:
      departments.length >= INCOMING_DEPARTMENTS.length ? departments : INCOMING_DEPARTMENTS,
    organizations: organizations.length ? organizations : INCOMING_ORGANIZATIONS,
    payers: payers.length ? payers : INCOMING_PAYERS
  }
}

export type IncomingRouteSuggestion = {
  department?: IncomingDepartmentOption
  organization?: IncomingOrganizationOption
  payer?: IncomingPayerOption
  direction?: string
  confidence?: number
  source?: string
  reasoning?: string
}

function parseCodeName(raw: unknown): IncomingDepartmentOption | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const item = raw as Record<string, unknown>
  const code = String(item.code || '').trim()
  const name = String(item.name || '').trim()
  if (!code) return undefined
  return { code, name: name || code }
}

/**
 * Подсказка отдела и плательщика по контексту письма (backend onec.incoming_suggest,
 * перенос RAG-каскада agent-pochta). Возвращает null при любой ошибке — форма
 * остаётся полностью ручной.
 */
export async function suggestIncomingRoute(input: {
  subject?: string
  body?: string
  sender?: string
  senderEmail?: string
}): Promise<IncomingRouteSuggestion | null> {
  const response = await api.invokeServerTool(
    'onec.incoming_suggest',
    {
      subject: (input.subject || '').slice(0, 500),
      body: (input.body || '').slice(0, 8000),
      sender: input.sender || '',
      sender_email: input.senderEmail || ''
    },
    30_000
  )
  if (!response.ok) return null
  const result = response.result as Record<string, unknown> | undefined
  if (!result) return null
  return {
    department: parseCodeName(result.department),
    organization: parseCodeName(result.organization),
    payer: parseCodeName(result.payer),
    direction: String(result.direction || '').trim() || undefined,
    confidence: typeof result.confidence === 'number' ? result.confidence : undefined,
    source: String(result.source || '').trim() || undefined,
    reasoning: String(result.reasoning || '').trim() || undefined
  }
}

export async function fetchIncomingDepartments(): Promise<IncomingDepartmentOption[]> {
  const catalog = await fetchIncomingCatalog()
  return catalog.departments
}

function parseWriteResult(result: unknown): Omit<IncomingCreateResult, 'ok' | 'error'> {
  if (!result || typeof result !== 'object') return {}
  const payload = result as Record<string, unknown>
  const data =
    payload.data && typeof payload.data === 'object'
      ? (payload.data as Record<string, unknown>)
      : undefined
  return {
    refKey: String(payload.erp_document_id || data?.Ref_Key || '').trim() || undefined,
    number: String(data?.Number || payload.number || '').trim() || undefined,
    summary: String(payload.summary || '').trim() || undefined,
    attachmentWarning: String(payload.attachment_warning || '').trim() || undefined
  }
}

export async function createIncomingFromMail(
  user: UserProfile | null,
  mail: SpecMailRow,
  draft: IncomingCreateDraft,
  _detail?: { receivedAt?: string }
): Promise<IncomingCreateResult> {
  if (!hasOutlookEntryId(mail)) {
    return {
      ok: false,
      error: 'Регистрация входящей доступна для писем Outlook (COM).'
    }
  }

  const departmentId = draft.departmentId.trim()
  if (!departmentId) {
    return { ok: false, error: 'Укажите код подразделения (кому на исполнение)' }
  }
  const theme = draft.theme.trim()
  if (!theme) {
    return { ok: false, error: 'Укажите тему входящей' }
  }
  if (!draft.partner.trim()) {
    return { ok: false, error: 'Укажите партнёра — без него 1С не записывает входящую' }
  }

  const entryId = entryIdOf(mail)
  const saveRes = await invokeLocalAcTool(
    'outlook.save_message',
    onecComInvokeArgs(
      {
        entry_id: entryId,
        stage_for_incoming: true
      },
      user
    ),
    180_000,
    user
  )
  if (!saveRes.ok || !saveRes.result) {
    return { ok: false, error: saveRes.error || 'Не удалось сохранить .msg из Outlook' }
  }

  const staged = saveRes.result
  const stagedPath = String(staged.staged_path || '').trim()
  if (!stagedPath) {
    return {
      ok: false,
      error: 'Outlook сохранил письмо, но путь для 1С не получен. Повторите создание.'
    }
  }

  const msgBase64 = String(staged.msg_base64 || '').trim()
  const msgFilename = String(
    staged.msg_filename || staged.file_name || 'message.msg'
  ).trim()

  // Date in 1C = registration moment (backend Europe/Moscow now).
  // Prefer local staged_path; also send msg_base64 so attach works if path is unreadable.
  const args: Record<string, unknown> = {
    action: 'create',
    department_id: departmentId,
    department_name: draft.departmentName.trim(),
    theme,
    partner: draft.partner.trim(),
    organization: draft.organization.trim() || 'НП',
    payer_direction: draft.payerDirection.trim(),
    email_sender: draft.emailSender.trim(),
    email_recipient: draft.emailRecipient.trim(),
    content: draft.content.trim() || theme,
    attach_msg: true,
    staged_path: stagedPath,
    msg_file_path: stagedPath,
    msg_filename: msgFilename
  }
  if (msgBase64) {
    args.msg_base64 = msgBase64
  }

  const response = await api.invokeServerTool('onec.incoming_correspondence_write', args, 180_000)
  if (!response.ok) {
    return { ok: false, error: response.error || 'OData: не удалось создать входящую в 1С' }
  }
  const parsed = parseWriteResult(response.result)
  if (!parsed.refKey && !parsed.number) {
    return {
      ok: false,
      error:
        parsed.summary ||
        'Backend не вернул номер/ссылку документа — запись в 1С, вероятно, не выполнена'
    }
  }
  return {
    ok: true,
    ...parsed,
    summary:
      parsed.summary ||
      (parsed.number
        ? `Создана входящая ${parsed.number}`
        : 'Документ входящей создан в 1С через OData')
  }
}
