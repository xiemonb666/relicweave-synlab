import { expect, test, type ConsoleMessage, type Page } from '@playwright/test';

/**
 * 真实端到端：启动真实后端（playwright.config.ts 的 webServer）→ 用构建产物打开概览 →
 * 打开退化对比页并断言“误差热图 + 点云叠加”用**真实数组**渲染出来 → 再巡检其它新增面板。
 *
 * 断言只依赖真实后端响应带来的内容：
 * * 概览页必须显示后端 `/health` 的工作区/角色，且顶栏不得出现“后端不可用”；
 * * 退化页的点云面板必须给出真实点数与真实统计（总点数 > 1000），canvas 真的被画过；
 * * 纹样页必须由真实 PNG 字节解码出图片；母体页必须出现真实 surface_tag 面数与名称；
 * * 全程不得出现 `.state--error`，控制台不得有 error/pageerror。
 *
 * 面板定位统一用 `region(name)`：`SectionCard` / `AssetBrowser` 都把标题写进 `aria-label`，
 * 因此按无障碍角色定位比按文本过滤更稳（同一标题可能出现在正文表格里）。
 */

const ROUTES = [
  '/synlab',
  '/synlab/mothers/new',
  '/synlab/patterns',
  '/synlab/fracture',
  '/synlab/degradation',
  '/synlab/camera-profiles',
  '/synlab/jobs',
  '/synlab/releases',
  '/synlab/training',
  '/synlab/diagnostics',
  '/synlab/episodes',
  '/synlab/quality',
];

function watchConsole(page: Page): { errors: string[] } {
  const errors: string[] = [];
  page.on('console', (message: ConsoleMessage) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`));
  return { errors };
}

function region(page: Page, name: string) {
  return page.getByRole('region', { name });
}

test('真实后端 → 概览 → 退化页：误差热图与点云叠加断言', async ({ page }) => {
  const console = watchConsole(page);

  // ---------------------------------------------------------------- 1) 概览
  await page.goto('/synlab');
  await expect(page.locator('main h1').first()).toBeVisible();
  await expect(page.locator('.topbar')).toContainText('工作区');
  await expect(page.locator('.topbar')).not.toContainText('后端不可用');
  await expect(page.locator('.topbar')).toContainText('researcher');

  // ---------------------------------------------------------------- 2) 退化页：真实数组面板
  await page.goto('/synlab/degradation');
  const panel = region(page, '误差热图与点云叠加（真实数组）');
  await expect(panel).toBeVisible();
  await expect(panel.getByText('前端由真实 depth/points 计算，非后端误差场').first()).toBeVisible();

  // 点云模式：等待 npz 下载 + 解码 + 绘制完成（真实统计表出现）
  await expect(panel.getByText('总点数')).toBeVisible({ timeout: 90_000 });
  const stats = panel.locator('dl.kv').first();
  await expect(stats).toContainText('有效点数');
  const totalText = await stats.locator('.kv__row', { hasText: '总点数' }).locator('dd').first().innerText();
  const total = Number(totalText.replace(/[^0-9]/g, ''));
  expect(total).toBeGreaterThan(1000);
  const validText = await stats.locator('.kv__row', { hasText: '有效点数' }).locator('dd').first().innerText();
  expect(Number(validText.replace(/[^0-9]/g, ''))).toBeGreaterThan(1000);

  // 画布真的被画过（存在不透明像素）
  const painted = await panel.locator('canvas').first().evaluate((node) => {
    const canvas = node as HTMLCanvasElement;
    const context = canvas.getContext('2d');
    if (!context || canvas.width === 0) return 0;
    const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let count = 0;
    for (let index = 3; index < data.length; index += 4) if (data[index] > 0) count += 1;
    return count;
  });
  expect(painted).toBeGreaterThan(0);
  await expect(panel.locator('.state--error')).toHaveCount(0);

  // ---------------------------------------------------------------- 3) 深度差热图（同一面板的第二个模式）
  await panel.getByRole('tab', { name: /深度差热图/ }).click();
  await expect(panel.getByText('基准资产 A（含 arrays）')).toBeVisible();
  await expect(panel.getByText('深度绝对差', { exact: false }).first()).toBeVisible({ timeout: 90_000 });
  await expect(panel.locator('.state--error')).toHaveCount(0);

  // ---------------------------------------------------------------- 4) 其它新增面板也必须在真实数据下渲染
  await page.goto('/synlab/patterns');
  const channels = region(page, '展开 chart 与三通道图（真实 PNG 解码）');
  await expect(channels).toBeVisible();
  const channelBrowser = region(page, '纹样资产（recipe / channels / audit）');
  await expect(channelBrowser.locator('tbody tr').first()).toBeVisible();
  await channelBrowser.locator('tbody tr', { hasText: 'pattern_channels' }).first().locator('input').check();
  await expect(channels.locator('img').first()).toBeVisible({ timeout: 90_000 });
  await expect(channels.getByText('IHDR', { exact: false }).first()).toBeVisible();
  await expect(channels.locator('.state--error')).toHaveCount(0);
  await expect(region(page, '纯背景 / 轮廓负控视图（A05 / A32 相关）')).toBeVisible();

  await page.goto('/synlab/mothers/new');
  const tags = region(page, '真实面属性视图（surface_tag / 法向 / 到轴距离）');
  await expect(tags).toBeVisible();
  const meshBrowser = region(page, '权威母体 mesh（mother_mesh）');
  await expect(meshBrowser.locator('tbody tr').first()).toBeVisible();
  await meshBrowser.locator('tbody tr').first().locator('input').check();
  await expect(tags.getByText('surface_tag 合法值', { exact: false })).toBeVisible({ timeout: 90_000 });
  await expect(tags.locator('.state--error')).toHaveCount(0);

  await page.goto('/synlab/camera-profiles');
  const uPanel = region(page, 'U 位置 → 真实新场景帧');
  await expect(uPanel).toBeVisible();
  await expect(uPanel.getByText('旧帧').first()).toBeVisible();
  await expect(region(page, 'I09 数字降采样（与 U 移动分开）')).toBeVisible();

  // ---------------------------------------------------------------- 5) 12 路由巡检（不得出现错误卡片）
  for (const route of ROUTES) {
    await page.goto(route);
    await expect(page.locator('main h1').first()).toBeVisible();
    const errors = await page.locator('.state--error').count();
    expect(errors, `${route} 出现错误卡片`).toBe(0);
  }

  expect(console.errors, `控制台错误：${console.errors.join(' | ')}`).toHaveLength(0);
});
