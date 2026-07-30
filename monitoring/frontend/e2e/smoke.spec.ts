import { expect, test } from '@playwright/test'

const password = process.env.MONITORING_E2E_PASSWORD

test('管理员可以登录并看到算力资源概览', async ({ page }) => {
  test.skip(!password, '需要设置 MONITORING_E2E_PASSWORD')

  await page.goto('/login')
  await page.getByPlaceholder('管理员账号').fill(process.env.MONITORING_E2E_USER ?? 'admin')
  await page.getByPlaceholder('密码').fill(password!)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByRole('heading', { name: '算力资源' })).toBeVisible()
  await expect(page.getByRole('button', { name: '新建算力资源' })).toBeVisible()
})
