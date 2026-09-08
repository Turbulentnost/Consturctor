import { resolve } from 'node:path'
import { defineConfig } from 'electron-vite'
import react from '@vitejs/plugin-react'

const rendererPort = Number(process.env.CONSTRUCTOR_VITE_PORT || 5173)

export default defineConfig({
  main: {
    build: {
      rollupOptions: {
        input: { index: resolve(__dirname, 'src/main/index.ts') }
      }
    }
  },
  preload: {
    build: {
      rollupOptions: {
        input: { index: resolve(__dirname, 'src/preload/index.ts') }
      }
    }
  },
  renderer: {
    root: resolve(__dirname, 'src/renderer'),
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src/renderer/src'),
        '@agent-icons': resolve(__dirname, 'src/temp/icons')
      }
    },
    server: {
      host: '127.0.0.1',
      port: Number.isFinite(rendererPort) ? rendererPort : 5173,
      strictPort: false,
      fs: {
        allow: [resolve(__dirname, 'src')]
      }
    },
    build: {
      rollupOptions: {
        input: { index: resolve(__dirname, 'src/renderer/index.html') }
      }
    },
    plugins: [react()]
  }
})
