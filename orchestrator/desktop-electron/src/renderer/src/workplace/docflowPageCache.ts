/**
 * Кэш страниц журналов протоколов и поручений из 1С.
 * Повторное открытие вкладки отдаёт уже загруженную страницу сразу, без ожидания 1С.
 * После записи в 1С кэш сбрасывается целиком.
 */
const PAGE_TTL_MS = 3 * 60_000
const pages = new Map<string, { at: number; value: unknown }>()

export function readDocflowPage<T>(key: string): T | null {
  const hit = pages.get(key)
  if (!hit) return null
  if (Date.now() - hit.at > PAGE_TTL_MS) {
    pages.delete(key)
    return null
  }
  return hit.value as T
}

export function writeDocflowPage(key: string, value: unknown): void {
  pages.set(key, { at: Date.now(), value })
}

export function clearDocflowPages(): void {
  pages.clear()
}
