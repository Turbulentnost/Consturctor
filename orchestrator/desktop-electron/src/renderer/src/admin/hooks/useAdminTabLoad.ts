import { useCallback, useEffect, useState } from 'react'
import { formatAdminLoadError } from '../adminLoadError'

const ADMIN_TAB_TTL_MS = 120_000
const adminTabCache = new Map<string, { data: unknown; fetchedAt: number }>()

function adminCacheKey(fetcher: () => Promise<unknown>): string {
  return fetcher.name || 'admin-tab'
}

export function useAdminTabLoad<T>(
  fallback: T,
  fetcher: () => Promise<T>
): {
  data: T
  loading: boolean
  error: string | null
  reload: () => Promise<void>
} {
  const cacheKey = adminCacheKey(fetcher)
  const cached = adminTabCache.get(cacheKey)
  const [data, setData] = useState<T>(() => (cached ? (cached.data as T) : fallback))
  const [loading, setLoading] = useState(!cached)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    const hit = adminTabCache.get(cacheKey)
    const fresh = Boolean(hit && Date.now() - hit.fetchedAt < ADMIN_TAB_TTL_MS)
    if (fresh && hit) {
      setData(hit.data as T)
      setLoading(false)
      // #region agent log
      fetch('http://127.0.0.1:7847/ingest/b2a622e9-6027-4fae-9a68-3d036eb3c49e',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'d8a6bb'},body:JSON.stringify({sessionId:'d8a6bb',runId:'post-fix',hypothesisId:'H1',location:'useAdminTabLoad.ts:reload',message:'admin tab cache hit',data:{cacheKey},timestamp:Date.now()})}).catch(()=>{})
      // #endregion
      return
    }
    setLoading(!hit)
    setError(null)
    // #region agent log
    const _dbgStart = Date.now()
    fetch('http://127.0.0.1:7847/ingest/b2a622e9-6027-4fae-9a68-3d036eb3c49e',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'d8a6bb'},body:JSON.stringify({sessionId:'d8a6bb',runId:'post-fix',hypothesisId:'H1',location:'useAdminTabLoad.ts:reload',message:'admin tab reload start',data:{cacheKey,hadCache:Boolean(hit)},timestamp:Date.now()})}).catch(()=>{})
    // #endregion
    try {
      const next = await fetcher()
      adminTabCache.set(cacheKey, { data: next, fetchedAt: Date.now() })
      setData(next)
      // #region agent log
      fetch('http://127.0.0.1:7847/ingest/b2a622e9-6027-4fae-9a68-3d036eb3c49e',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'d8a6bb'},body:JSON.stringify({sessionId:'d8a6bb',runId:'post-fix',hypothesisId:'H1',location:'useAdminTabLoad.ts:reload:ok',message:'admin tab reload ok',data:{ms:Date.now()-_dbgStart,cacheKey},timestamp:Date.now()})}).catch(()=>{})
      // #endregion
    } catch (err) {
      setError(formatAdminLoadError(err))
      if (!hit) setData(fallback)
      // #region agent log
      fetch('http://127.0.0.1:7847/ingest/b2a622e9-6027-4fae-9a68-3d036eb3c49e',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'d8a6bb'},body:JSON.stringify({sessionId:'d8a6bb',runId:'post-fix',hypothesisId:'H1',location:'useAdminTabLoad.ts:reload:err',message:'admin tab reload error',data:{ms:Date.now()-_dbgStart,cacheKey},timestamp:Date.now()})}).catch(()=>{})
      // #endregion
    } finally {
      setLoading(false)
    }
  }, [fallback, fetcher, cacheKey])

  useEffect(() => {
    // #region agent log
    fetch('http://127.0.0.1:7847/ingest/b2a622e9-6027-4fae-9a68-3d036eb3c49e',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'d8a6bb'},body:JSON.stringify({sessionId:'d8a6bb',runId:'post-fix',hypothesisId:'H1',location:'useAdminTabLoad.ts:effect',message:'admin tab load effect (mount or reload identity change)',data:{cacheKey},timestamp:Date.now()})}).catch(()=>{})
    // #endregion
    void reload()
  }, [reload, cacheKey])

  return { data, loading, error, reload }
}
