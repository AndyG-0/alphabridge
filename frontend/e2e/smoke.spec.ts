import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

const PAGES = [
  { name: 'Dashboard', path: '/' },
  { name: 'Portfolio & Dropzone', path: '/portfolio' },
  { name: 'Retirement Plan', path: '/plan' },
  { name: 'Research Lab', path: '/research' },
  { name: 'Chat', path: '/chat' },
  { name: 'Settings', path: '/settings' },
]

for (const { name, path } of PAGES) {
  test(`${name} renders on seeded data with no serious a11y violations`, async ({ page }) => {
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

test('nav switches pages', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('link', { name: 'Settings' }).click()
  await expect(page).toHaveURL(/\/settings$/)
})
