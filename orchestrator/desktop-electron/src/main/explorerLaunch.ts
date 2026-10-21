import { app, BrowserWindow } from 'electron'
import { execFile, spawn } from 'node:child_process'
import { existsSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join } from 'node:path'

let pendingPath = ''

/** Путь файла из аргументов запуска: проводник Windows передаёт его последним. */
export function filePathFromArgv(argv: string[]): string {
  const ownRoots = [app.getAppPath(), process.resourcesPath, process.execPath]
    .filter(Boolean)
    .map((item) => item.replace(/\\/g, '/').toLowerCase())
  for (let index = argv.length - 1; index >= 1; index -= 1) {
    const arg = String(argv[index] || '')
      .trim()
      .replace(/^"|"$/g, '')
    if (!arg || arg.startsWith('-')) continue
    const normalized = arg.replace(/\\/g, '/').toLowerCase()
    if (/\.(js|mjs|cjs|json|html|asar)$/.test(normalized)) continue
    if (ownRoots.some((root) => normalized === root || normalized.startsWith(root.endsWith('/') ? root : `${root}/`))) {
      continue
    }
    try {
      if (existsSync(arg) && statSync(arg).isFile()) return arg
    } catch {
      continue
    }
  }
  return ''
}

export function peekPendingExplorerOpen(): string {
  return pendingPath
}

export function clearPendingExplorerOpen(filePath?: string): void {
  if (!filePath || filePath === pendingPath) pendingPath = ''
}

export function queueExplorerOpen(filePath: string): void {
  const path = filePath.trim()
  if (!path) return
  pendingPath = path
  for (const win of BrowserWindow.getAllWindows()) {
    if (win.isDestroyed()) continue
    if (win.isMinimized()) win.restore()
    win.show()
    win.focus()
    if (!win.webContents.isLoading()) win.webContents.send('explorer:open-path', path)
  }
}

const OPEN_WITH_EXTENSIONS = [
  '.png',
  '.jpg',
  '.jpeg',
  '.gif',
  '.webp',
  '.bmp',
  '.svg',
  '.txt',
  '.md',
  '.rtf',
  '.pdf',
  '.doc',
  '.docx',
  '.xls',
  '.xlsx',
  '.csv',
  '.ppt',
  '.pptx',
  '.odt',
  '.ods'
]

function installedOrchestratorExe(): string {
  const current = process.execPath
  if (/orchestrator\.exe$/i.test(basename(current))) return current
  const programFiles = process.env.ProgramFiles || 'C:\\Program Files'
  const programFilesX86 = process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)'
  const localAppData = process.env.LOCALAPPDATA || ''
  const candidates = [
    join(programFiles, 'Orchestrator', 'Orchestrator.exe'),
    join(programFilesX86, 'Orchestrator', 'Orchestrator.exe'),
    join(localAppData, 'Programs', 'Orchestrator', 'Orchestrator.exe')
  ]
  return candidates.find((candidate) => candidate && existsSync(candidate)) || ''
}

function appIconSource(): string {
  const candidates = [
    join(process.resourcesPath || '', 'icon.ico'),
    join(app.getAppPath(), 'build', 'icon.ico'),
    join(app.getAppPath(), 'src', 'renderer', 'src', 'assets', 'logo.png'),
    join(process.cwd(), 'build', 'icon.ico'),
    join(process.cwd(), 'src', 'renderer', 'src', 'assets', 'logo.png')
  ]
  return candidates.find((candidate) => candidate && existsSync(candidate)) || ''
}

function powershellQuote(value: string): string {
  return `'${value.replace(/'/g, "''")}'`
}

const STUB_EXE_NAME = 'Оркестратор.exe'
const EXPLORER_PROG_ID = 'Orchestrator.File'

function stubLauncherPath(): string {
  const root = process.env.LOCALAPPDATA || ''
  return root ? join(root, 'Orchestrator', STUB_EXE_NAME) : ''
}

function regText(args: string[]): Promise<string> {
  return new Promise((resolve) => {
    execFile('reg.exe', args, { windowsHide: true, timeout: 8000 }, (error, stdout) => {
      resolve(error ? '' : String(stdout || ''))
    })
  })
}

function regDelete(key: string, valueName?: string): Promise<void> {
  const args = ['delete', key, '/f']
  if (valueName) args.splice(2, 0, '/v', valueName)
  return new Promise((resolve) => {
    execFile('reg.exe', args, { windowsHide: true, timeout: 8000 }, () => resolve())
  })
}

/** Убирает из «Открыть с помощью» значение с именем неподписанного лаунчера. */
async function removeOpenWithName(key: string, exeName: string): Promise<void> {
  const dump = await regText(['query', key])
  if (!dump) return
  const wanted = exeName.toLowerCase()
  for (const line of dump.split(/\r?\n/)) {
    const match = line.match(/^\s+([a-z])\s+REG_SZ\s+(.*)$/i)
    if (!match || match[2].trim().toLowerCase() !== wanted) continue
    await regDelete(key, match[1])
  }
}

/**
 * Лаунчер, собранный csc.exe в LocalAppData, не подписан.
 * «Интеллектуальное управление приложениями» блокирует его, когда им открывают docx.
 * Установленный Orchestrator.exe не трогаем.
 */
async function removeUnsignedLauncher(): Promise<void> {
  const stub = stubLauncherPath()
  const command = await regText(['query', `HKCU\\Software\\Classes\\${EXPLORER_PROG_ID}\\shell\\open\\command`, '/ve'])
  const stubIsHandler =
    Boolean(stub) && command.replace(/\//g, '\\').toLowerCase().includes(stub.replace(/\//g, '\\').toLowerCase())
  const installed = Boolean(installedOrchestratorExe())
  if (stub && existsSync(stub)) {
    try {
      rmSync(stub, { force: true })
    } catch {
      /* файл ещё удерживается */
    }
  }
  await regDelete(`HKCU\\Software\\Classes\\Applications\\${STUB_EXE_NAME}`)
  for (const ext of OPEN_WITH_EXTENSIONS) {
    const base = `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\${ext}`
    await removeOpenWithName(`${base}\\OpenWithList`, STUB_EXE_NAME)
    if (installed && !stubIsHandler) continue
    await regDelete(`${base}\\OpenWithProgids`, EXPLORER_PROG_ID)
    const choice = await regText(['query', `${base}\\UserChoice`, '/v', 'ProgId'])
    if (choice.includes(EXPLORER_PROG_ID)) await regDelete(`${base}\\UserChoice`)
  }
  if (!installed || stubIsHandler) await regDelete(`HKCU\\Software\\Classes\\${EXPLORER_PROG_ID}`)
}

let unsignedLauncherCleanup: Promise<void> | null = null

/** Сбрасывает ассоциацию на неподписанный лаунчер, из-за которой Windows блокирует открытие. */
export function forgetUnsignedExplorerLauncher(): Promise<void> {
  if (process.platform !== 'win32') return Promise.resolve()
  if (!unsignedLauncherCleanup) {
    unsignedLauncherCleanup = removeUnsignedLauncher().catch(() => undefined)
  }
  return unsignedLauncherCleanup
}

/**
 * Показывает установленный Оркестратор в «Открыть с помощью».
 * Неподписанный exe в dev не собираем: Smart App Control его блокирует.
 * Программу по умолчанию для расширений не меняем.
 */
export function registerExplorerContextMenu(): void {
  if (process.platform !== 'win32') return
  const installed = installedOrchestratorExe()
  void forgetUnsignedExplorerLauncher().finally(() => {
    if (installed) registerInstalledExplorerHandler(installed)
  })
}

function registerInstalledExplorerHandler(installed: string): void {
  const mainScript = join(app.getAppPath(), 'out', 'main', 'index.js')
  const electronPath = process.execPath
  if (!installed && !existsSync(mainScript)) return
  const iconSource = installed ? `${installed},0` : appIconSource()
  const script = `
$ErrorActionPreference = 'SilentlyContinue'
$installed = ${powershellQuote(installed)}
$electron = ${powershellQuote(electronPath)}
$main = ${powershellQuote(mainScript)}
$iconSource = ${powershellQuote(iconSource)}
$progId = 'Orchestrator.File'
$iconDir = Join-Path $env:LOCALAPPDATA 'Orchestrator'
New-Item -Force -ItemType Directory -Path $iconDir | Out-Null
$ico = Join-Path $iconDir 'orchestrator.ico'
if ($iconSource -match '\\.png$') {
  Add-Type -AssemblyName System.Drawing
  $image = [System.Drawing.Image]::FromFile($iconSource)
  $bitmap = New-Object System.Drawing.Bitmap 64, 64
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $graphics.Clear([System.Drawing.Color]::Transparent)
  $graphics.DrawImage($image, 0, 0, 64, 64)
  $handle = $bitmap.GetHicon()
  $iconObj = [System.Drawing.Icon]::FromHandle($handle)
  $stream = [System.IO.File]::Create($ico)
  $iconObj.Save($stream)
  $stream.Close()
  $graphics.Dispose(); $bitmap.Dispose(); $image.Dispose()
} elseif ($iconSource -match '\\.ico$') {
  Copy-Item $iconSource $ico -Force
}
$exe = $installed
if (-not $exe) {
  $exe = Join-Path $iconDir 'Оркестратор.exe'
  $cs = Join-Path $iconDir 'Launcher.cs'
  @'
using System;
using System.Diagnostics;
using System.Net.Http;
using System.Reflection;
[assembly: AssemblyTitle("Оркестратор")]
[assembly: AssemblyProduct("Оркестратор")]
[assembly: AssemblyDescription("Оркестратор")]
class Program {
  static void Main(string[] args) {
    string electron = "${electronPath.replace(/\\/g, '\\\\')}";
    string main = "${mainScript.replace(/\\/g, '\\\\')}";
    var start = new ProcessStartInfo();
    start.FileName = electron;
    start.UseShellExecute = false;
    string quoted = "\\"" + main + "\\"";
    if (args.Length > 0) quoted += " \\"" + args[0] + "\\"";
    start.Arguments = quoted;
    string renderer = "";
    try {
      using (var client = new HttpClient()) {
        client.Timeout = TimeSpan.FromMilliseconds(300);
        for (int port = 5173; port <= 5185; port++) {
          try {
            var response = client.GetAsync("http://127.0.0.1:" + port + "/").Result;
            if ((int)response.StatusCode < 500) {
              renderer = "http://127.0.0.1:" + port;
              break;
            }
          } catch {}
        }
      }
    } catch {}
    if (renderer.Length == 0) {
      if (args.Length > 0) {
        string dir = System.IO.Path.Combine(System.Environment.GetFolderPath(System.Environment.SpecialFolder.LocalApplicationData), "Orchestrator");
        System.IO.Directory.CreateDirectory(dir);
        System.IO.File.WriteAllText(System.IO.Path.Combine(dir, "pending-open.txt"), args[0]);
      }
      var dev = new ProcessStartInfo();
      dev.FileName = "cmd.exe";
      dev.Arguments = "/c npm run dev";
      dev.WorkingDirectory = "${app.getAppPath().replace(/\\/g, '\\\\')}";
      dev.UseShellExecute = false;
      Process.Start(dev);
      return;
    }
    start.EnvironmentVariables["ELECTRON_RENDERER_URL"] = renderer;
    Process.Start(start);
  }
}
'@ | Set-Content -Path $cs -Encoding UTF8
  $csc = 'C:\\Windows\\Microsoft.NET\\Framework64\\v4.0.30319\\csc.exe'
  $iconArg = ''
  if (Test-Path $ico) { $iconArg = '/win32icon:' + $ico }
  & $csc /nologo /target:winexe /r:System.Net.Http.dll $iconArg ('/out:' + $exe) $cs | Out-Null
}
$exeName = [IO.Path]::GetFileName($exe)
$icon = if ($installed) { $installed + ',0' } elseif (Test-Path $ico) { $ico } else { $exe + ',0' }
$command = '"' + $exe + '" "%1"'
New-Item -Force -Path "HKCU:\\Software\\Classes\\$progId" | Out-Null
Set-Item -Path "HKCU:\\Software\\Classes\\$progId" -Value 'Оркестратор'
New-Item -Force -Path "HKCU:\\Software\\Classes\\$p