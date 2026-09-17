import { app, safeStorage } from 'electron'
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

export type ComSessionSecret = {
  login: string
  password: string
  nameMail: string
}

let memory: ComSessionSecret | null = null

function secretFilePath(): string {
  return join(app.getPath('userData'), 'com-session.bin')
}

function normalize(secret: Partial<ComSessionSecret> | null | undefined): ComSessionSecret | null {
  const password = secret?.password || ''
  if (!password) return null
  return {
    login: (secret?.login || '').trim(),
    password,
    nameMail: (secret?.nameMail || '').trim()
  }
}

function readPersisted(): ComSessionSecret | null {
  const path = secretFilePath()
  if (!existsSync(path)) return null
  if (!safeStorage.isEncryptionAvailable()) return null
  try {
    const raw = readFileSync(path)
    const text = safeStorage.decryptString(raw)
    const parsed = JSON.parse(text) as Partial<ComSessionSecret>
    return normalize(parsed)
  } catch {
    return null
  }
}

function writePersisted(secret: ComSessionSecret): void {
  if (!safeStorage.isEncryptionAvailable()) return
  const path = secretFilePath()
  mkdirSync(dirname(path), { recursive: true })
  const payload = JSON.stringify({
    login: secret.login,
    password: secret.password,
    nameMail: secret.nameMail
  })
  writeFileSync(path, safeStorage.encryptString(payload))
}

function removePersisted(): void {
  const path = secretFilePath()
  if (!existsSync(path)) return
  try {
    unlinkSync(path)
  } catch {
    /* ignore */
  }
}

export function setComSessionSecret(
  secret: Partial<ComSessionSecret> | null,
  persist: boolean
): ComSessionSecret | null {
  const next = normalize(secret)
  memory = next
  if (persist && next) writePersisted(next)
  else removePersisted()
  return next
}

export function getComSessionSecret(sidecar?: Partial<ComSessionSecret> | null): ComSessionSecret | null {
  if (memory?.password) return memory
  const fromSidecar = normalize(sidecar)
  if (fromSidecar) {
    memory = fromSidecar
    return fromSidecar
  }
  const persisted = readPersisted()
  if (persisted) memory = persisted
  return persisted
}

export function clearComSessionSecret(): void {
  memory = null
  removePersisted()
}
