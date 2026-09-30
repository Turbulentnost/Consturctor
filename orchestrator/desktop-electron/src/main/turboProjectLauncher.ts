import { spawn } from 'node:child_process'
import { createServer } from 'node:net'

const DEBUG_HOST = '127.0.0.1'
const DEBUG_TIMEOUT_MS = 15_000
const AUTH_STABLE_MS = 2_000
// TurboProject shows its login form while it validates a saved token (seen 4–11 s), then leaves it.
const SAVED_TOKEN_GRACE_MS = 30_000

export type TurboProjectCredentials = {
  nameMail: string
  password: string
}

export type TurboProjectLaunchResult = {
  ok: boolean
  autoLogin: boolean
  error?: string
  message?: string
}

type DebugTarget = {
  type?: string
  url?: string
  webSocketDebuggerUrl?: string
}

function turboEmail(nameMail: string): string {
  const value = nameMail.trim().toLowerCase()
  if (!value) return ''
  if (value.includes('@')) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) ? value : ''
  }
  return /^[a-z0-9._-]+$/.test(value) ? `${value}@turbo-don.ru` : ''
}

async function reserveLocalPort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer()
    server.unref()
    server.once('error', reject)
    server.listen(0, DEBUG_HOST, () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : 0
      server.close((error) => {
        if (error) reject(error)
        else if (port) resolve(port)
        else reject(new Error('Не удалось выбрать локальный порт'))
      })
    })
  })
}

async function waitForDebugTarget(port: number): Promise<DebugTarget> {
  const deadline = Date.now() + DEBUG_TIMEOUT_MS
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://${DEBUG_HOST}:${port}/json/list`)
      if (response.ok) {
        const targets = (await response.json()) as DebugTarget[]
        const target = targets.find(
          (item) => item.type === 'page' && item.webSocketDebuggerUrl && item.url !== 'about:blank'
        )
        if (target) return target
      }
    } catch {
      // TurboProject is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  throw new Error('Не удалось подключиться к окну TurboProject для автоматического входа')
}

async function evaluateTarget<T>(target: DebugTarget, expression: string): Promise<T> {
  const socketUrl = target.webSocketDebuggerUrl
  if (!socketUrl) throw new Error('TurboProject не предоставил отладочное подключение')

  return new Promise<T>((resolve, reject) => {
    const socket = new WebSocket(socketUrl)
    const requestId = 1
    let settled = false
    const timer = setTimeout(() => {
      finish(new Error('TurboProject не ответил на команду автоматического входа'))
    }, 5_000)

    const finish = (error?: Error, value?: T): void => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      socket.close()
      if (error) reject(error)
      else resolve(value as T)
    }

    socket.addEventListener('open', () => {
      socket.send(
        JSON.stringify({
          id: requestId,
          method: 'Runtime.evaluate',
          params: { expression, returnByValue: true }
        })
      )
    })
    socket.addEventListener('message', (event) => {
      try {
        const payload = JSON.parse(String(event.data)) as {
          id?: number
          error?: { message?: string }
          result?: {
            exceptionDetails?: { exception?: { description?: string }; text?: string }
            result?: { value?: T }
          }
        }
        if (payload.id !== requestId) return
        if (payload.error || payload.result?.exceptionDetails) {
          const details = payload.result?.exceptionDetails
          finish(
            new Error(
              payload.error?.message ||
                details?.exception?.description ||
                details?.text ||
                'TurboProject отклонил команду автоматического входа'
            )
          )
          return
        }
        finish(undefined, payload.result?.result?.value)
      } catch {
        finish(new Error('TurboProject вернул некорректный ответ автологина'))
      }
    })
    socket.addEventListener('error', () => {
      finish(new Error('Не удалось подключиться к окну TurboProject'))
    })
  })
}

type LoginPageState = {
  authenticated: boolean
  loginForm: boolean
  hasToken: boolean
  error: string
}

async function loginPageState(target: DebugTarget): Promise<LoginPageState> {
  return evaluateTarget<LoginPageState>(
    target,
    `(() => {
      const loginForm = Boolean(document.querySelector('input[name="email"]') && document.querySelector('input[name="password"]'));
      const hasToken = Boolean(localStorage.getItem('token'));
      const authenticated = hasToken && location.hash !== '#/login' && !loginForm;
      const errorNode = [...document.querySelectorAll('[role="alert"], .text-red-500, .text-destructive')]
        .find((node) => (node.textContent || '').trim());
      return { authenticated, loginForm, hasToken, error: (errorNode?.textContent || '').trim() };
    })()`
  )
}

const OVERLAY_ID = '__orch_saved_session_overlay'

async function setSavedSessionOverlay(target: DebugTarget, visible: boolean): Promise<void> {
  await evaluateTarget<boolean>(
    target,
    visible
      ? `(() => {
          if (document.getElementById(${JSON.stringify(OVERLAY_ID)})) return true;
          const node = document.createElement('div');
          node.id = ${JSON.stringify(OVERLAY_ID)};
          node.textContent = 'Входим по сохранённой сессии…';
          node.style.cssText = 'position:fixed;inset:0;z-index:2147483647;display:flex;align-items:center;' +
            'justify-content:center;background:#0b1f3a;color:#fff;font:600 18px system-ui,sans-serif;';
          document.body.appendChild(node);
          return true;
        })()`
      : `(() => { document.getElementById(${JSON.stringify(OVERLAY_ID)})?.remove(); return true; })()`
  ).catch(() => undefined)
}

async function waitForLoginForm(target: DebugTarget): Promise<'authenticated' | 'login'> {
  const deadline = Date.now() + SAVED_TOKEN_GRACE_MS + DEBUG_TIMEOUT_MS
  let authenticatedSince = 0
  let loginSince = 0
  let overlay = false
  try {
    while (Date.now() < deadline) {
      const state = await loginPageState(target)
      if (state.loginForm) {
        if (!loginSince) loginSince = Date.now()
        if (!state.hasToken || Date.now() - loginSince >= SAVED_TOKEN_GRACE_MS) return 'login'
        if (!overlay) {
          overlay = true
          await setSavedSessionOverlay(target, true)
        }
      } else {
        loginSince = 0
      }
      if (state.authenticated) {
        if (!authenticatedSince) authenticatedSince = Date.now()
        if (Date.now() - authenticatedSince >= AUTH_STABLE_MS) return 'authenticated'
      } else {
        authenticatedSince = 0
      }
      await new Promise((resolve) => setTimeout(resolve, 200))
    }
    throw new Error('Форма входа TurboProject не появилась')
  } finally {
    if (overlay) await setSavedSessionOverlay(target, false)
  }
}

async function submitLogin(
  target: DebugTarget,
  credentials: TurboProjectCredentials
): Promise<void> {
  const email = turboEmail(credentials.nameMail)
  if (!email || !credentials.password) throw new Error('Нет корректного логина или пароля TurboProject')

  const submitted = await evaluateTarget<boolean>(
    target,
    `(() => {
      const emailInput = document.querySelector('input[name="email"]');
      const passwordInput = document.querySelector('input[name="password"]');
      if (!(emailInput instanceof HTMLInputElement) || !(passwordInput instanceof HTMLInputElement)) {
        return false;
      }
      const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
      if (!setValue) return false;
      const update = (input, value) => {
        setValue.call(input, value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      };
      update(emailInput, ${JSON.stringify(email)});
      update(passwordInput, ${JSON.stringify(credentials.password)});
      const submit = [...document.querySelectorAll('button[type="submit"]')]
        .find((button) => (button.textContent || '').trim() === 'Войти');
      const form = emailInput.closest('form');
      if (!(submit instanceof HTMLButtonElement) || !(form instanceof HTMLFormElement)) return false;
      form.requestSubmit(submit);
      return true;
    })()`
  )
  if (!submitted) throw new Error('Не удалось заполнить форму входа TurboProject')
}

async function submitRememberedLogin(target: DebugTarget): Promise<boolean> {
  return evaluateTarget<boolean>(
    target,
    `(() => {
      let accounts = [];
      try {
        const raw = localStorage.getItem('tp_saved_accounts');
        const parsed = raw ? JSON.parse(raw) : [];
        if (Array.isArray(parsed)) accounts = parsed;
      } catch {
        return false;
      }
      const account = accounts.find((item) => item && item.email && item.password);
      if (!account) return false;
      const emailInput = document.querySelector('input[name="email"]');
      const passwordInput = document.querySelector('input[name="password"]');
      if (!(emailInput instanceof HTMLInputElement) || !(passwordInput instanceof HTMLInputElement)) {
        return false;
      }
      const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
      if (!setValue) return false;
      const update = (input, value) => {
        setValue.call(input, value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      };
      update(emailInput, String(account.email));
      update(passwordInput, String(account.password));
      const remember = document.querySelector('input[type="checkbox"]');
      if (remember instanceof HTMLInputElement && !remember.checked) remember.click();
      const submit = [...document.querySelectorAll('button[type="submit"]')]
        .find((button) => (button.textContent || '').trim() === 'Войти');
      const form = emailInput.closest('form');
      if (!(submit instanceof HTMLButtonElement) || !(form instanceof HTMLFormElement)) return false;
      form.requestSubmit(submit);
      return true;
    })()`
  )
}

async function enableRememberMe(target: DebugTarget): Promise<void> {
  await evaluateTarget<boolean>(
    target,
    `(() => {
      const remember = document.querySelector('input[type="checkbox"]');
      if (!(remember instanceof HTMLInputElement)) return false;
      if (!remember.checked) remember.click();
      return remember.checked;
    })()`
  )
}

async function waitForAuthenticated(target: DebugTarget): Promise<void> {
  const deadline = Date.now() + DEBUG_TIMEOUT_MS
  let lastError = ''
  let authenticatedSince = 0
  while (Date.now() < deadline) {
    const state = await loginPageState(target)
    if (state.authenticated) {
      if (!authenticatedSince) authenticatedSince = Date.now()
      if (Date.now() - authenticatedSince >= AUTH_STABLE_MS) return
    } else {
      authenticatedSince = 0
    }
    if (state.error) lastError = state.error
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  throw new Error(lastError || 'TurboProject не подтвердил автоматический вход')
}

let running: { pid: number; debugPort?: number } | null = null

function isAlive(pid: number): boolean {
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

function bringToFront(pid: number): void {
  const child = spawn(
    'powershell.exe',
    [
      '-NoProfile',
      '-NonInteractive',
      '-Command',
      `$null = (New-Object -ComObject WScript.Shell).AppActivate(${pid})`
    ],
    { windowsHide: true, stdio: 'ignore' }
  )
  child.on('error', () => undefined)
}

async function startTurboProject(executablePath: string, debugPort?: number): Promise<void> {
  const args = debugPort ? [`--remote-debugging-port=${debugPort}`] : []
  // windowsHide would hide the GUI window itself (SW_HIDE is passed to the app), not just a console.
  const child = spawn(executablePath, args, { detached: true, stdio: 'ignore' })
  await new Promise<void>((resolve, reject) => {
    child.once('spawn', resolve)
    child.once('error', reject)
  })
  child.unref()
  if (child.pid) running = { pid: child.pid, debugPort }
}

export async function launchTurboProject(
  executablePath: string,
  credentials?: TurboProjectCredentials | null
): Promise<TurboProjectLaunchResult> {
  if (running && isAlive(running.pid)) {
    bringToFront(running.pid)
    return { ok: true, autoLogin: false, message: 'TurboProject уже открыт' }
  }
  running = null
  let started = false
  try {
    const debugPort = await reserveLocalPort()
    try {
      await startTurboProject(executablePath, debugPort)
    } catch (error) {
      return {
        ok: false,
        autoLogin: false,
        error: `Не удалось запустить TurboProject: ${
          error instanceof Error ? error.message : 'неизвестная ошибка'
        }`
      }
    }
    started = true
    const target = await waitForDebugTarget(debugPort)
    const page = await waitForLoginForm(target)
    if (page === 'login') {
      // The account saved by TurboProject itself has its own password, which may differ from 1C.
      const remembered = await submitRememberedLogin(target)
      if (!remembered) {
        if (!credentials?.nameMail || !credentials.password) {
          await enableRememberMe(target)
          return {
            ok: true,
            autoLogin: false,
            message: 'Введите логин и пароль один раз — следующий вход будет автоматическим'
          }
        }
        await submitLogin(target, credentials)
      }
      await waitForAuthenticated(target)
    }
    return { ok: true, autoLogin: true, message: 'TurboProject открыт с автоматическим входом' }
  } catch (error) {
    if (!started) {
      try {
        await startTurboProject(executablePath)
      } catch {
        return { ok: false, autoLogin: false, error: 'Не удалось запустить TurboProject' }
      }
    }
    return {
      ok: true,
      autoLogin: false,
      message: `TurboProject открыт без автологина: ${
        error instanceof Error ? error.message : 'неизвестная ошибка'
      }`
    }
  }
}
