import { app, BrowserWindow } from 'electron'
import { spawn } from 'node:child_process'
import { createWriteStream, existsSync, mkdirSync, unlinkSync } from 'node:fs'
import { join } from 'node:path'
import { finished } from 'node:stream/promises'

export type UpdateState = 'idle' | 'available' | 'downloading' | 'installing' | 'error'

export interface UpdateStatus {
  state: UpdateState
  currentVersion: string
  availableVersion: string
  percent: number
  error: string
  source: string
  devMode: boolean
}

export interface UpdaterOptions {
  owner: string
  repo: string
  token?: string
}

interface GithubAsset {
  name: string
  size: number
  browser_download_url: string
}

interface GithubRelease {
  tag_name: string
  assets?: GithubAsset[]
}

interface FoundUpdate {
  version: string
  assets: GithubAsset[]
}

const CHECK_INTERVAL_MS = 30 * 60 * 1000
const FIRST_CHECK_MS = 4_000
const USER_AGENT = 'OrchestratorDesktop'
const INSTALLER_ORDER = ['constructor-setup.exe', 'orchestrator-setup.exe']

let options: UpdaterOptions = { owner: '', repo: '' }
let timer: NodeJS.Timeout | null = null
let firstTimer: NodeJS.Timeout | null = null
let found: FoundUpdate | null = null
let busy = false

const status: UpdateStatus = {
  state: 'idle',
  currentVersion: '',
  availableVersion: '',
  percent: 0,
  error: '',
  source: '',
  devMode: false
}

function sourceLabel(): string {
  return options.owner && options.repo ? `${options.owner}/${options.repo}` : ''
}

function isDevMode(): boolean {
  return !app.isPackaged
}

export function parseVersionParts(raw: string): number[] {
  const cleaned = String(raw || '')
    .trim()
    .replace(/^v/i, '')
    .split(/[+-]/)[0]
  if (!cleaned) return [0]
  return cleaned.split('.').map((part) => {
    const digits = part.replace(/\D/g, '')
    const value = parseInt(digits, 10)
    return Number.isFinite(value) ? value : 0
  })
}

export function compareVersions(left: string, right: string): number {
  const a = parseVersionParts(left)
  const b = parseVersionParts(right)
  const n = Math.max(a.length, b.length)
  for (let i = 0; i < n; i++) {
    const av = a[i] ?? 0
    const bv = b[i] ?? 0
    if (av > bv) return 1
    if (av < bv) return -1
  }
  return 0
}

function currentVersion(): string {
  return String(app.getVersion() || '0.0.0')
}

function snapshot(): UpdateStatus {
  return { ...status }
}

function broadcast(): void {
  const payload = snapshot()
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) win.webContents.send('updater:status', payload)
  }
}

function setStatus(patch: Partial<UpdateStatus>): UpdateStatus {
  Object.assign(status, patch)
  broadcast()
  return snapshot()
}

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: 'application/vnd.github+json',
    'User-Agent': USER_AGENT,
    'X-GitHub-Api-Version': '2022-11-28'
  }
  if (options.token) headers.Authorization = `Bearer ${options.token}`
  return headers
}

export function pickInstallers(assets: GithubAsset[]): GithubAsset[] {
  const exes = assets.filter((asset) => {
    const name = String(asset.name || '').toLowerCase()
    return name.endsWith('.exe') && !name.includes('blockmap')
  })
  const picked: GithubAsset[] = []
  const seen = new Set<string>()
  for (const wanted of INSTALLER_ORDER) {
    const asset = exes.find((item) => String(item.name || '').toLowerCase() === wanted)
    if (!asset) continue
    const key = asset.browser_download_url || asset.name
    if (seen.has(key)) continue
    seen.add(key)
    picked.push(asset)
  }
  if (!picked.length && exes[0]) picked.push(exes[0])
  return picked
}

async function fetchLatestRelease(): Promise<GithubRelease> {
  const source = sourceLabel() || 'unknown'
  const url = `https://api.github.com/repos/${options.owner}/${options.repo}/releases/latest`
  let response: Response
  try {
    response = await fetch(url, { headers: authHeaders() })
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err)
    throw new Error(`Сеть: не удалось проверить ${source} (${detail})`)
  }
  if (response.status === 404) {
    throw new Error(`Нет релиза в ${source}`)
  }
  if (!response.ok) {
    throw new Error(`GitHub ${source}: ошибка ${response.status}`)
  }
  return (await response.json()) as GithubRelease
}

async function checkForUpdate(): Promise<void> {
  if (busy) return
  status.currentVersion = currentVersion()
  status.devMode = isDevMode()
  status.source = sourceLabel()
  if (!options.owner || !options.repo) {
    setStatus({
      state: 'error',
      availableVersion: '',
      percent: 0,
      error: 'Не задан репозиторий обновлений'
    })
    return
  }
  try {
    const release = await fetchLatestRelease()
    const assets = pickInstallers(release.assets || [])
    const version = String(release.tag_name || '').trim()
    if (!version) {
      found = null
      if (status.state === 'downloading' || status.state === 'installing') return
      setStatus({
        state: 'error',
        availableVersion: '',
        percent: 0,
        error: `Нет релиза в ${sourceLabel()}`
      })
      return
    }
    if (!assets.length) {
      found = null
      if (status.state === 'downloading' || status.state === 'installing') return
      setStatus({
        state: 'error',
        availableVersion: version,
        percent: 0,
        error: `В релизе ${version} нет установщика`
      })
      return
    }
    if (compareVersions(version, status.currentVersion) <= 0) {
      found = null
      if (status.state === 'downloading' || status.state === 'installing') return
      setStatus({
        state: 'idle',
        availableVersion: version,
        percent: 0,
        error: ''
      })
      return
    }
    found = { version, assets }
    if (status.state === 'downloading' || status.state === 'installing') {
      status.availableVersion = version
      return
    }
    setStatus({
      state: 'available',
      availableVersion: version,
      percent: 0,
      error: ''
    })
    console.log(`Desktop update available: ${status.currentVersion} -> ${version}`)
  } catch (err) {
    const message = err instanceof Error ? err.message : 'GitHub update check failed'
    console.error(message)
    if (status.state === 'idle' || status.state === 'error') {
      setStatus({ state: found ? 'available' : 'error', error: found ? '' : message })
    }
  }
}

function updateDir(): string {
  const dir = join(app.getPath('temp'), 'constructor-updates')
  mkdirSync(dir, { recursive: true })
  return dir
}

async function downloadInstaller(asset: GithubAsset, dest: string): Promise<void> {
  if (existsSync(dest)) {
    try {
      unlinkSync(dest)
    } catch {
      /* overwrite below */
    }
  }
  const response = await fetch(asset.browser_download_url, {
    headers: {
      Accept: 'application/octet-stream',
      'User-Agent': USER_AGENT,
      ...(options.token ? { Authorization: `Bearer ${options.token}` } : {})
    },
    redirect: 'follow'
  })
  if (!response.ok || !response.body) {
    throw new Error(`Installer download failed (${response.status})`)
  }
  const total = Number(response.headers.get('content-length') || asset.size || 0)
  const file = createWriteStream(dest)
  const reader = response.body.getReader()
  let received = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      if (!value || !value.length) continue
      received += value.length
      if (!file.write(Buffer.from(value))) {
        await new Promise<void>((resolve) => file.once('drain', resolve))
      }
      const percent = total > 0 ? Math.max(1, Math.min(99, Math.round((received / total) * 100))) : 0
      setStatus({ state: 'downloading', percent, error: '' })
    }
    file.end()
    await finished(file)
  } catch (err) {
    file.destroy()
    throw err
  }
  if (!existsSync(dest)) {
    throw new Error('Installer was not saved to disk')
  }
}

function launchInstaller(installerPath: string): void {
  const child = spawn(installerPath, ['/S', '--updated', '--force-run'], {
    detached: true,
    stdio: 'ignore',
    windowsHide: true
  })
  child.unref()
}

export function getUpdateStatus(): UpdateStatus {
  status.currentVersion = currentVersion()
  status.devMode = isDevMode()
  status.source = sourceLabel() || status.source
  return snapshot()
}

export async function requestUpdateCheck(): Promise<UpdateStatus> {
  status.currentVersion = currentVersion()
  status.devMode = isDevMode()
  status.source = sourceLabel()
  if (isDevMode()) {
    return setStatus({
      state: 'idle',
      availableVersion: '',
      percent: 0,
      error: 'Проверка недоступна в dev'
    })
  }
  await checkForUpdate()
  return getUpdateStatus()
}

export async function installAvailableUpdate(): Promise<{ ok: boolean; error?: string }> {
  if (isDevMode()) return { ok: false, error: 'Установка exe недоступна в dev' }
  if (busy) return { ok: false, error: 'Update already in progress' }
  if (!found) {
    await checkForUpdate()
  }
  if (!found) {
    return { ok: false, error: 'No desktop update is available' }
  }
  busy = true
  const target = found
  setStatus({
    state: 'downloading',
    availableVersion: target.version,
    percent: 1,
    error: ''
  })
  const dir = updateDir()
  try {
    const paths: string[] = []
    for (const [index, asset] of target.assets.entries()) {
      const name = String(asset.name || '').toLowerCase().includes('orchestrator')
        ? 'Orchestrator-Setup.exe'
        : 'Constructor-Setup.exe'
      const dest = join(dir, name)
      const base = Math.round((index / target.assets.length) * 90)
      setStatus({
        state: 'downloading',
        availableVersion: target.version,
        percent: Math.max(1, base),
        error: ''
      })
      await downloadInstaller(asset, dest)
      paths.push(dest)
    }
    setStatus({ state: 'installing', percent: 100, error: '' })
    for (const dest of paths) launchInstaller(dest)
    setTimeout(() => app.quit(), 800)
    return { ok: true }
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to install update'
    console.error(message)
    setStatus({
      state: 'available',
      availableVersion: target.version,
      percent: 0,
      error: message
    })
    return { ok: false, error: message }
  } finally {
    busy = false
  }
}

export function startUpdater(next: UpdaterOptions): void {
  options = {
    owner: next.owner.trim(),
    repo: next.repo.trim(),
    token: next.token?.trim() || undefined
  }
  status.currentVersion = currentVersion()
  status.devMode = isDevMode()
  status.source = sourceLabel()
  if (firstTimer) clearTimeout(firstTimer)
  if (timer) clearInterval(timer)
  firstTimer = null
  timer = null
  if (status.devMode) {
    broadcast()
    return
  }
  firstTimer = setTimeout(() => {
    void checkForUpdate()
  }, FIRST_CHECK_MS)
  timer = setInterval(() => {
    void checkForUpdate()
  }, CHECK_INTERVAL_MS)
}

export function stopUpdater(): void {
  if (firstTimer) clearTimeout(firstTimer)
  if (timer) clearInterval(timer)
  firstTimer = null
  timer = null
}
