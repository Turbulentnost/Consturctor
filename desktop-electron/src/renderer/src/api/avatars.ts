import { api } from './client'
import type { UserProfile } from './types'

const cache = new Map<string, string | null>()

export function avatarPath(userId: string): string {
  return userId ? `/api/v1/auth/users/${userId}/avatar` : ''
}

function pathOnly(url: string): string {
  return url.split('?')[0] || url
}

export async function loadUserAvatar(
  user: Pick<UserProfile, 'id' | 'avatarUrl'>
): Promise<string | null> {
  const cacheKey = user.id || user.avatarUrl || ''
  if (cacheKey && cache.has(cacheKey)) {
    return cache.get(cacheKey) ?? null
  }

  const candidates: string[] = []
  if (user.avatarUrl) candidates.push(user.avatarUrl)
  const byId = avatarPath(user.id)
  if (byId && !candidates.some((item) => pathOnly(item) === byId)) {
    candidates.push(byId)
  }

  let dataUrl: string | null = null
  for (const url of candidates) {
    dataUrl = await api.fetchDataUrl(url)
    if (dataUrl) break
  }

  if (cacheKey) cache.set(cacheKey, dataUrl)
  return dataUrl
}

export function clearAvatarCache(): void {
  cache.clear()
}
