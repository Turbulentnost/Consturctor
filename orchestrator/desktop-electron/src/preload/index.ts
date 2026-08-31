import { contextBridge, ipcRenderer, webUtils } from 'electron'

export interface ApiResponse<T = unknown> {
  ok: boolean
  status: number
  data?: T
  error?: string
}

const api = {
  getConfig: (): Promise<{ backendUrl: string; testUser: boolean }> =>
    ipcRenderer.invoke('app:getConfig'),
  request: <T = unknown>(opts: {
    method?: string
    path: string
    body?: unknown
    params?: Record<string, string | number | boolean | undefined | null>
    token?: string | null
    timeoutMs?: number
  }): Promise<ApiResponse<T>> => ipcRenderer.invoke('api:request', opts),
  upload: <T = unknown>(opts: {
    endpoint: string
    filePath: string
    fieldName?: string
    token?: string | null
    extraFields?: Record<string, string>
    timeoutMs?: number
  }): Promise<ApiResponse<T>> => ipcRenderer.invoke('api:upload', opts),
  fetchDataUrl: (opts: {
    url: string
    token?: string | null
  }): Promise<{ ok: boolean; dataUrl?: string; error?: string }> =>
    ipcRenderer.invoke('api:fetchDataUrl', opts),
  download: (opts: {
    url: string
    defaultName?: string
    token?: string | null
  }): Promise<{ ok: boolean; canceled?: boolean; path?: string; error?: string }> =>
    ipcRenderer.invoke('api:download', opts),
  createWorkflow: <T = unknown>(opts: {
    notes: string
    draftId?: string
    token?: string | null
  }): Promise<ApiResponse<T>> => ipcRenderer.invoke('api:createWorkflow', opts),
  stream: <T = unknown>(opts: {
    method?: string
    path: string
    body?: unknown
    token?: string | null
    filePaths?: string[]
    extraFields?: Record<string, string>
  }): Promise<ApiResponse<T>> => ipcRenderer.invoke('api:stream', opts),
  onStreamEvent: (callback: (payload: Record<string, unknown>) => void): (() => void) => {
    const listener = (_event: unknown, payload: Record<string, unknown>): void => {
      callback(payload)
    }
    ipcRenderer.on('api:stream-event', listener)
    return () => {
      ipcRenderer.removeListener('api:stream-event', listener)
    }
  },
  getPathForFile: (file: unknown): string => {
    try {
      return webUtils.getPathForFile(file as File)
    } catch {
      return ''
    }
  },
  openFile: (options: {
    title?: string
    filters?: { name: string; extensions: string[] }[]
    properties?: string[]
  }): Promise<string[]> => ipcRenderer.invoke('dialog:openFile', options),
  startNotifications: (token: string): Promise<{ ok: boolean }> =>
    ipcRenderer.invoke('notifications:start', token),
  stopNotifications: (): Promise<{ ok: boolean }> => ipcRenderer.invoke('notifications:stop'),
  showNotification: (payload: {
    title: string
    body?: string
    workflowId?: string
    runId?: string
  }): Promise<{ ok: boolean }> => ipcRenderer.invoke('notify:show', payload),
  onNotificationOpen: (
    callback: (payload: { workflowId: string; runId: string }) => void
  ): (() => void) => {
    const listener = (_event: unknown, payload: { workflowId: string; runId: string }): void => {
      callback(payload)
    }
    ipcRenderer.on('notification:open', listener)
    return () => {
      ipcRenderer.removeListener('notification:open', listener)
    }
  },
  onInboxChanged: (callback: (payload: { id: string }) => void): (() => void) => {
    const listener = (_event: unknown, payload: { id: string }): void => {
      callback(payload)
    }
    ipcRenderer.on('inbox:changed', listener)
    return () => {
      ipcRenderer.removeListener('inbox:changed', listener)
    }
  },
  onBoardUpdated: (callback: (payload: Record<string, unknown>) => void): (() => void) => {
    const listener = (_event: unknown, payload: Record<string, unknown>): void => {
      callback(payload)
    }
    ipcRenderer.on('board:updated', listener)
    return () => {
      ipcRenderer.removeListener('board:updated', listener)
    }
  },
  onSessionKicked: (callback: (payload: { message: string }) => void): (() => void) => {
    const listener = (_event: unknown, payload: { message: string }): void => {
      callback(payload)
    }
    ipcRenderer.on('session:kicked', listener)
    return () => {
      ipcRenderer.removeListener('session:kicked', listener)
    }
  },
  onChatEvent: (callback: (payload: Record<string, unknown>) => void): (() => void) => {
    const listener = (_event: unknown, payload: Record<string, unknown>): void => {
      callback(payload)
    }
    ipcRenderer.on('chat:event', listener)
    return () => {
      ipcRenderer.removeListener('chat:event', listener)
    }
  }
}

const agent = {
  ready: (
    token: string | null,
    credentials?: { login?: string; password?: string }
  ): Promise<{ ok: boolean }> => ipcRenderer.invoke('agent:ready', token, credentials),
  start: (command: Record<string, unknown>): Promise<{ ok: boolean }> =>
    ipcRenderer.invoke('agent:start', command),
  answer: (command: Record<string, unknown>): Promise<{ ok: boolean }> =>
    ipcRenderer.invoke('agent:answer', command),
  hitl: (command: Record<string, unknown>): Promise<{ ok: boolean }> =>
    ipcRenderer.invoke('agent:hitl', command),
  skip: (command: Record<string, unknown>): Promise<{ ok: boolean }> =>
    ipcRenderer.invoke('agent:skip', command),
  cancel: (command: Record<string, unknown>): Promise<{ ok: boolean }> =>
    ipcRenderer.invoke('agent:cancel', command),
  onEvent: (callback: (payload: Record<string, unknown>) => void): (() => void) => {
    const listener = (_event: unknown, payload: Record<string, unknown>): void => {
      callback(payload)
    }
    ipcRenderer.on('agent:event', listener)
    return () => {
      ipcRenderer.removeListener('agent:event', listener)
    }
  }
}

contextBridge.exposeInMainWorld('api', api)
contextBridge.exposeInMainWorld('agent', agent)

export type ExposedApi = typeof api
export type ExposedAgent = typeof agent
