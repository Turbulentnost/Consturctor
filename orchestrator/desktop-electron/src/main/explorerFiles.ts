import { shell } from 'electron'
import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, rmSync, unwatchFile, watchFile, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join } from 'node:path'

export type ExplorerSyncEvent = {
  fileId: string
  name: string
  ok: boolean
  error?: string
}

type WatchedFile = {
  fileId: string
  name: string
  path: string
  token: string
  hash: string
  timer: ReturnType<typeof setTimeout> | null
}

const ROOT = join(tmpdir(), 'orchestrator-explorer')
const watched = new Map<string, WatchedFile>()

function digest(data: Buffer): string {
  return createHash('sha256').update(data).digest('hex')
}

function openWithDialog(filePath: string): void {
  const child = spawn('rundll32.exe', ['shell32.dll,OpenAs_RunDLL', filePath], {
    detached: true,
    windowsHide: false,
    stdio: 'ignore'
  })
  child.unref()
}

async function uploadBack(
  backendUrl: string,
  entry: WatchedFile,
  notify: (event: ExplorerSyncEvent) => void
): Promise<void> {
  let data: Buffer
  try {
    data = readFileSync(entry.path)
  } catch {
    // Программа ещё держит файл открытым на запись — попробуем на следующем изменении.
    scheduleUpload(backendUrl, entry, notify, 3000)
    return
  }
  const hash = digest(data)
  if (hash === entry.hash) return
  const form = new FormData()
  form.append('file', new Blob([new Uint8Array(data)]), entry.name)
  try {
    const response = await fetch(
      `${backendUrl}/api/v1/explorer/files/${encodeURIComponent(entry.fileId)}/content`,
      { method: 'POST', headers: { Authorization: `Bearer ${entry.token}` }, body: form }
    )
    if (!response.ok) {
      let detail = `Ошибка сохранения (${response.status})`
      try {
        const body = (await response.json()) as { detail?: unknown }
        if (typeof body.detail === 'string') detail = body.detail
      } catch {
        /* keep status text */
      }
      notify({ fileId: entry.fileId, name: entry.name, ok: false, error: detail })
      return
    }
    entry.hash = hash
    notify({ fileId: entry.fileId, name: entry.name, ok: true })
  } catch {
    notify({
      fileId: entry.fileId,
      name: entry.name,
      ok: false,
      error: `Не удалось сохранить «${entry.name}» в базу знаний: сервер недоступен`
    })
  }
}

function scheduleUpload(
  backendUrl: string,
  entry: WatchedFile,
  notify: (event: ExplorerSyncEvent) => void,
  delayMs = 1200
): void {
  if (entry.timer) clearTimeout(entry.timer)
  entry.timer = setTimeout(() => {
    entry.timer = null
    void uploadBack(backendUrl, entry, notify)
  }, delayMs)
}

/** Расшифрованная копия во временной папке; сохранения в программе уходят обратно на сервер. */
export async function openExplorerFile(
  backendUrl: string,
  opts: { fileId: string; name: string; token?: string | null },
  notify: (event: ExplorerSyncEvent) => void
): Promise<{ ok: boolean; error?: string }> {
  const fileId = String(opts?.fileId || '').trim()
  const name = basename(String(opts?.name || '').trim() || 'file')
  const token = String(opts?.token || '').trim()
  if (!fileId || !token) return { ok: false, error: 'Нет файла или авторизации' }

  let entry = watched.get(fileId)
  if (entry && existsSync(entry.path)) {
    entry.token = token
  } else {
    const dir = join(ROOT, fileId)
    const filePath = join(dir, name)
    let data: Buffer
    try {
      const response = await fetch(
        `${backendUrl}/api/v1/explorer/files/${encodeURIComponent(fileId)}/content`,
        { headers: { Authorization: `Bearer ${token}` } }
      )
      if (!response.ok) {
        let detail = `Не удалось открыть файл (${response.status})`
        try {
          const body = (await response.json()) as { detail?: unknown }
          if (typeof body.detail === 'string') detail = body.detail
        } catch {
          /* keep status text */
        }
        return { ok: false, error: detail }
      }
      data = Buffer.from(await response.arrayBuffer())
      mkdirSync(dir, { recursive: true })
      writeFileSync(filePath, data)
    } catch {
      return { ok: false, error: 'Не удалось загрузить файл с сервера' }
    }
    entry = { fileId, name, path: filePath, token, hash: digest(data), timer: null }
    watched.set(fileId, entry)
    const current = entry
    watchFile(filePath, { interval: 1500 }, (curr, prev) => {
      if (curr.mtimeMs === prev.mtimeMs && curr.size === prev.size) return
      if (!curr.mtimeMs) return
      scheduleUpload(backendUrl, current, notify)
    })
  }

  const openError = await shell.openPath(entry.path)
  if (openError) {
    if (process.platform !== 'win32') return { ok: false, error: openError }
    openWithDialog(entry.path)
  }
  return { ok: true }
}

/** Временные расшифрованные копии не должны переживать сеанс. */
export function cleanupExplorerFiles(): void {
  for (const entry of watched.values()) {
    if (entry.timer) clearTimeout(entry.timer)
    unwatchFile(entry.path)
  }
  watched.clear()
  try {
    rmSync(ROOT, { recursive: true, force: true })
  } catch {
    /* files still locked by an editor */
  }
}
