import { ApiError } from '../api/types'

const ADMIN_BACKEND_STARTING =
  'Запускаем локальный backend… Подождите несколько секунд и нажмите «Обновить».'

const ADMIN_BACKEND_UNAVAILABLE =
  'Не удалось подключиться к backend. Проверьте orchestrator\\backend (run_dev.bat) и что порт 7812 свободен.'

function isNotFoundDetail(message: string): boolean {
  const normalized = message.trim().toLowerCase()
  return normalized === 'not found' || normalized === 'not found.'
}

function isLegacyGatewayDeployMessage(message: string): boolean {
  return /admin api не развёрнут|gateway.*6d0e958|deploy.*gateway/i.test(message)
}

export function formatAdminLoadError(err: unknown, fallback = 'Не удалось загрузить данные'): string {
  if (err instanceof ApiError) {
    if (err.status === 404 || isNotFoundDetail(err.message)) {
      if (isLegacyGatewayDeployMessage(err.message)) {
        return ADMIN_BACKEND_UNAVAILABLE
      }
      return ADMIN_BACKEND_STARTING
    }
    if (err.status === 0 && /не удалось подключиться к backend/i.test(err.message)) {
      return ADMIN_BACKEND_UNAVAILABLE
    }
    if (err.status === 403) {
      return 'Недостаточно прав для доступа к этому разделу админ-панели (403).'
    }
    if (err.status === 401) {
      return 'Требуется авторизация (401). Перелогиньтесь в приложении.'
    }
    if (err.message.trim()) {
      if (isLegacyGatewayDeployMessage(err.message)) {
        return ADMIN_BACKEND_UNAVAILABLE
      }
      return err.message
    }
  }
  if (err instanceof Error && err.message.trim()) {
    if (isNotFoundDetail(err.message) || isLegacyGatewayDeployMessage(err.message)) {
      return ADMIN_BACKEND_UNAVAILABLE
    }
    return err.message
  }
  return fallback
}
