import { expect, test } from '@playwright/test'

const resources = [
  {
    id: 'resource-a', description: '仅用于训练\n请提前联系管理员 <b>重要</b>', name: 'A100 服务器', gpu_model: 'A100', gpu_count: 4,
    cpu_cores: 32, memory_gib: 128, default_cpu_cores: 8, default_memory_gib: 32,
    allocated_gpu_count: 0, available_gpu_count: 4, overallocated: false, status: 'active',
    reserved_gpu_count: 3, reserved_cpu_cores: 28, reserved_memory_gib: 112,
    remaining_gpu_count: 1, remaining_cpu_cores: 4, remaining_memory_gib: 16,
  },
  {
    id: 'resource-b', description: '', name: 'H100 服务器', gpu_model: 'H100', gpu_count: 8,
    cpu_cores: 64, memory_gib: 256, default_cpu_cores: 16, default_memory_gib: 64,
    allocated_gpu_count: 0, available_gpu_count: 8, overallocated: false, status: 'active',
    reserved_gpu_count: 9, reserved_cpu_cores: 72, reserved_memory_gib: 300,
    remaining_gpu_count: 0, remaining_cpu_cores: 0, remaining_memory_gib: 0,
  },
]

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = []
    if (path.endsWith('/auth/me')) body = {
      username: 'admin', full_name: '管理员', email: 'admin@example.test',
      email_verified: true, role: 'admin', csrf_token: 'test-csrf',
    }
    if (path.endsWith('/resources')) body = resources
    if (path.endsWith('/projects')) body = [{ id: 'squad', name: 'Research', status: 'active' }]
    if (route.request().method() === 'POST') body = { id: 'created', ...route.request().postDataJSON() }
    await route.fulfill({ json: body })
  })
})

test('服务器必填容量与默认申请值，默认值不能超过容量', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '新建算力资源' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('资源名称').fill('新服务器')
  await dialog.getByLabel('说明', { exact: true }).fill('多行说明\n仅供训练使用')
  await dialog.getByLabel('GPU 型号').fill('A100')
  await dialog.getByLabel('GPU 总卡数').fill('4')
  await dialog.getByLabel('CPU 总核心数（逻辑核心）').fill('32')
  await dialog.getByLabel('内存总容量（GiB）').fill('128')
  await dialog.getByLabel('默认申请 CPU 核心数').fill('33')
  await dialog.getByLabel('默认申请内存（GiB）').fill('32')
  await dialog.getByRole('button', { name: /保\s*存/ }).click()
  await expect(dialog.getByText('默认值不能超过 CPU 总核心数')).toBeVisible()
  await dialog.getByLabel('默认申请 CPU 核心数').fill('8')
  const submitted = page.waitForRequest((r) => r.method() === 'POST' && r.url().endsWith('/resources'))
  await dialog.getByRole('button', { name: /保\s*存/ }).click()
  expect((await submitted).postDataJSON()).toMatchObject({ description: '多行说明\n仅供训练使用', cpu_cores: 32, memory_gib: 128, default_cpu_cores: 8, default_memory_gib: 32 })
})

test('申请自动填入默认值，显示超配并允许超过剩余额度提交', async ({ page }) => {
  await page.goto('/requests')
  await page.getByRole('button', { name: '新建申请' }).click()
  await page.getByRole('button', { name: '我已阅读，继续申请' }).click()
  await expect(page.getByRole('dialog', { name: '算力资源使用须知' })).toHaveCount(0)
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('所属Squad').click()
  await page.locator('.ant-select-item-option-content').getByText('Research', { exact: true }).click()
  await dialog.getByLabel('算力资源', { exact: true }).click()
  await page.locator('.ant-select-item-option-content').filter({ hasText: 'A100 服务器' }).click()
  await expect(dialog.getByText('资源说明', { exact: true })).toBeVisible()
  await expect(dialog.getByText('仅用于训练\n请提前联系管理员 <b>重要</b>', { exact: true })).toBeVisible()
  await expect(dialog.getByLabel('需要 CPU 核心数（逻辑核心）')).toHaveValue('8')
  await expect(dialog.getByLabel('需要内存（GiB）')).toHaveValue('32')
  await expect(dialog.getByText('CPU：剩余 4 核 / 总计 32 核')).toBeVisible()
  await dialog.getByLabel('需要 CPU 核心数（逻辑核心）').fill('12')
  await dialog.getByLabel('算力资源', { exact: true }).click()
  await page.locator('.ant-select-item-option-content').filter({ hasText: 'H100 服务器' }).click()
  await expect(dialog.getByText('资源说明', { exact: true })).toHaveCount(0)
  await expect(dialog.getByLabel('需要 CPU 核心数（逻辑核心）')).toHaveValue('16')
  await expect(dialog.getByLabel('需要内存（GiB）')).toHaveValue('64')
  await expect(dialog.getByText('CPU：剩余 0 核 / 总计 64 核，已超配 8 核')).toBeVisible()
  await expect(dialog.getByText('申请超过当前剩余额度，仍可提交，由管理员审批。')).toBeVisible()
  await dialog.getByLabel('需要 GPU 数量').fill('0')
  await dialog.getByLabel('需要天数').fill('7')
  const submitted = page.waitForRequest((r) => r.method() === 'POST' && r.url().endsWith('/compute-requests'))
  await dialog.getByRole('button', { name: /确\s*定/ }).click()
  expect((await submitted).postDataJSON()).toMatchObject({ resource_id: 'resource-b', gpu_count: 0, cpu_cores: 16, memory_gib: 64, duration_days: 7 })
})

test('配置调整预填当前 GPU、CPU 和内存，并整组提交', async ({ page }) => {
  await page.route('**/api/v1/compute-requests', async (route) => route.fulfill({ json: [{
    id: 'request-a', applicant_id: 'admin', applicant_username: 'admin', applicant_name: '管理员',
    project_id: 'squad', project_name: 'Research', resource_id: 'resource-a', resource_name: 'A100 服务器',
    gpu_count: 2, cpu_cores: 8, memory_gib: 32, duration_days: 7,
    approval_status: 'approved', runtime_status: 'not_started', actual_gpu_count: 0,
    over_quota: false, reviewer_name: '管理员', review_comment: null, reviewed_at: null,
    token: 'cda_example', started_at: null, expires_at: null, created_at: '2026-11-07T00:00:00Z', changes: [],
  }] }))
  await page.goto('/requests')
  await page.getByRole('tab', { name: '已通过' }).click()
  await page.getByRole('button', { name: '申请变更' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByLabel('调整后的 GPU 数量')).toHaveValue('2')
  await expect(dialog.getByLabel('调整后的 CPU 总核心数')).toHaveValue('8')
  await expect(dialog.getByLabel('调整后的内存总量（GiB）')).toHaveValue('32')
  await dialog.getByLabel('调整后的 GPU 数量').fill('0')
  await dialog.getByLabel('调整后的内存总量（GiB）').fill('64')
  await dialog.getByLabel('调整后的 CPU 总核心数').fill('12')
  const submitted = page.waitForRequest((r) => r.method() === 'POST' && r.url().endsWith('/request-a/changes'))
  await dialog.getByRole('button', { name: /确\s*定/ }).click()
  expect((await submitted).postDataJSON()).toEqual({ change_type: 'config', gpu_count: 0, cpu_cores: 12, memory_gib: 64 })
})

test('时间调整支持增加和减少天数', async ({ page }) => {
  await page.route('**/api/v1/compute-requests', async (route) => route.fulfill({ json: [{
    id: 'request-time', applicant_id: 'admin', applicant_username: 'admin', applicant_name: '管理员',
    project_id: 'squad', project_name: 'Research', resource_id: 'resource-a', resource_name: 'A100 服务器',
    gpu_count: 2, cpu_cores: 8, memory_gib: 32, duration_days: 7,
    approval_status: 'approved', runtime_status: 'running', actual_gpu_count: 0,
    over_quota: false, reviewer_name: '管理员', review_comment: null, reviewed_at: null,
    token: 'cda_example', started_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + 7 * 86400000).toISOString(), created_at: new Date().toISOString(), changes: [],
  }] }))
  await page.goto('/requests')
  await page.getByRole('tab', { name: '已通过' }).click()
  for (const [direction, delta] of [['增加天数', 3], ['减少天数', -2]] as const) {
    await page.getByRole('button', { name: '申请变更' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('变更类型').click()
    await page.locator('.ant-select-item-option-content').getByText('时间调整', { exact: true }).click()
    await dialog.getByLabel('调整方向').click()
    await page.locator('.ant-select-item-option-content').getByText(direction, { exact: true }).click()
    await dialog.getByLabel('调整天数', { exact: true }).fill(String(Math.abs(delta)))
    const submitted = page.waitForRequest((r) => r.method() === 'POST' && r.url().endsWith('/request-time/changes'))
    await dialog.getByRole('button', { name: /确\s*定/ }).click()
    expect((await submitted).postDataJSON()).toEqual({ change_type: 'time', days_delta: delta })
    await expect(dialog).toHaveCount(0)
  }
})
