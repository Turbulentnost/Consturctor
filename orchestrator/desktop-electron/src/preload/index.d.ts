import type { ExposedApi, ExposedAgent } from './index'

declare global {
  interface Window {
    api: ExposedApi
    agent: ExposedAgent
  }
}

export {}
