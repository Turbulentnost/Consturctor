import type { ExposedApi, ExposedAgent, ExposedPlatform } from './index'

declare global {
  interface Window {
    api: ExposedApi
    agent: ExposedAgent
    platform: ExposedPlatform
  }
}

export {}
