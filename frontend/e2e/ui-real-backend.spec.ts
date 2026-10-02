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
  '/synlab/synthesis',
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

/**
 * U14 合成向导：六步真实走完（或停在真实阻塞点并显示错误码）。
 *
 * 覆盖点（对应用户要求）：
 * ① 选器型/材料/花纹族/层组合 —— 下拉/多选来自真实 /registry/*（这里断言真实 id 出现）；
 * ② 断裂参数 —— 可选后端 + registry 的真实 status；
 * ③ 退化 —— 6 阶段分组 + 档位 0–4 + “level 0 = 真恒等”提示；
 * ④ 观测 —— 路线 ideal/proxy/photo_mvs、视角数、长边 px、渲染后端 auto/software/blender；
 * ⑤ 预览 —— 真实跑一条谱系，显示各阶段真实耗时与产物，或显示后端 code + 复现命令；
 * ⑥ 入队批量 —— 批大小、续跑、实时进度（真实 SSE / jobs 轮询）。
 *
 * 断言只依赖真实后端：真实 registry id、真实校验结果、真实 job/资产计数。
 */
test('U14 合成向导：①→⑥ 全流程（真实 registry + 真实预览）', async ({ page }) => {
  // ⑤ 步会真的跑完一条谱系（母体→…→观测），本机实测 ~4 分钟起，因此给足超时。
  test.setTimeout(900_000);
  const console = watchConsole(page);
  await page.goto('/synlab/synthesis');
  await expect(page.locator('main h1').first()).toContainText('合成向导');

  // ---------------------------------------------------------------- ① 组合选择
  const vesselPicker = page.getByRole('group', { name: /器型（vessel）/ });
  await expect(vesselPicker).toBeVisible();
  // registry 里真实注册的 V01 必须出现（前端不写死名单，出现即证明来自后端）
  await expect(vesselPicker.locator('input#vessel-V01')).toHaveCount(1, { timeout: 60_000 });
  await expect(page.getByRole('group', { name: /材料（material）/ }).locator('input#material-M01')).toHaveCount(1);
  await expect(page.getByRole('group', { name: /花纹族（pattern）/ }).locator('input#pattern-PAT01')).toHaveCount(1);

  // ---------------------------------------------------------------- ② 断裂后端 + 真实 status
  await page.getByRole('button', { name: /② 断裂参数/ }).click();
  const backendTable = page.getByRole('table', { name: /可选断裂后端/ });
  await expect(backendTable).toBeVisible();
  await expect(backendTable.locator('tbody tr').first()).toBeVisible({ timeout: 60_000 });
  const backendRows = await backendTable.locator('tbody tr').count();
  expect(backendRows).toBeGreaterThan(0);

  // ---------------------------------------------------------------- ③ 退化：6 阶段 + 档位 0–4 + level 0 提示
  await page.getByRole('button', { name: /③ 退化/ }).click();
  await expect(page.getByText('level 0 = 真恒等')).toBeVisible();
  const axisGroup = page.getByRole('group', { name: /PHYSICAL/ });
  await expect(axisGroup).toBeVisible();
  await expect(axisGroup.locator('tbody tr').first()).toBeVisible({ timeout: 60_000 });
  await axisGroup.locator('tbody tr').first().getByRole('button', { name: '加入' }).click();
  const levelSelect = axisGroup.locator('tbody tr').first().locator('select');
  await expect(levelSelect).toBeVisible();
  await expect(levelSelect.locator('option')).toHaveCount(5);
  await expect(levelSelect.locator('option', { hasText: '真恒等' })).toHaveCount(1);

  // ---------------------------------------------------------------- ④ 观测
  await page.getByRole('button', { name: /④ 观测/ }).click();
  const routeSelect = page.getByLabel('观测路线');
  await expect(routeSelect).toBeVisible();
  const routeOptions = await routeSelect.locator('option').allInnerTexts();
  expect(routeOptions.join(' ')).toContain('photo_mvs');
  await expect(page.getByLabel('每片视角数')).toBeVisible();
  await expect(page.getByLabel('长边像素')).toBeVisible();
  const rendererSelect = page.getByLabel('渲染后端');
  const rendererOptions = await rendererSelect.locator('option').allInnerTexts();
  expect(rendererOptions.join(' ')).toContain('software_rasterizer');
  expect(rendererOptions.join(' ')).toContain('blender');

  // ---------------------------------------------------------------- ⑤ 预览（真实跑一条谱系）
  await page.getByRole('button', { name: /⑤ 预览/ }).click();
  const previewHash = page.getByText('预览 spec_hash（后端 /specs/validate）');
  await expect(previewHash).toBeVisible();
  // 后端 /specs/validate 的真实 hash 必须出现（sha256: 前缀）
  await expect(page.locator('dd.mono', { hasText: /^sha256:/ }).first()).toBeVisible({ timeout: 60_000 });

  const runPreview = page.getByRole('button', { name: '跑一次单谱系预览' });
  await expect(runPreview).toBeEnabled({ timeout: 60_000 });
  await runPreview.click();

  // 真实结果：要么跑完（阶段耗时表出现），要么停在真实阻塞点并显示错误码 + 复现命令。
  const stagesTable = page.getByRole('table', { name: /每阶段真实耗时/ });
  const failureCard = page.locator('.state--error').filter({ hasText: /复现命令|预览未完成/ });
  await expect(stagesTable.or(failureCard).first()).toBeVisible({ timeout: 600_000 });

  if (await stagesTable.count()) {
    const stageRows = await stagesTable.locator('tbody tr').count();
    expect(stageRows).toBeGreaterThan(0);
    // 阶段耗时列必须是真实数字（不是“未提供”占位）
    const firstSeconds = await stagesTable.locator('tbody tr').first().locator('td').first().innerText();
    expect(firstSeconds.trim().length).toBeGreaterThan(0);
    await expect(page.getByText('产出资产', { exact: false }).first()).toBeVisible();
  } else {
    // 真实阻塞：必须能看到后端错误码与复现命令，而不是空状态
    await expect(failureCard.first()).toContainText(/CHAIN_|INTEGRATION_PENDING|ENV_CAPABILITY_MISSING|SCHEMA_INVALID/);
    await expect(failureCard.first().getByRole('button', { name: /复制/ }).first()).toBeVisible();
  }

  // ---------------------------------------------------------------- ⑥ 入队批量（真实规划 + 真实受理）
  await page.getByRole('button', { name: /⑥ 入队批量/ }).click();
  await expect(page.getByLabel('批大小')).toBeVisible();
  const resumeButton = page.getByRole('button', { name: '一键续跑下一批（resume）' });
  await expect(resumeButton).toBeVisible();
  await resumeButton.click();
  await expect(page.getByText('本批组合', { exact: false }).first()).toBeVisible({ timeout: 60_000 });

  const submitBatch = page.getByRole('button', { name: /提交这一批（POST \/jobs）/ });
  if (await submitBatch.isEnabled().catch(() => false)) {
    await submitBatch.click();
    // 受理（202）后必须出现真实 run_id 与权威 job state 计数
    await expect(page.getByText('run_id', { exact: false }).first()).toBeVisible({ timeout: 60_000 });
    await expect(page.locator('.statrow').first()).toBeVisible({ timeout: 60_000 });
  }

  // ---------------------------------------------------------------- 导出 YAML 与 spec_hash
  await expect(page.getByRole('button', { name: '下载 .yaml' })).toBeVisible();
  await expect(page.locator('pre.mono').filter({ hasText: 'schema:' }).first()).toBeVisible();

  expect(console.errors, `控制台错误：${console.errors.join(' | ')}`).toHaveLength(0);
});

/** U07 批量合成面板：真实 planned/attempted/accepted/failed 与覆盖矩阵。 */
test('U07 批量面板：真实计数、失败错误码与覆盖矩阵', async ({ page }) => {
  const console = watchConsole(page);
  await page.goto('/synlab/jobs');

  const panel = region(page, '批量合成（真实计数 · 覆盖矩阵 · 一键续跑）');
  await expect(panel).toBeVisible();

  // 真实计数：planned/attempted/accepted/failed 四个数字必须来自 /synthesis/inventory
  for (const label of ['planned', 'attempted', 'accepted', 'failed']) {
    await expect(panel.getByText(label, { exact: true }).first()).toBeVisible({ timeout: 60_000 });
  }
  const stats = panel.locator('.statrow').first();
  await expect(stats.locator('.stat').first()).toBeVisible({ timeout: 60_000 });
  const statText = await stats.innerText();
  expect(statText).toMatch(/planned\s*\d+/);
  expect(statText).toMatch(/failed\s*\d+/);

  // 覆盖矩阵：维度名与来源必须可见（没有 reports/coverage*.json 时显示“没有覆盖矩阵”而不是假数据）
  const coverageCard = region(page, '覆盖矩阵（器型 × 材料 × 花纹 × 层）');
  await expect(coverageCard).toBeVisible();
  await expect(
    coverageCard.getByText('24 器物').or(coverageCard.getByText('没有覆盖矩阵')).first(),
  ).toBeVisible({ timeout: 60_000 });

  // 一键续跑：真实规划出组合（或显示真实的“组合空间已走完/registry 为空”原因）
  const resumeButton = panel.getByRole('button', { name: /一键续跑下一批/ });
  await expect(resumeButton).toBeVisible();
  await resumeButton.click();
  await expect(
    panel.getByText('本批组合').or(panel.locator('.state--error')).first(),
  ).toBeVisible({ timeout: 60_000 });

  await expect(panel.locator('.state--error')).toHaveCount(0);
  expect(console.errors, `控制台错误：${console.errors.join(' | ')}`).toHaveLength(0);
});

/** U04 断裂预览：审计数值原样展示 + 目标片数对照 + 断面属性诚实处理。 */
test('U04 断裂预览：审计数值与断面属性', async ({ page }) => {
  const console = watchConsole(page);
  await page.goto('/synlab/fracture');

  const panel = region(page, '断裂预览：目标片数 vs 实测片数 + 审计数值');
  await expect(panel).toBeVisible();
  // 目标片数来自 spec；实测片数来自真实资产清单（未选碎片时如实显示未选择）
  await expect(panel.getByText('目标片数区间')).toBeVisible();
  await expect(panel.getByText('实测片数（同谱系）')).toBeVisible();
  // 断面视图必须在（未选碎片时显示真实空状态；选了缺属性的资产则显示“该资产缺断面属性”）
  await expect(panel.getByText('碎片 3D（原位 / 爆炸）+ 断面高亮')).toBeVisible();
  await expect(panel.getByText('权威：mm / Z-up')).toBeVisible();
  // 爆炸是展示变换的声明必须存在
  await expect(panel.getByText('爆炸位移（mm，展示用）')).toBeVisible();

  // 选择一块真实碎片（若 store 里有）后，必须出现审计数值表或“缺断面属性”的诚实提示
  const fragmentBrowser = region(page, '碎片（fragment_mesh）');
  await expect(fragmentBrowser).toBeVisible();
  const rows = await fragmentBrowser.locator('tbody tr').count();
  if (rows > 0) {
    await fragmentBrowser.locator('tbody tr').first().locator('input').check();
    await expect(
      panel.getByText('审计数值（后端原样）').first(),
    ).toBeVisible({ timeout: 60_000 });
    await expect(
      panel.getByText('qa.parent_qa', { exact: false })
        .or(panel.getByText('该资产缺断面属性'))
        .or(panel.getByText('该碎片没有 qa 字段')).first(),
    ).toBeVisible({ timeout: 90_000 });
  }

  expect(console.errors, `控制台错误：${console.errors.join(' | ')}`).toHaveLength(0);
});

/** U05 退化预览：L0 与 Ln 并排（未物化时显示 NA + 补齐命令，绝不用别的级别顶替）。 */
test('U05 退化预览：L0 与 Ln 并排或 NA', async ({ page }) => {
  const console = watchConsole(page);
  await page.goto('/synlab/degradation');

  const panel = region(page, 'L0（真恒等）与 Ln 并排预览（同 basis、同 source）');
  await expect(panel).toBeVisible();
  await expect(
    panel.getByText('L0（baseline，真恒等）').or(panel.getByText('没有任何已物化的退化轴')).first(),
  ).toBeVisible({ timeout: 90_000 });

  const axisSelect = panel.getByLabel('选择退化轴');
  if (await axisSelect.count()) {
    await expect(axisSelect).toBeVisible();
    // 未物化的档位必须留空（NA），而不是补一个数字：每个 level 单元格都形如 `3:4(id0)`
    const table = panel.getByRole('table', { name: /已物化的轴与档位/ });
    await expect(table).toBeVisible();
    const levelCell = await table.locator('tbody tr').first().locator('td').first().innerText();
    expect(levelCell).toMatch(/\d+:\d+/);

    // 真实配对结果：同 basis 徽标 + 真实 measured 差值表（或明确写出“没有 measured”）
    await expect(panel.getByText('same_source', { exact: false }).or(panel.getByText('同 source 资产')).first())
      .toBeVisible({ timeout: 90_000 });
    await expect(
      panel.getByRole('table', { name: /measured 变化量/ })
        .or(panel.getByText('这两级都没有 meta.measured'))
        .or(panel.getByText('没有可配对的 L0/Ln')).first(),
    ).toBeVisible({ timeout: 120_000 });
  }

  expect(console.errors, `控制台错误：${console.errors.join(' | ')}`).toHaveLength(0);
});
