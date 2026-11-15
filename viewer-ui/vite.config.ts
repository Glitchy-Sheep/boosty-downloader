import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import type { ProxyOptions } from 'vite'
import { defineConfig } from 'vitest/config'

const backendTarget = process.env.BOOSTY_VIEWER_BACKEND ?? 'http://127.0.0.1:8314'

function backendProxy(): ProxyOptions {
  return {
    target: backendTarget,
    changeOrigin: true,
    configure(proxy) {
      proxy.on('proxyReq', (proxyRequest, request) => {
        if (request.headers.origin) {
          proxyRequest.setHeader('Origin', new URL(backendTarget).origin)
        }
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    proxy: { '/api': backendProxy(), '/media': backendProxy(), '/thumbs': backendProxy() },
  },
  build: {
    outDir: '../boosty_downloader/viewer/static/app',
    emptyOutDir: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/**/*.test.{ts,tsx}',
        'src/test/**',
        'src/**/*.d.ts',
        'src/lib/api.gen.ts',
        'src/lib/api.gen.typecheck.ts',
      ],
      reporter: ['text-summary', 'json-summary', 'lcov', 'html'],
      reportOnFailure: true,
      // Negative thresholds cap uncovered counts as the codebase grows.
      thresholds: { statements: -136, branches: -128, functions: -38, lines: -94 },
    },
  },
})
