import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: { baseURL: 'http://localhost:5199', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: [
    {
      command: 'API_PORT=5101 ./e2e/serve-backend.sh',
      url: 'http://localhost:5101/api/health',
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: 'ignore',
    },
    { command: 'API_PORT=5101 npx vite --port 5199 --strictPort', url: 'http://localhost:5199', reuseExistingServer: false, stdout: 'ignore' },
  ],
})
