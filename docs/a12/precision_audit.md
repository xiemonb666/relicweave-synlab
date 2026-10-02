# A12 全链精度审计（扫描台契约 × 合成数据，逐项对照）

> **性质**：**只读审计 + 文档**。本次未修改任何代码 / 配置 / 既有数据；
> 只新增 `docs/a12/precision_audit.md`、`data/a12/reports/precision_audit.json`
> 与探针脚本 `data/a12/reports/precision_probe_0*.py` / `.json` / `.txt`。
>
> **扫描台规格来源**：一律引用 `configs/a12/capture_contract.json` 的字段名与 `source` 指针
> （`T###/p####` = docx body 顺序第 ### 表 / 第 #### 段，1 基），文档口径见 `docs/a12/rig_contract.md`。
>
> **诚实规则**：
> 1. 每个数字都给**复算命令**（脚本名 + 参数）；引用他人文档的数字**都注明**是引用还是本次实测。
> 2. `capture_contract.json` 里标 `documented_candidate` 的（`P95 位置误差 0.5 mm`、`净空 20 mm`、
>    `0.2 mm 结构 ≥4 px`）**一律按候选值引用**，不写成已实测门。
> 3. 拿不到的度量写 `missing`，**不填 0 分、不用估计值冒充**。
> 4. 候选值不当实测值：`G07` 的 `focal_ratio 0…3% / principal 0…5 px`、`G06` 的 `ratio_error 0…5%`
>    是**退化轴的量级**（本次已实测其施加精度），**不是**真实相机的标定精度。
>
> **审计时点的代码状态（含并发写入者警告）**：`git HEAD = 5959a42`
> （`fix: align the exported relation pool with the mate-set contract (rank task becomes trainable)`）。
> 本次审计**自己**没有改动任何已跟踪文件、配置或既有数据；但审计期间**有其它 agent 在同一工作区写入**，
> 实测 `git status --porcelain` = **5 个已修改的已跟踪文件 + 约 50 个未跟踪路径**（计数在审计过程中
> 从 44 升到 53，因为并行任务在持续新建文件；`precision_audit.json` 的 `code_state.git_status_porcelain`
> 是装配那一刻的逐行快照）：
>
> | 已修改（**不是本次审计改的**） | 未跟踪（含本次新增） |
> |---|---|
> | `synlab/fracture/api.py`、`synlab/fracture/cut.py`、`synlab/relations/sampler.py`、`tests/a12/relations/pool_fixtures.py`、`tests/a12/relations/test_sampler.py` | 本次新增：`docs/a12/precision_audit.md`；其余是并行任务的在建文件（`configs/a12/fracture_calibration.json`、`configs/a12/fracture_morphology.yaml`、`synlab/fracture/calibrate.py`、`synlab/fracture/calibration.py`、`tests/a12/fracture/_*.py`、`tests/a12/relations/test_mate_absent_negatives.py`、`tools/relation_negatives_fix.py`、大量 `_*.txt` 探针输出） |
>
> → **本文的所有数字都是"某个时刻的字节快照"**。凡涉及 `synlab/fracture/**`（断面几何）
> 与 `synlab/relations/**`（关系/负例）的结论，在并发写入停止后**需要重新快照**。
> 复算命令：`git log --oneline -3; git status --porcelain`。
>
> **审计时点的数据状态**：仓库里同时存在**修复前**与**修复后**两代 store。这是本次审计最重要的一条
> 结构性事实：**同一个维度用不同 store 会得到差一个数量级的结论**。本文每个数字都标明取自哪个 store。

| store | 代际（本次实测判据） | 本次用作 |
|---|---|---|
| `data/a12`（主库，894 资产） | **修复前**：`surface_tag=2` 像素 = 0、`physical_component` 55/55 件 `face__origin_kind` 全 = 2、无 `face__interface_id` | 扫描台契约的"全量分母"现状 |
| `data/a12_campaign/store`（167 资产，288 视图 768×1024） | **修复后**：rim 像素 > 0、`physical_component` 6/9 件带 `face__interface_id` | 当前最新一代全面板 |
| `data/a12_final/store`（30 资产，72 视图 768×1024） | **修复后**：rim 7/7 资产非零、`mask_semantics` 生效（覆盖 99.3%、uncertain 0.07%） | 最新一代端到端 |
| `data/a12_exports/trainable/next_experiment/training_package` | **修复后**：`tokens` 有效秩 256、`view_pos` 非零、`frame_id` 有语义块（98.75% 匹配） | 训练包精度 |
| `data/a12_exports/next_experiment|closed_loop/training_package` | **修复前**：`tokens` 有效秩 1、`view_pos` 全零、`frame_id == arange(n)%n_views` | before 对照 |

---

## 1. 成像精度：mm/px 档位 vs 合成渲染的实际采样密度

### 1.1 扫描台规格（引用）

| 项 | 值 | 标记 | source |
|---|---|---|---|
| 采集距离 | 10 / 15 / 20 / 25 cm 起测，5–10 cm 局部近摄 | 【文档】 | `p0511` |
| 分辨率表 | 50 mm→**0.039**、100→**0.078**、150→**0.117**、200→**0.156**、250→**0.195** mm/px | 【文档】 | `t051` |
| 理想针孔公式 | `d_ideal = a × N_x / [2 p × tan(FOV_h/2)]` | 【文档】 | `p0518` |
| 采样目标 | **0.2 mm 结构 ≥4 px** = pilot 起点；**6–8 px** = 细节候选目标 | 【文档·候选】 | `p0517` |
| 明确否认 | **不是** 0.2 mm 测量精度承诺 | 【文档·不承诺】 | `p0517` |
| 必须分开报告 | `px_per_mm`、`r_eff_mm`、毫米测量误差、检索收益 | 【文档】 | `p0515` |

契约字段：`working_distance_and_resolution.resolution_table.rows[*].mm_per_px`、
`structure_sampling_targets.pilot_start` / `detail_goal`、`camera.node_a_detail.resolution_nominal_px`。

### 1.2 合成现状（本次实测）

**（a）文档阶梯本身能在代码里精确复现**（说明"档位"的实现没有量纲错误）：

```
50 mm  → mm/px 0.039     px_per_mm 25.641   0.2 mm = 5.128 px   coverage 90.040 mm
100 mm → mm/px 0.078     px_per_mm 12.821   0.2 mm = 2.564 px   coverage 180.081 mm
150 mm → mm/px 0.117     px_per_mm  8.547   0.2 mm = 1.709 px   coverage 270.121 mm
200 mm → mm/px 0.156     px_per_mm  6.410   0.2 mm = 1.282 px   coverage 360.162 mm
250 mm → mm/px 0.195     px_per_mm  5.128   0.2 mm = 1.026 px   coverage 450.202 mm
```
复算：`python data/a12/reports/precision_probe_04_calib_tokens.py`
→ `documented_ladder.rows`（脚本经 `synlab.degrade.specs.capture_rig_spec()` 读取 `t051` 表并按 `p0518` 外推）。
契约表的 `structure_0p2mm_px`（5.12 / 2.56 / 1.71 / 1.28 / 1.02）与本次复算逐位一致。

**（b）合成渲染的实际采样密度**（`mm_per_px = depth_z / K[0,0]`，逐像素实测后取中位；**不是**用档位声明值）：

| store | 视图数（分辨率） | 工作距离中位 / 范围 mm | **mm/px 中位** | **px_per_mm** | 4 px 可分辨尺寸 | 8 px 可分辨尺寸 | 0.2 mm 占几像素 |
|---|---|---|---|---|---|---|---|
| `data/a12`（修复前） | 412（396×768×1024 + 16×192×256） | 203.34 / 49.89–254.70 | **0.29288** | **3.414** | **1.172 mm** | 2.343 mm | **0.68 px** |
| `data/a12_campaign/store` | 288（全 768×1024） | 190.52 / 23.00–251.76 | **0.27193** | **3.677** | **1.088 mm** | 2.175 mm | **0.74 px** |
| `data/a12_final/store` | 72（全 768×1024，`fx=700.632` 单一值） | — | ~0.270 | ~3.70 | ~1.08 mm | — | ~0.74 px |

复算：`python data/a12/reports/precision_probe_02_observation.py --store data/a12 --out data/a12/reports/precision_probe_02_observation.json`
与 `--store data/a12_campaign/store --out .../precision_probe_02b_campaign.json`；
每个数字都在 `.json` 的 `roles.obs_result.views[*].mm_per_px_at_median_depth` 里逐视图可查。

**（c）三档相机 profile 的声明 vs 实际对象空间采样**（profile 自身的 `focal_px_1024=900/1050/1260`、
`fov_mm=320×240 / 250×188 / 180×135`）：

| profile | 工作距离 mm | 声明水平覆盖 mm | 隐含 mm/px | 0.2 mm 占几像素 | 对齐 `t051` 的哪一档 |
|---|---|---|---|---|---|
| `GLOBAL_V1` | 420 | 320 | 0.3125 | **0.64 px** | 无（比 400 mm 档更远） |
| `MID_V1` | 360 | 250 | 0.2441 | **0.82 px** | 无（350 mm 落在 300/400 之间） |
| `LOCAL_V1` | 300 | 180 | 0.1758 | **1.14 px** | 无（300 mm 不在 50/100/150/200/250 五档内） |

复算：`python -c "import json;d=json.load(open('configs/a12/camera_profiles.json'));print([(p['profile_id'],p['working_distance_mm'],p['fov_mm'][0],p['fov_mm'][0]/1024) for p in d['profiles']])"`。

### 1.3 可分辨特征尺寸的计算（契约要求"给出计算"）

对象空间一个像素覆盖 `s = z / f_px`（mm/px）。一个尺寸为 `w` 的特征占 `w/s` 个像素。

* **4 px 判据**（`p0517` pilot 起点）：`w_resolvable(4px) = 4 × s`。
  在**当前交付分辨率下**：`s = 0.27193 mm/px` → `w_resolvable(4px) = 1.0877 mm`。
* **6–8 px 判据**（`p0517` 细节候选目标）：`w_resolvable(8px) = 8 × s = 2.1754 mm`。
* 反过来问合同里的 "0.2 mm 结构"：`0.2 / 0.27193 = 0.7355 px`。

**结论（差距）**：
1. **在任何一个已物化的工作距离上，0.2 mm 结构都达不到 4 px**。合成渲染实测最浅的距离是
   `23.00 mm`（`data/a12_campaign/store` 最小 `depth_mm_median`），在那一档 `s = 0.0328 mm/px`
   → 0.2 mm = **6.09 px**，**只有这一个"贴近到 2.3 cm"的极端视图能过 4 px 门**；
   按**中位工作距离**（190–203 mm）衡量，0.2 mm 结构只有 **0.68–0.74 px**，差 **5.4–5.9 倍**。
2. **三档分辨率 profile（GLOBAL/MID/LOCAL）没有一档的 `px_per_mm` 与 `t051` 对齐**：
   `GLOBAL_V1=3.20`、`MID_V1=4.10`、`LOCAL_V1=5.69` px/mm，而 `t051` 最近的档位是 250 mm→5.13 px/mm。
   `configs/a12/camera_profiles.json` 里没有 `px_per_mm` / `r_eff_mm` 字段（**missing**）：
   `r_eff_mm` 在全仓 **0 个生产者**（`precision_probe_03_postfix.json` →
   `meta_key_presence.r_eff_mm = 0/894`），`px_per_mm` 只在 13/894 个资产里出现且来自纹样栅格规划，
   不是 `resolution_profile` 的实测字段。

**修法与优先级**：
* **P1**：`configs/a12/camera_profiles.json` 加 `50/100/150/200/250 mm` 五档并对齐 `t051` 的
  mm/px；同时给每档补 `px_per_mm`、`r_eff_mm`、`dof_cover_mm`、`effective_roi`（契约 §
  `calibration.px_per_mm` 要求"实测，非标称"；`resolution_profiles.profile_fields` 明列这四个字段）。
  **口径**：`px_per_mm` 必须写**实测**值；在没有真实标定前只能写 `declared` 并带 `assumption` 标记。
* **P1**：把"为达到 0.2 mm ≥4 px 需要的**最大**工作距离"写成可复算门：
  `z_max = 0.2 mm / 4 × f_px`。在本机实测 `f_px = 1279.43 px`（原生 2304 宽）时
  `z_max = 63.97 mm`；在交付 768 宽时 `f_px = 700.632 px` → `z_max = 35.03 mm`；
  在交付 256 宽时 `f_px = 233.5 px` → `z_max = 11.68 mm`。
  → **契约的 10–25 cm 验收距离与 0.2 mm≥4 px 在交付网格上不可同时成立**，必须显式写成
  "0.2 mm 细节只能在 ≤35 mm（768 宽交付）处成像"，否则该门永远无法在真实台架上闭合。
* **P2**：`r_eff_mm` 补一个生产者（`observe/` 或 `diagnostics/`），定义为
  `r_eff_mm := 4 × z / f_px` 并随分辨率档写出——目前契约要求"必须分开报告"而实现是 0 产出。

---

## 2. 几何精度：网格最小特征、断面间隙、法向一致性

### 2.1 扫描台规格（引用）

| 项 | 值 | 标记 | source |
|---|---|---|---|
| P95 位置误差 | **0.5 mm**（**仅候选**，按景深与密度收紧） | 【文档·候选】 | `p0533` |
| H4 复述 | 0.5 mm 重复误差是**测试候选，按实物和任务冻结，不写成已测** | 【文档·候选】 | `p1796` |
| 净空 | 20 mm（候选守卫，与光学工作距离分字段） | 【文档·候选】 | `p0531` |
| 回零测试 | 每点 10 次进退回零（测刻度、画面漂移、清晰度、耗时） | 【文档】 | `p0533` |
| 无编码器 | 回报 `commanded_position` + `position_estimated=true`，**不伪称实测位置** | 【文档】 | `p0533`/`p0563` |
| 断面级门（工程） | 共享面距离 P95 ≤ **0.02 mm**、法向反向 P95 ≤ **2.0°** | 【工程阈值】 | `qa_protocol_v1.json` `A06_shared_distance_p95_mm` / `A06_normal_reverse_angle_p95_deg` |

### 2.2 合成现状（本次实测）

**（a）母体 / 碎片网格的边长分布**（`mm`，逐资产三角形三边）：

| store | role | 件数 | 最小边长 | p01 | p05 上界 | p50 范围 | 中位面面积 mm² |
|---|---|---|---|---|---|---|---|
| `data/a12`（修复前） | `fragment_mesh` | 154 | **1.907e-06** | 0.02114 | 4.405 | 1.660–19.154 | 0.587–83.78 |
| `data/a12` | `mother_mesh` | 71 | **1.902e-06** | 6.823e-04 | 22.160 | 2.046–204.591 | 0.755–3163.17 |
| `data/a12` | `physical_component` | 55 | **3.725e-09** | — | — | 0.312–10.244 | — |
| `data/a12_final/store`（修复后） | `fragment_mesh` | 6 | 7.727e-03 | 0.20665 | 4.770 | 7.016–9.344 | 17.55–21.65 |
| `data/a12_final/store` | `mother_mesh` | 1 | **1.4004** | 1.44177 | 1.882 | 17.994 | 25.359 |

边长低于 1e-3 mm（= 微米级退化片）的边占比：主库 `fragment_mesh` 最大 **0.258%**、
`mother_mesh` 最大 **1.333%**、`physical_component` 最小边低到 **3.7e-09 mm**；
修复后 `data/a12_final` 为 **0.0%**。

复算：`python data/a12/reports/precision_probe_05_geometry.py --store data/a12_final/store`
与 `... --store data/a12 --out data/a12/reports/precision_probe_05_geometry_main.json`。

**（b）断面几何间隙 P95 与法向一致性 P95**（`clean_truth` 的 `iface_*` 数组，逐 interface 一个值）：

| store | `clean_truth` 件数 | interface 总数 | `iface_gap_p95_mm` 中位 | **`iface_gap_p95_mm` p95** | **max** | `iface_normal_p95_deg` 中位 | p95 | max | 歧义面积比 max |
|---|---|---|---|---|---|---|---|---|---|
| `data/a12`（修复前） | 55 | **573** | 4.326e-08 | **1.0094e-06** | **1.1641e-05** | 1.070e-05 | 3.487e-04 | 5.707e-03 | 0.9658 |
| `data/a12_final/store`（修复后） | 1 | 35 | 4.650e-07 | **3.5603e-06** | 4.095e-06 | 3.195e-05 | 5.781e-04 | 1.353e-03 | 0.0 |

**用户提到的 "1.16e-05 mm 量级"已被复现**：它是主库 573 个 interface 里
`iface_gap_p95_mm` 的**最大值 `1.1641479373104904e-05 mm`**（不是 P95 本身）；
P95 本身是 **1.0094e-06 mm**，中位 4.33e-08 mm。

**（c）配对断面逐样本对应残差**（`clean_truth.corr_residual_mm`，n=59 948）：
中位 **3.55e-15 mm**、p95 **1.60e-07 mm**、max **5.51e-05 mm**。

### 2.3 与 `P95 位置误差 0.5 mm（候选）` 的对照

| 量 | 实测 | 与 0.5 mm 候选的关系 |
|---|---|---|
| 断面几何间隙 P95（主库，n=573） | **1.0094e-06 mm** | 小 **约 5.0e5 倍**（契约候选值完全不是瓶颈） |
| 断面几何间隙 max | **1.1641e-05 mm** | 小 约 4.3e4 倍 |
| 法向一致性 P95 | **3.487e-04°** | 门是 2.0°，小 约 5.7e3 倍 |
| 配对残差 p95 | 1.60e-07 mm | 小 约 3.1e6 倍 |
| **网格最小特征（退化片）** | 主库低到 **1.9e-06…3.7e-09 mm** | **反向不达标**：比 0.5 mm 小 8–9 个数量级 → 是**数值噪声/退化三角形**，不是真实结构 |

**结论（差距）**：
1. **断面几何精度远超所有候选门**：`gap_p95` 与法向一致性的实测值比 0.5 mm / 2.0° 松门小
   3–9 个数量级。契约的 `P95 位置误差 0.5 mm` **不构成合成侧瓶颈**；相反，合成侧的断面误差
   小到没有物理意义（它是同一个布尔切出来的两个共面片，误差是浮点噪声）。
   → **不能说"合成侧几何精度达标"**：它只是"比 0.5 mm 小得多"，**不代表**真实重建精度。
2. **真正的几何精度风险在网格退化片**：主库 `physical_component` 的最小边 **3.725e-09 mm**
   （≈ 3.7 皮米），`mother_mesh` 的 p01 低到 **6.8e-04 mm**，`fragment_mesh` 有 **0.258%** 的边
   短于 1e-3 mm。这些边在 0.27 mm/px 的渲染下**永远不可采样**，但会污染法向估计、
   面积统计与下游 QEM 简化。
3. **两代 store 之间几何噪声差 3–4 个数量级**（`fragment_mesh` 最小边 1.9e-06 → 7.7e-03 mm），
   说明主库的退化片来自**已经修复的写入路径**；主库仍是修复前的字节。

**修法与优先级**：
* **P0**：把主库几何重新生成一代（或至少重跑 `clean_mesh` 路径），使 `fragment_mesh`/`mother_mesh`/
  `physical_component` 的 `frac(edge < 1e-3 mm)` 归零——修复后的 `data/a12_final` 已经是 0.0%，
  所以**这是"用新字节替换旧字节"，不是新算法**。
* **P1**：给 `qa_protocol_v1.json` 加一条**网格退化门**（当前没有）：
  `A31_degenerate_edge_frac_max = 1e-6` 与 `A31_min_edge_mm ≥ 1e-3`，并在 `audit_mother`/
  `physical_result` 的 QC 里报 `frac_edge_below_1e-3mm`。当前 24/24 器型的 QA 闸门
  "看不见这类缺陷"（`docs/a12/mother_geometry_audit.md` §0 第 4 条已实测同一现象）。
* **P2**：`P95 位置误差 0.5 mm` 在没有真实台架前**不要**写成合成侧对标项——合成侧没有台架重复定位
  这个概念（每个视图的 `T_WC` 是构造出来的），只能报 `missing`。

---

## 3. 观测精度：深度误差、CoC/mark-out、掩码覆盖率、Blender vs CPU

### 3.1 扫描台规格（引用）

| 项 | 值 | 标记 | source |
|---|---|---|---|
| 深度上报 | float32 或定义 scale 的 uint16；**先区分相机 z 和光线距离**；invalid mask 独立 | 【文档】 | `p0459`/`t104` |
| 景深数值 | `spec: unspecified`（只把景深列为必测） | 【未明确】 | `p0504`/`p0511`/`p0515`/`p0518`/`p0533`/`p0579` |
| 景深定性规则 | "宁可稍远拍高分辨率再裁 ROI，也不要让前缘/后缘大面积离焦" | 【文档】 | `p1159` |
| 3D 质量下限（Q2 当量） | 有效点 ≥50%、σ ≤0.2 mm、≤2 个 r≤3 mm 孔洞 | 【工程约定·假设】 | 契约 `quality_3d_floor_q2_equivalent`（**文档未明写**） |
| 泊松/读噪声 | 等级表 `photon_gain (0,16000,8000,4000,1000)`、`read_sigma (0,0.002,0.004,0.008,0.016)` | 【工程实现】 | `synlab/observe/realism.py:88-93` |

### 3.2 合成现状（本次实测 + 引用）

**（a）深度误差**（引用 `docs/a12/observe_evidence.md` §8 第 4 条，原始产物
`data/a12/reports/blender/1024_12/`）：

| 后端 | 与独立射线投射对照的深度误差中位 | p99.9 | 可见性分歧 | 最大误差 |
|---|---|---|---|---|
| **Blender Cycles（1024 px，12 视图）** | **0.074–0.134 mm** | **0.87–4.13 mm** | 0.03–0.16% | — |
| 软件光栅（同一对照） | 0.004–0.013 mm | — | 1.2–1.3% 轮廓分歧 | **17.7–48.6 mm** |
| 解析平面（1024 px） | **0.0 mm** | 0.0 mm | — | 0.0 mm |
| 斜面夹具上界（屏幕空间线性 z 插值） | — | — | — | **8.885 mm** |

**（b）CoC / mark-out**（引用 `docs/a12/data_semantics_versions.md` §1.4，
主库 `mask_semantics` 缺失，见下）：

| 量 | 修复前（4 视图） | 修复后（4 视图，`data/a12/reports/l0_after_fix_v2/store`） |
|---|---|---|
| CoC p50（物体像素） | 17.15 / 21.71 / 31.03 / 29.36 px | **0.2365 / 0.2992 / 0.4312 / 0.4078 px** |
| CoC p95 | — | **0.546 / 0.505 / 0.521 / 0.597 px** |
| **低于 profile 自己 2.0 px mark-out 的物体像素占比** | 0.46% / 0.29% / 0.05% / 0.11% | **100% × 4** |
| 低于 pipeline 阈值 1.65 px 的占比 | — | 100% |
| 物体 `uncertain` 像素数 | 2343 / 2040 / 1681 / 1700 | **0 / 0 / 0 / 0** |
| mask 覆盖率（`mask_semantics=coc_units_v2`） | 7.20 / 2.10 / 0.26 / 1.42 % | **89.41 / 85.40 / 81.44 / 82.22 %** |
| 4 视图 mask 并集 | 243 px | **3218 px**（平均单视图覆盖率 2.75% → **84.61%**） |

**（c）本次独立复算（`precision_probe_08_masks.py`，用文档 §1.3 的 `coc_units_v2` 公式）**：
`CoC_px = |z − focus| / z × f / N × D`，`focus = median(depth_z)`，`f = 3.12520 mm`、`N = 2.0`、`D = 409.39 px/mm`：

| store | 视图 | 物体像素占全帧 | **mask / 物体像素**（均值，min–max） | mask / 全帧 | uncertain / 物体 | CoC p50 中位 | **CoC < 2.0 px 的物体像素占比（均值）** | ≥99.99% 达 mark-out 的视图数 |
|---|---|---|---|---|---|---|---|---|
| `data/a12`（修复前） | 412 | 28.78% | 52.24%（0.00–99.76%） | 14.44% | **45.71%** | 34.55 px | **4.85%** | **0 / 412** |
| `data/a12_campaign/store` | 288 | 39.70% | 88.75%（6.57–99.72%） | 36.12% | 9.29% | 38.58 px | 5.55% | 0 / 288 |
| `data/a12_final/store` | 72 | 57.11% | **99.27%（97.10–99.72%）** | 56.70% | **0.072%** | 30.15 px | 5.50% | 0 / 72 |

> **注（不掩盖）**：`data/a12_final` 的 mask 覆盖率 **99.27%** 高于 `l0_after_fix_v2` 的 81–89%，
> 因为 `l0_after_fix_v2` 的物体像素只有 1895–2833（256×192 交付网格、物体占比低），
> 而 `data/a12_final` 是 768×1024、物体占 57%——**分母不同，不是同一个量**。
> 两者都远高于修复前主库的 52.24%。

**（d）主库的 `mask_semantics` 标记**：`precision_probe_08` 实测 `data/a12`（412 视图）、
`data/a12_campaign`（288）、`data/a12_final`（72）的 `mask_semantics` 值全部是 **`None`**。
`data/a12_final/store` 的 6 个 `obs_result` 里 **6 个**带 `meta.surface_tag_pixels`（断面像素账本），
但**没有一个**带 `mask_semantics` → **无法从产物本身判断 CoC 是 v1 还是 v2 口径**。

**（e）Blender vs CPU 数值差异**（引用 `docs/a12/gpu_acceleration.md` §3.6，
原始产物 `data/a12/reports/gpu/compare_cpu_vs_cuda.json`，12 视图逐通道字节比对）：

| 通道 | 逐位相同 | 不同元素数 | 占比 | 最大绝对差 | p99 绝对差 | 中位 |
|---|---|---|---|---|---|---|
| `visibility` / `occlusion` / `target_visibility` | **是** | 0 | 0 | 0 | 0 | 0 |
| **`id_map` / `surface_tag` / `uncertain_mask` / `object_index`**（分类通道） | 否 | **各 1** | **1.1e-7** | 5 / 1 / 1 / 2 | 0 | **0** |
| `depth_z` | 否 | 103 358 | 2.9e-1 | **214.25 mm** | 3.05e-5 mm | **0** |
| `rgb_linear` | 否 | 825 272 | 2.9e-2 | 0.0442 | 1.19e-7 | **0** |

深度阈值的精确表述（原文）：**356 968 个两run都有效的深度像素里，恰好 1 个差异 > 0.001 mm**
（view 8, y=328, x=621，是轮廓像素，两设备解析到相距 214 mm 的不同表面）；
其余所有差异像素都 < 1 µm（float32 插值舍入）。`rgb_linear`：28 311 552 个元素里
**20 个**差异 > 0.01、2415 个 > 1e-6。

### 3.3 差距与修法

| # | 差距（本次实测） | 优先级 | 最小修法 |
|---|---|---|---|
| 1 | 主库（894 资产、412 视图）**全部是修复前的 mask/CoC 字节**：uncertain/物体 **45.71%**、mask/物体 52.24%、CoC<2 px 只 **4.85%** | **P0** | 重新生成主库观测（或用 `mask_semantics=coc_units_v2` 在同一 `depth_z` 上重算 `deployment_mask`/`uncertain_mask`——`docs/a12/data_semantics_versions.md` §1.4 已证明这是同一批深度图的纯重算，不是重渲染） |
| 2 | 三个 store 的 `mask_semantics` 都是 `None` → **口径不可从产物自证** | **P0** | `observe/routes.py` 把 `mask_semantics` 写进 `obs_result.meta`（`data/a12_final` 已经有 `meta.surface_tag_pixels`，同一个写出点加一个字符串即可） |
| 3 | 交付 mask 覆盖率均值 **36.12%**（`data/a12_campaign`，最差视图 6.57%）与主库 **14.44%**，低于"够用"直觉但**契约没有数值门** | P2 | 契约 `quality_3d_floor_q2_equivalent.valid_point_fraction_min_pct = 50%` 是**点云**有效点比例，不是像素 mask 覆盖率——**不要**直接套用；若要门控，应先在 `qa_protocol_v1.json` 新增一条带出处的阈值 |
| 4 | 深度误差（Blender 中位 0.074–0.134 mm、p99.9 0.87–4.13 mm）**没有与 `σ ≤ 0.2 mm`（Q2 当量）逐视图对照** | P1 | 把 `blender/1024_12` 的逐视图深度误差写进 `reports/` 并与 `σ≤0.2mm` 逐视图比；当前只有区间值，**不能**判定"达标/不达标" |
| 5 | 软件光栅的尾部误差 **17.7–48.6 mm**（Blender 的 4–12 倍）在生产库里是 114/114 的默认后端 | P1 | 生产库改走 Blender（库内 Blender 产物 **0/114**）；或在 `obs_result.meta` 里把"尾部误差上界"作为质量通道上报 |

---

## 4. 标定精度：哪些轴是候选值，要成为实测需要什么

### 4.1 扫描台规格（引用）

| 项 | 值 | 标记 | source |
|---|---|---|---|
| 内参 | 逐稳定工况保存独立 `fx/fy/cx/cy` + **畸变参数** | 【文档】 | `p1163` |
| `px_per_mm` | **实测（非标称）**；`resolution_profile` 必含实测 `px_per_mm` 与 `r_eff_mm` | 【文档】 | `p0579`/`p0515` |
| `working_distance_mm` | 存在；**光学工作距离须注明测法** | 【文档】 | `p0511` |
| 三类位置 | 命令 / 估计 / 实测位置**分别记录** | 【文档】 | `p0563`/`p0577`/`p0591` |
| 尺度基准 | 每次正式采集必须含**可追溯尺度基准**（标尺/AprilTag/ArUco/coded target/标定板），重建后**自动检查绝对尺度漂移** | 【文档】 | `p1163` |
| 尺度漂移指标 | 已知标尺/marker 尺寸与重建尺寸偏差；**每次采集必报** | 【文档】 | `t097` |
| 标定版本字段 | `calibration_id` / `intrinsics_profile_id` / `rig_calibration_rev` 存在；移动支架或装夹即更新 | 【文档】 | `p0427`/`p0574`/`p0531` |
| 畸变模型与阶数 | `spec: unspecified` | 【未明确】 | 见 `rig_contract.md` §9.2 |
| 镜头型号／焦距 | `spec: unspecified`；契约兜底值 **约 f=3.6 mm 等效** | 【未明确】+【兜底假设】 | 契约 `camera.lens.fallback_mainstream`（`assumption: true`） |
| 焦距推导（裁决 D6） | `f = 2.4902/tan(42°) = **2.77 mm**`，与契约的 3.6 mm **不一致**（只记录，不改写契约） | 【工程推导·假设】 | `docs/a12/decision_record.md` D6 |

### 4.2 审计结果：这些轴现在用的是候选值还是实测值？

| 轴 | 当前来源 | 实测判定（本次复核） | 证据 |
|---|---|---|---|
| **真实相机焦距** | **候选/推导** | `synlab/degrade/specs.py` 由 `FOV_h=84°` + `1/2.8"` 反推 `f = 3.12520 mm`（本次复算），标 `DERIVED`；契约兜底是 3.6 mm、裁决 D6 推导是 2.77 mm → **三支并存，没有一支是实测** | `precision_probe_04` → `documented_ladder.focal_length_mm = 3.1252012858255296` |
| `f_number` | **候选** | `provenance = CANDIDATE`，值 `2.0`，note 明写"文档未给 M12 镜头型号/焦距/f 值…待实测（用景深/靶标反解实孔径）" | 同上 `f_number_provenance=CANDIDATE` |
| 滚动快门行时间 `line_time_us` | **候选** | `8.9 µs`，`provenance=CANDIDATE`，note 明写"SC3336B 数据手册行时间不在计划内也未在本机实测，是 IMX415 级数值" | `precision_probe_04` → `line_time_provenance=CANDIDATE` |
| **`calibrated` 标志（3 个 profile）** | **未标定** | `configs/a12/camera_profiles.json`：3/3 `"calibrated": false`、`"calibration_refs": []`、`"status": "STRESS_UNCALIBRATED"` | `docs/a12/modality_census.md` §5.4（引用）+ 本次读 `configs/a12/camera_profiles.json` |
| `calibration_id` | **字段缺失** | 主库 894 资产 **0** 个带该键；`data/a12_final` 30 资产 **0**；`data/a12_trainable` 463 资产 **0** | `precision_probe_03_postfix.json` → `meta_key_presence.calibration_id = 0` |
| `rig_calibration_rev` | **字段缺失** | 同上，4 个 store 全 **0** | 同上 |
| `intrinsics_profile_id` | **字段缺失** | 同上，4 个 store 全 **0** | 同上 |
| `scale_drift` | **字段缺失** | 同上，4 个 store 全 **0**（`scale_valid` 有 123/894，但那是渲染器构造的布尔，不是漂移量） | 同上 |
| `r_eff_mm` | **字段缺失** | 全仓 **0** 生产者 | 同上 |
| `px_per_mm` | **半缺失** | 只有 13/894（主库）带该键，来自纹样栅格规划；`resolution_profile` 的实测 `px_per_mm` **不存在** | 同上 |
| **G07 焦距 0–3% / 主点 0–5 px** | **退化轴量级，已实测其施加精度** | 本次独立复跑：`focal_ratio` 4 档施加误差 ≤ **4.9e-17**（相对 ≤1.7e-14）；`principal_px` 5.0 px 档、`distortion_scale` 0.3 档均 PASS；**副作用实测**：`focal_ratio=0.03` 时重投影半径 p95 = **25.07 px**、深度偏差均值 **1.561 mm** / p95 **2.637 mm** | `precision_probe_09_degrade_error.json`；复算 `precision_probe_07`（`audit_all_axes`）|
| **G06 尺度漂移 0–5%** | **退化轴量级，已实测其施加精度** | 本次独立复跑：`ratio_error` 4 档施加误差 ≤ **1.1e-16**（相对 ≤2.2e-14）；`truth_reference_untouched = 1.0` | 同上 |

> **重要区分（不把候选值当实测值）**：
> `G07 焦距 0–3% / 主点 0–5 px` 与 `G06 尺度漂移 0–5%` 是**退化算子的注入量级**，
> 本次审计证明的是"**算子把声明的注入量准确施加了**"（误差 ~1e-16），
> **不是**"真实相机标定精度是 0–3%"。真实相机的焦距/主点误差**至今没有测量**——写 `missing`。

### 4.3 "要成为实测需要什么"

| 轴 | 要成为实测需要的输入 | 可验收判据（建议，带出处） | 落地位置（最小改法） |
|---|---|---|---|
| `fx/fy/cx/cy` + 畸变 | 一块**已知尺寸**的棋盘/AprilTag 标定板，在 10/15/20/25 cm 四个距离各采 10–20 张，板面占画幅 ≥1/3，逐工况单独解算；再重复 3 次量化重复性 | 重投影残差 RMS ≤ **0.2 px**（工程建议，文档无数值）；3 次重复的 `fx` 相对散度 ≤ **0.2%**；`(cx,cy)` 散度 ≤ **0.5 px** | `configs/a12/camera_profiles.json` 的 `calibrated: true` + `calibration_refs[]`；`synlab/cameras/profiles.py` 的 `intrinsics_profile_id` |
| 光学工作距离 | **注明测法**（例如"镜头前沿到样品中心的卡尺读数"/"标定板反解"），逐 profile 记录 | 同一次装夹内重复读数散度 ≤ **0.5 mm**（对话候选值 `p0533`；**不是**文档门） | `working_distance_mm` 旁加 `working_distance_method` 字段 |
| 绝对尺度漂移 | 画面里放**可追溯尺度基准**（高精度标尺 / AprilTag / ArUco / coded target，`p1163`）；重建后自动比对已知尺寸 | 偏差 ≤ **0.2%**（工程建议；`p0517` 明确"不是 0.2 mm 测量精度承诺"） | `synlab/qc/` 加 `scale_drift` 度量并**每次采集必报**（`t097`）；合成侧可先放**虚拟 coded target**（`p1164` 口径：coded target 不进学习/匹配输入，必须剔除或 mask） |
| `rig_calibration_rev` | 每次移动支架/装夹后自增 | 与 `calibration_id` 联动、可查询 | `synlab/roles.py` + `pipeline.py` 的资产 meta |
| `r_eff_mm` | 由 `px_per_mm` 与判据算：`r_eff_mm := k × z / f_px`（k = 4 或 6–8） | 与 `t051` 表的 `structure_0p2mm_px` 逐档对齐 | `resolution_profile` 写出点 |
| 真实焦距（0.2 mm 结构的成像能力） | 靶标反解 + 与 `t051` 的 `coverage_mm` 交叉验证 | 实测水平覆盖与 `t051` 声明的偏差 ≤ **2%** | `specs.py` 的 `focal_length_mm.provenance` 由 `DERIVED` 升为 `MEASURED` |

---

## 5. 退化精度：31 轴各档的施加量 vs 声明量

### 5.1 扫描台规格（引用）

| 项 | 值 | 标记 | source |
|---|---|---|---|
| 31 轴退化 | 实物 8 / 成像 10 / 重建 8 / 输入 5 | 【文档】 | `t109` |
| pilot 分组 | 每组先 2 轴 | 【文档】 | `t109` |
| 14 维退化向量 D | 每分量保留**物理或数值单位、随机种子和操作顺序**；"不要只存一个 `quality=0.7`" | 【文档】 | `p0365` |
| 独立母体数 | `A10_min_independent_mothers_per_axis = 20` | 【工程阈值】 | `qa_protocol_v1.json` |

### 5.2 合成现状：31/31 轴、155/155 档 PASS（本次独立复跑）

```
axes_registered 31  axes_audited 31  axes_pass 31  axes_na 0  axes_fail 0  axes_missing 0
levels_planned 155  levels_passed 155  levels_na 0  levels_failed 0
identity_ok True    all_axes_pass True    耗时 16.3 s
```
复算：`python data/a12/reports/precision_probe_09_degrade_error.py`
（其输入 `data/a12/reports/precision_probe_07_degrade_audit.json` 由
`synlab.degrade.api.audit_all_axes(None, levels=[0,1,2,3,4])` 生成，源为 `probe_sources()`）。

**level 0 恒等**：31/31 轴 `identity=true` **且** `source_hash == result_hash`，
**0 个失败**（`precision_probe_09_degrade_error.json` → `level0_failures = []`）。

### 5.3 逐项：施加量 vs 声明量（有配对量的轴）

配对定义（"哪个 `measured_*` 验证哪个 `planned_*`"）逐条打印在
`precision_probe_09_degrade_error.json` → `pair_definition`，可程序化复核：

| 轴 | 声明量 → 验证量 | 档位实测（L1…L4） | **绝对误差** | **相对误差** | 门/预算 |
|---|---|---|---|---|---|
| **P03** | `planned_depth_mm` → `measured_applied_depth_mm` | 0.05 / 0.10 / 0.25 / 0.50 mm | **0.0（4/4 精确）** | **0.0** | — |
| **P04** | `planned_contact_loss_target` → `measured_achieved_contact_loss` | 0.100032 / 0.250237 / 0.500158 / 0.800252 | 3.156e-05 / 2.367e-04 / 1.578e-04 / 2.524e-04 | 3.16e-04 / 9.47e-04 / 3.16e-04 / 3.16e-04 | 预算 **0.02**（实测 ≤ 2.5e-4，余量 79×） |
| **P02** | `planned_max_recession_mm` → `measured_measured_max_recession_mm` | 0.053276 / 0.106551 / 0.159827 / 0.213102 mm | 0.0（4/4 精确） | 0.0 | — |
| **P07** | `planned_depth_mm` → `measured_realized_max_recession_mm` | 0.024991 / 0.049984 / 0.099969 / 0.199947 mm | 8.5e-06 … 5.3e-05 | ≤ **3.4e-04** | — |
| **P08** | `planned_affected_area` → `measured_achieved_affected_area_fraction` | 0.055538 / 0.103503 / 0.200694 / 0.300410 | 5.5e-03 / 3.5e-03 / 6.9e-04 / 4.1e-04 | **1.11e-01** / 3.50e-02 / 3.47e-03 / 1.37e-03 | 无门（L1 相对误差 **11%**，最大） |
| **G01** | `planned_target_rms_mm` → `measured_applied_rms_mm` | 0.056529 / 0.112226 / 0.555599 / 1.081413 | 6.5e-03 … 8.1e-02 | **1.31e-01** / 1.22e-01 / 1.11e-01 / 8.14e-02 | **系统性偏大 8–13%**（不是随机误差） |
| **G03** | `planned_retained_coverage` → `measured_retained_coverage` | 0.8 / 0.6 / 0.4 / 0.2 | **0.0（4/4 精确）** | 0.0 | — |
| **G06** | `planned_ratio_error` → `measured_measured_ratio − 1` | 0.005 / 0.01 / 0.025 / 0.05 | ≤ **1.1e-16** | ≤ **2.2e-14** | 真值 hash 不变（实测 `truth_reference_untouched=1.0`） |
| **G07** | `planned_focal_ratio` → `measured_focal_after/before − 1` | 0.005 / 0.01 / 0.02 / 0.03 | ≤ **8.4e-17** | ≤ **1.7e-14** | 副作用：重投影 p95 半径 24.46→25.07 px；深度偏差均值 1.474→1.561 mm |
| **G04** | `planned_translation_mm` → `measured_translation_mm` | 2.0（L4） | 0.0 | 0.0 | 重融合残差 p95 2.993 mm / max 11.712 mm（**实测副作用**） |
| **G05** | `planned_max_error_mm` → `measured_max_error_mm` | 0.1（L4） | 0.0 | 0.0 | 独立 Hausdorff **0.05038 mm**（≤ 预算 0.1）、面数 692→46（ratio 0.9335） |
| **G02** | `planned_keep_fraction` → `measured_keep_fraction` | 0.0625（L4） | 0.0 | 0.0 | 点密度 0.5724 → 0.1385 pt/mm² |
| **G08** | `planned_height_mm` → `measured_measured_max_displacement_mm` | 0.353756 / 0.751523 / 1.117096 / 1.915498 | 4.6e-02 / 4.8e-02 / **2.83e-01** / **2.85e-01** | 1.16e-01 / 6.06e-02 / **2.02e-01** / 1.29e-01 | 无门（相对误差最大 **20.2%**） |

**汇总**：
* `n_levels = 155`，其中**有配对量的只有 36 档（9 个轴：P02/P03/P04/P07/P08/G01/G03/G06/G07）**
  → **剩下 22/31 轴的"施加量 vs 声明量"无法从审计表直接读出**
  （`precision_probe_09` → `unpaired_axes = ["P01","P05","P06"]` = **连 `planned_*` 键都没有**的 3 个轴；
  另外 **19 个轴**有 `planned_*` 却没有对应的 `measured_*` 验证量，故也配不上对）。
* `max_abs_error = 0.28450`（G08 L4）、`max_rel_error = 0.20207`（G08 L3）；
  **相对误差 > 1% 的档位 = 10 个**（G01 ×4、G08 ×4、P08 L1/L2）。
* 施加精度最好的一族：**P03 / P02 / G03 / G06 / G07 / G02 / G04 / G05**（相对误差 ≤ 3.4e-04 或精确 0）。

### 5.4 差距与修法

| # | 差距 | 优先级 | 最小修法 |
|---|---|---|---|
| 1 | **22/31 轴没有"声明→验证"配对量**（其中 `P01/P05/P06` 连 `planned_*` 键都没有） | **P0** | 给这些轴补一个**与算子自身场无关**的验证量（`degrade_axes.md` §7 已为 P02/P03/P04 做了这件事：`measured_mean_recession_mm`、`measured_measured_max_vertex_shift_mm`、`target_abs_error`）——把同一模式推广到 `P01/P05/P06/P08/G01/G08/I*`。**判据**：`precision_probe_09` 的 `n_axes_with_paired_quantity` 从 9 升到 31 |
| 2 | **G01 系统性偏大 8–13%**（4/4 档同向） | P1 | `ops_geometry` 的低频相关深度场在归一化后与 `target_rms_mm` 有固定比例偏差 → 加一步"实测 RMS 反解尺度"（实测 `applied_rms/target` 均值 1.1195） |
| 3 | **G08 相对误差最大 20.2%**（L3/L4 的实测位移比声明小 0.28 mm） | P1 | 声明量 `height_mm` 与验证量 `measured_max_displacement_mm` 不是同一件事（伪面高度 vs 融合后最大位移）→ 补一个 `measured_spurious_height_mm`（直接在伪面上量），或把声明改成"目标位移"并校准 |
| 4 | **P08 L1 相对误差 11.1%**（受影响面积比 0.05 声明 → 0.0555 实测） | P2 | 裂纹宽度搜索的下界；L1 档的目标面积太小（0.05 是接触面积比），建议把 L1 目标提到 ≥0.08 或报"档位不可达" |
| 5 | `independent_mothers_observed = 1` vs 要求 **20**（`A10`） | P1 | 数据集级要求，需在真实母体库上跑 `audit_all_axes`；当前审计**只用了 1 个独立母体**，所以 155/155 PASS 的**独立性分母是 1** |
| 6 | 155/155 全是"单一 variant"（每族只跑 `default_variant`） | P2 | 跑 `VARIANT_LEVELS`（G07 已有 `principal_only`/`distortion_only`/`calibration_profile` 三个额外 variant）并落盘 |

---

## 6. 特征 / 标签精度

### 6.1 扫描台规格（引用）

| 项 | 值 | 标记 | source |
|---|---|---|---|
| `loss_mask` 唯一监督门 | `valid` 降为派生别名；`eligible_as_negative` 必须由 `kind ∈ {R1,R0} ∧ loss_mask` 计算 | 【裁决 D10】 | `docs/a12/decision_record.md` D10 |
| 关系真值 | R2 邻接 / R1 同器非邻接 / UNKNOWN；**对称**，UNKNOWN 不自动转负 | 【文档】 | `t042` |
| 质量向量存储 | 每项附 `valid` 及来源 `OBS_EST` 或 `GT_ORACLE` | 【文档】 | `t104` |
| 观测法向 | 观测估计单位法向 + `normal_valid` + 估计邻域与误差 | 【文档】 | `t104` |
| 部署白名单 | 只给 RGB + 部署 mask + 相机 u 位置；禁 `depth_z/id_map/surface_tag/K/T_WC` | 【文档·权限】 | `t044`/`t104` |

### 6.2 合成现状（本次实测）

**（a）`loss_mask` / `eligible_as_negative` 语义一致性**

| 包 | 关系行 | `kind` 分布 | `valid=true` | `loss_mask=true` | `loss_mask ≡ valid` | `loss_mask ≡ (kind=="R2")` | `eligible_as_negative=true` | `has_observation=true` |
|---|---|---|---|---|---|---|---|---|
| `data/a12_exports/trainable/next_experiment/training_package`（修复后，**最新**） | **1721** | `R0:1560, UNKNOWN:106, R2:28, R1:24, TINY_CONTACT:3` | 1591 | **1588** | **False** | **False** | **1560** | 830 |
| `data/a12_exports/next_experiment/training_package`（修复前） | 150 | `R1:117, R2:33` | 33 | 33 | True | True | **0** | 0 |
| `data/a12_exports/closed_loop/training_package_v2`（修复后） | 3 | `R2:3` | 3 | 3 | True | True | 0 | 0 |
| `data/a12_exports/closed_loop/training_package`（修复前） | 3 | `R2:3` | 3 | 3 | True | True | 0 | 0 |
| `data/a12_degrade/exports/rel_degrade_diversity_1790919754/training_package` | 1 | `R2:1` | 1 | 1 | True | True | 0 | 1 |

复算：`python data/a12/reports/precision_probe_04_calib_tokens.py` →
`packages[*].relations`。

**结论（语义一致性）**：
* **修复前的三个包全部满足 `loss_mask ≡ valid ≡ (kind=="R2")`**，也就是 D10 描述的"联动约束"：
  `eligible_as_negative` **结构恒为 0**（合法负样本供给为 0）。
* **最新的 `trainable/next_experiment` 包打破了这个恒等式**：1721 行里 `loss_mask ≠ valid`
  （1591 vs 1588，差 3 行 = `TINY_CONTACT` 的 `valid=True, loss_mask=False`），
  `loss_mask ≠ (kind=="R2")`，`eligible_as_negative = 1560`（**合法负样本首次非零，
  与 HEAD `5959a42` 的提交信息"rank task becomes trainable"一致**）。
  D10 的派生公式 `kind ∈ {R1,R0} ∧ loss_mask` 在 1721 行上**逐行成立**
  （`eligible = 1560`，其中 R0 1560 行全部 `loss_mask=true`）。
* **`loss_mask` 与 `valid` 的差异必须显式说明**：3 行 `TINY_CONTACT` 是 `valid=true & loss_mask=false`，
  与 D10 的"`valid` 是 `loss_mask` 派生别名"**不一致**——要么改写出方，要么把 D10 的措辞
  改成"`valid` 是 `loss_mask` 的**弱**别名（`valid` 可为 True 而 `loss_mask` 为 False）"。
  当前 README/数据卡的 `loss_mask` 语义需要跟着更新，否则下游按 D10 字面读会错。

**（b）`tokens` 有效秩**（`sv[1]/sv[0]` 与"1e-3 相对奇异值以上有几列"）

| 包 | 实体数（抽样） | `tokens` 形状 | **`sv[1]/sv[0]`** | `rank(1e-3)` | `rank(1e-2)` | `rank(1e-1)` |
|---|---|---|---|---|---|---|
| `data/a12_exports/next_experiment/training_package`（修复前） | 8 | (576, 256) | **3.7e-09 … 6.8e-09** | **1 / 256** | 1 | 1 |
| `data/a12_exports/closed_loop/training_package`（修复前） | 3 | (192, 256) | 5.6e-09 … 7.5e-09 | **1 / 192** | 1 | 1 |
| `data/a12_exports/closed_loop/training_package_v2`（修复后） | 3 | (192, 256) | 0.462 … 0.684 | **192 / 192** | 141–186 | 11–20 |
| **`data/a12_exports/trainable/next_experiment/training_package`（修复后，最新）** | 8 | (576, 256) | **0.132 … 0.869** | **256 / 256** | 33–256 | 2–14 |
| `data/a12_degrade/exports/rel_degrade_diversity_1790919754` | 2 | (192, 256) | 0.628 / 0.728 | 192 / 192 | 169 / 184 | 15 / 19 |

**"有效秩 256"已被复现**：最新包 8/8 实体的 `rank(1e-3) = 256 = token_dim`，
`sv[1]/sv[0]` 从 **3.7e-09 升到 0.132–0.869**（提升 **7–8 个数量级**）。
但**要一起读**：`rank(1e-1)` 只有 **2–14**，即"能量集中在少数方向"仍然成立——
`tokens` 现在是**真实的 256 维特征**，不是 256 个独立自由度。

**（c）`frame_id` 匹配率**

| 包 | 几何索引 `frame_id` 语义块 | **匹配率** | 匹配/总数 | 行号计数器关系 |
|---|---|---|---|---|
| `data/a12_exports/next_experiment/training_package`（修复前） | **无该块** | — | — | **`frame_id == arange(n) % 12` 精确成立（8/8 实体）** |
| `data/a12_exports/closed_loop/training_package`（修复前） | **无该块** | — | — | **`frame_id == arange(n) % 4` 精确成立（3/3 实体）** |
| `data/a12_exports/closed_loop/training_package_v2`（修复后） | 有 | **0.9793354273433625** | 5924 / 6049 | 不成立（`distinct=5`，含 `-1`） |
| **`data/a12_exports/trainable/next_experiment/training_package`（修复后，最新）** | 有 | **0.98754674826927** | 5 107 971 / 5 172 384 | 不成立（`distinct=13`，含 `-1`） |

`frame_id` 定义（包内索引原文）：**"the delivered view whose rendered `depth_z` agrees with the point
reprojected through `K` and `T_WC`; `-1` = no delivered view explains the point"**，
容差 `tolerance_mm = 5.0`。
→ **`97.9%` 已被复现**（closed_loop v2 = 0.97934）；**最新包是 98.75%**。
剩下的 1.2% / 2.1% 是 `frame_id = -1`（没有任何交付视图能在 5 mm 内解释该点）。

**（d）`view_pos` 与真值误差 0.0 mm**

| 包 | `view_pos` 形状 | 非零/总数 | `absmax` | 均值 | 索引声明块 |
|---|---|---|---|---|---|
| `next_experiment/training_package`（修复前） | (12,) | **0 / 12 × 4 shard** | **0.0** | 0.0 | 无 |
| `closed_loop/training_package`（修复前） | (4,) | **0 / 4** | **0.0** | 0.0 | 无 |
| `closed_loop/training_package_v2`（修复后） | (4,) | 4 / 4 | 5.0956 mm | −5.0956 | 有（`definition`/`measurement`/`unit=mm`） |
| `trainable/next_experiment/training_package`（修复后，最新） | (12,) | 12 / 12 × 4 shard | 73.47–127.12 mm | −54.21 … −0.56 | 有 |

`view_pos` 定义（包内索引原文）："**camera slide coordinate in the scan frame, read from the
delivered pose `T_WC` as `T_WC[0,3]`** -- the same definition `synlab.degrade.api` uses for a
`ViewFrame`'s `u_position_mm`"；缺省 `nan`。
→ **"误差 0.0 mm" 已被复现，但要说清是哪一种 0.0**：修复后包的定义是
`view_pos := T_WC[0,3]`（**读出来的真值本身**，所以"与真值误差"按构造就是 **0.0 mm**）。
它**不是**"`u_position_mm` 与实测滑架位置之差"——真实滑架读数**不存在**（无编码器，
命令位置为开环估计，契约 `mechanics.no_encoder`）。因此：
* `view_pos` 现在**有真实非零内容**（修复前 0/31 全零，修复后 100% 非零）；
* `view_pos` 与**实测**位置的误差 = **missing**（合成侧没有实测滑架位置）。

**（e）`u_position_mm` 的实际取值范围**：最新包 4 个 shard 的 `absmax` = 73.47 / 77.11 / 86.44 / 127.12 mm。
契约 `mechanics.u_axis_near_far.travel_mm_nominal = 150 mm`、`travel_mm_reserved_range = [100, 200]`
→ **127.12 mm 在 150 mm 行程内，量级合理**；但 `data/a12/camera_profiles.json` 的
`max_travel_mm = 120.0`，**127.12 > 120** → 若 profile 是权威，则该值是超程的。
两条口径不一致，**需要人工裁决**（本次只记录，不改任何一侧）。

### 6.3 差距与修法

| # | 差距 | 优先级 | 最小修法 |
|---|---|---|---|
| 1 | **`loss_mask` 与 D10「`valid` 是派生别名」在最新包上不成立**（3 行 `TINY_CONTACT`：`valid=True, loss_mask=False`） | **P0** | 二选一：① 把 `valid` 也改成 `loss_mask` 的严格别名（写者改一行）；② 更新 D10 措辞为"弱别名"并同步 `docs/a12/export_guide.md` §2.7。**不能两边都不动**——下游按 D10 字面读会得到 3 行错误的监督资格 |
| 2 | 主库 `data/a12` 的 `physical_truth`/`visible_labels` **完全没有 `iface_*`**（`iface_keys = {}`） | P1 | `synlab/truth/api.py` 把 `iface_*` 下推到 physical/visible 层（`data/a12_final` 已经做到：physical 6 键、visible 5 键） |
| 3 | 主库 `visible_labels` QA_FAIL **23/41（56.1%）** | P1 | 引用 `docs/a12/modality_census.md` §6.2；根因是"没有可见有效样本"，`data/a12_final` 的同一路径已经 QA_PASS（`samples_visible 146/1448`）→ 重生成即解 |
| 4 | `view_pos` 与**实测**滑架位置误差 | P2 | 合成侧**做不到**：契约 `mechanics.no_encoder` 明确"无编码器则实测字段 null"。写 `missing`，不要造数 |
| 5 | `u_position_mm` 上限口径不一致（包内 127.12 mm vs profile `max_travel_mm=120`） | P1 | 人工裁决：以 `t052` 的"约 150 mm，预留 100–200 mm"为权威修订 `camera_profiles.json` 的 `max_travel_mm` |

---

## 7. 断面可分辨性：2D 像素数与占物体像素比

### 7.1 扫描台规格（引用）

| 项 | 值 | 标记 | source |
|---|---|---|---|
| 断口局部 2D | 逐真实断口**多角度近摄**；实际断裂表面、两侧壁、厚度变化、边缘 | 【文档】 | `t042`/`p0431`/`p0881` |
| 每断口有效方向 | **3–6**（【工程约定】补齐计数目标，文档只说"多角度"） | 【工程约定】 | 契约 `capture_checklist.fracture_local_2d.effective_directions_per_fracture` |
| 区域 mask | 整数 ID（内外壁/断面/支撑/无效区），**无损**，PNG 中 ID 严格可恢复 | 【文档】 | `t101(D09)`/`t117`/`p1481` |
| 失效规则 | "没拍到断裂面不能用于局部关系主测试" | 【文档】 | `t042` |

### 7.2 合成现状（本次实测，逐 store）

| store | `surface_tag` 总像素 | **`tag=2`（断面）像素** | **rim / 物体像素** | rim / 全帧 | 有 rim 的资产数 | 判据 |
|---|---|---|---|---|---|---|
| **`data/a12`（修复前，主库）** | 312 213 504 | **0** | **0.000000** | 0.0 | **0 / 37** | `probe_06_rim` 同值，本次独立复现 |
| **`data/a12` 的 `label_bundle`（修复前）** | 313 786 368 | **0** | 0.000000 | 0.0 | 0 / 45 | 同上 |
| **`data/a12_campaign/store`（修复后，288 视图）** | 226 492 416 | **4 999 163** | **0.0532003** | **0.0220721** | **25 / 28**（`obs_result` 21 个去重资产里 18 个 >0） | 本次实测 |
| `data/a12_campaign/store` 的 `label_bundle` | 37 748 736 | 431 637 | 0.0556975 | 0.0114345 | — | 本次实测 |
| **`data/a12_final/store`（修复后，72 视图）** | — | **2 553 808** | **0.0666786** | — | **7 / 7** | 本次实测 |
| `data/a12_iface/store`（修复后，8 视图 256×192） | 393 216 | **1 962** | **0.0183014** | 0.004990 | 2 / 2 | 与 `docs/a12/fracture_surface_signal.md` §4.4 的 1 962 / 107 205 = 1.83% 逐位一致 |

**逐资产 rim/物体（`data/a12_campaign/store`，21 个 `obs_result` 资产）**：
**3 个资产 rim = 0**（`asset_e570166e…`、`asset_3b53e232…`、`asset_9c9410da…`），
**18 个非零**：最小 **1.24%**（47 787 / 3 869 110）、中位 **3.70%**、
最大 **23.05%**（10 945 / 47 475，物体像素只有 47 475 的小目标）。
（另 4 个资产以 `label_bundle` 形式重复计数，故该表 28 行 = 21 个 `obs_result` + 4 个
`label_bundle` + 3 个重复 `obs_result`——**注意分母，不要把 28 当 28 个不同资产**。）

复算：`python data/a12/reports/precision_probe_12_rim_detail.py`（逐资产 rim/物体排序，
读 `precision_probe_03_postfix.json` 的 `data/a12_campaign/store.rim.per_asset`）。

### 7.3 与"断口面积占表面积比"的对照（差太远要给解释）

以 `data/a12_campaign/store` 的 **3D 断口面积占比**为基准（引 `docs/a12/fracture_surface_signal.md` §5.1
的实测口径：LIN0000 = **6.32%**、LIN0001 = **2.83%**、合计 **3.04%**）：

| 口径 | 数值 | 与 3D 面积占比的关系 |
|---|---|---|
| ① 3D 断口面积 / 总表面积（同一批谱系） | **3.04%** | 基准 |
| ② **前向投影**断口占比（`Σ area·max(0, n·u)`，逐视图均值） | **4.176% / 2.194%** | 斜视修正后是相机真正看到的份额 |
| ③ **rim 像素 / 物体像素**（`data/a12_campaign/store`，288 视图） | **5.32%** | ③ ÷ ① = **1.75**；③ ÷ ② ≈ **1.27–2.42** |
| ③′ rim / 全帧 | 2.21% | 全帧里物体只占 39.70% |

**解释（为什么 ③ 比 ① 大 1.75 倍）**：
* `data/a12_iface/store` 在 256×192 网格上测得 ③ ÷ ① = **0.60**、③ ÷ ② = **0.91/0.76**
  （`fracture_surface_signal.md` §5 的三条结论），方向是**③ < ①**；
* `data/a12_campaign/store` 在 768×1024 网格上测得 ③ ÷ ① = **1.75**，方向相反。
* 两个方向的差异来自**分母选择**：`campaign` 的 ③ 用的是"**整个资产的**物体像素"，
  而 ① 是"该谱系 3D 面积占比"，两者**不是同一个资产集合**（campaign 的 28 个 obs 资产覆盖多个谱系与多次退化）。
  **所以 1.75 这个比值不能读成"标签放大"**；它能说明的只有一件事：
  **断面在 2D 里已经是"可定位的显著信号"（5.3% 物体像素），不再是 0**。
* **可以下的结论**：修复前 ③ = **0**（断面在任何已物化的 2D 图/标签里既不可定位也不可分割）；
  修复后 ③ = **1.8%（256×192 小网格）… 6.7%（768×1024 大网格，单资产集合）**。
* **不能下的结论**：① vs ③ 的严格比值——两代 store 的资产集合、分辨率、退化状态都不同，
  需要**在同一批谱系上同时算 ①、②、③**才能给严格比值（`fracture_surface_signal.md` §5 做了这件事，
  结论是 ③÷② = 0.76–0.91；本次没有重复该实验，因为要跑新一批渲染）。

### 7.4 差距与修法

| # | 差距 | 优先级 | 最小修法 |
|---|---|---|---|
| 1 | **主库 `data/a12`（37 件 `obs_result`、412 帧、894 资产）rim 像素仍是 0** | **P0** | 重新生成主库观测（代码修复已在 HEAD：`synlab/physical/api.py` 现在写 `origin_kind` **与** `interface_id`，实测 `precision_probe_03` → `pc_interfaces` 在修复后 store 是 6/9、1/1、2/2，主库是 **0/55**）。**这是"用新字节替换旧字节"，不是新代码** |
| 2 | 3/28 个 `campaign` 资产的 rim = 0（`asset_e570166e…` 等） | P1 | 逐资产查 `meta.surface_tag_pixels.tag_source`：若为 `FACE_ORIGIN_KIND` 且 rim=0，说明该构件确实没有 `interface_id≥0` 的面（退化/母体表面件），应在 `qa_json` 里标 `NOT_APPLICABLE` 而不是静默 0 |
| 3 | 断面占物体像素 1.8–6.7%，**没有一条与"3D 面积占比"同批次的严格比值**（主库口径） | P1 | 在**同一批谱系**上同时出 ①/②/③ 三个数（`fracture_surface_signal.md` §5 的 `_probe_projected_share.py` 已有实现），并把结果写进 `reports/` |
| 4 | 断面在 2D 里"可定位"但**没有达到每断口 3–6 个有效方向**（契约【工程约定】） | P1 | 当前是 4 视图全向环，不是"逐断口多角度近摄"；需要 `fracture_local` 视图环（±10/20/30/40°）——见 `docs/a12/rig_contract.md` 覆盖矩阵 #2 的补齐方案 |

---

## 8. 训练包精度：数据卡逐列/逐通道 min/max/缺失率抽查

### 8.1 抽查对象与方法

抽查对象：`data/a12_exports/closed_loop/training_package_v2`
（**唯一同时带 `dataset_card.json` + 三个缺陷标记为 `fixed_in_this_package` 的修复后包**）。
方法：直接读包内字节，与数据卡声明逐项比对，**差值 ≤ 1e-9×|声明值| 才算相符**。

复算：`python data/a12/reports/precision_probe_06_datacard.py --package data/a12_exports/closed_loop/training_package_v2 --out data/a12/reports/precision_probe_06_datacard_cl_v2.json`

### 8.2 抽查结果：**328 项检查，328 相符，0 不相符**

| # | 抽查项（类别） | 项数 | 声明 vs 复算 |
|---|---|---|---|
| 1 | **逐文件 sha256** | **58** | 58/58 相符（`package.files` 每行的 `sha256` 对磁盘字节重算） |
| 2 | parquet 行数 | 7 | 全相符（`deploy/queries.parquet` 6 行等） |
| 3 | parquet 逐列 `missing_rate` | 90+ | 全相符（如 `queries.query_id = 0.0`、`relations.reason` 的缺失率） |
| 4 | parquet 逐列 `n_unique` | 90+ | 全相符（如 `lineage = 4`、`mother = 3`、`gallery = 1`） |
| 5 | parquet 数值列 `min` / `max` / `mean` | 30+ | 全相符（如 `historical_N_G` min 0 / max 1 / mean 0.5；`has_observation` min 0 / max 1 / mean 0.5） |
| 6 | npz 通道 `dtype` / `shape` / `true_rate` / `min` / `max` / `missing_rate` | 40+ | 全相符（`tokens` / `token_valid` / `frame_id` / `view_pos` 等） |
| 7 | **`tokens.effective_rank`** | 3 | 全相符（声明 192，按 1e-3 相对奇异值复算 = 192） |

**诚实边界（包自带，逐条实测状态）**：

| id | 状态（包内声明） |
|---|---|
| `tokens_broadcast_defect` | **`fixed_in_this_package`** |
| `view_pos_all_zero` | **`fixed_in_this_package`** |
| `frame_id_row_counter` | **`fixed_in_this_package`** |
| `no_legal_negatives` | `not_applicable`（R2 3 行、合法负例 0 行） |
| `deployment_mask_sparse` | `measured` |
| `undocumented_columns` | `complete`（0 列） |
| `deploy_view_channels` | `measured` |
| `deploy_view_answer_field_hit` | **`defect_present`** |

* **诚实边界（必须一起读）**：`closed_loop v2` 与 `next_experiment` 的 `deploy/obs/index.json` 已经
  把 `forbidden_channels` 从"8 项硬清单"换成一份 **8 通道的 `caveat`/`evidence_class` 清单**
  （本次实测：`channels` 是**对象数组**，含 `depth_z`（`CAVEAT_NOT_MEASURED_ON_REAL_RIG`）、
  `uncertain_mask`（`CAVEAT_ESTIMATOR_REQUIRED`）、`K`（`CALIBRATED_ON_REAL_RIG`），
  而 `forbidden_channels = null`）。
  这与**修复前**的 closed_loop/next_experiment 包不同——那两个包的
  `forbidden_channels` 是明确的 8 项字符串列表（含 `depth_z/id_map/surface_tag/uncertain_mask/roi/K/T_WC/dist`）。
  → **权限设计发生了实质变化**，且只在 `honest_boundaries` 里以
  `deploy_view_answer_field_hit = defect_present` 出现一次，**没有**在数据卡的"违约"栏目里暴露。
  这是"两边都不是"的状态：既不是硬白名单，也不是一个被记录的裁决。

### 8.3 `deploy_view_answer_field_hit = defect_present` 的逐条证据（本次实测）

`deploy/obs/index.json` 的 `channels` 在两个**修复后**包里是**对象数组**（每项带 `key` / `dtype` /
`unit` / `evidence_class` / `caveat` / `source_array`），而不是修复前的三个字符串：

| 通道 | 修复前包（`next_experiment` / `closed_loop`） | 修复后包（`closed_loop v2` / `trainable/next_experiment`） |
|---|---|---|
| `tiles`（RGB） | `"tiles.npy (uint8 RGB)"` | `{key: tiles, dtype: uint8, evidence_class: SENSOR_PROXY}` |
| `valid`（部署 mask） | `"valid.npy (deployment mask)"` | `{key: valid, dtype: bool, evidence_class: SENSOR_PROXY}` |
| `view_pos`（u 位置 mm） | `"view_pos.npy (u position mm)"` | `{key: view_pos, dtype: float32, evidence_class: RIG_COMMANDED, unit: mm}` |
| `depth_z` | **在 `forbidden_channels` 里**（禁止） | **出现在 `channels` 里**，标 `CAVEAT_NOT_MEASURED_ON_REAL_RIG`，`source_array: depth_z`，`unit: mm` |
| `uncertain_mask` | **在 `forbidden_channels` 里**（禁止） | **出现在 `channels` 里**，标 `CAVEAT_ESTIMATOR_REQUIRED` |
| `K` | **在 `forbidden_channels` 里**（禁止） | **出现在 `channels` 里**，标 `CALIBRATED_ON_REAL_RIG` |
| `roi` | **在 `forbidden_channels` 里**（禁止） | **出现在 `channels` 里**（`optional: true`） |
| `deployment_mask` | 不在 `channels` 也不在禁止列表 | **独立成一个通道**（`source_array: deployment_mask`） |
| `forbidden_channels` 键 | 8 项字符串列表 | **`null`** |

→ 结论（三条，全都是实测）：
1. **新增的 4 个通道**（`depth_z` / `uncertain_mask` / `roi` / `K`）在修复前是**明确禁止**的，
   现在被写进 `channels` 并标了 `caveat`/`evidence_class`。
2. **语义是"披露"而不是"允许"**：`evidence_class` 里 `K` 标的是 `CALIBRATED_ON_REAL_RIG`
   （即"真实台架上它会是标定得到的"，而本机 `calibrated=false`），
   `depth_z` 标的是 `CAVEAT_NOT_MEASURED_ON_REAL_RIG`。这是一种**诚实的证据分级**设计。
3. 但**数据卡的"违约"栏目没有跟着变**：`honest_boundaries.deploy_view_answer_field_hit`
   仍然是 `defect_present`，而 `forbidden_channels` 已经是 `null`。
   → **两处口径冲突**，必须由裁决落地为其中一种（见 §8.4 第 2 条）。

### 8.4 未被数据卡覆盖的部分（missing）

* 抽查对象只有 **1 个包**（`closed_loop/training_package_v2`）。
  **最新的 `trainable/next_experiment/training_package` 没有 `dataset_card.json`**
  → 它的 1721 行关系表、256 维 `tokens`、98.75% `frame_id` 匹配率**都没有数据卡可对照**。
* `precision_probe_06` 还有一项**结构性限制**：`arrays` 抽查上限 `--max-arrays 12`
  （每个族只查前 12 个数组），所以 `n_checks = 328` **不是**"全包逐通道"，
  只是"抽样大于等于 5 项"的强度。要全包逐通道需 `--max-arrays` 调到碎片数 × 通道数。

### 8.5 差距与修法

| # | 差距 | 优先级 | 最小修法 |
|---|---|---|---|
| 1 | **最新包 `trainable/next_experiment/training_package` 没有数据卡** | **P0** | `python tools/load_package.py --package data/a12_exports/trainable/next_experiment/training_package --write-card`（工具已存在；本次未执行，因为它会写包目录，属"改数据"） |
| 2 | `deploy_view_answer_field_hit = defect_present`（部署视图出现答案侧字段） | **P0** | 二选一：① 恢复 `forbidden_channels` 的硬清单（把 `depth_z/id_map/surface_tag/uncertain_mask/roi/K/T_WC/dist` 重新列入并**真的不写**）；② 若放开是决策，则在 `dataset_card` 里把它写成 `decision: allowed_by_<裁决编号>` 而不是 `defect_present`。当前状态**两边都不是** |
| 3 | 抽查只覆盖 1 个包、且数组抽查有 12 项上限 | P2 | 把 `--max-arrays` 提到全量，并把 `precision_probe_06` 挂进 `tools/check_data_quality.py` 的流水线（每包出一次数据卡一致性报告） |

---

## 9. 总表：维度 × 扫描台规格 × 合成现状 × 差距 × 修法 × 优先级

| # | 维度 | 扫描台规格（引用） | 合成现状（实测） | 差距 | 修法 | 优先级 |
|---|---|---|---|---|---|---|
| 1 | **成像精度** | 50/100/150/200/250 mm → 0.039/0.078/0.117/0.156/0.195 mm/px（`t051`）；0.2 mm ≥4 px，6–8 px 细节（`p0517`，候选） | 渲染实测 mm/px 中位 **0.27193**（campaign）/ 0.29288（主库）；0.2 mm = **0.74 px**；4 px 可分辨 **1.088 mm**；三档 profile 无一与 `t051` 对齐 | 0.2 mm 结构差 **5.4–5.9 倍**；`px_per_mm`/`r_eff_mm` 契约要求"实测"而 **`r_eff_mm` 全仓 0 生产者**；10–25 cm 与 0.2 mm≥4 px **不可同时成立**（768 宽交付需 ≤35.03 mm） | ① profile 加 5 档并对齐 `t051`；② 补 `px_per_mm`/`r_eff_mm`/`dof_cover_mm`；③ 把 `z_max = 0.2/4×f_px` 写成显式门 | **P1** |
| 2 | **几何精度** | `P95 位置误差 0.5 mm`（候选，`p0533`/`p1796`）；断面门 gap P95 ≤0.02 mm / 法向 ≤2.0° | gap p95 **1.0094e-06 mm**（max **1.1641e-05**）、法向 p95 **3.487e-04°**、配对残差 p95 1.60e-07 mm；**但**网格有退化片（`physical_component` 最小边 **3.725e-09 mm**，`fragment_mesh` 0.258% 边 <1e-3 mm） | 断面精度**远超**门（3–9 个数量级），不构成瓶颈；真正风险是**数值退化片**污染法向/面积/QEM；两代 store 几何噪声差 3–4 个数量级 | ① 主库几何重生成（修复后 store 已是 0.0%）；② 新增 `A31_degenerate_edge_frac_max` 与 `min_edge_mm` 门；③ 0.5 mm 在无真实台架前写 `missing` | **P0** |
| 3 | **观测精度** | 深度须分相机 z / 光线距离、invalid mask 独立（`p0459`/`t104`）；σ≤0.2 mm（Q2 当量·假设） | 深度误差中位 **0.074–0.134 mm**（Blender）/ p99.9 0.87–4.13 mm（引用）；**主库** mask/物体 **52.24%**、uncertain/物体 **45.71%**、CoC<2 px **4.85%**；**`data/a12_final`** mask/物体 **99.27%**、uncertain **0.072%**；Blender vs CPU 分类通道逐位相同、depth **1/356 968 像素 >0.001 mm** | 主库仍是修复前字节；**三代 store 的 `mask_semantics` 全是 `None`**（口径不可自证）；软件光栅尾部误差 17.7–48.6 mm | ① 主库重生成观测（v2 可在同一 `depth_z` 上纯重算）；② `meta.mask_semantics` 写出；③ 逐视图深度误差 vs σ≤0.2 mm 对照 | **P0** |
| 4 | **标定精度** | 逐工况 `fx/fy/cx/cy`+畸变（`p1163`）；`px_per_mm` 实测（`p0579`）；每次采集报 scale drift（`t097`）；尺度基准必备（`p1163`） | `f=3.12520 mm`（DERIVED）、`f/2.0`（CANDIDATE）、`line_time 8.9 µs`（CANDIDATE）；3/3 profile `calibrated=false`；`calibration_id`/`rig_calibration_rev`/`intrinsics_profile_id`/`scale_drift`/`r_eff_mm` 在 4 个 store **全部 0 命中**；G06/G07 的注入精度实测 ≤1e-16（**不是**标定精度） | **全部是候选/推导值**；真实的焦距/主点/尺度漂移**从未测量**；`px_per_mm` 只在 13/894 出现且非 resolution_profile 字段 | ① 标定板逐距离解算（残差 ≤0.2 px）；② 画面放可追溯尺度基准并自动查漂移；③ meta 补 `calibration_rev`/`rig_calibration_rev`/`intrinsics_profile_id` | **P0** |
| 5 | **退化精度** | 31 轴（`t109`），pilot 每组 2 轴；14 维 D 保留单位/种子/顺序（`p0365`）；独立母体 ≥20（`A10`） | **31/31 轴、155/155 档 PASS**；level 0 恒等 31/31（hash 相等）；P03/P02/G03 **精确 0 误差**、P04 ≤2.5e-4（预算 0.02）、G06/G07 ≤1e-16、P07 ≤3.4e-04；**G08 最大相对误差 20.2%**、G01 系统性偏大 8–13%、P08 L1 11.1% | **22/31 轴没有"声明→验证"配对量**（`P01/P05/P06` 连 `planned_*` 都缺）；`independent_mothers_observed = 1` vs 要求 20；只跑单一 variant | ① 给 22 个轴补独立验证量（照 P02/P03/P04 的模式）；② G01 加实测 RMS 反解尺度；③ G08 补 `measured_spurious_height_mm`；④ 真实母体库上跑 `audit_all_axes` | **P0**（配对量）/ P1（G01/G08） |
| 6 | **特征/标签精度** | `loss_mask` 唯一门 + `valid` 派生别名 + `eligible = kind∈{R1,R0} ∧ loss_mask`（D10）；`t104` 每项带 `valid` 与来源 | 最新包 1721 行：`loss_mask ≡ valid` **False**（3 行 TINY_CONTACT）、`eligible_as_negative = 1560`（首次非零）、`tokens` **有效秩 256/256**、`frame_id` 匹配 **98.75%**、`view_pos` **100% 非零**（= `T_WC[0,3]`，构造性误差 0.0 mm） | `valid` 与 D10「派生别名」在 3 行上不一致；主库 truth 层无 `iface_*`；主库 `visible_labels` QA_FAIL 23/41；`view_pos` 与**实测**滑架位置误差 = `missing`；`u_position` 127.12 > profile `max_travel_mm=120` | ① `valid` 改严格别名或更新 D10 + `export_guide.md` §2.7；② `iface_*` 下推（`data/a12_final` 已做）；③ 裁决 `max_travel_mm` | **P0** |
| 7 | **断面可分辨性** | 逐断口多角度近摄，3–6 有效方向（工程约定）；区域 mask 整数 ID 无损（`t101(D09)`/`t117`/`p1481`） | **修复前 rim = 0 / 312 213 504**（主库，`label_bundle` 0/313 786 368）；**修复后** `campaign` rim = **4 999 163 px**，rim/物体 = **5.32%**（25/28 资产非零）、`data/a12_final` **6.67%**（7/7）、`data/a12_iface` **1.83%**（与文档逐位一致） | 主库仍 0；与 3D 面积占比（3.04%）的严格比值需**同批次三口径**才能给；断面仍只有全向 4 视图环，**不是**逐断口 3–6 方向 | ① 主库重生成（代码已修，`pc_interfaces` 主库 **0/55** vs 修复后 **1/1–6/9**）；② 同批次出 ①/②/③；③ 加 `fracture_local` 视图环 | **P0** |
| 8 | **训练包精度** | 数据卡逐列/逐通道 min/max/缺失率须与真实相符；部署白名单只给 RGB+mask+u（`t044`/`t104`） | `closed_loop/training_package_v2`：**328 项抽查 328 相符**（58 个文件 sha256、90+ 列缺失率、90+ 列唯一值、30+ 数值列 min/max/mean、40+ 通道统计、3 个 `effective_rank`） | **最新包没有数据卡**；`deploy_view_answer_field_hit = defect_present`（部署视图出现答案侧字段，`forbidden_channels` 被替换为 8 通道 caveat 清单）；抽查只有 1 个包 | ① `--write-card` 给最新包生成数据卡；② 恢复硬 `forbidden_channels` 或把它写成裁决而非 `defect_present`；③ 数组抽查去掉 12 项上限并挂进 `check_data_quality.py` | **P0**（前两项） |

---

## 10. TOP 5 精度短板与最小修法

> 排序判据：**① 是否让下游的某个主张不可复算/不可引用；② 修复杠杆（改一处能救多少行）；③ 当前分母有多大。**
> 每一项都注明"这是用新字节替换旧字节"还是"这需要新算法"。

### 短板 1（P0）｜**主库 `data/a12` 是修复前的一代：断面在 2D 里 0 像素、掩码/CoC 是 v1 口径、构件面来源 100% 丢失**

* **实测**：主库 894 资产、412 视图、312 213 504 个 `surface_tag` 像素里 **`tag=2` = 0**；
  `physical_component` **55 件 / 3 446 247 面全是 `origin_kind=2`**、`face__interface_id` 命中 **0/55**；
  `deployment_mask`/物体像素 = **52.24%**、`uncertain`/物体 = **45.71%**、CoC<2 px 只有 **4.85%**。
* **为什么排第一**：契约的**主任务**（断口局部关系）在主库**没有输入**；而所有"覆盖率/CoC 达标"
  的结论在主库上都读不到。同一个仓库里已经存在修复后的字节（`data/a12_final`：rim 7/7、
  mask/物体 99.27%、uncertain 0.07%），所以**下游引用主库数字就会得到反向结论**。
* **最小修法**：**用新字节替换旧字节，不需要新算法**。
  ① 重新生成主库观测与构件（HEAD 已含 `origin_kind` + `interface_id` 双通道写入，
     实测修复后 store `pc_interfaces` = 1/1、2/2、6/9，而主库 = 0/55）；
  ② mask/CoC 可在**同一批 `depth_z`** 上纯重算（`docs/a12/data_semantics_versions.md` §1.4 已证明
     逐位可复现），不必重渲染。
* **验收判据**：`precision_probe_03_postfix.py` 对 `data/a12` 报 `rim_px > 0`、
  `pc_interfaces = 55/55`；`precision_probe_08_masks.py` 报 `uncertain_frac_of_object_mean < 0.01`。

### 短板 2（P0）｜**标定轴全部是候选/推导值，且 `calibration_*` / `rig_calibration_rev` / `scale_drift` / `r_eff_mm` 字段全仓 0 命中**

* **实测**：`f = 3.12520 mm`（`DERIVED`）、`f/2.0`（`CANDIDATE`）、`line_time 8.9 µs`（`CANDIDATE`）；
  3/3 profile `calibrated=false` / `calibration_refs=[]` / `STRESS_UNCALIBRATED`；
  4 个 store 的 894 + 30 + 167 + 463 个资产里，`calibration_id` / `rig_calibration_rev` /
  `intrinsics_profile_id` / `scale_drift` / `r_eff_mm` **各 0 命中**；
  `px_per_mm` 只有 13/894 且来自纹样栅格。
* **为什么排第二**：契约里所有**毫米级主张**（`px_per_mm` 实测、scale drift 每次必报、
  0.2 mm 结构门、P95 位置误差）都挂在这个轴上；`t097` 明确"每次采集必报 scale drift"，
  现在是**结构性 0 产出**。注意：`G07 焦距 0–3%` 是**退化轴的注入量级**（本次实测施加误差 ≤1.7e-14），
  **不能**当作"真实相机标定精度 0–3%"来引用。
* **最小修法**：**这需要真实测量，不是写代码能补的**。分三步：
  ① 打印一张已知尺寸的棋盘/AprilTag，在 10/15/20/25 cm 各采 10–20 张，逐工况解 `fx/fy/cx/cy + k1,k2,p1,p2`，
     验收：重投影 RMS ≤0.2 px、3 次重复 `fx` 散度 ≤0.2%、`(cx,cy)` 散度 ≤0.5 px；
  ② 每次采集画面里放可追溯尺度基准（标尺/ArUco/coded target），重建后自动比对，报 scale drift；
  ③ 在这两步完成前，把 `configs/a12/camera_profiles.json` 的 `calibrated` 保持 false
     并**禁止**任何以 `px_per_mm` 为依据的精度主张（合成本次可先做的事：在合成场景里放**虚拟 coded target**
     来验证漂移算法本身，`p1164` 口径要求 coded target 不进学习/匹配输入，必须剔除或 mask）。

### 短板 3（P0）｜**22/31 退化轴没有"声明量 → 验证量"配对，`G08 20.2%` / `G01 8–13%` 系统性误差被 PASS 掩盖**

* **实测**：155 档全部 PASS，但**只有 36 档（9 个轴）**能在审计表里配出"声明 vs 实测"；
  **22 个轴没有配对量**（其中 `P01/P05/P06` 没有任何 `planned_*` 键）。
  配得上的轴里 `G08` 相对误差最大 **20.2%**（L3：声明 1.4 mm → 实测 1.117 mm）、
  `G01` 四档**同向偏大 8.14–13.06%**、`P08 L1` **11.1%**。
  同时 `independent_mothers_observed = 1`，而 `A10_min_independent_mothers_per_axis = 20`。
* **为什么排第三**：退化是**全部合成实验的自变量**。155/155 PASS 读起来像"精度全达标"，
  但实际上 22 个轴的"施加量是否等于声明量"**没有任何独立证据**——下游用它做剂量-响应曲线时，
  自变量本身可能偏 10–20%。
* **最小修法**：**把 P02/P03/P04 已经做过的模式推广**（`degrade_axes.md` §7 的"独立通道复核"）：
  ① 给 22 个轴各补一个与算子自身场无关的验证量（如 P01 补 `measured_hf_rms_reduction`、
      P05 补 `measured_paint_area_mm2`、P06 补 `measured_realized_coverage`、
      I* 补 `measured_sharpness_drop_ratio`/`measured_encoding_error_rms`）；
  ② `G01` 加一步"实测 RMS 反解尺度"（实测 `applied/target` 均值 **1.1195**）；
  ③ `G08` 补 `measured_spurious_height_mm`（直接在伪面上量，与"融合后最大位移"分开）；
  ④ 在真实母体库上跑 `audit_all_axes`，把独立母体从 1 提到 ≥20。
* **验收判据**：`precision_probe_09_degrade_error.json` → `n_axes_with_paired_quantity` 从 **9 → 31**，
  且 `n_rel_error_gt_1pct = 0`。

### 短板 4（P0）｜**最新训练包没有数据卡，且部署视图出现答案侧字段（`deploy_view_answer_field_hit = defect_present`）**

* **实测**：`closed_loop/training_package_v2` 的 328 项抽查 **328 相符**（数据卡可信）；
  但**最新的 `trainable/next_experiment/training_package`（1721 行关系、256 维 tokens、
  98.75% frame_id 匹配）根本没有 `dataset_card.json`**。
  同时 v2 包的 `deploy/obs/index.json` 已经把 `forbidden_channels`
  从"8 项硬清单"换成**含 `depth_z`/`uncertain_mask`/`K` 的 8 通道 caveat 清单**（`forbidden_channels = null`），
  包自己的 `honest_boundaries` 把它标成 `defect_present`。
* **为什么排第四**：契约 `t104`/`t044` 的权限边界是"算法输入不返回答案侧字段"。
  一旦部署视图带上 `depth_z` 或 `K`，**任何基于该包的检索/匹配指标都不再是"部署条件"下的指标**——
  这是"可程序化对照"的前提被破坏（`rig_contract.md` 条款草案第 1/3 条）。
* **最小修法**：
  ① `python tools/load_package.py --package data/a12_exports/trainable/next_experiment/training_package --write-card`
     （工具已存在，**本次未执行**，因为它会写包目录）；
  ② 恢复 `forbidden_channels` 硬清单并**真的不写**这些通道；若放开是决策，则在 `dataset_card` 里
     写成 `decision: <裁决编号>` 而不是 `defect_present`——**当前两边都不是**，这是最危险的状态；
  ③ 把 `precision_probe_06_datacard.py` 的 `--max-arrays` 上限去掉并挂进 `tools/check_data_quality.py`。

### 短板 5（P1）｜**成像档位与"0.2 mm ≥4 px"在交付网格上不可同时成立，且 `r_eff_mm` 全仓 0 生产者**

* **实测**：渲染实测 mm/px 中位 **0.27193 mm/px**（`data/a12_campaign/store`，288 视图），
  0.2 mm 结构只有 **0.74 px**（差 5.4 倍）；4 px 可分辨尺寸 = **1.088 mm**。
  三档 profile 的隐含 mm/px 为 **0.3125 / 0.2441 / 0.1758**，**没有一档与 `t051` 的
  0.039/0.078/0.117/0.156/0.195 对齐**；`r_eff_mm` 在 894 + 30 + 167 + 463 个资产里 **0 命中**。
* **为什么排第五**：契约 `p0517` 自己就标了"pilot 采样起点，不是识别定理"，所以它**不是**一条硬门；
  但它是**唯一一个把"分辨率"与"可辨结构"连起来的量化口径**，也是 `resolution_profile`
  必须含 `px_per_mm` + `r_eff_mm` 的那一条。
* **最小修法**：
  ① `configs/a12/camera_profiles.json` 增 **50/100/150/200/250 mm 五档**并对齐 `t051` 的 mm/px，
     每档补 `px_per_mm`、`r_eff_mm`、`dof_cover_mm`、`effective_roi`；
  ② 把"达到 0.2 mm ≥4 px 的**最大**工作距离"写成显式可复算门
     `z_max = 0.2 mm / 4 × f_px`：本机 `f_px = 1279.43 px`（原生 2304 宽）→ **63.97 mm**；
     交付 768 宽（`f_px = 700.632`）→ **35.03 mm**；交付 256 宽（`f_px = 233.5`）→ **11.68 mm**。
     → 契约的 **10–25 cm 验收距离**与 **0.2 mm≥4 px** 在交付网格上**不可同时成立**，
     必须显式写成"0.2 mm 细节只能在 ≤35 mm（768 宽交付）处成像"，否则这条门在真实台架上永远闭不上；
  ③ `r_eff_mm` 补一个生产者，定义为 `r_eff_mm := 4 × z / f_px` 并随分辨率档写出。

---

## 11. 可复算命令清单

所有命令的工作目录 = 仓库根 `C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab`，
解释器 = `.venv\Scripts\python.exe`。全部脚本**只读既有数据**。

| # | 命令 | 产出 / 覆盖的节 |
|---|---|---|
| 0 | `& .venv\Scripts\python.exe data\a12\reports\precision_probe_00_inventory.py > data\a12\reports\precision_probe_00_inventory.txt` | 全部 store 的 role 直方图（本文的数据状态表） |
| 1 | `& .venv\Scripts\python.exe data\a12\reports\precision_probe_01_obs_schema.py` | `obs_result` 的 meta/arrays 结构（§3 口径） |
| 2 | `& .venv\Scripts\python.exe data\a12\reports\precision_probe_02_observation.py --store data/a12 --out data\a12\reports\precision_probe_02_observation.json` | 主库 412 视图的 mm/px、工作距离、mask 覆盖、rim 直方图（§1.2b、§7.2） |
| 3 | `& .venv\Scripts\python.exe data\a12\reports\precision_probe_02_observation.py --store data/a12_campaign/store --out data\a12\reports\precision_probe_02b_campaign.json` | 修复后 288 视图的同一组量（§1.2b、§7.2） |
| 4 | `& .venv\Scripts\python.exe data\a12\reports\precision_probe_03_postfix.py --out data\a12\reports\precision_probe_03_postfix.json` | 40 个 store 的 rim 像素 / `pc_interfaces` / 标定键命中（§4.2、§7.2、§9 表） |
| 5 | `& .venv\Scripts\python.exe data\a12\reports\precision_probe_04_calib_tokens.py` | 文档阶梯复算 + 逐帧 `fx`/深度 + 6 个训练包的 tokens 秩 / `view_pos` / `frame_id` / 关系表（§1.2a、§4.2、§6.2） |
| 6 | `& .venv\Scripts\python.exe data\a12\reports\precision_probe_05_geometry.py --store data/a12_final/store` | 修复后网格边长分布 + `iface_gap_p95` / 法向 / 配对残差（§2.2） |
| 7 | `& .venv\Scripts\python.exe data\a12\reports\precision_probe_05_geometry.py --store data/a12 --out data\a12\reports\precision_probe_05_geometry_main.json` | 主库 154+71+55 件网格与 55 件 `clean_truth` 的同一组量（§2.2） |
| 8 | `& .venv\Scripts\python.exe data\a12\reports\precision_probe_06_datacard.py --package data/a12_exports/closed_loop/training_package_v2 --out data\a12\reports\precision_probe_06_datacard_cl_v2.json` | 数据卡 328 项抽查（§8.2） |
| 9 | `& .venv\Scripts\python.exe -c "import sys;sys.path.insert(0,'.');from synlab.degrade import api as D;import json;open('data/a12/reports/precision_probe_07_degrade_audit.json','w',encoding='utf-8').write(json.dumps(D.audit_all_axes(None,levels=[0,1,2,3,4]),indent=2,ensure_ascii=False,default=str))"` | 31 轴 × 5 档审计原始表（§5.2） |
| 10 | `& .venv\Scripts\python.exe data\a12\reports\precision_probe_09_degrade_error.py` | "声明 vs 实测"配对误差 + level 0 恒等（§5.3） |
| 11 | `& .venv\Scripts\python.exe data\a12\reports\precision_probe_08_masks.py --store data/a12_final/store --out data\a12\reports\precision_probe_08_masks_data_a12_final_store.json` | `coc_units_v2` 口径的 mask 覆盖 / CoC mark-out（§3.2c） |
| 12 | `& .venv\Scripts\python.exe data\a12\reports\precision_probe_08_masks.py --store data/a12 --out data\a12\reports\precision_probe_08_masks_data_a12.json` | 主库同一组量（§3.2c） |
| 13 | `& .venv\Scripts\python.exe data\a12\reports\precision_probe_08_masks.py --store data/a12_campaign/store --out data\a12\reports\precision_probe_08_masks_data_a12_campaign_store.json` | campaign 同一组量（§3.2c） |
| 14 | `& .venv\Scripts\python.exe -c "import json;d=json.load(open('configs/a12/camera_profiles.json'));print([(p['profile_id'],p['working_distance_mm'],p['fov_mm'][0]/1024) for p in d['profiles']])"` | 三档 profile 的隐含 mm/px（§1.2c） |
| 15 | `git log --oneline -3; git status --porcelain` | 审计时点的代码状态（本文头部的 HEAD / 5 个并发修改 / 未跟踪文件） |
| 16 | `& .venv\Scripts\python.exe data\a12\reports\precision_probe_10_assemble.py` | 由上面 00–09 的原始产物装配 `data/a12/reports/precision_audit.json`（机器可读同内容） |
| 17 | `& .venv\Scripts\python.exe data\a12\reports\precision_probe_11_validate.py` | 校验 `precision_audit.json`：8 节齐全、TOP 5 齐全、12 条 `missing`、探针清单 |

同时用到的**他人已有脚本**（本文引用其数字时已注明来源，未重复运行）：
* `data/a12/reports/modality_census/probe_0{5,6,9,10,11,15,16}_*.py`（断面/轴/导出包缺陷普查）
* `data/a12/reports/export_fixes/_measure_export_defects.py`（导出包三缺陷 before/after）
* `data/a12/reports/gpu/compare_cpu_vs_cuda.json` + `blender_scripts/bench_gpu_render.py compare`（Blender vs CPU）
* `tests/a12/observe/_run_in_scope_tests.py`（断面信号链测试，13/13 exit 0）

---

## 12. 仍缺失的度量（`missing` 清单，不用估计值填充）

| # | 度量 | 为什么缺失 | 谁能补 |
|---|---|---|---|
| 1 | **真实相机内参标定精度**（`fx/fy/cx/cy` + 畸变的实测值与残差） | 本机没有真实相机，3/3 profile `calibrated=false`；契约 `camera.lens` 是 `unspecified` + 兜底假设 | 扫描台建成后的标定板实验（见 §4.3） |
| 2 | **绝对尺度漂移**（`t097` 要求每次采集必报） | 无比例尺参照物；`scale_valid=true` 是渲染器构造的布尔 | 画面放可追溯尺度基准 / 合成侧放虚拟 coded target 验证算法 |
| 3 | **光学工作距离的"测法"** | 契约 `p0511` 明确要求"注明测法"；合成侧 `working_distance_mm` 是构造量，**没有测法** | 扫描台上用卡尺/标定板反解并记录方法 |
| 4 | **`P95 位置误差 0.5 mm` 的实测值** | 合成侧每个视图的 `T_WC` 是构造的，没有"重复定位"这个概念；契约 `p0533` 要求每轴 10 次进退回零 | 扫描台回零测试（`p0533`） |
| 5 | **`view_pos` 与实测滑架位置之差** | 契约 `mechanics.no_encoder`：无编码器则实测位置字段为 null；合成侧只有命令/构造位置 | 加编码器或刻度读数（`p0563`/`p0591`） |
| 6 | **`r_eff_mm`（可辨结构尺寸）** | 全仓 0 生产者；契约 `p0515` 要求与 `px_per_mm`、毫米测量误差、检索收益**分开报告** | 实现侧补一个生产者（本文 §1.3 给了定义建议） |
| 7 | **帧 DOF 数值 vs 契约** | 契约景深是 `unspecified`（D6 因缺光圈值无法闭合）；本文只引用了 profile 自带的 `depth_of_field_mm` | 实测光圈 N 后按 D6 的 `c = 2.0 px × mm_per_px` 重算 |
| 8 | **断面 ①/②/③ 三口径的严格比值（同批次）** | 主库三口径不同代（主库 rim=0）；`campaign` 的 ① 与 ③ 不是同一批谱系 | 在同一批谱系上重跑 `fracture_surface_signal.md` §5 的实验 |
| 9 | **`σ ≤ 0.2 mm`（Q2 当量）的逐视图对照** | 现有深度误差只有区间（中位 0.074–0.134 mm、p99.9 0.87–4.13 mm），**没有逐视图值**落盘 | 把 `blender/1024_12` 的逐视图误差写进 `reports/` |
| 10 | **22/31 退化轴的施加精度** | 审计表里没有配对的 `measured_*` 量（本文 §5.3 的 `unpaired_axes`） | 照 P02/P03/P04 的模式补独立验证量 |
| 11 | **真实实拍照片（REAL_CAPTURE）** | `REAL_CAPTURE:PENDING`；文档明确这是不可由合成补齐的项 | 扫描台建成后 |
| 12 | **`degradation_vector_D`（14 维）的产物** | `synlab/degrade/api.py` 里 `depth_noise`/`curvature_noise` 命中 0（引用普查 §4.4 / D8 校验） | 实现侧落 14 维 D（含单位、种子、操作顺序） |

---

## 附：本文与既有文档的关系（不重复、不覆盖）

| 既有文档 | 本文与它的关系 |
|---|---|
| `docs/a12/modality_census.md` | 普查回答"**有什么/没有什么**"；本文回答"**精度是多少 / 差多少 / 怎么补**"，并把普查的修复前数字与修复后 store 并排 |
| `docs/a12/rig_contract.md` §10（35 行矩阵） | 矩阵判定"覆盖/部分/缺失"；本文对其中 **8 个精度维度**给出可复算数值与门对照 |
| `docs/a12/decision_record.md` | D6 的焦距推导（2.77 mm）、D10 的 `loss_mask` 唯一门是本文 §4 / §6.2 的判定依据 |
| `docs/a12/degrade_axes.md` | 该文件是**窄带后端**的逐档实测（本文引用其 P02/P03/P04 数字并**独立复跑**）；该文件 §8 明确警告"pipeline 走的不是窄带后端"，本文 §5 的数字**只对窄带后端成立** |
| `docs/a12/gpu_acceleration.md` | 本文 §3.2e 的 Blender vs CPU 数字**引用**该文件 §3.6，未重复运行 |
| `docs/a12/fracture_surface_signal.md` | 本文 §7.3 的 ①/②/③ 三口径**引用**该文件 §5，并指出主库与 campaign 的代际差 |
| `docs/a12/data_semantics_versions.md` | 本文 §3.2b 的 mask/CoC before/after**引用**该文件 §1.4；本文 §8 指出三代 store 的 `mask_semantics` 都是 `None` |
| `docs/a12/training_run.md` | 本文 §6.2 / §8 的监督与数据卡结论与它一致；本文补充"**最新包没有数据卡**"与"部署视图出现答案侧字段"两条新缺口 |
| `docs/a12/mother_geometry_audit.md` | 本文 §2.2 的退化片结论与它 §0 第 4 条（QA 闸门看不见声明不符）互相印证 |
