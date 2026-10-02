# A12 数据语义版本与批产分界（mask / damage）

本文记录一次**数据语义变更**：`visible`/`deployment_mask` 一族掩码的判定式（弥散圆
CoC 单位）与物理损伤结果的合法性判定（A09）在同一批代码里被修正。语义变更不能用时间戳
区分，因此每个产物都写入一个可程序化查询的版本标记（§3），并在此逐条给出**修复前后的
定义、判定式、实测数值、影响面**。

- 全部数字来自本机实测；可复算脚本与产物见 §5。
- 本文件写于语义变更提交点；**在此提交点之前**生成的 run/资产全部是旧语义。

| 语义键 | 旧（v1） | 新（v2） | 定义位置 |
|---|---|---|---|
| `mask_semantics` | `coc_units_v1_pixel_units`（仅当 frame 未声明光学时才走该分支） | `coc_units_v2` | `synlab/observe/render.py::MASK_SEMANTICS` |
| `damage_semantics` | `subset_v1_as_shipped`（无标记即为它） | `subset_v2` | `synlab/physical/api.py::DAMAGE_SEMANTICS` |

---

## 1. 缺陷 1：CoC 单位错误导致可见性掩码被侵蚀

### 1.1 修复前的语义（v1）

`render_view` 用

```
coc = f_px^2 / (N * z) * |z - z_f| / z_f          # N ≡ 1.0（硬编码），f_px 单位是像素
uncertain = mixed_id | mixed_tag | (coc > spec.coc_px_threshold)
deployment_mask = erode(id_map>=0 & visibility & ~uncertain)
visible = 在图像内 & z>0 & |z - 渲染深度|<=tol & id_map>=0 & ~uncertain & deployment_mask
```

把**像素单位**的 `f_px` 代进**毫米制**薄透镜公式，并且**没有**除以传感器采样密度
`D`。物理量纲上 `c_mm = f_mm^2/(N(z-f_mm)) * |z-z_f|/z_f` 是**像面长度（mm）**，
转成交付像素必须乘 `D = width_px / sensor_width_mm = f_px / f_mm`（px/mm）。

### 1.2 独立复核（不采信队友结论，重新推导 + 三条独立反证）

**(a) 量纲与解析推导。** 薄透镜下离焦点 `z` 的物点成像于 `s' = f z/(z-f)`，传感器位于
对焦像距 `s_f = f z_f/(z_f-f)`；孔径 `A = f/N` 的边缘光线落在传感器上，模糊直径

```
c = A * |1 - s_f / s'|  （精确光线追迹）
  ≈ f_mm^2 / (N (z - f_mm)) * |z - z_f| / z_f   （标准小模糊近似）
c_px = D * c_mm ,  D = f_px / f_mm
```

数值对照（CAM_MID_V3，f=5.2 mm、N=2.2、z_f=220 mm、交付 256 px / 传感器 7.6 mm，
`D = 33.68421052631579`、`f_px = 175.1578947368421`；实测脚本 §5）：

| z (mm) | 光线追迹 c (px) | 修复后公式 (px) | 相对差 |
|---|---|---|---|
| 190 | 0.304329 | 0.305497 | 0.38 % |
| 215 | 0.044824 | 0.044849 | 0.056 % |
| 220 | 0 | 0 | 0 |
| 230 | 0.083801 | 0.083713 | 0.11 % |
| 260 | 0.296526 | 0.295426 | 0.37 % |

**(b) 反证 1：修复前后比值 = `D * N`（同一像素、同一深度）。** 4 个视图逐像素比值的
中位数实测 **72.10 / 72.24 / 71.96 / 71.99**，与解析式
`D·N·(z-f_mm)/z = 74.105263… × 0.97636 = 72.35` 一致。队友报告里的 `74.105 = D × f_number`
来自它把"声明光学"参考实现写成 `(z)` 而非 `(z - f_mm)`（在 220 mm 处差 2.4 %）；两种写法
都证明同一件事：旧值是声明光学的 **70 倍量级**。

**(c) 反证 2：`D` 的两个独立确认。** `D = 交付宽 / 传感器宽 = 256/7.6 = 33.6842105263`；
另一方面由放大率关系 `mm_per_px@物 = (1/D)·(z/f)` 得 **1.2560096153846154**，与
census 资产 meta 里committed 的 `mm_per_px_at_object = 1.2560096153846154` 完全一致。

**(d) 反证 3：反演 profile 自己声明的景深。** profile 声明 DOF = [206.32025263857722,
235.62259409143022] mm、`coC_px = 2.0`、native 4000 px（像元 0.0019 mm）。把修复后的公式
代进近端：`c_mm(206.3202526) = 0.0038000000000000095` mm，判据 `2.0 px × 0.0019 = 0.0038`
mm，相对误差 **3.2e-16**；远端 `0.00378782`（0.32 %，因为声明远端用了超焦距近似式）。
即修复后的公式能被 profile 自己的 DOF 声明**逐位重现**。

### 1.3 修复后的语义（v2）

```
D       = f_px / focal_length_mm          # focal_length_mm 来自 RenderSpec /
                                          # ViewFrame.meta / 相机 profile 注册表
c_px    = D * f_mm^2 / (N_declared * (z - f_mm)) * |z - z_f| / z_f
uncertain / deployment_mask / visible 判定式不变（判据未放宽）
```

`render_view` 的 `meta` 新增 `mask_semantics`、`coc_optics{rule,f_px,focal_length_mm,
f_number,sampling_px_per_mm,declared,source}`；只有 frame 完全不声明光学（合成测试/审计
帧）时才回落到旧表达式，并明确写成 `coc_units_v1_pixel_units`，不会与 v2 数字混在一批。

**阈值**：pipeline 的阈值补偿保持原样（`RenderSpec.coc_px_threshold × 声明 f-number`），
在 CAM_MID_V3 上即 `0.75 × 2.2 = 1.65 px`，比 profile 自己的 `coC_px = 2.0 px` mark-out
**更严**；因此修复只改"被比较的量"，不改判据方向。

### 1.4 before / after 实测（同一 store、同一批深度图、逐像素）

数据源：L0 census store（`data/a12/reports/l0_role_census.json` 记录的 run
`run_563ae39481ee5ff5`）的 obs 资产 `asset_dafa19d53f663c2295b9`；v1 列取已提交的
`deployment_mask`/`uncertain_mask`，v2 列按 §1.3 在同一深度图上重算，两者一致地复现在
新 run `run_548e5b5a4a27b144` 的提交产物中（§5.2 表二）。

| 视图 | 物体像素 | 修复前 uncertain(物体) | 修复后 uncertain(物体) | 修复前 mask px | 修复后 mask px | 修复前覆盖率 | 修复后覆盖率 |
|---|---|---|---|---|---|---|---|
| v00 | 2833 | 2343 (82.7 %) | **0** | 204 | **2533** | 7.20 % | **89.41 %** |
| v01 | 2376 | 2040 (85.9 %) | **0** | 50 | **2029** | 2.10 % | **85.40 %** |
| v02 | 1907 | 1681 (88.2 %) | **0** | 5 | **1553** | 0.26 % | **81.44 %** |
| v03 | 1895 | 1700 (89.7 %) | **0** | 27 | **1558** | 1.42 % | **82.22 %** |

- 4 视图 mask 并集：**243 px → 3218 px**；平均单视图覆盖率 **2.75 % → 84.61 %**。
- CoC（物体像素）：修复前 p50 = 17.15 / 21.71 / 31.03 / 29.36 px；修复后
  p50 = **0.2365 / 0.2992 / 0.4312 / 0.4078 px**，p95 = **0.546 / 0.505 / 0.521 / 0.597 px**。
- **低于 profile 自己 2.0 px mark-out 的物体像素占比：修复前 0.46 % / 0.29 % / 0.05 % /
  0.11 % → 修复后 100 % / 100 % / 100 % / 100 %**（验收要求 ≥95 %）。低于 1.65 px 的
  pipeline 阈值同样是 100 %。
- 景深：物体相机 z 跨度 **88.31 – 94.25 mm**；交付网格上 `c_px ≤ 2.0 px` 的窗口为
  **[167.4, 261.6] mm**（逐视图实测），完全覆盖该跨度。注意 profile 声明的
  *native 像元* DOF 只有 **29.30 mm**（206.32–235.62 mm），那是 4000 px 判据下的窗口，
  与交付 256 px 网格的判据不是一回事（本文给出两者，不混淆）。

### 1.5 影响面（哪些角色/字段的语义变了）

| 角色 / 字段 | 变化 |
|---|---|
| `obs_result`：`uncertain_mask`、`deployment_mask`、每视图 mask 覆盖 | **语义变更**（数值显著变化） |
| `visible_labels`：`visible`、`samples_visible`、`visible_fraction`、QA `pass` | **语义变更**（QA_FAIL → QA_PASS） |
| `feature_bundle`：`pixel_valid` / `global_valid` / `tokens_total`（来自 deployment mask） | 语义变更（可选像素变多） |
| `label_bundle`：`visible_json` | 随 visible 层变化 |
| `mask_semantics` 标记 | 新增（§3） |
| 几何通道 `depth_z`/`id_map`/`surface_tag` | **不变**（本次未触碰） |

---

## 2. 缺陷 2：A09 —— 物理损伤结果不合法

### 2.1 失败资产与根因定位（逐条实测）

失败资产：`asset_373e79ee5e6bafaabe78`（`physical_result`，P03_depth_light / level 1），
`audit_physical` 报 `DAMAGED_NOT_SUBSET_OF_CLEAN + NON_POSITIVE_VOLUME + NOT_WATERTIGHT`，
`lost_volume_mm3 = 276.58071298516006`（ratio 0.0039724），components 3 = core 1 + debris 2。
用 `data/a12/reports/probe_a09_p03.py` 从归档 store 复现，数值与 census 逐位一致。

**(1) 走的是哪个 P03？** pipeline 走 `synlab.physical.operators.erode_interface`
（全局均匀 SDF + marching cubes + manifold 布尔裁剪）；`synlab/degrade/physical_narrowband`
的窄带 P03 只被 `degrade.axes`（`NARROWBAND=True`）使用。两条路径的实测对比见 §2.3。

**(2) `NON_POSITIVE_VOLUME`：两个 0 体积连通体。** 布尔裁剪输出被
`component_split` 分成 3 个连通体，其中 2 个是 **2 面 / 3 顶点 / 体积恰为 0.0 mm³** 的
重合反向三角形对（三角形引擎残留），却被 `register_components` 当作 DEBRIS 组件登记。

**(3) `NOT_WATERTIGHT`：6 条边界边（2 个纳米级孔）。** 裁剪输出的主连通体（87172 面）
有 6 条只被 1 个面使用的边，构成 2 个边界环，其包围盒对角线 **50 nm / 23 nm**、面积 ~0；
`trimesh.repair.fill_holes` 在 trimesh 5.1.0 上**无法**修复（其 `extend_faces` 在此网格上
不添加任何面，实测），因此必须自己按有向边界环补面。
另外：marching cubes 候选体本身是水密的，但 **19.78 % 的表面在 clean 体之外（最大
0.206 mm）**——这是提取漂移，被随后的布尔裁剪消掉，所以裁剪本身必须保留。

**(4) `DAMAGED_NOT_SUBSET_OF_CLEAN`：是量具坏了，不是几何坏了。** 原判定用
`sdf.outside_fraction`（Open3D `compute_signed_distance`，点被转成 float32，正值=外部）：

| 对照 | Open3D 近似 SDF | 精确 float64 判定 |
|---|---|---|
| clean 自身表面 vs clean（完美子集） | max **0.0161 mm**，0.275 % 越界 | max **1.4e-10 mm**，0 越界 |
| identity level 0（组件**就是** clean 网格对象） | 审核 **FAIL**（`max_outside 0.0087 mm`） | 0 越界 → PASS |
| 全局 P03 体 | max 0.0014 mm（>tol 1e-3）→ FAIL | max **3.7e-6 mm** → PASS |
| 窄带 P03 体 | max 0.0035 mm → FAIL | max **6.2e-7 mm** → PASS |

量具自身噪声底（0.0161 mm）是判据容差（1e-3 mm）的 16 倍，且**恒等结果都会 FAIL** ——
该检查在原量具下不可满足。符号约定也已用轴对齐立方体验证并落盘：
Open3D 正值=外部；`trimesh.proximity.signed_distance` 正值=内部。

### 2.2 修法与判定式（`damage_semantics = subset_v2`）

1. **装配顺序**（`physical/api.py::assemble_damage_bodies`）：先
   `component_split` → 丢弃"无可测体积"的连通体（阈值
   `max(1e-9 mm³, 1e-12·V_source)`，本例 6.96e-8 mm³）→ **再**对留下的材料体补纳米孔。
   顺序是被实测逼出来的：0 体积重合三角形对占用的正是那些边界边，先补孔会让边被用 3 次，
   永远不水密。
2. **补孔**（`close_numerical_pinholes`）：只补"小于声明针孔尺度"（包围盒对角线 ≤1e-3 mm
   且面积 ≤1e-6 mm²）的有向边界环；补面后必须**同时**满足 `is_watertight`、
   `is_winding_consistent`、体积不变，否则原样返回并把测量写进 `qa`。更大的洞=真洞，
   **不补**，让审核如实报 `NOT_WATERTIGHT`。
3. **子集判定**（`subset_outside_stats`）：改用精确 float64 点-网格判定
   （`trimesh.proximity.signed_distance`，正值=内部），**容差 1e-3 mm 不变**；旧量具的
   数值并排保留在 `checks.damaged_subset_clean.approx_open3d_max_outside_mm`。
4. **计账**：被丢弃的残留体在 ledger/`audit.pinhole_closure` 里逐项记录
   （数量、面数、体积、补孔数、ΔV），不隐藏。

### 2.3 before / after 实测

| 项 | 修复前 | 修复后 |
|---|---|---|
| `audit_physical.status` | **FAIL** | **PASS** |
| `failure_codes` | `DAMAGED_NOT_SUBSET_OF_CLEAN`, `NON_POSITIVE_VOLUME`, `NOT_WATERTIGHT` | `[]` |
| 组件 | 3（core 1 + debris 2，其中 2 个体积 0.0） | **1**（CORE，69349.69521397488 mm³，87174 面，watertight **True**，euler 2） |
| 子集 max_outside（精确） | 3.7e-6 mm（旧量具报 1.402e-3 → FAIL） | **2.6133040176739605e-06 mm**，越界采样 0/1200 |
| 水密 | 主连通体 6 条边界边 | 补 2 个环（ΔV = 0.0 mm³）→ 水密 |
| `lost_volume_mm3` | 276.58071298516006 | **276.58071298516006（不变）** |
| 材料账 | `debris_volume 0.0`、`component_count 3` | `component_count 1`、assembly：`connected_bodies 3 → material 1 / non_material 2（各 2 面，0.0 mm³）`、`pinholes_filled 2` |
| 恒等（level 0）对照审核 | FAIL（`max_outside 0.0087`） | **PASS** |
| 窄带 P03 对照审核 | FAIL（`DAMAGED_NOT_SUBSET_OF_CLEAN`） | **PASS**（精确 max 2.28e-08 mm） |

**语义边界要说清**：本次修复**没有**更换 P03 算子，损伤量级不变
（276.5807 mm³ 逐位相同）；改变的是"交付体必须是闭合正体积固体 + 子集用精确量具判"。
窄带 P03 仍只由 `degrade.axes` 使用（其损伤量级不同：本例 37.45 mm³ vs 线性预估
43.54 mm³），**不属于**本次 pipeline 语义变更。

### 2.4 影响面

| 角色 / 字段 | 变化 |
|---|---|
| `physical_component`（代表体网格） | **几何变更**：补 2 个纳米三角（87172 → 87174 面），ΔV = 0.0 |
| `physical_result`：`qa`、`audit_failure_codes`、`components`、`ledger` | **语义变更**（QA_FAIL → QA_PASS；组件 3 → 1） |
| `physical_result`：`lost_volume_mm3/ratio` | 不变（逐位相同） |
| `physical_truth` / `visible_labels` / `label_bundle` | 随 physical_result 的组件集合与 QA 变化（残差关联数量、可见层） |
| `damage_semantics` / `subset_instrument` 标记 | 新增（§3） |

---

## 3. 批产数据的分界与判别方法

**分界（事实陈述）**：本提交点之前生成的一切 run 与资产是旧语义；之后是新语义。已有的
`data/a12`、`data/a12_exports/closed_loop/store` 内资产**全部**属于旧语义（它们没有任何
语义标记，见下）。`configs/a12/next_experiment.yaml`（sha256 `81866531…`）与
`tools/batch_generate.py` **未被修改**；`batch_generate` 逐母体调用
`synlab.pipeline.build_one_mother`，因此**下一个批次自动带新标记、按新语义产出**。

标记写入位置（全部可程序化读取，不依赖时间戳）：

| 位置 | 键 | 取值 |
|---|---|---|
| run 记录（`metadata.sqlite` 的 `runs.meta_json`） | `data_semantics` | `{mask_semantics, damage_semantics, subset_instrument, defined_in}` |
| `reports/coverage.json` 与 `coverage.parquet`/`coverage_rows.json` | `data_semantics` | 同上 |
| `obs_result` 资产 `meta.meta.data_semantics` | `data_semantics` | 同上 |
| `physical_result` 资产 `meta` | `damage_semantics`、`subset_instrument` | `subset_v2` / 精确量具名 |
| `physical_component` 资产 `meta` | `damage_semantics` | `subset_v2` |
| `mother_mesh` / `fragment_mesh` / `feature_bundle` / `label_bundle` / `provenance` 资产 `meta` | `data_semantics` | 同上 |
| 每个渲染输出的 `RenderOutput.meta` | `mask_semantics`、`coc_optics` | `coc_units_v2` 等 |

**尚未带标记的角色**（其提交入口在本次写入范围之外）：`clean_truth`、`physical_truth`、
`visible_labels`、`pattern_recipe`、`pattern_channels`、`material_profile`。它们必须用
**所属 run 的标记**判别（同一个 run 的 `obs_result`/`physical_result`/`mother_mesh` 等一定带标记）。

**判别式**（可直接抄）：

```python
# 一个 physical_result 资产属于哪一代
sem = (record.meta or {}).get("damage_semantics")          # 缺失 => subset_v1_as_shipped
# 一个 observation 资产渲染时用的掩码语义
sem = ((record.meta or {}).get("meta") or {}).get("data_semantics", {}).get("mask_semantics")
# 一个 run 属于哪一代：看它自己产出的带标记角色（旧 run 一个都没有）
def run_semantics(store, run_id):
    for role in ("obs_result", "physical_result", "mother_mesh", "feature_bundle"):
        for asset in store.list_assets(role=role, limit=10000):
            meta = dict(asset.meta or {})
            if str(meta.get("run_id")) != str(run_id):
                continue
            sem = meta.get("data_semantics") or (
                {"damage_semantics": meta["damage_semantics"]}
                if meta.get("damage_semantics") else
                ((meta.get("meta") or {}).get("data_semantics")))
            if sem:
                return sem
    return {"mask_semantics": "coc_units_v1_pixel_units",
            "damage_semantics": "subset_v1_as_shipped"}   # 无标记 = 变更前
```

```sql
-- 直接查库（assets.meta_json / runs.meta_json 是 JSON 文本列）
SELECT run_id,
       json_extract(meta_json, '$.data_semantics.mask_semantics')   AS mask_semantics,
       json_extract(meta_json, '$.data_semantics.damage_semantics') AS damage_semantics
FROM runs ORDER BY created_at;
-- 逐资产：physical_result 的 damage_semantics / obs_result 的 mask_semantics
SELECT role, qa_status,
       json_extract(meta_json, '$.damage_semantics')                          AS dmg,
       json_extract(meta_json, '$.meta.data_semantics.mask_semantics')         AS mask,
       COUNT(*) FROM assets GROUP BY role, dmg, mask;
```

**实测的批产混批情况（重要）**：`tools/batch_generate.py` 的每个批次是一个独立进程，
本次语义变更落地时该队友正在跑批，因此 `data/a12` 里**同一个 run 也会混代**——
实测 `run_c1bf35c0ae7b0387`（变更落地瞬间在跑的那一批）里既有带标记的
`obs_result`（`mask_semantics=coc_units_v2`）/`physical_result`（`damage_semantics=subset_v2`），
也有不带标记的旧语义资产；变更之前的 7 个 run（`run_e69efa4c…`、`run_c8e819f2…`、
`run_1f0eb1ef…`、`run_bdc7b25b…`、`run_92f4b8e5…`、`run_e031b565…`、`run_2fad0ac4…` 等）
**全部**无标记（实测脚本 `data/a12/reports/probe_batch_semantics.py`，结果
`data/a12/reports/batch_data_semantics.json`）。
结论：**按资产/按角色的 meta 判别，不要按 run_id 或时间戳判别**；混批 run 的数据要么按标记
分开用，要么整批重生成。`configs/a12/next_experiment.yaml`（sha256 `81866531…`）与
`tools/batch_generate.py` 未被改动。

---

## 4. 本次**没有**放宽的判据

- `coc_px_threshold` 补偿保持原样（1.65 px，严于 profile 的 2.0 px）。
- `damaged ⊆ clean` 容差保持 **1e-3 mm**；只换量具（并被恒等对照证明原量具不可满足）。
- 水密/正体积判据不变；纳米孔只在"小于声明尺度"时才补，大洞照旧 FAIL。
- `visible_labels` 的 QA 判据（至少一个对应采样可见）不变；修复后它靠自己转 PASS。
- 审核不修几何：`audit_physical.no_auto_repair.geometry_hashes_unchanged = true`（逐次实测）。

## 5. 复现命令与留档

```powershell
# 1) CoC 单位复核（解析 + 反演 DOF + before/after，含 .npz 归档可离线复算）
& .venv\Scripts\python.exe data\a12\reports\verify_coc_units.py `
    --store <store> --obs <obs_asset> --out data\a12\reports\coc_units_v2_verification_l0.json
# 2) A09 根因（逐组件水密/体积/子集、量具对照、补孔策略）
& .venv\Scripts\python.exe data\a12\reports\probe_a09_p03.py --store <store>
& .venv\Scripts\python.exe data\a12\reports\probe_a09_geometry.py --store <store>
& .venv\Scripts\python.exe data\a12\reports\probe_a09_subset_instrument.py --store <store>
& .venv\Scripts\python.exe data\a12\reports\probe_a09_seam.py --store <store>
& .venv\Scripts\python.exe data\a12\reports\probe_a09_acceptance.py --store <store>
# 3) 单母体端到端（新 store：data/a12/reports/l0_after_fix/store）
& .venv\Scripts\python.exe data\a12\reports\run_l0_after_fix.py
```

| 留档 | 内容 |
|---|---|
| `data/a12/reports/coc_units_v2_verification_l0.json` | §1.2/§1.4 全部数字 |
| `data/a12/reports/coc_units_v2/<obs>_views.npz` | 逐视图 depth/id/K/旧掩码（离线复算 before/after） |
| `data/a12/reports/visible_labels_coc_units.json` | 队友的旧量具实测（比值 74.105） |
| `data/a12/reports/a09_p03_probe.json` / `..._after.json` | A09 修复前后逐组件实测 |
| `data/a12/reports/a09_p03_geometry.json` | marching cubes 候选 / 裁剪 / 修补策略对照 |
| `data/a12/reports/a09_subset_instrument.json` | 量具噪声底与恒等对照（决定性证据） |
| `data/a12/reports/a09_p03_seam.json` | 6 条边界边的几何与 fill_holes 失效实测 |
| `data/a12/reports/a09_signed_distance_convention.json` | 两个库的符号约定 |
| `data/a12/reports/a09_acceptance_after.json` | 四个对照的审核结论 |
| `data/a12/reports/l0_after_fix_census.json` | 新语义下的单母体端到端 census |
| `data/a12/reports/l0_after_fix_v2_census.json` | 追加标记后的复验 census（全角色标记覆盖） |
| `data/a12/reports/batch_data_semantics.json` + `probe_batch_semantics.py` | 批产 store 的逐 run/逐资产标记实测（混批证据） |
| `data/a12/reports/l0_role_census.json` | 旧语义下的同一 census（对照组） |

测试（退出码；junit XML 留档 `data/a12/reports/junit_*_after_fix.xml`）：

| 命令 | 退出码 | 计数 |
|---|---|---|
| `-m pytest tests/a12/observe -q` | **0** | 60 tests / 0 failed / 1 skipped（skip = 本机无 Blender 的用例） |
| `-m pytest tests/a12/truth -q` | **0** | 24 tests / 0 failed / 1 skipped |
| `-m pytest tests/a12/operators -q` | **0** | 156 tests / 0 failed / 0 skipped |
| `-m pytest tests/a12/integration -q` | **0** | 39 tests / 0 failed / 0 skipped |
| 三个套件合并一次跑（要求项） | **0** | 240 tests / 0 failed / 0 errors / 2 skipped |

新增回归测试（锁死两处语义，判据未放宽）：

- `tests/a12/observe/test_coc_units.py`：v2 = 毫米制薄透镜式 × `D`；反演 profile 声明 DOF；
  旧表达式被 `D·N·(z-f)/z` 放大；光学解析来源（spec/frame/注册表）；`mask_semantics` 标记；
  合焦平板物体像素无一被 defocus 丢弃。
- `tests/a12/operators/test_damage_legality.py`：0 体积残留不当组件（且"全残留"时仍保留最大体，
  失败可见）；纳米孔补面（水密+体积不变）；真洞拒补；"先丢残留再补孔"的顺序；
  精确量具在自身对照下为 0 越界；恒等结果必须 PASS；真正越界仍 FAIL。

## 6. 单母体端到端验收（新语义）

新 store：`data/a12/reports/l0_after_fix/store`，run `run_548e5b5a4a27b144`（config
`configs/a12/sandbox.yaml`，`max_mothers=1`）。

| 验收项 | 修复前（`run_563ae39481ee5ff5`） | 修复后（`run_548e5b5a4a27b144`） |
|---|---|---|
| `visible_labels` QA | **QA_FAIL**（`no correspondence sample is visible in any view`，samples_visible 0/1448） | **QA_PASS**（`pass=true`、`samples_visible 146/1448 = 10.08 %`、逐视图 visible 144/0/0/2） |
| `physical_result` QA | **QA_FAIL**（3 个 failure code） | **QA_PASS**（`audit_status=PASS`、`failure_codes=[]`、`damage_semantics=subset_v2`） |
| store QA 计数 | QA_PASS 10 / QA_PENDING 3 / **QA_FAIL 2** | QA_PASS **12** / QA_PENDING 3 / **QA_FAIL 0** |
| 视图 uncertain（物体像素） | 2343 / 2040 / 1681 / 1700 | **0 / 0 / 0 / 0** |
| mask 覆盖率 | 7.20 / 2.10 / 0.26 / 1.42 % | **89.41 / 85.40 / 81.44 / 82.22 %** |
| CoC p50（物体像素） | 17.15 / 21.71 / 31.03 / 29.36 px | **0.2365 / 0.2992 / 0.4312 / 0.4078 px** |
| CoC 低于 2.0 px mark-out | 0.46 / 0.29 / 0.05 / 0.11 % | **100 % ×4** |
| 物体 z 跨度 | 94.25 / 88.31 / 88.31 / 92.68 mm | 相同（几何通道未变） |
| 交付网格 DOF 窗口（`c_px ≤ 2.0 px`） | — | [167.4, 261.6] mm 等，**覆盖 z 跨度** |

QA_PENDING 的 3 个角色（`pattern_channels`、`pattern_recipe`、`physical_component`）是
release 准备阶段才定判的既有设计，与本次语义无关。

**可复现性 + 标记覆盖**：换一个全新 store 重跑同一 config（
`data/a12/reports/l0_after_fix_v2/store`，`data/a12/reports/l0_after_fix_v2_census.json`）
得到**逐位相同**的数值（mask 2533/2029/1553/1558 px、覆盖率 0.8941051888457465…、
CoC p95 0.5460063742385314…、`lost_volume_mm3 276.58071298516006`、visible 146/1448、
QA_PASS 12 / QA_PENDING 3 / QA_FAIL 0）。该 run 的 15 个资产里 **9 个自带标记**：

| 角色 | 标记 |
|---|---|
| `mother_mesh`、`fragment_mesh`×2、`feature_bundle`、`label_bundle`、`provenance` | `meta.data_semantics` |
| `obs_result` | `meta.meta.data_semantics`（`mask_semantics=coc_units_v2`） |
| `physical_result` | `meta.damage_semantics=subset_v2` + `meta.subset_instrument` |
| `physical_component` | `meta.damage_semantics=subset_v2` |
| `clean_truth`、`physical_truth`、`visible_labels`、`pattern_recipe`、`pattern_channels`、`material_profile` | 无（提交入口在本次写入范围外）→ 按所属 run 的上面 9 个角色判别 |
