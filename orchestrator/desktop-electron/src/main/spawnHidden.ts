import { execFileSync, spawn, type SpawnOptions } from 'node:child_process'

/** Windows: subprocess without console window (py.exe / python.exe). */
export const WIN_CREATE_NO_WINDOW = 0x08000000

type SpawnHiddenOptions = SpawnOptions & { creationFlags?: number }

export function spawnHidden(
  command: string,
  args: string[],
  options: SpawnHiddenOptions = {}
): ReturnType<typeof spawn> {
  const flags =
    process.platform === 'win32'
      ? (options.creationFlags ?? 0) | WIN_CREATE_NO_WINDOW
      : options.creationFlags
  return spawn(command, args, {
    ...options,
    windowsHide: true,
    ...(flags !== undefined ? { creationFlags: flags } : {})
  } as SpawnOptions)
}

/** Путь к python.exe без запуска видимого py.exe (Windows launcher). */
export function resolveWindowsPythonExe(preferred?: string): string {
  const fromEnv =
    preferred ||
    process.env.ORCH_PYTHON ||
    process.env.CONSTRUCTOR_PYTHON ||
    process.env.PYTHON ||
    ''
  if (fromEnv.trim()) return fromEnv.trim()
  if (process.platform !== 'win32') return 'python3'

  const attempts: Array<{ cmd: string; args: string[] }> = [
    { cmd: 'py', args: ['-3.12', '-c', 'import sys; print(sys.executable)'] },
    { cmd: 'py', args: ['-3', '-c', 'import sys; print(sys.executable)'] },
    { cmd: 'python', args: ['-c', 'import sys; print(sys.executable)'] }
  ]
  for (const attempt of attempts) {
    try {
      const raw = execFileSync(attempt.cmd, attempt.args, {
        encoding: 'utf8',
        windowsHide: true,
        creationFlags: WIN_CREATE_NO_WINDOW
      } as Parameters<typeof execFileSync>[2])
      const out = String(raw).trim()
      if (out && out.toLowerCase().endsWith('.exe')) return out
    } catch {
      /* try next */
    }
  }
  return 'python'
}
