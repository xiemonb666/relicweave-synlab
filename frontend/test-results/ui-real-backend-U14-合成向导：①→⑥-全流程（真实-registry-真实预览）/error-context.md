# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: ui-real-backend.spec.ts >> U14 合成向导：①→⑥ 全流程（真实 registry + 真实预览）
- Location: e2e\ui-real-backend.spec.ts:142:1

# Error details

```
Error: expect(locator).toBeEnabled() failed

Locator:  getByRole('button', { name: '跑一次单谱系预览' })
Expected: enabled
Received: disabled
Timeout:  60000ms

Call log:
  - Expect "toBeEnabled" getByRole('button', { name: '跑一次单谱系预览' }) with timeout 60000ms
  - waiting for getByRole('button', { name: '跑一次单谱系预览' })
    120 × locator resolved to <button disabled type="button" aria-disabled="true" class="btn btn--primary" title="spec 未通过后端校验（1 个错误）">跑一次单谱系预览</button>
        - unexpected value "disabled"

```

```yaml
- button "跑一次单谱系预览" [disabled]
```

# Test source

```ts
  96  |   await expect(channelBrowser.locator('tbody tr').first()).toBeVisible();
  97  |   await channelBrowser.locator('tbody tr', { hasText: 'pattern_channels' }).first().locator('input').check();
  98  |   await expect(channels.locator('img').first()).toBeVisible({ timeout: 90_000 });
  99  |   await expect(channels.getByText('IHDR', { exact: false }).first()).toBeVisible();
  100 |   await expect(channels.locator('.state--error')).toHaveCount(0);
  101 |   await expect(region(page, '纯背景 / 轮廓负控视图（A05 / A32 相关）')).toBeVisible();
  102 | 
  103 |   await page.goto('/synlab/mothers/new');
  104 |   const tags = region(page, '真实面属性视图（surface_tag / 法向 / 到轴距离）');
  105 |   await expect(tags).toBeVisible();
  106 |   const meshBrowser = region(page, '权威母体 mesh（mother_mesh）');
  107 |   await expect(meshBrowser.locator('tbody tr').first()).toBeVisible();
  108 |   await meshBrowser.locator('tbody tr').first().locator('input').check();
  109 |   await expect(tags.getByText('surface_tag 合法值', { exact: false })).toBeVisible({ timeout: 90_000 });
  110 |   await expect(tags.locator('.state--error')).toHaveCount(0);
  111 | 
  112 |   await page.goto('/synlab/camera-profiles');
  113 |   const uPanel = region(page, 'U 位置 → 真实新场景帧');
  114 |   await expect(uPanel).toBeVisible();
  115 |   await expect(uPanel.getByText('旧帧').first()).toBeVisible();
  116 |   await expect(region(page, 'I09 数字降采样（与 U 移动分开）')).toBeVisible();
  117 | 
  118 |   // ---------------------------------------------------------------- 5) 12 路由巡检（不得出现错误卡片）
  119 |   for (const route of ROUTES) {
  120 |     await page.goto(route);
  121 |     await expect(page.locator('main h1').first()).toBeVisible();
  122 |     const errors = await page.locator('.state--error').count();
  123 |     expect(errors, `${route} 出现错误卡片`).toBe(0);
  124 |   }
  125 | 
  126 |   expect(console.errors, `控制台错误：${console.errors.join(' | ')}`).toHaveLength(0);
  127 | });
  128 | 
  129 | /**
  130 |  * U14 合成向导：六步真实走完（或停在真实阻塞点并显示错误码）。
  131 |  *
  132 |  * 覆盖点（对应用户要求）：
  133 |  * ① 选器型/材料/花纹族/层组合 —— 下拉/多选来自真实 /registry/*（这里断言真实 id 出现）；
  134 |  * ② 断裂参数 —— 可选后端 + registry 的真实 status；
  135 |  * ③ 退化 —— 6 阶段分组 + 档位 0–4 + “level 0 = 真恒等”提示；
  136 |  * ④ 观测 —— 路线 ideal/proxy/photo_mvs、视角数、长边 px、渲染后端 auto/software/blender；
  137 |  * ⑤ 预览 —— 真实跑一条谱系，显示各阶段真实耗时与产物，或显示后端 code + 复现命令；
  138 |  * ⑥ 入队批量 —— 批大小、续跑、实时进度（真实 SSE / jobs 轮询）。
  139 |  *
  140 |  * 断言只依赖真实后端：真实 registry id、真实校验结果、真实 job/资产计数。
  141 |  */
  142 | test('U14 合成向导：①→⑥ 全流程（真实 registry + 真实预览）', async ({ page }) => {
  143 |   const console = watchConsole(page);
  144 |   await page.goto('/synlab/synthesis');
  145 |   await expect(page.locator('main h1').first()).toContainText('合成向导');
  146 | 
  147 |   // ---------------------------------------------------------------- ① 组合选择
  148 |   const vesselPicker = page.getByRole('group', { name: /器型（vessel）/ });
  149 |   await expect(vesselPicker).toBeVisible();
  150 |   // registry 里真实注册的 V01 必须出现（前端不写死名单，出现即证明来自后端）
  151 |   await expect(vesselPicker.locator('input#vessel-V01')).toHaveCount(1, { timeout: 60_000 });
  152 |   await expect(page.getByRole('group', { name: /材料（material）/ }).locator('input#material-M01')).toHaveCount(1);
  153 |   await expect(page.getByRole('group', { name: /花纹族（pattern）/ }).locator('input#pattern-PAT01')).toHaveCount(1);
  154 | 
  155 |   // ---------------------------------------------------------------- ② 断裂后端 + 真实 status
  156 |   await page.getByRole('button', { name: /② 断裂参数/ }).click();
  157 |   const backendTable = page.getByRole('table', { name: /可选断裂后端/ });
  158 |   await expect(backendTable).toBeVisible();
  159 |   await expect(backendTable.locator('tbody tr').first()).toBeVisible({ timeout: 60_000 });
  160 |   const backendRows = await backendTable.locator('tbody tr').count();
  161 |   expect(backendRows).toBeGreaterThan(0);
  162 | 
  163 |   // ---------------------------------------------------------------- ③ 退化：6 阶段 + 档位 0–4 + level 0 提示
  164 |   await page.getByRole('button', { name: /③ 退化/ }).click();
  165 |   await expect(page.getByText('level 0 = 真恒等')).toBeVisible();
  166 |   const axisGroup = page.getByRole('group', { name: /PHYSICAL/ });
  167 |   await expect(axisGroup).toBeVisible();
  168 |   await expect(axisGroup.locator('tbody tr').first()).toBeVisible({ timeout: 60_000 });
  169 |   await axisGroup.locator('tbody tr').first().getByRole('button', { name: '加入' }).click();
  170 |   const levelSelect = axisGroup.locator('tbody tr').first().locator('select');
  171 |   await expect(levelSelect).toBeVisible();
  172 |   await expect(levelSelect.locator('option')).toHaveCount(5);
  173 |   await expect(levelSelect.locator('option', { hasText: '真恒等' })).toHaveCount(1);
  174 | 
  175 |   // ---------------------------------------------------------------- ④ 观测
  176 |   await page.getByRole('button', { name: /④ 观测/ }).click();
  177 |   const routeSelect = page.getByLabel('观测路线');
  178 |   await expect(routeSelect).toBeVisible();
  179 |   const routeOptions = await routeSelect.locator('option').allInnerTexts();
  180 |   expect(routeOptions.join(' ')).toContain('photo_mvs');
  181 |   await expect(page.getByLabel('每片视角数')).toBeVisible();
  182 |   await expect(page.getByLabel('长边像素')).toBeVisible();
  183 |   const rendererSelect = page.getByLabel('渲染后端');
  184 |   const rendererOptions = await rendererSelect.locator('option').allInnerTexts();
  185 |   expect(rendererOptions.join(' ')).toContain('software_rasterizer');
  186 |   expect(rendererOptions.join(' ')).toContain('blender');
  187 | 
  188 |   // ---------------------------------------------------------------- ⑤ 预览（真实跑一条谱系）
  189 |   await page.getByRole('button', { name: /⑤ 预览/ }).click();
  190 |   const previewHash = page.getByText('预览 spec_hash（后端 /specs/validate）');
  191 |   await expect(previewHash).toBeVisible();
  192 |   // 后端 /specs/validate 的真实 hash 必须出现（sha256: 前缀）
  193 |   await expect(page.locator('dd.mono', { hasText: /^sha256:/ }).first()).toBeVisible({ timeout: 60_000 });
  194 | 
  195 |   const runPreview = page.getByRole('button', { name: '跑一次单谱系预览' });
> 196 |   await expect(runPreview).toBeEnabled({ timeout: 60_000 });
      |                            ^ Error: expect(locator).toBeEnabled() failed
  197 |   await runPreview.click();
  198 | 
  199 |   // 真实结果：要么跑完（阶段耗时表出现），要么停在真实阻塞点并显示错误码 + 复现命令。
  200 |   const stagesTable = page.getByRole('table', { name: /每阶段真实耗时/ });
  201 |   const failureCard = page.locator('.state--error').filter({ hasText: /复现命令|预览未完成/ });
  202 |   await expect(stagesTable.or(failureCard).first()).toBeVisible({ timeout: 300_000 });
  203 | 
  204 |   if (await stagesTable.count()) {
  205 |     const stageRows = await stagesTable.locator('tbody tr').count();
  206 |     expect(stageRows).toBeGreaterThan(0);
  207 |     // 阶段耗时列必须是真实数字（不是“未提供”占位）
  208 |     const firstSeconds = await stagesTable.locator('tbody tr').first().locator('td').first().innerText();
  209 |     expect(firstSeconds.trim().length).toBeGreaterThan(0);
  210 |     await expect(page.getByText('产出资产', { exact: false }).first()).toBeVisible();
  211 |   } else {
  212 |     // 真实阻塞：必须能看到后端错误码与复现命令，而不是空状态
  213 |     await expect(failureCard.first()).toContainText(/CHAIN_|INTEGRATION_PENDING|ENV_CAPABILITY_MISSING|SCHEMA_INVALID/);
  214 |     await expect(failureCard.first().getByRole('button', { name: /复制/ }).first()).toBeVisible();
  215 |   }
  216 | 
  217 |   // ---------------------------------------------------------------- ⑥ 入队批量（真实规划 + 真实受理）
  218 |   await page.getByRole('button', { name: /⑥ 入队批量/ }).click();
  219 |   await expect(page.getByLabel('批大小')).toBeVisible();
  220 |   const resumeButton = page.getByRole('button', { name: '一键续跑下一批（resume）' });
  221 |   await expect(resumeButton).toBeVisible();
  222 |   await resumeButton.click();
  223 |   await expect(page.getByText('本批组合', { exact: false }).first()).toBeVisible({ timeout: 60_000 });
  224 | 
  225 |   const submitBatch = page.getByRole('button', { name: '提交这一批（POST /jobs）' });
  226 |   if (await submitBatch.isEnabled().catch(() => false)) {
  227 |     await submitBatch.click();
  228 |     // 受理（202）后必须出现真实 run_id 与权威 job state 计数
  229 |     await expect(page.getByText('run_id', { exact: false }).first()).toBeVisible({ timeout: 60_000 });
  230 |     await expect(page.locator('.statrow').first()).toBeVisible({ timeout: 60_000 });
  231 |   }
  232 | 
  233 |   // ---------------------------------------------------------------- 导出 YAML 与 spec_hash
  234 |   await expect(page.getByRole('button', { name: '下载 .yaml' })).toBeVisible();
  235 |   await expect(page.locator('pre.mono').filter({ hasText: 'schema:' }).first()).toBeVisible();
  236 | 
  237 |   expect(console.errors, `控制台错误：${console.errors.join(' | ')}`).toHaveLength(0);
  238 | });
  239 | 
  240 | /** U07 批量合成面板：真实 planned/attempted/accepted/failed 与覆盖矩阵。 */
  241 | test('U07 批量面板：真实计数、失败错误码与覆盖矩阵', async ({ page }) => {
  242 |   const console = watchConsole(page);
  243 |   await page.goto('/synlab/jobs');
  244 | 
  245 |   const panel = region(page, '批量合成（真实计数 · 覆盖矩阵 · 一键续跑）');
  246 |   await expect(panel).toBeVisible();
  247 | 
  248 |   // 真实计数：planned/attempted/accepted/failed 四个数字必须来自 /synthesis/inventory
  249 |   for (const label of ['planned', 'attempted', 'accepted', 'failed']) {
  250 |     await expect(panel.getByText(label, { exact: true }).first()).toBeVisible({ timeout: 60_000 });
  251 |   }
  252 |   const stats = panel.locator('.statrow').first();
  253 |   await expect(stats.locator('.stat').first()).toBeVisible({ timeout: 60_000 });
  254 |   const statText = await stats.innerText();
  255 |   expect(statText).toMatch(/planned\s*\d+/);
  256 |   expect(statText).toMatch(/failed\s*\d+/);
  257 | 
  258 |   // 覆盖矩阵：维度名与来源必须可见（没有 reports/coverage*.json 时显示“没有覆盖矩阵”而不是假数据）
  259 |   const coverageCard = region(page, '覆盖矩阵（器型 × 材料 × 花纹 × 层）');
  260 |   await expect(coverageCard).toBeVisible();
  261 |   await expect(
  262 |     coverageCard.getByText('24 器物').or(coverageCard.getByText('没有覆盖矩阵')).first(),
  263 |   ).toBeVisible({ timeout: 60_000 });
  264 | 
  265 |   // 一键续跑：真实规划出组合（或显示真实的“组合空间已走完/registry 为空”原因）
  266 |   await expect(panel.getByRole('button', { name: '一键续跑下一批' })).toBeVisible();
  267 |   await panel.getByRole('button', { name: '一键续跑下一批' }).click();
  268 |   await expect(
  269 |     panel.getByText('本批组合').or(panel.locator('.state--error')).first(),
  270 |   ).toBeVisible({ timeout: 60_000 });
  271 | 
  272 |   await expect(panel.locator('.state--error')).toHaveCount(0);
  273 |   expect(console.errors, `控制台错误：${console.errors.join(' | ')}`).toHaveLength(0);
  274 | });
  275 | 
  276 | /** U04 断裂预览：审计数值原样展示 + 目标片数对照 + 断面属性诚实处理。 */
  277 | test('U04 断裂预览：审计数值与断面属性', async ({ page }) => {
  278 |   const console = watchConsole(page);
  279 |   await page.goto('/synlab/fracture');
  280 | 
  281 |   const panel = region(page, '断裂预览：目标片数 vs 实测片数 + 审计数值');
  282 |   await expect(panel).toBeVisible();
  283 |   // 目标片数来自 spec；实测片数来自真实资产清单（未选碎片时如实显示未选择）
  284 |   await expect(panel.getByText('目标片数区间')).toBeVisible();
  285 |   await expect(panel.getByText('实测片数（同谱系）')).toBeVisible();
  286 |   // 断面视图必须在（未选碎片时显示真实空状态；选了缺属性的资产则显示“该资产缺断面属性”）
  287 |   await expect(panel.getByText('碎片 3D（原位 / 爆炸）+ 断面高亮')).toBeVisible();
  288 |   await expect(panel.getByText('权威：mm / Z-up')).toBeVisible();
  289 |   // 爆炸是展示变换的声明必须存在
  290 |   await expect(panel.getByText('爆炸位移（mm，展示用）')).toBeVisible();
  291 | 
  292 |   // 选择一块真实碎片（若 store 里有）后，必须出现审计数值表或“缺断面属性”的诚实提示
  293 |   const fragmentBrowser = region(page, '碎片（fragment_mesh）');
  294 |   await expect(fragmentBrowser).toBeVisible();
  295 |   const rows = await fragmentBrowser.locator('tbody tr').count();
  296 |   if (rows > 0) {
```