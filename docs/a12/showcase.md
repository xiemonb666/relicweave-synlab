# docs/a12/showcase.md — 合成数据可视化展示界面（U13 `/synlab/showcase`）

本文记录 `/synlab/showcase` 的页面结构、每个分区的**真实数据来源**、生成与启动命令（含真实退出码）、
真实条数与失败项，以及哪些能力在当前环境里没有数据、原因是什么。

**诚实性口径**：页面上每一个数字都来自 `tools/build_demo_assets.py` 对真实模块 API 的调用，
或来自真实资产文件的字节；生成器与前端都不含任何 mock 数据、占位图、随机曲线或假进度。
缺失写 NA、失败写 FAILED/BLOCKED 并附真实错误码与 message，绝不改写成“通过”。

- 计划依据：第 20 节（页面与组件）、20.14（三维与前端细节）、20.15（状态完备性）。
- 写入范围：`tools/build_demo_assets.py`、`synlab/api/{app.py,routers/showcase.py}`、
  `frontend/**`、`tests/a12/showcase/**`、`docs/a12/showcase.md`、`data/a12_demo/**`。
  未修改 `synlab/mothers|materials|patterns|fracture|truth|physical|degrade|observe|cameras|
  training|diagnostics|episodes|storage|jobs|qc/**`、`synlab/cli.py`、`synlab/pipeline.py`、
  `configs/**`、`data/a12/**`。

---

## 1. 页面结构（分区说明，可直接对照页面从上到下核对）

页面路由：`/synlab/showcase`（`frontend/src/App.tsx`），导航入口「U13 合成数据展示」
（`frontend/src/components/Layout.tsx`）。整体是**单页纵向滚动**，5 个 `SectionCard` + 1 个顶部摘要卡。

### 0) 顶部「数据摘要」

| 位置 | 内容 | 数据来源 |
|---|---|---|
| 徽标 | `manifest OK` / `manifest NOT_RUN` | `GET /showcase/manifest` 的 `status` |
| 条目总数 / OK·FAILED·BLOCKED·NA | 真实计数 | 清单 `counts` |
| 母体 / 纹样 / 碎裂（成功）/ 退化轴（成功）/ 退化源 条数 | 分类计数 | 清单 `counts.by_kind` |
| 真实失败数（FAILED + BLOCKED） | 红色徽标 | 同上 |
| 生成时间 | ISO 原值 + 本地时间 | 清单 `generated_at`（清单原值也显示，避免时区误读） |
| manifest 路径 / 演示资产库 | `data/a12_demo/demo_manifest.json`、`data/a12_demo/store` | API 返回的仓库相对路径（**不含服务器绝对路径**） |
| master_seed / lineage | `20261001 / a12_demo` | 清单 |
| 生成命令 | 可复制按钮 | 固定字符串 `& .venv\Scripts\python.exe tools\build_demo_assets.py` |
| 刷新按钮 | 重新请求 manifest | — |
| 可展开的 `runs` | 每次运行的命令、单元数、耗时、真实计数 | 清单 `runs`（最多保留 20 条） |

空状态：清单不存在时显示「尚未生成演示数据集」+ 生成命令，**不显示任何占位数据**。

### 1) 母体库

- 8 张卡片（`V01/V02/V03/V04/V06/V07/V13/V18`，材料均为 `M03`），点击切换；
- 选中母体的 **three.js + GLTFLoader 三维视口**（复用 `components/SceneViewport.tsx`）：
  显示毫米标尺、权威尺寸（mm/Z-up）、展示尺寸（m/Y-up）、三角面数、GLB 字节数、
  服务端 `X-SynLab-File-Sha256` 与浏览器 `crypto.subtle` 重算值对照、100 mm 解析立方体自检；
- 右侧「真实 QA 数值（audit_mother）」：水密 / 体积 / 表面积 / 壁厚 min·P05·median / 探针数 /
  `void_ratio` / 连通体 / genus / 自交面对 / 面数与顶点 / 尺寸 / 耗时；
- 「真实 checks」原样 JSON（`audit_mother` 的 `checks`）与「采样参数」（`sample_parameters` 的真实输出）。

### 2) 纹样通道

- 8 个族的选择器（`PAT01/PAT02/PAT03/PAT06/PAT10/PAT12/PAT14/PAT15`），显示中文族名；
- **albedo / roughness / height_mm 三张 PNG 并排**（256×128），每张标注 `payload key`；
- 「显示编码说明（图例）」横幅：逐通道写明 `uint8 = round(255*clip(v,0,1)^(1/2.2))`（albedo/rgb）、
  线性灰度（roughness）、对称归一化蓝-白-红发散色标（height_mm，含 `amax` 与实测 min/max），
  并说明栅格方法（面积加权随机采样 → `evaluate` → (x,s) 分箱算术平均、覆盖率、每 bin 平均样本数、
  未覆盖 bin 为黑、bin 内颗粒是采样噪声）；
- 「接缝与尺度实测（audit_pattern）」：接缝最大色差、接缝容差、导数失配 P99、导数比值预算、
  接缝采样对 n、x 周期与周期性、s 范围、声明线宽与实测线宽（NA 时给出原因）、主波长、
  倍频带覆盖、高频残差、三通道实测范围、pattern_region 占比；
- 通道资产直链（`?name=albedo_png` 等）与 `audit_pattern` 原始返回。

### 3) 碎裂演示

- 8 个真实事件的标签页（每个标签带真实状态：`OK / FAILED / BLOCKED`）；
- **事件 OK 时**：爆炸位移滑杆 + 「回到原位」按钮 + 碎片装配视图
  （`components/showcase/FragmentAssemblyViewport.tsx`，把每个碎片的真实 GLB 放进同一个场景；
  原位 / 爆炸切换，**爆炸只是纯展示变换**，面板上标出位移量并说明不写回任何资产）；
- **事件失败/阻塞时**：不画任何碎片几何，改显示
  （a）真实错误码 + message + stage 的红色错误卡，
  （b）「打开失败详情（FailureDrawer）」按钮 —— 复用既有 `FailureDrawer` 的**静态失败模式**
      （新增 `staticFailure` prop，原 job 语义不变），展示 code / message / stage / measurements /
      source_ref / 最小复现命令，
  （c）母体的**参考**几何（明确标注「不是断裂结果」）；
- 右侧：真实指标（碎片段数 / tiny 数 / debris 数 / 共享面 patch 数 / 母体体积 / 碎片体积和 /
  体积守恒相对差 / 后端注册状态）、碎片列表（体积 / 面积 / 面数 / 来源面覆盖 / tiny / GLB 下载）、
  以及**从真实注册表读取**的 5 个后端状态。

### 4) 退化对比

- 31 个轴按 **P（物理）/ I（成像）/ G（几何）/ X（估计）** 分组，每个轴一个 chip；
  未生成数据的轴标 `· NA` 并在 `title` 里给出具体原因；
- 选中已生成轴后：真实声明（stage / substage / variant / factor_kind / accepted_sources /
  label_invalidations / calibration_status）+ 「level 0 identity」徽标；
- 档位：0–4 的滑杆 + L0…L4 按钮；
- 对比模式：**图像对比** / **几何、点云对比**（该档没有对应产物时按钮禁用并说明原因）；
- 左右并排：`baseline · level 0（identity，引用 source 资产）` 与 `当前档 · level N`；
- level 0 时显示绿色恒等横幅：`identity / identity_reference_ok / bytes_unchanged` 三个真实布尔值
  与 source/result 的 content hash；
- 逐档失败时用 FailureDrawer 展示真实 code / message / measurements + 复现命令；
- 右下：`Measurement.measured` 实测变化量表（带 units）、`planned` 声明参数、
  「同一 source / 同一 basis」表（source_kind / source_asset / provenance / content_hash /
  basis_id / basis_seed_ref / basis_payload_keys）与逐档真实状态表。

### 5) 状态与诚实性面板

- 按类别统计表（total / OK / FAILED / BLOCKED / NA）；
- **非 OK 条目表**：entry_id、类别、状态、错误码、message、stage、可复制的复现命令；
- **31 个轴中未生成数据的轴表**：axis_id / stage / substage / 变体 / 接受源 / NA 原因；
- 断裂后端注册状态（`IMPLEMENTED / PENDING / MISSING`，来自清单里的真实注册表快照）；
- 环境与能力事实（清单 `environment_findings` 原样展示）；
- 逐档失败列表（**数据驱动**，直接来自各退化条的 `metrics.levels[].failure`）；
- 指向本文档的仓库内路径说明。

---

## 2. 每个分区的数据来源（真实 asset_id 示例）

以下 id 取自本次真实运行的 `data/a12_demo/demo_manifest.json`；内容寻址，同一输入可复现。

| 分区 | 条目 | asset_id（示例） | role / schema | 备注 |
|---|---|---|---|---|
| 母体库 | `mother:V01` | `asset_167bef6a43a93438ec26` | `mother_mesh` / `synlab.mother.v1` | 权威 mm/Z-up |
| 母体库（展示） | `mother:V01` 的 `artifacts.glb` | `asset_f8dd1f356638dd5b6e12` | `display_lod_glb` / `synlab.display_glb.v1` | 米/Y-up，7008 面，123.9 KiB |
| 纹样通道 | `pattern:PAT01` | `asset_dd885e4b9fdc9912efd4`（recipe） | `pattern_recipe` / `synlab.pattern.v1` | recipe_hash 见清单 |
| 纹样通道 | `pattern:PAT01` 的 `artifacts.channels` | `asset_cf4f842fd1b58ad3e1c4` | `pattern_channels` | 内含 `albedo_png` / `roughness_png` / `height_png` |
| 碎裂演示 | `fracture:V01:plane_shared_cut` | 2 个碎片 GLB（见 `metrics.fragments[].glb.asset_id`） | `display_lod_glb` | 2 片 / 138 个共享面 patch / 体积守恒相对差 3.8e-10 |
| 退化对比 | `degrade:I01` 的 source | 见 `metrics.source_asset` | `obs_view` / `synlab.obs.v1` | 真实 `PROXY_SCAN` 观测（320×240×4 视角） |
| 退化对比 | `degrade:P03` 的 source | `asset_ab3085f11f1be039b14f` | `physical_component` / `synlab.physical.v1` | 内置探针实体，provenance 写在清单里 |

退化条目的每一档都有自己的 `asset_id`（`metrics.levels[].asset_id`）与可视化产物：
`artifacts.png`（`obs_view`，image/png）与 `artifacts.glb`（`display_lod_glb`）。

### 2.1 展示 API

| 路由 | 说明 |
|---|---|
| `GET /api/synlab/showcase/manifest` | 读 `demo_manifest.json`，返回条目 + 指标 + 状态；未生成时 `status="NOT_RUN"` + 生成命令 + `empty_reason`，**不返回假数据** |
| `GET /api/synlab/showcase/asset/{asset_id}/{key}` | 白名单 `key ∈ {glb, png, arrays, meta}`；可选 `name=<payload key>` 在该资产已记录的 key 里精确指定；逐个校验存在性与 sha256，返回正确 Content-Type 与 `X-SynLab-File-Sha256` 等响应头 |

结构化错误（都走统一的 `{ok:false,error:{…}}` 信封）：

| 场景 | HTTP | code |
|---|---|---|
| 未知 key（例如 `bogus`） | 400 | `SHOWCASE_KEY_NOT_ALLOWED`（details 里带白名单） |
| key 与 payload 类型不匹配（`key=png&name=glb`） | 422 | `SHOWCASE_KEY_MISMATCH` |
| 未知 asset_id | 404 | `NOT_FOUND` |
| 资产存在但没有该类 payload | 404 | `NOT_FOUND`（details.available 列出真实 key） |
| 演示资产库不存在 | 404 | `SHOWCASE_NOT_GENERATED` |
| 清单存在但无法解析 | 409 | `SHOWCASE_MANIFEST_UNREADABLE` |

两个路由都在 `create_app` 里挂载（`synlab/api/app.py`）；**既有角色策略完全不变**：
展示路由不带研究真值，`deployment_client` 也能只读浏览（测试断言它读 manifest 返回 200，
而 `/research/...` 仍是 `403 TRUTH_ROUTE_UNMOUNTED`）。路由读的是**独立的演示资产库**
（`data/a12_demo/store`），与会话的 `store_root` 无关（测试断言会话库资产数不变）。

---

## 3. 生成与启动命令（真实命令与退出码）

### 3.1 生成演示数据集

```powershell
# 全量（幂等：已 OK 的单元会跳过）
& .venv\Scripts\python.exe tools\build_demo_assets.py
```

**实测**（2026-10-01，`data/a12_demo` 已有数据，即"续跑"路径）：

```
$ & .venv\Scripts\python.exe tools\build_demo_assets.py
== build_demo_assets == 2026-10-01T17:57:26+00:00
-- 步骤 mothers：8 个单元      （8 skipped）
-- 步骤 patterns：8 个单元     （8 skipped）
-- 步骤 fracture：8 个单元
   [FAILED] fracture:V13:rough_shared_cut  91.9s  PRECISION_BUDGET_EXCEEDED: ...
   [FAILED] fracture:V01:secondary_fracture  22.8s  AttributeError: '_Piece' object has no attribute 'mother_id'
   [BLOCKED] fracture:V01:warped_partition  2.2s  OPERATOR_NOT_REALIZED: ...
   [BLOCKED] fracture:V01:fracture_modes  2.1s  OPERATOR_NOT_REALIZED: ...
-- 步骤 degrade：16 个单元     （1 run + 15 skipped）
条目总数：40  OK=35  FAILED=2  BLOCKED=3  NA=0
本次执行单元数：5   总耗时：125.0s
EXIT：1（5 个非 OK 条目）                                            exit 1
```

`exit 1` 是**真实结果**而不是脚本崩溃：`0 = 全部 OK`，`1 = 至少一个单元 FAILED/BLOCKED`，
`2 = 参数错误`。首次全量生成（`data/a12_demo` 为空时）约 8–12 分钟，退出码同为 1（因为碎裂后端确实失败）。

分步 / 可续跑：

```powershell
& .venv\Scripts\python.exe tools\build_demo_assets.py --only mothers
& .venv\Scripts\python.exe tools\build_demo_assets.py --only patterns --limit 4
& .venv\Scripts\python.exe tools\build_demo_assets.py --only fracture --limit 2
& .venv\Scripts\python.exe tools\build_demo_assets.py --only degrade
& .venv\Scripts\python.exe tools\build_demo_assets.py --force                 # 重跑全部
& .venv\Scripts\python.exe tools\build_demo_assets.py --unit degrade:I01 --force   # 只跑一个单元
& .venv\Scripts\python.exe tools\build_demo_assets.py --summary               # 只打印清单摘要（exit 0）
```

### 3.2 启动页面

```powershell
# 1) 真实后端（create_app 是工厂函数，需要显式 store_root；展示路由会自动找到 ../a12_demo）
& .venv\Scripts\python.exe tests\a12\api_ui\_serve.py --store-root data\a12 --port 8077 --role researcher

# 2) 预览构建产物（/api 反代到 8077），打开 http://localhost:4188/synlab/showcase
cd frontend
$env:VITE_SYNLAB_PROXY_TARGET = "http://127.0.0.1:8077"
node node_modules/vite/bin/vite.js preview --port 4188
```

也可以显式指定演示数据根（部署/打包时更安全）：

```python
from synlab.api import create_app
app = create_app("data/a12", role="deployment_client", showcase_root="data/a12_demo")
```

`showcase_root` 是**严格覆盖**：给了它就只看它，不会回退到仓库默认位置。

### 3.3 验证命令与退出码（本次实跑）

```
$ cd frontend
$ node node_modules/typescript/bin/tsc --noEmit
（无输出）                                                        exit 0

$ node node_modules/vite/bin/vite.js build
vite v5.4.21 building for production...
✓ 97 modules transformed.
dist/index.html                     0.49 kB │ gzip:   0.43 kB
dist/assets/index-DW9rroQe.css     22.73 kB │ gzip:   4.89 kB
dist/assets/index-BskWm2eh.js   1,128.96 kB │ gzip: 328.18 kB
✓ built in 3.04s                                                  exit 0

$ cd ..
$ & .venv\Scripts\python.exe -m pytest tests/a12/showcase -q
....................s.                                            exit 0

$ & .venv\Scripts\python.exe -m pytest tests/a12/showcase
....................s.                                            exit 0
21 passed, 1 skipped in 10.62s

$ & .venv\Scripts\python.exe tests\a12\showcase\check_showcase_frontend.py
OVERALL: PASS                                                     exit 0
```

说明：`pyproject.toml` 已配 `addopts = "-q"`，命令行再传一个 `-q` 会变成 `-qq`，
pytest 因此**不打印汇总行**（只有进度点）。两种写法都退出 0；需要看条数时用第二条命令。

`pytest` 里的 1 个 skip 是"仓库数据集里的纹样 PNG"检查——小规模测试集只跑 `--only mothers`，
所以该测试按设计跳过（真实仓库数据集存在时它会执行；本次仓库数据集存在但小规模测试集不存在）。

浏览器端核验（`vite preview` + 真实后端，逐区滚动检查）：

```
$ & .venv\Scripts\python.exe tests\a12\api_ui\_serve.py --store-root data\a12 --port 8077 --role researcher
$ cd frontend; $env:VITE_SYNLAB_PROXY_TARGET="http://127.0.0.1:8077"; node node_modules/vite/bin/vite.js preview --port 4188
→ http://localhost:4188/synlab/showcase
```
实测结果：`.state--error` 数量 **0**；2 个 three.js 画布（母体视口 + 碎片装配视口）；
5 张 `<img>` 全部加载成功（3 张纹样通道 256×128 + 2 张退化对比 320×255）；
母体视口的服务端 sha256 与浏览器重算值一致；爆炸位移 0.120 m 后两个真实碎片分离
（徽标显示「爆炸视图（展示位移 0.120 m）」）；I01 level 2 相对 level 0 可见地变模糊。

仓库数据集规模：`data/a12_demo/store` 里 **186 个资产**，清单 **40 条**。

---

## 4. 本次真实条数与失败项

清单：`data/a12_demo/demo_manifest.json`（`schema = synlab.showcase.demo_manifest.v1`，40 条）。
演示资产库：`data/a12_demo/store`（内容寻址，与 `data/a12` 完全隔离）。

| 类别 | 总数 | OK | FAILED | BLOCKED | NA |
|---|---|---|---|---|---|
| `mother` | 8 | 8 | 0 | 0 | 0 |
| `pattern` | 8 | 8 | 0 | 0 | 0 |
| `fracture` | 8 | 3 | 2 | 3 | 0 |
| `degrade_source` | 4 | 4 | 0 | 0 | 0 |
| `degrade`（轴） | 12 | 12 | 0 | 0 | 0 |
| **合计** | **40** | **35** | **2** | **3** | **0** |

退化：12 个轴 × 5 档 = 60 档，**全部 OK**（P03/P05/P06/I01/I03/I09/I10/G03/G05/G08/X01/X04）。
31 个轴中另外 19 个轴在 `axis_catalog` 里列为 `NA` 并带原因。

### 4.1 非 OK 条目（真实原因，页面原样展示）

| entry_id | 状态 | code | message |
|---|---|---|---|
| `fracture:V13:rough_shared_cut` | FAILED | `PRECISION_BUDGET_EXCEEDED` | `cutter refinement exceeded the cell budget (400000) while chasing a 0.01 mm budget at wavelength 0.2581 mm; the shortest wavelength is not relaxed` |
| `fracture:V01:secondary_fracture` | FAILED | `AttributeError` | `'_Piece' object has no attribute 'mother_id'` |
| `fracture:V01:rough_shared_cut` | BLOCKED | `PROCESS_KILLED` | 运行该单元时父进程与子进程一起被系统杀掉（无 Python 异常、无退出码），已连续被杀 3 次 |
| `fracture:V01:warped_partition` | BLOCKED | `OPERATOR_NOT_REALIZED` | `backend 'warped_partition' is registered as PENDING: the conformal shared-PLC warp stage (gmsh) is not implemented in this build ...` |
| `fracture:V01:fracture_modes` | BLOCKED | `OPERATOR_NOT_REALIZED` | `backend 'fracture_modes' is registered as MISSING: ...` |

成功事件（页面有碎片三维视图与爆炸视图）：

| entry_id | 碎片 | 共享面 patch | 体积守恒相对差 | 来源面覆盖 | 共享面 P95 距离 | 法向反向角 P95 |
|---|---|---|---|---|---|---|
| `fracture:V01:plane_shared_cut` | 2 | 138 | 3.78e-10 | 1.0 | 4.25e-05 mm | 8.31e-04° |
| `fracture:V13:plane_shared_cut` | 3 | 149 | 1.69e-08 | 见清单 `metrics.audit` | 见清单 | 见清单 |
| `fracture:V04:plane_shared_cut` | 6 | 7 | -2.47e-09 | 见清单 | 见清单 | 见清单 |

（上表只填了有代表性的第一行，其余数值都在清单的 `metrics.audit` 里，页面直接读同一份数据。）

### 4.2 进程被杀（`PROCESS_KILLED`）与可续跑设计

本机对重负载 Python 进程会**直接杀进程树**（无 Python 异常、无退出码）。生成器为此做了三件事：

1. **每个工作单元跑在独立子进程**里（父进程只负责编排与写盘）；
2. 单元开始前写 `data/a12_demo/.inflight.json`，结束后删除；下次启动时若发现它存在，
   就把那个单元记成 `BLOCKED / PROCESS_KILLED`（附被杀时间与 attempts），并删除标记；
3. 同一单元连续被杀 ≥ `--max-attempts`（默认 2）次后不再自动重试，`--force` 可再试一次。

因此**被杀只丢一个单元**（`fracture:V01:rough_shared_cut` 就是这样被记录下来的），
已完成的条目留在清单里，重跑会跳过。

---

## 5. 缺口：哪些东西没有数据、为什么

| 缺口 | 现状 | 真实原因（页面照实显示） |
|---|---|---|
| 19 / 31 个退化轴 | `NA` | 本次演示集只生成 12 个轴（`tools/build_demo_assets.py::DEGRADE_AXES`）；补齐只需把轴号加进该元组后重跑 `--only degrade`。每个 NA 轴仍显示真实 stage / substage / 变体 / 接受源 |
| `rough_shared_cut`（2 个事件） | FAILED / BLOCKED | 默认 0.01 mm 插值误差预算下刀具体细化超出 40 万 cell 预算（`PRECISION_BUDGET_EXCEEDED`，真实测量）；部分器型上进程被杀（`PROCESS_KILLED`） |
| `secondary_fracture` | FAILED | `synlab/fracture/api.py::_secondary_event` 里 `_Piece(target.mesh)` 缺少 `mother_id`，二次事件在子事件调用处抛 `AttributeError`（真实缺陷，页面显示原样 message） |
| `warped_partition` | BLOCKED（PENDING） | 注册表状态就是 `PENDING`：共形共享 PLC 形变阶段（gmsh）未在本构建中实现，管道拒绝用平面分区冒充 |
| `fracture_modes` | BLOCKED（MISSING） | 注册表状态 `MISSING`：未获得动力学断裂模式求解器的许可/依赖 |
| Blender / bpy | 不存在 | 无 Windows + py3.12 wheel；渲染只有软件光栅后端，`synlab.observe.render.capability_probe()` 如实报告 |
| 真实实拍数据 | 不存在 | 仓库里没有任何实拍数据；本页所有数据都是合成数据（`data_scope=SYNTHETIC`） |
| `synlab.observe.routes::_carve_holes` 越界缺陷 | 未修复，只记录 | `delivered_size=(320,240)` 且 `route_params.hole_count=2` 时抛 `IndexError: index 240 is out of bounds for axis 0 with size 240`；演示集用 `hole_count=0` 换取稳定的 320×240 真实渲染。`synlab/**` 不在本任务写入范围 |
| 纹样 height 通道为 0 | 正常 | `PAT01/PAT02/...` 这些外观族的 `height.mode="none"`，`height_mm` 真值就是 0；页面写出 `amax` 与实测 min/max，不伪造浮雕 |
| 纹样栅格不是逐像素真值 | 设计如此 | 用面元面积加权随机采样 → `evaluate` → (x,s) 分箱算术平均；覆盖率与每 bin 样本数写在图例里，未覆盖 bin 保持黑色 |

---

## 6. 目录与新增文件

```
tools/build_demo_assets.py                     真实演示数据集生成器（可分步/可续跑/子进程隔离）
synlab/api/routers/showcase.py                 两条只读展示路由 + ShowcaseLocator
synlab/api/app.py                              + showcase_root 参数与挂载（既有语义不变）
frontend/src/pages/Showcase.tsx                U13 页面（摘要 + 5 个分区）
frontend/src/api/showcase.ts                   展示 API 客户端与类型
frontend/src/components/showcase/sections.tsx  五个分区实现
frontend/src/components/showcase/FragmentAssemblyViewport.tsx  碎片装配视图（原位/爆炸）
frontend/src/styles-showcase.css               展示页样式（独立文件，不改既有选择器）
frontend/src/components/FailureDrawer.tsx      + staticFailure（非 job 来源的真实失败）
frontend/src/components/SceneViewport.tsx      + source（assets / showcase 取数来源）
frontend/src/lib/glb.ts                        + GlbSource / glbFileUrl
frontend/src/App.tsx, components/Layout.tsx    + 路由与导航入口
tests/a12/showcase/test_generator.py           生成器幂等 / 清单结构（真实小规模运行）
tests/a12/showcase/test_showcase_api.py        展示 API 白名单 / 404 / 结构化错误（TestClient）
tests/a12/showcase/check_showcase_frontend.py  构建 + 路由 + 关键字符串检查
data/a12_demo/demo_manifest.json               真实清单（40 条）
data/a12_demo/store/                           独立演示资产库（内容寻址）
docs/a12/showcase.md                           本文档
```
