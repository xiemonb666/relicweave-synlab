# docs/a12/api_ui.md — A12 合成实验室前端（U01–U12）

本文记录 `frontend/` 的实现范围、每个页面调用的**真实** API、构建命令与退出码、类型检查结果，
以及未实现/降级项和“后端能力缺失时页面如何显示阻塞”。
所有数据来自 `synlab.api.app:create_app`（前缀 `/api/synlab`），**没有 mock 数据**。

- 计划依据：第 20 节（页面与组件）、第 25.2 节（端到端验收脚本）、第 20.14 节（三维与前端细节）。
- 写入范围：`frontend/**`、`tests/a12/api_ui/**`、`docs/a12/api_ui.md`；未修改 `synlab/**`。

---

## 1. 工程与命令

| 项 | 值 |
|---|---|
| 目录 | `frontend/`（Vite 5.4.21 + React 18.3.1 + TypeScript 5.9.3） |
| 依赖（已安装） | `react`、`react-dom`、`react-router-dom` 6.30、`three` 0.180（含 `examples/jsm` GLTFLoader/OrbitControls）、`@types/three`、`echarts` 5.6（**未使用**，见 §6） |
| 包管理器 | pnpm 11.7.0（`node node_modules/.../pnpm.mjs install`，`node-linker=hoisted`）；`npm install` 同样可用 |
| Node | v24.14.1 |

### 1.1 真实执行的命令与退出码

```
$ node node_modules/typescript/bin/tsc --noEmit
（无输出）                                              exit 0

$ node node_modules/vite/bin/vite.js build
vite v5.4.21 building for production...
✓ 97 modules transformed.
dist/index.html                     0.49 kB │ gzip:   0.43 kB
dist/assets/index-DW9rroQe.css     22.73 kB │ gzip:   4.89 kB
dist/assets/index-BmATc4jc.js   1,127.99 kB │ gzip: 327.78 kB
✓ built in 2.29s                                       exit 0

$ python tests/a12/api_ui/check_frontend.py
...
OVERALL: PASS                                          exit 0

$ python tests/a12/api_ui/run_e2e.py --skip-build        # Playwright 真实端到端
$ corepack pnpm@11.7.0 exec playwright test  (cwd=frontend)
  1 passed (11.2s)
playwright exit=0                                      exit 0
```

一键复现（同时校验产物、12 路由、12 组件、8 个新增组件、3 个新增 lib、e2e 文件、fixture 不泄漏）：

```
$ python tests/a12/api_ui/check_frontend.py
...
OVERALL: PASS                                          exit 0
```

`check_frontend.py` 的结果（真实输出节选）：

```json
[{"cmd": "tsc --noEmit", "exit": 0},
 {"cmd": "vite build", "exit": 0},
 {"dist_assets": ["index-BmATc4jc.js", "index-DW9rroQe.css"]},
 {"missing_routes": []},
 {"missing_components": []},
 {"missing_new_components": []},
 {"missing_new_libs": []},
 {"missing_e2e_files": []},
 {"fixture_data_in_bundle": [], "fixture_label_present": true},
 {"missing_in_app": []}]
```

### 1.2 运行方式

```powershell
# 1) 启动真实后端（create_app 是工厂函数，需要显式 store_root）
python tests/a12/api_ui/_serve.py --store-root data\a12 --port 8077 --role researcher

# 2) 开发服务器（/api 反代到 VITE_SYNLAB_PROXY_TARGET，默认 http://127.0.0.1:8077）
cd frontend; npm run dev          # http://localhost:5173

# 3) 或预览构建产物（同一套反代配置）
cd frontend; npm run preview      # http://localhost:4173
```

可用环境变量（均为可选）：

| 变量 | 作用 |
|---|---|
| `VITE_SYNLAB_API_BASE` | 直连后端基址（留空=同源，走 vite 反代）；设置后客户端拼 `/api/synlab` |
| `VITE_SYNLAB_PROXY_TARGET` | dev/preview 的 `/api` 反代目标 |
| `VITE_SYNLAB_ROLE` / `VITE_SYNLAB_SESSION` / `VITE_SYNLAB_WORKSPACE` | 覆盖 `X-SynLab-*` 请求头；默认不发送（用服务端启动的角色） |
| `VITE_SYNLAB_FIXTURES=1` | **仅测试**：启用本地 fixture 兜底，并在 UI 顶部与数据卡片上标注 “FIXTURE 模式” |

---

## 2. 页面清单与真实 API

统一入口：`http://<host>:<port>/synlab`。全部 12 条路由在 `src/App.tsx` 注册，导航在 `src/components/Layout.tsx`。

| # | 路由 | 组件文件 | 主要真实 API |
|---|---|---|---|
| U01 | `/synlab` | `pages/Overview.tsx` | `GET /health`、`GET /capabilities?doctor=light`、`GET /stages`、`GET /jobs`、`GET /assets`、`GET /releases`、`GET /audits`、`GET /registry/all` |
| U02 | `/synlab/mothers/new` | `pages/MotherEditor.tsx` | `GET /registry/{vessel,material,layer_combo}`、`POST /specs/validate`、`POST /budgets`、`POST /previews`(stage=mother)、`POST /jobs`(stage=mother)、`GET /assets`(mother_mesh / display_lod_glb)、`GET /jobs?run_id=` |
| U03 | `/synlab/patterns` | `pages/Patterns.tsx` | `GET /registry/pattern`（16 族 + `param_schema`）、`POST /specs/validate`、`POST /budgets`、`POST /previews`(stage=pattern)、`POST /jobs`(stage=pattern)、`GET /assets`(pattern_recipe/channels/audit、display_lod_glb) |
| U04 | `/synlab/fracture` | `pages/Fracture.tsx` | `GET /registry/fracture_backend`、`POST /specs/validate`、`POST /budgets`、`POST /previews`(stage=fracture)、`POST /jobs`(stage=fracture)、`GET /assets`(mother_mesh/fragment_mesh/physical_result/cutter_mesh)、`GET /assets/{id}`、`GET /research/assets/{id}/truth` |
| U05 | `/synlab/degradation` | `pages/Degradation.tsx` | `GET /registry/axis`、`POST /specs/validate`(kind=recipe)、`POST /budgets`、`GET /assets`(display_lod_glb/obs_view/obs_result/clean_truth/physical_truth)、`GET /assets/{id}`、`GET /camera-profiles` |
| U06 | `/synlab/camera-profiles` | `pages/CameraProfiles.tsx` + `components/CameraFrustumView.tsx` | `GET /camera-profiles`、`POST /camera-profiles`、`GET /camera-profiles/{id}`、`GET /capabilities`；补齐后另有 `POST /specs/validate`、`POST /previews`(stage=observe/degrade)、`GET /jobs/{id}`、`GET /assets?role=obs_view`、`GET /assets/{id}/files/obs_view?key=arrays` |
| U07 | `/synlab/jobs` | `pages/Jobs.tsx` | `GET /stages`、`POST /specs/validate`、`POST /budgets`、`POST /jobs`、`GET /jobs`（cursor/state/stage/run_id/with_total）、`GET /jobs/{id}`、`POST /jobs/{id}/pause|resume|cancel|retry`、`GET /runs/{run_id}/events`（SSE） |
| U08 | `/synlab/releases` | `pages/Releases.tsx` | `POST /audits`、`GET /audits`、`GET /audits/{id}`、`POST /releases`、`GET /releases`、`GET /releases/{id}`、`POST /exports`、`GET /exports/{id}`、`GET /assets` |
| U09 | `/synlab/training` | `pages/Training.tsx` | `GET /releases`、`GET /pools`、`POST /pools`、`POST /specs/validate`(kind=train)、`POST /budgets`、`POST /training/runs`、`GET /training/runs`、`GET /training/runs/{id}`、`POST /training/runs/{id}/resume`、`GET /jobs` |
| U10 | `/synlab/diagnostics` | `pages/Diagnostics.tsx` | `GET /pools`、`GET /training/runs`、`POST /specs/validate`(kind=diagnose)、`POST /budgets`、`POST /diagnostics/runs`、`GET /diagnostics/runs`、`GET /diagnostics/runs/{id}`、`GET /assets` |
| U11 | `/synlab/episodes` | `pages/Episodes.tsx` | `POST /episodes/{id}/reset`、`POST /episodes/{id}/step`、`GET /episodes/{id}`、`GET /pools`、`GET /camera-profiles`、`GET /assets` |
| U12 | `/synlab/quality` | `pages/Quality.tsx` | `GET /capabilities?doctor=full`、`GET /jobs?state=FAILED|QUARANTINED|RETRYABLE`、`GET /assets?qa_status=QA_FAIL`、`GET /audits`、`GET /releases` |

### 2.1 统一组件（计划 20.1 的 12 个，全部真实实现并被复用）

| 组件 | 文件 | 数据来源 / 职责 |
|---|---|---|
| SchemaForm | `components/SchemaForm.tsx` | 两种来源：`/registry/{kind}` 的 `param_schema`（Pydantic `model_json_schema()`）由 `schemaToFields` 转换；或页面显式 `FieldSpec[]`。服务端 `errors[].loc` 精确落到字段；未展开的构造列进 `skipped` 并引导到高级 JSON 区 |
| AssetBrowser | `components/AssetBrowser.tsx` | `GET /assets`，keyset 分页（`cursor`/`has_more`/`next_cursor`/`with_total`）、角色与 QA 过滤、详情抽屉；空状态直接用后端 `empty_reason` |
| SceneViewport | `components/SceneViewport.tsx` | three.js + GLTFLoader 加载 `display_lod_glb` 的真实 GLB；线框、剖切面、重置视角、mm 标尺、`display_to_authority` 读数、100 mm 立方体自检、响应头 sha256 与浏览器重算 sha256 对照 |
| CompareViewport | `components/CompareViewport.tsx` | 单 renderer + 单相机 + 两个 scene：`wipe`（scissor 分界）/`side`（各占半屏、aspect 重算）/`overlay`（透明度可调）；实测读数表（权威尺寸、三角面、GLB 大小、QA/坐标契约） |
| MeasuredQualityTable | `components/MeasuredQualityTable.tsx` | 只渲染后端真实字段；缺失显示“未提供”，从不写 0；可标 `n`、`flag`、来源路径；`minSamples` 未达要求时提示“不能声称已证明” |
| CoverageMatrix | `components/CoverageMatrix.tsx` | 渲染 `coverage_matrix()` 的结构（`required/covered/complete/covered_ids/missing_ids/evidence`） |
| JobTimeline | `components/JobTimeline.tsx` | SSE 事件时间线：`seq`/`revision`/`type`/`state`/`progress`/`message`；无 progress 的事件明确写“未计数” |
| ResourceBudgetCard | `components/ResourceBudgetCard.tsx` | `POST /budgets` 的 rss/vram/临时磁盘/磁盘水位/GPU 环境/`budget_ref`，以及后端 `assumptions` 原文 |
| RunSelector | `components/RunSelector.tsx` | 由 `GET /jobs` 的真实 job 行按 `run_id` 归并（`lib/runs.ts`），无 job 即无可选项 |
| MetricChart (+MetricHeatmap) | `components/MetricChart.tsx` | 自绘 SVG；缺数据断线不插值；tooltip 显示 n/单位/flag/ref；热图用真实 `queries` 组成 N×Q 矩阵 |
| FailureDrawer | `components/FailureDrawer.tsx` | `GET /jobs/{id}` 的 `error`/`spec`：问题代码、evidence、最小复现（含等价 CLI）、下一动作、重试是否允许（按 `error.retryable` 禁用按钮并给出原因） |
| ProvenanceDrawer | `components/ProvenanceDrawer.tsx` | 资产：`GET /assets/{id}`（逐文件 sha256/完整性/ancestry/`display_transform`）+ 按需 `GET /research/assets/{id}/truth`（403 原样显示）；release：`GET /releases/{id}`；job：`GET /jobs/{id}` |

其他复用件：`components/SpecStudio.tsx`（草稿→校验→预算→预览/提交 的通用工作台）、
`components/RegistryParamPanel.tsx`（registry `param_schema` → 表单）、`components/states.tsx`（状态/抽屉/按钮/键值表原语）、
`components/CameraFrustumView.tsx`（相机视锥/光轴导轨/景深，全部由 catalogue 真实参数计算）。

---

## 3. 单位与坐标契约（计划 20.14.1）

* 权威几何：**毫米 / Z-up**；GLB 展示几何：**米 / Y-up**。
* `src/lib/display.ts` 与后端 `synlab/api/display.py` **逐元素一致**：
  `T_display_authority = [[0.001,0,0,0],[0,0,0.001,0],[0,-0.001,0,0],[0,0,0,1]]`，逆矩阵同后端；
  仅暴露 `authorityToDisplay` / `displayToAuthority` 两个入口，避免 1000 倍误用。
* 100 mm 解析立方体自检在视口面板上直接显示，实测输出：
  `100 mm 立方体：展示 0.1000 × 0.1000 × 0.1000 m，反算 100.0000 × 100.0000 × 100.0000 mm，误差 0.00e+0 mm`。
* mm 标尺：网格总宽取 1/2/5 序列的整毫米值，每格 = 总宽/10；面板写明“每格 X mm（展示 0.0X m/格）”。
* 视口对真实派生 GLB 的实测（100 mm 立方体，`display_lod_glb`，`unit=m`/`frame=Y_up_m`）：
  权威尺寸 100.000 × 100.000 × 100.000 mm、展示 0.10000 m³、12 三角面 / 1 mesh、GLB 976 B、
  服务端 `X-SynLab-File-Sha256` 与浏览器 `crypto.subtle` 重算结果一致（`sha256:c147322c…`）。

---

## 4. 状态完备性（计划 20.15）

| 状态 | 呈现方式 |
|---|---|
| loading | `LoadingState`（含 API 名称），后台刷新时保留旧数据并显示 `refreshing` |
| 空 | `EmptyState`，优先显示后端 `empty_reason`（如 “no asset in this workspace matches the filter…”） |
| 排队/运行 | job `state` 徽标（PENDING/RUNNING/OUTPUT_READY/QA_PASS/COMMITTED/RETRYABLE/QUARANTINED/FAILED/CANCELLED/BLOCKED） |
| 失败 | `ErrorState`/`FailureDrawer`：`code`、HTTP 状态、`stage`、`message`、`request_id`、`retryable`、可展开 `details` |
| 不支持/阻塞 | `BlockedState`：显示具体能力状态码（如 `DEPENDENCY_CAPABILITY_MISSING`）、缺失的 façade 入口函数、阶段名 |
| 断线 | 顶栏 `后端不可用`；错误码 `BACKEND_UNREACHABLE` + 启动后端的命令；SSE 断线显示 `断线重连中（带 Last-Event-ID）` 并可退化为 `GET /jobs?run_id=` 轮询 |
| 按钮禁用 | 一律带 `disabledReason`，例如“只有 PAUSED 的 run 能恢复（当前 PENDING）”“后端 error.retryable=无 error” |
| 单位 | 所有数值带单位（mm / m / px / GB / s）；`mm` 与 `m` 在视口与表格中同时出现时标明各自坐标系 |
| 键盘 | 侧栏/按钮/抽屉/tab 均为原生可聚焦元素；抽屉 `Esc` 关闭；图表数据点可 Tab 聚焦 + Enter 选中；`跳到主内容` skip link |
| 中文文案 | 全部界面文案为中文；枚举值保留后端原文（如 `PENDING`、`DEPENDENCY_CAPABILITY_MISSING`）并配中文标签 |
| 颜色之外 | 状态一律“图标/文字 + 颜色”，徽标内含中文标签 |

---

## 5. 后端不可用时的行为（无 mock）

* 全部请求都打到真实 `/api/synlab`；后端未启动时：
  * 顶栏：`工作区 未知（后端不可达）`、`角色 未连接`、`任务列表不可用`、`后端不可用`；
  * 每个卡片：`后端不可用（代理无法连接） BACKEND_UNREACHABLE …`，含
    `请确认后端已启动：python tests/a12/api_ui/_serve.py --store-root data/a12 --port 8077` 与“重试”按钮。
* 判定规则（`src/api/client.ts`）：FastAPI 的任何失败都带 `{ok:false,error:{…}}` 信封，因此
  **“5xx 且无信封”= 没连上后端** → 统一报 `BACKEND_UNREACHABLE`；带信封则原样透出真实 `code`（例如
  `ENV_CAPABILITY_MISSING`、`DEPENDENCY_CAPABILITY_MISSING`、`NOT_FOUND`、`SCHEMA_INVALID`、`STOP_QA`）。
* `VITE_SYNLAB_FIXTURES` 默认未设置：`check_frontend.py` 断言默认 bundle 里**不含** fixture 数据
  （`store_fixture`/`fixtureJobs`/`fixtureCapabilities` 均不出现）。仅当显式 `=1` 时 fixture 才会被
  动态 import 进产物，且 UI 顶部会出现红色 “FIXTURE 模式” 横幅。

---

## 6. 未实现 / 降级项（如实列出）

> 本节在「补齐降级项」之后重写：原先标注“未实现”的 5 项里，4 项已用**真实后端数据**实现，
> 1 项（负控视图）改为**数据驱动的 NOT_RUN**；仍未实现的部分保留并写明原因。
> 逐项证据（命令、退出码、数据端点/资产 ID、无数据时的页面表现）见 §6.1。

| 项 | 状态 | 原因与替代 |
|---|---|---|
| U06 相机页「U 位置变化 → 真实新场景帧」 | **已实现（含显式阻塞）** | 滑块只改草稿并标“未计算”；松手发出真实请求序列 `POST /specs/validate` → `POST /previews`(stage=observe，带 `u_position_mm`) → `POST /previews`(stage=degrade，带 `camera_profile_ref`) → `GET /jobs/{id}`。后端**没有任何路由接受 `u_position_mm`**：stage=observe 被 422 `BAD_REQUEST`（`previews.stage`）拒绝，spec 里带 U 被 422 `SCHEMA_INVALID`（`loc=["observation","u_position_mm"]`, `type=extra_forbidden`）拒绝 —— 两条真实信封原样显示。不含 U 的 degrade 预览真实受理（202），有 outputs 时按真实资产 ID 取回新帧与旧帧并排；无 worker 时停在 PENDING 并给出运行命令。**超出行程不前端拦截** |
| U06 相机「I09 与 U 移动分开」 | **已实现（真实核对）** | `I09ExtrinsicsCheck`：取基准 obs_view（无 axis_id）与 `axis_id=I09` 的 obs_view，逐帧比较真实 `payload.frames.N.T_WC` 与 `K` 是否逐元素一致，并显示 `pixel_transform` 与两侧真实 rgb 尺寸。实测：I09（`antialiased_downsample`）**保持相机外参**（T_WC/K 一致、尺寸 320×240 → 180×240） |
| U05 误差热图 / 点云叠加 | **已实现（前端由真实数组计算）** | 浏览器内解码 `arrays` npz：点云模式用 `obs_fused_geometry` 的 `payload.points` 与 `payload.reference_points` 逐点欧氏距离；深度模式用两个 `obs_view` 的 `payload.frames.N.depth_z` 逐像素绝对差。图上明确标注“前端由真实 depth/points 计算，非后端误差场”，并把后端 `meta.measured` 原样并排 |
| U03 展开 chart / albedo-roughness-height 通道 | **已实现** | 选中 `pattern_channels` 资产后，按真实成员键 `albedo_png`/`roughness_png`/`height_png` 取字节 → 校验 PNG 签名与 IHDR → 浏览器解码显示；编码说明取后端 `meta.encoding_legend`/`legend` 原文，chart 参数取 `meta.chart`。无图像成员时显示“尚未生成，运行 `tools/build_demo_assets.py`” |
| U02 内外壁 / 厚度热图 | **内外壁已实现；厚度：无数据（不编造）** | `SurfaceTagView` 用权威 `mother_mesh` 的 `mesh.face__surface_tag` 逐面着色（名称取 `meta.surface_tag_names`），并计算面心到轴距离 r、面心 z、几何法向。该资产的数组里**没有厚度场**，页面列出真实键名并写明“不推算厚度” |
| 纯背景 / 轮廓负控视图（§25.1 A05/A32） | **NOT_RUN（数据驱动）** | `NegativeControlPanel` 真实扫描本工作区可见资产（`GET /assets?limit=200&with_total=true`），谓词 `silhouette / silhouette_only / background_only / bg_only / mask_only / no_object / negative_control`；命中就显示真实 PNG 或 meta，未命中就显示 NOT_RUN 并附扫描数量、role 分布与解除条件。实测命中 0 |
| U06 近/中/远同片帧、碰撞包络、灯态 | 未实现 | 无对应路由 / catalogue 未提供灯态取值；页面不编造 |
| L1/L2 展示 LOD（三维简化） | 取决于环境 | 本机 `fast_simplification` 未安装，派生的 GLB 只有 L0；资产 `meta.lod_notes` 会如实显示 |
| 训练/诊断曲线 | 结构自适应 | `result.curves` 结构由实现模块决定；识别不了的原样列在“结构未识别”里 |
| 诊断“材料/器型最差层”“增益/成本图” | 未实现 | 依赖后端 result 提供分层统计与成本字段；字段出现即原样渲染 |
| Playwright 端到端 | **已实现** | `frontend/playwright.config.ts` + `frontend/e2e/ui-real-backend.spec.ts`（真实后端 + `vite preview`，1 条用例，`1 passed`）。运行入口 `python tests/a12/api_ui/run_e2e.py`；`check_frontend.py` 仍作为不依赖浏览器的替代证据保留 |
| 服务端分页“上一页” | 受限 | keyset cursor 无法反向解码：U07 只提供“回到第一页”；AssetBrowser 用本地游标栈实现上一页 |
| U 作为“已应用参数”写回后端 | **阻塞（后端）** | 生成 spec 是 `extra="forbid"`，`/previews` 的 stage 白名单没有 `observe`，`/camera-profiles` 的 `payload` 又被静默丢弃（缺陷 B2）——因此新帧永远不会带新 U。页面把两条真实 422 与“未变”读数并排显示 |
| ECharts 图表 | **未使用** | 计划允许“轻量 SVG/自绘”。`echarts` 已在依赖里但未 import：自绘 SVG/canvas 能保证“无点不画线、缺失断线/透明”，且不掩盖异常。可用 `MetricChart`/`MetricHeatmap` 的 props 换成 echarts 而不改数据层 |

### 6.1 补齐项的逐项证据（命令 / 退出码 / 数据来源 / 无数据表现）

| # | 项 | 命令与退出码 | 真实数据来源 | 无数据时页面显示 |
|---|---|---|---|---|
| 1 | U06 U→真实新场景帧 | `tsc --noEmit` exit 0 · `vite build` exit 0 · `check_frontend.py` exit 0 · `playwright test` exit 0 | `POST /specs/validate`、`POST /previews`(stage=observe/degrade)、`GET /jobs/{job_id}`、`GET /assets?role=obs_view`、`GET /assets/{id}/files/obs_view?key=arrays`；旧帧资产 `asset_fd5eb693a4a06c7477cd`；catalogue `CAM_GLOBAL_V3/CAM_MID_V3/CAM_LOCAL_V3` | 无 obs_view arrays → “没有可用于对照的旧帧”空状态；已受理但无 outputs → `BlockedState`（真实 state + worker 运行命令）；新帧列一律“未计算” |
| 2 | U05 误差热图 + 点云叠加 | 同上（e2e 断言 canvas 已绘制、总点数 > 1000） | `GET /assets?role=obs_view,obs_fused_geometry`；`GET /assets/{id}/files/{role}?key=arrays`；实测资产 `asset_add7c0c0541ebda90610`（G05·L2·qem_decimation，`payload.points`/`reference_points` 各 73120 点）、`asset_3367387de335d6c3dbb8`；深度对 `asset_fd5eb693a4a06c7477cd` × `asset_307b14aec1e5c2305645`（I01·L1） | 无 `obs_fused_geometry` → 空状态“没有数据，不是 0 差异”；含 arrays 的 obs_view < 2 → `BlockedState INSUFFICIENT_ASSETS`；两侧分辨率不同 → `BlockedState SHAPE_MISMATCH`（不做缩放对齐） |
| 3 | U03 三通道 | 同上（e2e 断言 `<img>` 与 IHDR 读数出现） | `pattern_channels` 资产（如 `asset_3753a7a16bb7efc0cbc0`，512×256、bitDepth 8、colorType 2）的 `albedo_png`/`roughness_png`/`height_png` | 无图像成员 → 空状态列出真实 `files` 键并提示运行 `python tools/build_demo_assets.py` |
| 4 | U02 面标签视图 | 同上（e2e 断言 surface_tag 表出现） | `mother_mesh` 资产（如 `asset_167bef6a43a93438ec26`，3505 顶点 / 7008 面）的 `mesh.vertices`/`mesh.faces`/`mesh.face__surface_tag`；标签名取 `meta.surface_tag_names` | 无 mother_mesh → 空状态；缺逐面数组 → 列出真实键名；厚度字段不存在 → 明确写“没有厚度场，不推算” |
| 5 | 负控视图 | 同上 | `GET /assets?limit=200&with_total=true`（真实扫描 71 个资产：obs_view 58、obs_fused_geometry 13 等） | 命中 0 → `BlockedState NOT_RUN` + 扫描谓词 + role 分布 + 解除条件 |
| 6 | Playwright e2e | `python tests/a12/api_ui/run_e2e.py --skip-build` → `playwright exit=0`；`1 passed` | 真实后端（`_serve.py`，store=`data/a12_demo/store`）+ `vite preview` 构建产物 | 后端/浏览器缺失时：`run_e2e.py` 打印具体缺失项并 `exit 2`；用例失败会给出 Playwright 报告 |
| 7 | 既有 12 路由不回退 | `check_frontend.py` 断言 12 路由 + 12 组件 + 关键契约串全在，`OVERALL: PASS` | 构建产物 `frontend/dist` | — |

**新增基础设施**（真实解码，无第三方图像/npz 依赖）：

* `src/lib/npz.ts` —— ZIP 中央目录 + NPY 头解析；`stored`/`deflate` 两种成员；大端与 Fortran 序**显式报错**；数据段按元素大小对齐（不对齐时先复制，绝不按错误偏移读数）。
* `src/lib/assetData.ts` —— `GET /assets/{id}/files/{role}?key=...` 的字节流，按 `assetId|role|key` 在同一会话内缓存；PNG 签名与 IHDR 尺寸读取。
* `src/lib/analysis.ts` —— 统计量（含 p50/p95/p99 与 `n`）、逐点距离、逐像素绝对差、viridis 色标、热图光栅化、三维投影、K/T_WC 读取与逐元素比较。

### 6.2 本次验证中确认的两条后端行为（原样引用真实响应）

```
$ curl -s -X POST .../previews -d '{"stage":"observe","spec":{...,"observation":{"u_position_mm":-70,...}}}'
{"ok":false,"error":{"code":"BAD_REQUEST","status":422,"stage":"previews.stage",
 "message":"preview stage must be one of ['mother', 'pattern', 'fracture', 'degrade', 'display_lod'], got 'observe'",
 "retryable":false,"details":{},"evidence_refs":[],"request_id":"80ab860a99e34db7"}}      HTTP 422

$ curl -s -X POST .../previews -d '{"stage":"degrade","spec":{"schema":"synlab.v3","observation":{"u_position_mm":-70}}}'
{"ok":false,"error":{"code":"SCHEMA_INVALID","status":422,"stage":"jobs.validate",
 "message":"spec rejected: 1 error(s)",
 "details":{"validation":{"errors":[{"loc":["observation","u_position_mm"],
   "type":"extra_forbidden","msg":"Extra inputs are not permitted","input":-70}], ...}},
 "request_id":"c3a5e7c4841e43ee"}}                                                        HTTP 422
```

> 副作用声明：上面第二条与“不含 U 的 degrade 预览”验收会在**演示数据根** `data/a12_demo/store`
> 里留下真实 job/run 行（`POST /previews` 本身就是写操作）。这是后端真实行为，不是前端伪造；
> 验收结束后演示库里会多出 1 个 `degrade` PENDING job。

---

## 7. 后端能力缺失时的页面表现

| 场景 | 页面表现 |
|---|---|
| 能力模块缺失（`DEPENDENCY_CAPABILITY_MISSING`） | U04 显示 “断裂阶段被后端能力阻塞”，列出 `fracture（synlab.fracture）= DEPENDENCY_CAPABILITY_MISSING：missing façade functions: ['fracture_event', 'make_closed_cutter', 'audit_fracture']`，并说明 `POST /previews|jobs` 会 503 且不创建半成品 run |
| 环境能力缺失（`ENV_CAPABILITY_MISSING`） | 顶栏 GPU 徽标显示 `ENV_CAPABILITY_MISSING`；`ResourceBudgetCard` 显示 `cuda_available=false · status=ENV_CAPABILITY_MISSING · torch 2.5.1+cpu`；`/budgets` 对需要 GPU 的阶段附 `gpu_blocked` |
| registry 为空 | U02/U04/U05 显示 `REGISTRY_EMPTY` 阻塞卡：写明“后端返回 0 条，前端不复制范围表”，并给出手填 + 服务端校验的降级路径与 `registry_fingerprint` |
| 需要真值但角色不允许 | 溯源抽屉“研究真值入口”按需请求，`403 ROLE_FORBIDDEN` / `403 TRUTH_ROUTE_UNMOUNTED` 原样展示 |
| 审计未运行 | U08 对 `status=NOT_RUN/QUEUED/RUNNING` 的审计不推断任何 gate，显示“这份审计还没有结果” |
| 发布 gate 未通过 | 冻结按钮禁用并给出原因（`audit_id` 为空 / `asset_ids` 为空）；后端 `409 STOP_QA` 原样显示 |
| 未运行的训练/诊断 | `not_run_reason` 直接被 `MetricChart`/`MeasuredQualityTable` 当作空状态文案 |

---

## 8. 与计划/后端的实际差异（按真实路由实现，逐条记录）

以下差异均已按**实际后端行为**实现，并保留在 UI 文案里：

### 8.1 路由差异（计划 21.1 表格 ↔ 实际）

| 计划条目 | 实际情况 |
|---|---|
| 表格未列 `GET /audits`、`GET /releases`、`GET /exports/{id}`、`GET /pools`、`GET /training/runs`、`GET /diagnostics/runs`、`GET /stages`、`GET /capabilities/{...}` | 后端**有**列表路由，UI 使用它们（分页/limit 由后端 `DEFAULT_LIMIT=50`、`MAX_LIMIT=200` 约束） |
| 计划 `GET /registry/{kind}` | 实际存在；`kind` 合法集合为 `vessel/material/layer_combo/pattern/fracture_backend/axis/operator_stage` 加 `all` |
| 计划只列 `GET/POST /camera-profiles` | 实际还有 `GET /camera-profiles/{profile_id}`（版本历史），UI 已用 |
| 计划只列 `POST /episodes/{id}/reset|step` | 实际还有 `GET /episodes/{id}`，UI 已用 |
| 计划未列 `/api/synlab/health` | 实际存在，顶栏用它显示连接与 `store_id`/`research_routes_mounted` |

### 8.2 后端缺陷（UI 原样暴露，不掩盖）

| # | 现象 | 定位 | UI 表现 |
|---|---|---|---|
| B1 | `POST /audits` **任何**调用都返回 `500 INTERNAL_ERROR / KeyError: 'asset_ids'`，但 run/job 已被创建（留下孤儿 audit run） | `synlab/api/routers/governance.py` 传 `scope=`，而 `synlab/api/tables.py::insert` 只识别 `scope_json` 列 → 读回后 `row["scope"]` 是空 dict，`len(row["scope"]["asset_ids"])` 抛错 | U08 显示真实 `INTERNAL_ERROR` + `request_id`，并给出 CLI 替代路径与缺陷定位 |
| B2 | `POST /camera-profiles` 的 `payload` 被静默丢弃（表里永远是 `{}`） | 同上：路由传 `payload`，列名是 `payload_json` | U06 注册成功后显示提示，并展示注册表里真实的（空）payload |
| B3 | `POST /pools`、`POST /training/runs`、`POST /diagnostics/runs` 的 `spec` 被丢弃 | 同上：传 `spec`，列名 `spec_json` | 相关页面以 `status`/`result` 判断“未运行”，不依赖被丢弃的 spec |
| B4 | `POST /episodes/{id}/reset` 的 `spec/state/observation/steps` 被丢弃，`GET` 回来 `state={}` | 同上：传 `state`/`observation`/`steps`，列名带 `_json` 后缀 | U11 显示真实空 state，并在“没有可达动作”处说明该缺陷 |
| B5 | `calibration_source` 的“未标定”取值拼写为 `UNGALIBRATED`，而 `/camera-profiles` 返回的 `calibration_states` 里写的是 `UNCALIBRATED` | `synlab/api/deps.py` 的 `Literal[...]` vs `synlab/api/routers/cameras.py::CALIBRATION_STATES` | U06 的下拉用**可被接受**的 `UNGALIBRATED`，字段 hint 明确说明该拼写差异 |
| B6 | **没有 HTTP 路径能创建 `display_lod` 任务**：handler 读 `job.spec["asset_id"]`（顶层），而 `POST /jobs` 只把校验过的 generation spec 放进 `spec.spec` | `synlab/api/handlers.py::run_display_lod` ↔ `synlab/api/routers/jobs.py::post_jobs` | 视口空状态说明可用 CLI/worker 路径产出；`tests/a12/api_ui/_seed_demo.py` 提供真实的产出脚本 |
| B7 | **没有路由接受 `DegradationRecipeSpec`**：`POST /jobs|previews` 一律按 `synlab.v3` generation spec 校验 | `synlab/api/routers/jobs.py` + `synlab/api/specs.py::kind_for_schema` | U05 只做真实的 `POST /specs/validate`(kind=recipe)，并解释配方经 `degraded_recipe_refs` 进入生成 spec |
| B8 | `ROLE_DISPLAY_LOD = "display_lod_glb"`（不是 `display_lod`）；派生 GLB 的 payload key 是 `glb`（不是 `assets.py::FILE_KEY_PRIORITY` 里的 `glb.bin`） | `synlab/roles.py` / `synlab/api/handlers.py` | 视口/比较视口从资产记录里自动取 `role` 与 `files` key（`lib/glb.ts::pickGlbKey`），不硬编码 |
| B9 | registry 在进程内是**按需导入**填充的：冷启动后首次 `GET /registry/*` 可能返回 0 条，`GET /capabilities`（会 import 各实现模块）之后才有条目 | `synlab/registry.py` + `synlab/api/capabilities.py` | 每个 registry 卡片都有“刷新”按钮；空状态写明“后端返回 0 条”而非“不存在” |
| B10 | 本机 `fast_simplification` 缺失 → 派生 GLB 只有 L0 | `synlab/api/handlers.py::run_display_lod` 的 `lod_notes` | 视口徽标显示“仅 L0：未简化（L1 skipped: ModuleNotFoundError…）” |

---

## 9. 端到端核验记录（真实后端的实测输出）

环境：`python tests/a12/api_ui/_serve.py --store-root data\a12 --port 8077`（真实 `data/a12` 数据根）
与一个隔离的演示数据根（`%TEMP%\synlab_ui_store`，由 `_seed_demo.py` + 真实 worker 子进程产出），
前端用 `vite preview`（指向演示数据根）在浏览器中逐页核验。

> 注意：`synlab/**` 由并行队友持续推进，**能力状态与 registry 条目是移动目标**
> （实测过程中 `missing` 从 `fracture,truth` 逐步减少，registry 从 0 涨到 61 条）。
> 下面的“阻塞示例”是**当时**的真实快照；页面本身永远显示请求那一刻后端的回答，
> 并在每次刷新后与后端保持一致。

1. **U01 概览**：`registry` 条目为**当时真实值**（实测过程中从 0 → 52 → 56 → 61 条变化，因为实现模块在并行注册，
   见 B9；`empty_kinds` 同样随实现进度变化）；中文名如 碗/深盘/浅碟；job `total` 与 run 归并取自真实 job 行；
   能力表按 available/missing 分列；doctor（light）返回 `sqlite integrity=ok` 与逐表计数。
2. **U02 母体编辑**：`/registry/vessel` → `RegistryParamPanel` 用真实 `param_schema` 生成表单
   （`diameter_mm 60–320`、`wall_mm 0.15–60`、`warp_*` 等，默认值取自 schema；material/layer_combo 同样有 12/4 条真实条目）；
   选择 `display_lod_glb` 资产后 3D 视口渲染真实 GLB：
   `权威尺寸 100.000 × 100.000 × 100.000 mm`、`展示尺寸 0.10000 m`、`12 三角面 / 1 mesh`、`GLB 976 B`、
   服务端 sha256 与浏览器重算一致、`100 mm 解析立方体自检通过`。
3. **U03 花纹**：`/registry/pattern` 16 族；`param_schema` 生成 9 个真实字段
   （complexity / line_width_mm / spacing_mm / roughness_paint / low_freq_color / color_amount /
   colour_bands / base_wavelength_mm / roughness_variation）。
4. **U04 断裂**：显示 `fracture_backend` registry 为空（阻塞）**且** `fracture` 能力缺失
   （`missing façade functions: ['fracture_event', 'make_closed_cutter', 'audit_fracture']`）。
5. **U05 退化**：`axis` registry 为空 → `REGISTRY_EMPTY` 阻塞；相机档来自真实 catalogue；
   算子表可编辑 `DegradationOperatorSpec[]`。
6. **U06 相机**：真实 catalogue（`CAM_GLOBAL_V3` rev3、WD 380 mm、U 范围 −100…−40 步长 10、
   FOV 656.36 × 492.27 mm、景深 331.24…445.59 mm、K `fx=2315.789 cy=1499.5`、`calibrated=false`）；
   视锥画布按这些数字绘制；U 滑块被可达范围约束。
7. **U07 任务**：`校验 spec → spec 通过（spec_hash=sha256:0e50a4cf…）` → `估算资源 → 可准入
   （RSS 0.30/30 GB，磁盘剩余 396.00/924.41 GB，cuda_available=false）` → `提交 freeze_spec →
   202 受理 run_b38a49473abfb50b9f4c / job_f869a56b1a601feab56e + 1 节点 DAG`；
   SSE `事件流已连接，已接收 4 个事件，Last-Event-ID(seq)=16`，事件 `run.created/job.created/run.accepted/run.status`
   均标注“本事件未携带 progress —— 不按墙钟推算”。
8. **U08 发布**：执行 `POST /audits` 得到真实缺陷 B1：
   `INTERNAL_ERROR · KeyError: 'asset_ids' · request_id=8efa7e8658594a26`，页面同时给出定位与 CLI 替代路径。
9. **U09/U10**：无 release/checkpoint/pool 时按钮禁用并给出具体原因（如
   `不可用：先在 spec.release_ref 里指定 release`）。
10. **U11 主动观察**：`POST /episodes/ep_ui_01/reset` 返回 `{"ok":true,"episode_id":"ep_ui_01","state":{}}`；
    `GET /episodes/ep_ui_01` 显示 `status=RESET_PENDING`、`cost_total=0`、步数 0，
    显式说明未揭示帧不进入 state（并指出缺陷 B4）。
11. **U12 质量**：`doctor=full` 实测 `mode=full · files_checked=2 · assets=2`；问题任务按 `state` 过滤为 0；
    缺失指标（接受率、验收门结论）标 `未提供` 而不是 0。
12. **后端不可用**：停掉后端后刷新，顶栏显示 `后端不可用 / 未知（后端不可达）/ 任务列表不可用`，
    卡片显示 `BACKEND_UNREACHABLE`（`transport.proxy`）与启动命令，并提供“重试”。
13. **12 路由导航巡检**（对构建产物 `vite preview` + 真实后端，SPA 内逐条点击左侧导航）：
    12/12 路由全部渲染成功，`.state--error` 数量为 **0**，浏览器控制台无 `error`/`warn`；
    5 个页面创建 three.js 画布（U02/U03/U04/U05/U06）；U05 出现 1 个 `BlockedState`（当时 `axis` registry 为空）。

### 9.1 补齐降级项后的 Playwright 实测（自动化，非手工）

```
$ python tests/a12/api_ui/run_e2e.py --skip-build
$ C:\Program Files\nodejs\corepack.cmd pnpm@11.7.0 exec playwright test  (cwd=...\frontend)
[WebServer] INFO:  Uvicorn running on http://127.0.0.1:8081
[WebServer] INFO:  "GET /api/synlab/assets?role=obs_view&role=obs_fused_geometry&limit=200&with_total=true" 200 OK
[WebServer] INFO:  "GET /api/synlab/assets/asset_3367387de335d6c3dbb8/files/obs_fused_geometry?key=arrays" 200 OK
  1 passed (11.2s)
playwright exit=0                                                        exit 0
```

用例 `frontend/e2e/ui-real-backend.spec.ts` 断言的真实内容：

1. 概览页顶栏显示 `工作区 default` / `角色 researcher`，且**不含**“后端不可用”；
2. 退化页“误差热图与点云叠加（真实数组）”面板：`总点数` 与 `有效点数` 均 > 1000（该资产 73120 点），
   点云 canvas 存在不透明像素（真的画过），面板内 `.state--error` = 0；
3. 切到“深度差热图”页签后出现真实深度绝对差热图，且无错误卡片；
4. 纹样页选中真实 `pattern_channels` 资产后必须出现解码后的 `<img>` 与 `IHDR … bitDepth … colorType` 读数；
5. 母体页选中真实 `mother_mesh` 后必须出现 `surface_tag 合法值` 表；
6. 相机页必须出现“U 位置 → 真实新场景帧”与“I09 数字降采样（与 U 移动分开）”两个面板；
7. 12 条路由逐条打开，每条 `.state--error` 必须为 0；控制台 `error`/`pageerror` 必须为 0。

环境说明（如实记录）：

* 首次尝试用 `npm i -D @playwright/test` 失败（`EUNSUPPORTEDPROTOCOL link:./src/types`），
  改用仓库已有的 pnpm：`corepack pnpm@11.7.0 add -D @playwright/test@1.63.0` 成功；
  浏览器用 `corepack pnpm@11.7.0 exec playwright install chromium` 下载（本机原本只有 chromium-1237，
  Playwright 1.63 需要 chromium-1243）。
* 本机对重负载 Python 进程会直接杀掉（exit −1）：e2e 期间真实后端被 kill 过 2 次，
  表现为 Playwright 报 `Process from config.webServer was not able to start. Exit code: 4294967295`；
  重跑即通过。`reuseExistingServer: true`，因此也可以先手工起后端再跑用例。
* 用例**不点击**“U 位置 → 请求真实预览”按钮：那会通过 `POST /previews` 真实写入演示数据根
  （见 §6.2 的副作用声明）。该请求链路已用 curl 单独验证并原样记录在 §6.2。

复现演示数据（可选）：

```powershell
python tests/a12/api_ui/_seed_demo.py --store-root $env:TEMP\synlab_ui_store
$env:PYTHONPATH = "<repo root>"
python -m synlab.api.worker --store-root $env:TEMP\synlab_ui_store --once --json --quiet
python tests/a12/api_ui/_serve.py --store-root $env:TEMP\synlab_ui_store --port 8078
cd frontend; $env:VITE_SYNLAB_PROXY_TARGET = "http://127.0.0.1:8078"; npm run preview
```

---

## 10. 目录结构

```
frontend/
  index.html  vite.config.ts  tsconfig.json  package.json
  playwright.config.ts        真实端到端配置（后端起 _serve.py + vite preview 双 webServer）
  e2e/        ui-real-backend.spec.ts   真实端到端用例
  src/
    main.tsx  App.tsx  styles.css  vite-env.d.ts
    api/       client.ts  endpoints.ts  hooks.ts  types.ts
    lib/       display.ts  glb.ts  curves.ts  runs.ts  caps.ts  format.ts  fixtures.ts
               npz.ts（真实 npz/npy 解码） assetData.ts（资产字节流 + PNG 头） analysis.ts（统计/色标/投影）
    state/     app-state.tsx
    components/ SchemaForm.tsx AssetBrowser.tsx SceneViewport.tsx CompareViewport.tsx
                MeasuredQualityTable.tsx CoverageMatrix.tsx JobTimeline.tsx ResourceBudgetCard.tsx
                RunSelector.tsx MetricChart.tsx FailureDrawer.tsx ProvenanceDrawer.tsx
                SpecStudio.tsx RegistryParamPanel.tsx CameraFrustumView.tsx Layout.tsx states.tsx
                RealArrayHeatmap.tsx PointCloudDiffView.tsx DegradationDiffPanel.tsx
                PatternChannelViewer.tsx SurfaceTagView.tsx NegativeControlPanel.tsx
                CameraUPreviewPanel.tsx I09ExtrinsicsCheck.tsx
    pages/     Overview.tsx MotherEditor.tsx Patterns.tsx Fracture.tsx Degradation.tsx
               CameraProfiles.tsx Jobs.tsx Releases.tsx Training.tsx Diagnostics.tsx
               Episodes.tsx Quality.tsx NotFound.tsx
tests/a12/api_ui/
  _serve.py         真实后端启动器（create_app 需要显式 store_root）
  _seed_demo.py     产出真实 100 mm 母体 + display_lod 任务的演示数据根
  check_frontend.py  构建 / 路由 / 组件 / 新增组件与 lib / e2e 文件 / fixture 断言
  run_e2e.py        真实端到端运行器（拉起后端 + vite preview，调 playwright test）
docs/a12/api_ui.md  本文档
```
