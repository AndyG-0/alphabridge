import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
    css: false,
    coverage: {
      provider: 'v8',
      include: ['src/**'],
      exclude: ['src/test/**', 'src/**/*.test.tsx', 'src/main.tsx'],
      reporter: ['text-summary', 'lcov'],
      thresholds: { lines: 30, statements: 30, branches: 25 },
    },
  },
})
