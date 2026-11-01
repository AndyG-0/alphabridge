import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

const PAGES = [
  { name: 'Dashboard', path: '/' },
  { name: 'Portfolio & Dropzone', path: '/portfolio' },
  { name: 'Retirement Plan', path: '/plan' },
  { name: 'Research Lab', path: '/research' },
  { name: 'Chat', path: '/chat' },
  { name: 'Settings', path: '/settings' },
  { name: 'Onboarding', path: '/onboarding' },
  { name: 'Actions', path: '/actions' },
]

for (const theme of ['dark', 'light']) {
  for (const { name, path } of PAGES) {
    test(`${name} (${theme}) renders on seeded data with no serious a11y violations`, async ({ page }) => {
      await page.addInitScript((t) => localStorage.setItem('ab-theme', t), theme)
      const errors: string[] = []
      page.on('pageerror', (e) => errors.push(e.message))
      await page.goto(path)
      await expect(page.locator('main')).toBeVisible()
      await page.waitForLoadState('networkidle')
      await expect(page.getByText(/^(Loading|Running 5,000)/)).toHaveCount(0, { timeout: 30_000 })
      const results = await new AxeBuilder({ page }).analyze()
      const bad = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
      expect(bad.map((v) => `${v.id}: ${v.nodes.length} node(s)`)).toEqual([])
      expect(errors).toEqual([])
    })
  }
}

test('theme toggle switches and persists', async ({ page }) => {
  await page.goto('/')
  const html = page.locator('html')
  const before = await html.getAttribute('data-theme')
  await page.getByRole('button', { name: /Switch to (light|dark) theme/ }).click()
  await expect(html).not.toHaveAttribute('data-theme', before ?? '')
  await page.reload()
  await expect(html).not.toHaveAttribute('data-theme', before ?? '')
})

test('nav switches pages', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('link', { name: 'Settings' }).click()
  await expect(page).toHaveURL(/\/settings$/)
})

test('onboarding wizard is resumable and shows the completeness meter', async ({ page }) => {
  await page.goto('/onboarding')
  await expect(page.getByRole('progressbar', { name: 'Data completeness' })).toBeVisible()
  const saved = page.waitForResponse((r) => r.url().includes('/api/onboarding') && r.request().method() === 'PUT')
  await page.getByRole('button', { name: /^Goals/ }).click()
  await saved
  await expect(page.getByLabel(/Age you want to stop working/)).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Goals' })).toBeVisible()
})

test('plan page draws the fan chart with a table view', async ({ page }) => {
  await page.goto('/plan')
  const fig = page.getByRole('figure', { name: /Projected savings range/ })
  await expect(fig).toBeVisible({ timeout: 30_000 })
  await fig.getByText('View as table').click()
  await expect(fig.getByRole('table')).toBeVisible()
})
