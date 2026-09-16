/** TurboProject недоступен: нет сервисной учётки или ошибка авторизации API. */
export function isTurboNoSessionError(message: string): boolean {
  const text = (message || '').trim().toLowerCase()
  if (!text) return false
  if (/stub|not configured|не настроен|turboproject_api_base/.test(text)) return true
  if (/нет учётных данных|email\/password/.test(text)) return true
  return (
    /turboproject/.test(text) &&
    (/401|403|login|token|auth|unauthorized|password|учёт|войти|не удалось войти/.test(text) ||
      (text.includes('недоступ') && text.includes('turboproject')))
  )
}

/** Stub / missing API base / «нет сеанса» — never show on tiles or Today widgets. */
export function isTechnicalTurboMessage(message: string): boolean {
  const text = (message || '').trim()
  if (!text) return false
  if (isTurboNoSessionError(text)) return true
  return /turbo/i.test(text) && /настроен|сеанс|stub|api_base|недоступ/i.test(text)
}

export function missingTurboSessionHint(hasPassword: boolean, hasMailbox: boolean): string {
  if (!hasPassword) {
    return 'Войдите с паролем 1С — для TurboProject нужны email и пароль из сеанса.'
  }
  if (!hasMailbox) {
    return 'В профиле нет nameMail — перелогиньтесь или укажите латинский логин 1С для @turbo-don.ru.'
  }
  return 'TurboProject недоступен — проверьте TURBOPROJECT_API_BASE на gateway и пароль Turbo.'
}
