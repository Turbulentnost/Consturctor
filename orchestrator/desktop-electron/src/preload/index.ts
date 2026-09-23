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
  setComSecret: (payload: {
    login?: string
    password?: string
    nameMail?: string
    persist?: boolean
  }): Promise<{ ok: boolean }> => ipcRenderer.invoke('session:setComSecret', payload),
  getComSecret: (): Promise<{ login: string; password: string; nameMail: string } | null> =>
    ipcRenderer.invoke('session:getComSecret'),
  clearComSecret: (): Promise<{ ok: boolean }> => ipcRenderer.invoke('session:clearComSecret'),
  request: <T = unknown>(opts: {
    method?: string
    path: string
    body?: unknown
    params?: Record<string, string | number | boolean | undefined | null>
    token?: string | null
    timeoutMs?: number
    filePaths?: string[]
    extraFields?: Record<string, string>
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
  fetchBinary: (opts: {
    url: string
    token?: string | null
    maxBytes?: number
  }): Promise<{ ok: boolean; base64?: string; contentType?: string; size?: number; error?: string }> =>
    ipcRenderer.invoke('api:fetchBinary', opts),
  fetchFilePreview: (opts: {
    url: string
    fileName?: string
    token?: string | null
  }): Promise<
    | { ok: true; kind: 'text'; text: string; mime: string }
    | { ok: true; kind: 'embed'; dataUrl: string; mime: string }
    | { ok: true; kind: 'external'; hint: string; mime: string }
    | { ok: false; error: string; tooLarge?: boolean }
  > => ipcRenderer.invoke('api:fetchFilePreview', opts),
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
  openPath: (filePath: string): Promise<{ ok: boolean; error?: string }> =>
    ipcRenderer.invoke('shell:openPath', filePath),
  printToPdf: (opts: {
    html?: string
    landscape?: boolean
    openAfter?: boolean
    defaultName?: string
  }): Promise<{ ok: boolean; canceled?: boolean; path?: string; error?: string }> =>
    ipcRenderer.invoke('print:to-pdf', opts),
  printPreview: (opts: {
    html?: string
    landscape?: boolean
  }): Promise<{ ok: boolean; path?: string; error?: string }> =>
    ipcRenderer.invoke('print:preview', opts),
  printDialog: (opts: {
    html?: string
    landscape?: boolean
  }): Promise<{ ok: boolean; canceled?: boolean; error?: string }> =>
    ipcRenderer.invoke('print:dialog', opts),
  readLocalFilePreview: (
    filePath: string
  ): Promise<
    | {
        ok: true
        path: string
        size: number
        mime: string
        kind: 'text'
        text: string
      }
    | {
        ok: true
        path: string
        size: number
        mime: string
        kind: 'embed'
        dataUrl: string
      }
    | {
        ok: true
        path: string
        size: number
        mime: string
        kind: 'external'
        hint: string
      }
    | { ok: false; error: string; tooLarge?: boolean; path?: string; size?: number }
  > => ipcRenderer.invoke('fs:readLocalFilePreview', filePath),
  copyLocalFile: (opts: {
    sourcePath: string
    defaultName?: string
  }): Promise<{ ok: boolean; canceled?: boolean; path?: string; error?: string }> =>
    ipcRenderer.invoke('fs:copyLocalFile', opts),
  saveClipboardImage: (): Promise<string> => ipcRenderer.invoke('clipboard:saveImage'),
  startNotifications: (token: string): Promise<{ ok: boolean }> =>
    ipcRenderer.invoke('notifications:start', token),
  stopNotifications: (): Promise<{ ok: boolean }> => ipcRenderer.invoke('notifications:stop'),
  showNotification: (payload: {
    title: string
    body?: string
    workflowId?: string
    runId?: string
    requestId?: string
    draftId?: string
    openDecisions?: boolean
    canStop?: boolean
  }): Promise<{ ok: boolean }> => ipcRenderer.invoke('notify:show', payload),
  onNotificationOpen: (
    callback: (payload: {
      workflowId: string
      runId: string
      draftId?: string
      requestId?: string
      openDecisions?: boolean
    }) => void
  ): (() => void) => {
    const listener = (
      _event: unknown,
      payload: {
        workflowId: string
        runId: string
        draftId?: string
        requestId?: string
        openDecisions?: boolean
      }
    ): void => {
      callback(payload)
    }
    ipcRenderer.on('notification:open', listener)
    return () => {
      ipcRenderer.removeListener('notification:open', listener)
    }
  },
  onNotificationStop: (
    callback: (payload: { workflowId: string; runId: string }) => void
  ): (() => void) => {
    const listener = (_event: unknown, payload: { workflowId: string; runId: string }): void => {
      callback(payload)
    }
    ipcRenderer.on('notification:stop', listener)
    return () => {
      ipcRenderer.removeListener('notification:stop', listener)
    }
  },
  onNotificationHitl: (
    callback: (payload: {
      requestId: string
      approved: boolean
      workflowId: string
      runId: string
    }) => void
  ): (() => void) => {
    const listener = (
      _event: unknown,
      payload: { requestId: string; approved: boolean; workflowId: string; runId: string }
    ): void => {
      callback(payload)
    }
    ipcRenderer.on('notification:hitl', listener)
    return () => {
      ipcRenderer.removeListener('notification:hitl', listener)
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
  },
  getUpdateStatus: (): Promise<{
    state: 'idle' | 'available' | 'downloading' | 'installing' | 'error'
    currentVersion: string
    availableVersion: string
    percent: number
    error: string
    source: string
    devMode: boolean
  }> => ipcRenderer.invoke('updater:getStatus'),
  checkUpdate: (): Promise<{
    state: 'idle' | 'available' | 'downloading' | 'installing' | 'error'
    currentVersion: string
    availableVersion: string
    percent: number
    error: string
    source: string
    devMode: boolean
  }> => ipcRenderer.invoke('updater:check'),
  installUpdate: (): Promise<{ ok: boolean; error?: string }> => ipcRenderer.invoke('updater:install'),
  loadOdataExternalEnv: (): Promise<{
    ok: boolean
    path: string
    missing: string[]
    invokeArgs: Record<string, string>
  }> => ipcRenderer.invoke('orch:load-odata-external-env'),
  fetchErpOdataTasks: (opts: {
    token?: string | null
    fio?: string
    limit?: number
    fallbackSql?: boolean
  }): Promise<{
    ok: boolean
    status: number
    data?: unknown
    error?: string
  }> => ipcRenderer.invoke('orch:fetch-erp-odata-tasks', opts),
  onUpdateStatus: (
    callback: (payload: {
      state: 'idle' | 'available' | 'downloading' | 'installing' | 'error'
      currentVersion: string
      availableVersion: string
      percent: number
      error: string
      source: string
      devMode: boolean
    }) => void
  ): (() => void) => {
    const listener = (
      _event: unknown,
      payload: {
        state: 'idle' | 'available' | 'downloading' | 'installing' | 'error'
        currentVersion: string
        availableVersion: string
        percent: number
        error: string
        source: string
        devMode: boolean
      }
    ): void => {
      callback(payload)
    }
    ipcRenderer.on('updater:status', listener)
    return () => {
      ipcRenderer.removeListener('updater:status', listener)
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
  readCalendar: (command: Record<string, unknown>): Promise<{ ok: boolean }> =>
    ipcRenderer.invoke('agent:read-calendar', command),
  searchOutlookMail: (
    command: Record<string, unknown>
  ): Promise<{ ok: boolean; queued?: boolean; error?: string; reason?: string }> =>
    ipcRenderer.invoke('agent:search-mail', command),
  invokeAcTool: (
    command: Record<string, unknown>
  ): Promise<{ ok: boolean; queued?: boolean; error?: string; reason?: string }> =>
    ipcRenderer.invoke('agent:invoke-ac-tool', command),
  sidecarStatus: (): Promise<Record<string, unknown>> => ipcRenderer.invoke('agent:status'),
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
