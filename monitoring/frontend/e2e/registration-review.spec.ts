import { expect, test } from '@playwright/test'

const adminSession = {
  username: 'admin', full_name: '管理员', email: 'admin@example.test',
  email_verified: true, role: 'admin', csrf_token: 'test-csrf',
}

test('新注册直接提示等待管理员审核', async ({ page }) => {
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ status: 401, json: {} }))
  await page.route('**/api/v1/auth/register', (route) => route.fulfill({ status: 202, json: { status: 'pending' } }))
  await page.goto('/register')
  await page.getByLabel('用户名', { exact: true }).fill('alice')
  await page.getByLabel('姓名', { exact: true }).fill('Alice')
  await page.getByLabel('邮箱', { exact: true }).fill('alice@example.test')
  await page.getByLabel('密码', { exact: true }).fill('long-enough-user-password')
  await page.getByRole('button', { name: '提交注册' }).click()
  await expect(page.getByText('注册申请已提交，请等待管理员审核。')).toBeVisible()
  await expect(page.getByRole('button', { name: /重新发送/ })).toHaveCount(0)
})

test('旧验证页面不调用验证接口并引导重新注册', async ({ page }) => {
  const verificationRequests: string[] = []
  page.on('request', (request) => {
    if (/\/auth\/(verify-email|registration\/resend)/.test(request.url())) verificationRequests.push(request.url())
  })
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ status: 401, json: {} }))
  for (const path of ['/verify-email?token=old-link', '/resend-verification']) {
    await page.goto(path)
    await expect(page.getByRole('heading', { name: '注册无需验证邮箱' })).toBeVisible()
    await page.getByRole('button', { name: '前往注册' }).click()
    await expect(page).toHaveURL(/\/register$/)
  }
  expect(verificationRequests).toEqual([])
})

test('历史待验证申请显示为待审核并可直接审核', async ({ page }) => {
  let legacyStatus = 'email_pending'
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.endsWith('/auth/me')) body = adminSession
    if (path.endsWith('/users/registrations/legacy/review')) {
      expect(route.request().postDataJSON().decision).toBe('approved')
      legacyStatus = 'approved'
      body = { id: 'legacy', status: legacyStatus }
    }
    if (path.endsWith('/users/registrations')) body = [
      { id: 'legacy', username: 'legacy-user', full_name: '旧申请', status: legacyStatus },
      { id: 'new', username: 'new-user', full_name: '新申请', status: 'pending' },
      { id: 'unknown', username: 'unknown-user', full_name: '未知申请', status: 'unexpected' },
    ]
    await route.fulfill({ json: body })
  })
  await page.goto('/users')
  await page.getByRole('tab', { name: '注册审核 (2)' }).click()
  await expect(page.getByText('legacy-user', { exact: true })).toBeVisible()
  await expect(page.getByText('new-user', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /^审\s*核$/ })).toHaveCount(2)
  await expect(page.getByText('未知状态', { exact: true })).toBeVisible()
  await expect(page.getByText('已拒绝', { exact: true })).toHaveCount(0)
  const legacyRow = page.getByRole('row').filter({ hasText: 'legacy-user' })
  await expect(legacyRow.getByText('待审核', { exact: true })).toBeVisible()
  await legacyRow.getByRole('button', { name: /^审\s*核$/ }).click()
  await page.getByRole('dialog').getByRole('button', { name: /^确\s*定$/ }).click()
  await expect(page.getByRole('tab', { name: '注册审核 (1)' })).toBeVisible()
  await expect(legacyRow.getByText('已通过', { exact: true })).toBeVisible()
  await expect(legacyRow.getByRole('button', { name: /^审\s*核$/ })).toHaveCount(0)
})

test('登录后可自愿验证当前邮箱', async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const body = path.endsWith('/auth/me') ? { ...adminSession, email_verified: false } : []
    await route.fulfill({ json: body })
  })
  await page.goto('/users')
  await page.getByRole('button', { name: '验证邮箱', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('当前密码').fill('long-enough-admin-password')
  const submitted = page.waitForRequest((request) => request.url().endsWith('/auth/email/change-request'))
  await dialog.getByRole('button', { name: '发送验证邮件' }).click()
  const request = await submitted
  expect(request.postDataJSON()).toEqual({ new_email: adminSession.email, current_password: 'long-enough-admin-password' })
  expect(request.headers()['x-csrf-token']).toBe(adminSession.csrf_token)
  await expect(page.getByText('验证邮件已提交发送，请查收邮箱。')).toBeVisible()
})

test('自愿验证链接只提交一次并刷新邮箱状态', async ({ page }) => {
  let confirmations = 0
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({
    json: { ...adminSession, email_verified: confirmations > 0 },
  }))
  await page.route('**/api/v1/auth/email/change-confirm', async (route) => {
    confirmations += 1
    await route.fulfill(confirmations === 1
      ? { status: 204 }
      : { status: 400, json: { detail: 'verification link is invalid or expired' } })
  })
  await page.goto('/verify-new-email?token=current-email-token')
  await expect(page.getByText('邮箱已验证，可用于找回密码。')).toBeVisible()
  expect(confirmations).toBe(1)
})
