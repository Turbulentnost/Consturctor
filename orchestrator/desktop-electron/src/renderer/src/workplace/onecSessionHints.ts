import { comCredentials, hasComPassword } from '../store/session'

/** Dev-only suffix for empty 1C states (no password value). */
export function comPasswordSessionHint(): string {
  const login = (comCredentials().login || '').trim()
  if (hasComPassword()) {
    return login
      ? `Пароль 1С: введён на экране входа · логин SOAP: ${login}`
      : 'Пароль 1С: введён на экране входа'
  }
  return 'Пароль 1С: не введён (не берём пароль из .env)'
}

export function missingComPasswordMessage(): string {
  return (
    'Войдите с паролем 1С — после восстановления сеанса по JWT пароль не сохраняется. ' +
    'Выйдите и войдите снова или перезапустите приложение и введите пароль на экране входа.'
  )
}

export function formatComToolError(message: string): string {
  const text = (message || '').trim()
  if (!text) return ''
  if (/не удалось открыть сеанс|неверно указан пользователь|неверный логин|402|password/i.test(text)) {
    return `${text} ${comPasswordSessionHint()}`
  }
  return text
}

export type ApiAuthErrorKind =
  | 'session_revoked'
  | 'invalid_token'
  | 'auth_required'
  | 'gateway_auth'
  | 'other'

/** Classify backend / gateway auth errors for UI and re-login policy. */
export function classifyApiAuthError(message: string, status = 0): ApiAuthErrorKind {
  const text = (message || '').trim()
  if (!text && status !== 401 && status !== 402) return 'other'
  if (/Сеанс завершён|session_replaced|другом устройств/i.test(text)) return 'session_revoked'
  if (/Недействительный токен|invalid token/i.test(text)) return 'invalid_token'
  if (/Требуется авторизация|authorization required/i.test(text)) return 'auth_required'
  if (/Неверный логин или пароль/i.test(text)) return 'other'
  if (
    /Gateway отклонил|отклонил учётку OData|OData документооборота|docflow.*401|документооборот.*отклон/i.test(
      text
    )
  ) {
    return 'gateway_auth'
  }
  if (status === 402) return 'gateway_auth'
  if (status === 401 && /gateway|odata|docflow|отклонил учётку/i.test(text)) return 'gateway_auth'
  return 'other'
}

/** True when the desktop should clear JWT and show the login form. */
export function shouldForceReLogin(message: string, status = 0): boolean {
  const kind = classifyApiAuthError(message, status)
  return kind === 'session_revoked' || kind === 'invalid_token' || kind === 'auth_required'
}

const DOK_HTTP_ENV_BANNER =
  /Задайте DOK_HTTP_SERVER( и DOK_HTTP_USER)? в окружении или \.env/i
const GATEWAY_STUB_BANNER =
  /Gateway вернул stub \(нет ERP SQL\s*\/\s*OData на сервере\)/i
const DOK_STUB_BANNER = /Документооборот:\s*stub \(нет DOK_HTTP_\* на backend\)/i
const DOK_HTTP_CONFIG_HINT =
  /задайте DOK_HTTP_(SERVER|USER|PASSWORD)|нет DOK_HTTP_\*|Передайте ФИО и пароль сеанса/i
const COM_FALLBACK_HINT = /VITE_ONEC_COM_TASKS_FALLBACK|COM onec\.search_tasks/i

/** Env / stub / old-gateway paragraphs — never show these as user-facing errors. */
export function isTechnicalDocflowConfigMessage(text: string): boolean {
  const t = (text || '').trim()
  if (!t) return false
  return (
    DOK_HTTP_ENV_BANNER.test(t) ||
    GATEWAY_STUB_BANNER.test(t) ||
    DOK_STUB_BANNER.test(t) ||
    DOK_HTTP_CONFIG_HINT.test(t) ||
    COM_FALLBACK_HINT.test(t) ||
    /нет ERP SQL\s*\/\s*OData|Проверьте ERP_\* на backend/i.test(t)
  )
}

export function stripTechnicalDocflowMessages(text: string): string {
  if (!(text || '').trim()) return ''
  const kept = text
    .split(' · ')
    .map((part) => part.trim())
    .filter((part) => part && !isTechnicalDocflowConfigMessage(part))
  return kept.join(' · ')
}

/** User-facing 1C error: technical stub/env text is dropped. */
export function userFacingOneCError(text: string): string {
  const cleaned = stripTechnicalDocflowMessages(text)
  if (/^HTTP\s*40[123]\s*:?\s*$/i.test(cleaned) || /HTTP\s*40[123]:\s*$/i.test(cleaned)) {
    return 'Документооборот не принял учётку. Войдите с паролем 1С.'
  }
  if (/HTTP\s*40[123].*отклонил Basic/i.test(cleaned)) {
    return 'Документооборот не принял учётку. Войдите с паролем 1С.'
  }
  return cleaned
}

export function sessionOneCSourceLabel(fio: string): string {
  const name = (fio || '').trim()
  return name ? `1С · ${name}` : '1С'
}

export function sessionOneCEmptyText(fio: string): string {
  const name = (fio || '').trim()
  return name ? `Нет открытых задач 1С для ${name}.` : 'Нет открытых задач 1С.'
}

export function sessionOneCLoadingText(fio: string): string {
  const name = (fio || '').trim()
  return name ? `Загружаем задачи 1С для ${name}…` : 'Загружаем задачи 1С…'
}

/** COM / gateway / OData signals that 1C credentials or session must be re-entered. */
export function isOneCAuthFailure(...chunks: (string | undefined | null)[]): boolean {
  const text = chunks
    .filter(Boolean)
    .map((chunk) => String(chunk).trim())
    .join(' ')
    .trim()
  if (!text) return false
  const cleaned = stripTechnicalDocflowMessages(text)
  if (!cleaned) return !hasComPassword()
  if (/Войдите с паролем 1С|пароль не сохраняется|Пароль 1С в сессии: нет|экрана входа|не берём пароль из \.env/i.test(cleaned)) {
    return true
  }
  if (/Документооборот SOAP: нет (пароля|пользователя|учётн)/i.test(cleaned)) {
    return true
  }
  if (/Передайте ФИО и пароль сеанса|задайте DOK_HTTP_USER/i.test(cleaned)) {
    return true
  }
  if (
    /Сеанс Orchestrator завершён|JWT недействителен|Требуется авторизация/i.test(text)
  ) {
    return true
  }
  if (/Gateway\/OData отклонил|отклонил учётку OData|\b402\b|unauthorized|отклонил учётку/i.test(text)) {
    return true
  }
  if (/не удалось открыть сеанс|неверно указан пользователь|неверный логин|неверный пароль|authentication/i.test(text)) {
    return true
  }
  if (/docflow|документооборот|odata/i.test(text) && /401|402|отклон|auth|парол|учётк|unauthorized/i.test(text)) {
    return true
  }
  return false
}

/** 1C may ask for a second authorization step after the first password. */
export function isDoubleOneCAuthHint(...chunks: (string | undefined | null)[]): boolean {
  const text = chunks
    .filter(Boolean)
    .map((chunk) => String(chunk).trim())
    .join(' ')
    .trim()
  if (!text) return false
  return /двойн|double.?auth|second.?factor|повторн.*авториз|402|второй.*парол|two.?step/i.test(text)
}

export function formatGatewayToolError(message: string, status = 0): string {
  const text = (message || '').trim()
  const kind = classifyApiAuthError(text, status)

  if (kind === 'session_revoked') {
    return (
      'Сеанс Orchestrator завершён (вход на другом устройстве или повторный вход). ' +
      'Войдите с паролем 1С снова.'
    )
  }
  if (kind === 'invalid_token') {
    return (
      'JWT недействителен или выдан другим backend (localhost vs LAN :7812). ' +
      'Выйдите и войдите снова; для dev используйте run_dev.bat backend и BACKEND_URL=http://127.0.0.1:7812.'
    )
  }
  if (kind === 'auth_required') {
    return 'Требуется авторизация — войдите с паролем 1С.'
  }
  if (kind === 'gateway_auth') {
    const code = status === 402 ? 402 : 401
    const cleaned = userFacingOneCError(text)
    const tail = cleaned && !/Gateway отклонил/i.test(cleaned) ? ` (${cleaned})` : ''
    return (
      `Gateway/OData отклонил запрос (${code}). Проверьте пароль 1С в сеансе и ODATA_* / DOCFLOW_* на backend. ` +
      `На старом LAN gateway обновите constructor-gateway.${tail} ${comPasswordSessionHint()}`
    )
  }
  if (status === 401 && text) {
    const cleaned = userFacingOneCError(text)
    return cleaned ? `Доступ запрещён (401): ${cleaned}` : ''
  }
  if (status === 401) {
    return `Доступ запрещён (401). ${comPasswordSessionHint()}`
  }
  if (/401|402|unauthorized|отклонил учётку/i.test(text)) {
    if (/обновите|gateway/i.test(text)) return userFacingOneCError(text)
    return userFacingOneCError(
      `${text} Если ошибка повторяется — проверьте пароль 1С (${comPasswordSessionHint()}).`
    )
  }
  return userFacingOneCError(text)
}

/** Gateway/docflow hint strings must not appear as rows in the 1C task grid. */
export function isErpMetaHintRecord(task: Record<string, unknown>): boolean {
  const number = String(task.number || '').trim()
  if (/^\d{2}-[\wА-Яа-яЁё.-]+-\d{3,}$/i.test(number)) return false
  const title = String(task.title || number || '').trim()
  if (!title) return true
  if (isTechnicalDocflowConfigMessage(title)) return true
  if (
    /BACKEND_URL|127\.0\.0\.1:7812|192\.168\.\d+\.\d+:7812|LAN gateway|run_dev\.bat|erp_reachable|constructor-gateway устарел|VPN на вашем ПК/i.test(
      title
    )
  ) {
    return true
  }
  if (/Документооборот\s*\(\/doc\)|отклонил учётку OData|OData документооборота/i.test(title)) {
    return true
  }
  if (
    /Gateway\/SQL без задач|onec\.erp_tasks_current|erp_pm stub|Gateway вернул stub/i.test(title)
  ) {
    return true
  }
  if (/Войдите с паролем 1С|Пароль 1С в сессии|Пароль 1С: введён|Пароль 1С: не введён/i.test(title)) return true
  return false
}

/** Docflow /doc OData rejection or missing DOCFLOW_* (not erp_pm SQL). */
export function isDocflowOdataWarning(text: string): boolean {
  const t = (text || '').trim()
  if (!t) return false
  return /документооборот|\/doc\)|OData документооборота|DOCFLOW_ODATA|docflow/i.test(t)
}

export function formatDocflowSecondaryHint(warning: string): string {
  const w = (warning || '').trim()
  if (!w) return ''
  if (/^Документооборот \(доп\./i.test(w)) return w
  return `Документооборот (доп.): ${w}`
}

/** Desktop uses a private-LAN gateway (:7812); ERP SQL runs on that server, not on the PC. */
export function isLanBackendUrl(backendUrl: string): boolean {
  const url = (backendUrl || '').trim()
  if (!url) return false
  if (/127\.0\.0\.1|localhost/i.test(url)) return false
  return /:\/\/192\.168\.|:\/\/10\.|:\/\/172\.(1[6-9]|2\d|3[01])\./.test(url)
}

/** erp_reachable on gateway but onec.erp_tasks_current returns 0 — stale gateway image. */
export function lanGatewayZeroTasksHint(backendUrl: string): string {
  const host = (() => {
    try {
      return new URL(backendUrl).host
    } catch {
      return backendUrl.replace(/^https?:\/\//i, '').replace(/\/+$/, '') || '192.168.1.157:7812'
    }
  })()
  return (
    `1С на gateway (${host}) доступна (erp_reachable), но задач 0 — образ constructor-gateway устарел. ` +
    `Админу на сервере: пересоберите и задеплойте gateway из orchestrator/backend (коммит ≥ 6d0e958, fix _query_tasks в erp_tasks.py). ` +
    `VPN на вашем ПК для SQL не нужен. После деплоя — перезапуск контейнера и повторный вход в Orchestrator (JWT).`
  )
}

/** Never user-facing. Old remote gateways still return source=stub; hide that paragraph. */
export function stubSourceMessage(source: string): string {
  void source
  return ''
}

export function enrichEmptyOneCErrors(
  erpError: string,
  opts: {
    erpSource?: string
    docSource?: string
    mergedCount: number
    fio?: string
  }
): string {
  const cleaned = userFacingOneCError(erpError)
  if (opts.mergedCount > 0) return cleaned
  const stub =
    (opts.erpSource || '').trim().toLowerCase() === 'stub' ||
    (opts.docSource || '').trim().toLowerCase() === 'stub'
  if (stub && !cleaned) return ''
  return cleaned
}
