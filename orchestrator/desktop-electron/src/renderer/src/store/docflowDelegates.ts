/** ФИО сотрудников, за которых пользователь ведёт задачи 1С:ДО (замещение / помощник). */

const STORAGE_PREFIX = 'orch-docflow-delegates-v1'

function storageKey(userId: string): string {
  return `${STORAGE_PREFIX}:${(userId || 'default').trim() || 'default'}`
}

export function parseDelegateText(text: string): string[] {
  const out: string[] = []
  for (const part of String(text || '').split(/[,;\n]+/)) {
    const name = part.replace(/\s+/g, ' ').trim()
    if (name && !out.some((item) => item.toLowerCase() === name.toLowerCase())) out.push(name)
  }
  return out
}

export function loadDocflowDelegates(userId: string): string[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(storageKey(userId))
    const parsed = raw ? (JSON.parse(raw) as unknown) : []
    return Array.isArray(parsed) ? parseDelegateText(parsed.map(String).join('\n')) : []
  } catch {
    return []
  }
}

export function saveDocflowDelegates(userId: string, names: string[]): string[] {
  const clean = parseDelegateText(names.join('\n'))
  try {
    window.localStorage.setItem(storageKey(userId), JSON.stringify(clean))
  } catch {
    /* ignore quota */
  }
  return clean
}
