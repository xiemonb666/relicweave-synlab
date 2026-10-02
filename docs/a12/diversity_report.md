# A12 合成数据多元性报告（变量化 + 实测 before/after）

本文只写**实测**数字。每个数字都给出：分母、算法、以及产生它的命令。
无法变量化的维度列在 §6，并写明**精确接线点**而不是"看起来不同"。

产物：

| 文件 | 内容 |
|---|---|
| `configs/a12/diversity.yaml` | 变量化配置（新文件，未改任何冻结配置） |
| `data/a12/reports/diversity_before.json` | before 快照（磁盘上全部有碎片的库） |
| `data/a12/reports/diversity_after.json` | after 快照（`data/a12_diversity/store`） |
| `data/a12/reports/diversity_before_after.json` | 对照表（机器可读） |
| `data/a12/reports/diversity_context.json` | 硬件包线 / 相机档位可达域 / 花纹默认值 |
| `data/a12/reports/diversity_realised.json` | after 库**实际落地**的逐轴取值数 + 仍闭合的轴 |
| `tests/a12/integration/diversity_metrics.py` | 度量实现（before/after 共用） |
| `tests/a12/integration/diversity_compare.py` | before→after 对照表生成 |
| `tests/a12/integration/diversity_gaps.py` | "仍未多元"的实测清单 |
| `tests/a12/integration/diversity_context.py` | 上下文事实采集 |
| `tests/a12/integration/run_diversity_lineages.py` | ≥6 条谱系的实测运行器 |
| `tests/a12/integration/test_diversity_variables.py` | 把本文主张变成断言 |
| `data/a12_diversity/store` | 新库 |

**冻结配置未改**：`configs/a12/next_experiment.yaml`、`configs/a12/camera_profiles.json`、
`configs/a12/degrade_diversity.yaml` 一字未动（`git status` 可核）。所有质量门（conservation /
leakage / RMSE / 缺口门）未放宽。

---

## 1. 度量方法（公式与阈值来源）

### 1.1 事件切面法向——本文最重要的一个量

每一件 `clean_truth` 资产都存了它那次断裂事件的全部界面采样点
（`iface_points_a`，形状 `(N,3)`，世界 mm）。事件切面法向 = 这些点的**最小奇异向量**：

```
P  = iface_points_a
Pc = P - mean(P)
U, S, Vt = svd(Pc)
n  = Vt[-1] / |Vt[-1]|            # 平面法向（PCA）
```

- **为什么用 PCA 而不是读取某个字段**：pipeline 从不把 `FractureSpec.plane_normal`
  写进资产 meta，所以"法向"只能从几何里量出来。PCA 的第三主成分就是最佳拟合平面法向。
- **闭合集判定**：`distinct(round(n, 2))` 与 `distinct(round(n, 3))`，即把法向四舍五入到
  0.01 / 0.001 后数不同取值。**分母 = 有 `clean_truth` 的事件数**（不是谱系数：17 条谱系
  在断裂前就被隔离，没有事件）。
- **两两夹角**：`arccos(|n_i · n_j|)`，单位度，取全部无序对。用绝对值是因为切割面的正负
  朝向不可区分。这个量的意义：0° 表示所有切面互相平行（"所有碎片断口朝向一样"）。

### 1.2 资产级重复

`(role, blob_hash)` 分组，组内 `count > 1` 即为重复。
**分母**：该 role 在本库内的资产数（不是全盘资产数）。
算法：`SELECT role, blob_hash, COUNT(*) FROM assets GROUP BY role, blob_hash`。
只比字节；两个资产带着不同解释共享字节是设计允许的，所以分母按 role 分开。

### 1.3 几何级近似重复

碎片体积/面积取自 `fragment_mesh.meta.volume_mm3` / `area_mm2`（真实测量值）。
最近对用**相对差**：

```
rel_diff(a,b) = |a-b| / max(|a|,|b|)        (max=0 时定义 rel_diff=0)
similarity    = 1 - rel_diff                 (1.0 = 完全相同)
```

**分母**：去重后的全部碎片（同一 `asset_id` 只算一次，避免把磁盘上的库副本当成重复碎片）。
同时单独给出 `within_store`（不跨库），因为跨库比较会把"备份目录"误报成重复。

### 1.4 图像级近似重复

每件观测资产取第一张 8 位 `*.rgb`（`obs_result` 里是 `v000.rgb`，`obs_view` 里是
`payload.frames.0.rgb`），计算描述子 `(w, h, mean, std, 16-bin 灰度直方图)`，距离为

```
d = |w1-w2|/1024 + |h1-h2|/1024 + |mean1-mean2|/255 + |std1-std2|/255 + Σ|h1-h2|/n_px
similarity = max(0, 1 - d/6)
```

L1 预算的 6 来自五项各自的上界（1+1+1+1+2）。**分母**：抽样 N 张（默认 24，实际取到多少写多少）。

### 1.5 方位角网格占用率

视图方位角由 `T_WS`（物件扫描系到世界系的旋转）反解：

```
axis = R(T_WS) · (0,0,-1);  elevation = asin(axis_z);  azimuth = atan2(axis_y, axis_x)
```

`synlab/cameras/viewframes.py::make_view_frames` 把第 k 个视图放在
`azimuth = 360°·k/azimuths`、`elevation = -22.5° + 45°·layer/(layers-1)`，再叠一个
`N(0, 0.35°)` 的手腕抖动。因此"落在基准网格 2° 以内"的比例直接量出了**视图集合本身**是否
多元：比例接近 1 表示方位角集合就是那 4 个固定角（只差亚度抖动）。

### 1.6 硬件包线（阈值来源）

**不是本文自创**，来自 `configs/a12/capture_contract.json`（由 V1.44 需求文档第 6 章
DIY 采集台 C1–C15 生成）：

| 量 | 值 | 出处键 |
|---|---|---|
| 验收工作距离 | 10 / 15 / 20 / 25 cm | `working_distance_and_resolution.acceptance_distances_cm` |
| 近摄 | 5 / 10 cm | `...closeup_local_cm` |
| 灯态枚举 | `WHITE_DIFFUSE, LEFT_GRAZE, RIGHT_GRAZE, CROSS_POL, NORMAL_REFLECT`（5 个） | `lighting.real_capture_light_modes` |
| 传感器 | 2304×1296，FOV_h ≈ 84°，`rolling_shutter`，手动对焦 | `camera.node_a_detail` |
| 镜头 | `unspecified`（文档未给型号/焦距） | `camera.lens.spec` |
| 分辨率档位 id | `GLOBAL / MID / LOCAL` | `working_distance_and_resolution.resolution_profiles.ids` |

**运行时相机注册表**是 `synlab/cameras/profiles.py::_TIER_SPECS`，
`configs/a12/camera_profiles.json` 是**另一套、更旧的**声明（`GLOBAL_V1/MID_V1/LOCAL_V1`，
420/360/300 mm）。两者不是同一套数字，所以 `diversity.yaml` 让每条谱系**显式声明**自己用的
是哪一套（`observation.camera.source ∈ {registry_tier, documented_envelope}`），合并统计时
不会把两个来源混成一个。

实测可达域（由 `transform_profile_u` 逐 0.5 mm 反解 `u_travel_mm`，见
`diversity_context.json`）：

| 档位 | 基准工作距离 | 可达工作距离 | f/# | 物理焦距 | px/mm |
|---|---:|---|---:|---:|---:|
| `CAM_GLOBAL_V3` | 380 mm | **320 – 380 mm** | 2.0 | 4.4 mm | 526.32 |
| `CAM_MID_V3` | 220 mm | **190 – 250 mm** | 2.2 | 5.2 mm | 526.32 |
| `CAM_LOCAL_V3` | 140 mm | **140 – 170 mm** | 2.4 | 6.1 mm | 526.32 |

→ **文档包线与注册表可达域不相交于 5–10 cm 近摄档**：三个档位最低只能到 140 mm。
这是 §6 的头号缺口，不是本文的抽样失误。

---

## 2. 现状（before）：最严重的重复源

before 快照扫描 **23 个库 / 61 条谱系 / 350 个碎片**（`data/a12`、`data/a12_smoke`、
`data/a12_demo`、`data/a12_trainable`、`data/a12_campaign`、`data/a12_exports/**`、
`data/a12_realistic`、`data/a12_degrade`、`data/a12/reports/**`）。
完整清单与分母见 `data/a12/reports/diversity_before.json`。

### 2.1 头号重复源：断口朝向由**母体几何 hash** 决定，与事件随机流无关

`synlab/fracture/api.py::_default_basis`：当 `spec.plane_normal is None`（pipeline 永远传
`None`，因为 `_coerce_spec` 把 `FractureConfig` 投影成 `FractureSpec` 时不带平面字段）时

```
digest  = hash_json({"v": round(vertices, 9), "f": faces})
u1, u2  = int(digest[0:8],16)/2^32, int(digest[8:16],16)/2^32
azimuth = 2*pi*u1
normal  = normalize([cos(azimuth), sin(azimuth), -0.25 + 0.5*u2])
del rng                       # ← 源码里的这一行：事件随机流被显式丢弃
```

实测（`diversity_context.json`，同一母体 V01/M01）：法向 = `[-0.97152, 0.10384, 0.21297]`，
方位角 173.899°。z 分量被限制在 **[-0.25, 0.25]** 内。

实测 before：

| 量 | 值 | 分母 |
|---|---:|---|
| 事件总数 | 43 | 61 条谱系（17 条无事件） |
| 法向集合大小（2 位小数） | **43** | 43 个事件 |
| 两两夹角·均值 | 47.49° | 903 个法向对 |
| 两两夹角·**最小值** | **1.70°** | — |
| 断裂后端种类 | **1**（`plane_shared_cut`） | 43 个事件 |

**要点**：43 个法向看似"都不同"，但那个差异完全来自**母体几何的差异**（每条谱系的参数
不同 → 顶点不同 → hash 不同），不是事件层的随机性。同器型同材料的两条谱系
（`V04|M01`）实测夹角 **3.04°**，`V02|M01` 为 55.88°。
也就是说：**切面朝向不可控、不可复现地独立采样，且在同一母体上完全固定**——
对"每条谱系只切一次"的语料，这意味着断口朝向这一自由度实际没有被使用。

### 2.2 二号重复源：花纹族参数全部取模型默认值

`pipeline._build_pattern_recipe` 传 `params: {}` 且 `seed_ref = seed_ref(master_seed, pattern_id, "pattern")`
（**只按 pattern_id 派生，不含 lineage_id**）。于是：

| 量 | 实测 | 分母 |
|---|---:|---|
| `pattern_recipe` 资产 | 52 | 61 条谱系 |
| 配方 hash 唯一数 | **52**（每条谱系一个） | 52 |
| 配色取值数 | **6** | 52 |
| `footprint_mm` 记录数 | **0** | — |
| `height.amplitude_mm` 记录数 | **0** | — |
| `phase_deg` / `orientation_deg` | **0 个谱系记录** | 52 |

配方 hash 唯一只是因为它包住了不同的 chart/面积；**族参数本身是常量**。
实测 `patterns/params.py` 的模型默认值（`diversity_context.json`）：

| 族 | 默认值 |
|---|---|
| `PAT02`（环带） | `band_width_mm=2.0, gap_mm=8.0, line_width_mm=2.0, phase_s_mm=0.0, complexity=1, filled=false` |
| `PAT05`（波浪） | `wavelength_mm=40.0, amplitude_mm=3.0, line_width_mm=1.5, spacing_mm=20.0, n_harmonics=1, variant="sine"` |

`pipeline._build_pattern_recipe` 传空 `params` ⇒ 上面每一个数在**全部 52 条谱系**上相同
（`phase_s_mm` 恒为 0.0，`complexity` 恒为 1）。配色是唯一真正变化的族参数，而且只有 6 个取值。

### 2.3 三号重复源：观测层几乎全部贴死

实测（155 个观测资产）：

| 量 | 实测值 | 分母 |
|---|---:|---|
| 相机档位取值数 | **1**（`CAM_MID_V3`） | 155 |
| 工作距离取值数 | **1**（**220.0 mm**，std = 0） | 155 |
| 灯态取值数 | **0 个观测记录灯态** | 155 |
| 对焦设置取值数 | **1**（`SLIDE_MID_LOCK_B`） | 155 |
| `exposure_ev` 取值数 | **1**（0.0） | 155 |
| `read_noise_sigma` 取值数 | **1**（0.0） | 155 |
| `effective_gain` 取值数 | **1**（1.0） | 155 |
| `bit_depth` 取值数 | 1（8） | 155 |
| 视图数取值数 | 3（12 / 4 / 8） | 155 |
| 交付分辨率取值数 | 3（1024×768 / 512×384 / 256×192） | 155 |

根因两处，都在源码里可指：

1. `synlab/observe/api.py::_resolve_profile` —— `profile is None` 时**恒返回
   `camera_profiles()[1]`**（即 MID 档），而 `pipeline` 调 `observe()` 时从不传 `profile`。
2. `ObsSpec.resolved_light()` —— 默认光始终是那一个硬编码方向
   `(-0.35,-0.62,-0.70)`、`color=(2.35,2.25,2.10)`、`ambient=(0.30,0.30,0.33)`；
   `ImagingSpec` 默认是**真恒等**（`exposure_ev=0, read_noise_sigma=0, defocus_sigma_px=0,
   effective_gain=1`）。

### 2.4 四号重复源：退化层每条谱系同一组轴

| 量 | 实测 | 分母 |
|---|---:|---|
| 有退化变体的谱系 | 2 | 61 |
| 不同轴子集数 | **3** | 2 条有变体的谱系 + 58 条 `<none>` |
| 不同 `轴×档` 组合数 | **3** | 同上 |

`configs/a12/degrade_diversity.yaml` 的 `per_lineage.selection: declared` +
`max_axes: 9` 使每条谱系**都物化同一组 9 条轴 × 档位 0..4**。

### 2.5 其余 before 实测（分母见 JSON）

- 规划层：`(vessel,material,pattern,layer)` 组合数 **60 / 61 条谱系**；
  材料分布 `M01×13, M06×8, M02/M04/M10×4, M03/M05/M07/M12×3, M08/M09×2, <none>×8`；
  花纹族 16 个都出现过。
- 资产级重复：`fragment_mesh` 同 role 同 blob 的占比 **0 / 351**，全部 role 合计
  **0 / 894**（各库合计）。→ 字节级重复**不是**问题；重复发生在语义层（法向/参数/观测）。
- 几何级最近对：碎片体积最近对相似度 **1.0**（`rel_diff = 0`）——这是同一资产在
  `data/a12` 与 `data/a12/reports/failure_fix_store` 两处的副本（`asset_id` 相同），
  §1.3 的 `within_store` 指标把这种情况单独列出。去重后碎片数 350。
- 图像级最近对：描述子相似度 **0.99590**（24 张抽样）。
- 关系级：`R2` 44 对 / `R1` 116 对 / `UNKNOWN` 4 对；每谱系 R2 对数直方图
  `{0:22, 1:36, 2:1, 3:2}`；R2 共享面积 44 个值全部不同。
- 方位角：1724 个视图角，**落在 4 方位基准网格 ±2° 内的比例 2.78%**
  ——这个数字低是因为 `T_WS` 是"手放扫描系"的整体随机旋转，它把整套网格随机转了一下，
  但**网格本身**（相邻视图的相对角度）仍然是 0/90/180/270。

---

## 3. 变量化接线点

`configs/a12/diversity.yaml` 已建立。**接线方式是 opt-in**：不给开关时配置一个字节都不读，
既有调用方行为逐位不变（与既有的 `SYNLAB_DEGRADE_DIVERSITY` 同一纪律）。

`synlab/pipeline.py` 中已落地的部分（本会话写入，默认关闭）：

| 位置 | 作用 |
|---|---|
| `DIVERSITY_ENV = "SYNLAB_DIVERSITY"`、`DIVERSITY_DEFAULT_PATH` | 环境开关与默认路径 |
| `_resolve_diversity(override)` | 解析 + 校验 `synlab.diversity.v1`，返回带 `config_hash` 的字典 |
| `_div_block / _div_rng / _div_uniform / _div_choice / _div_weighted` | 取值原语；RNG 全部来自 `seed64(master_seed, lineage_id, group)` |
| `LIGHT_MODE_SPECS` + `_div_light` | 5 个文档灯态 → 真实 `LightSpec`（方向单位化） |
| `_div_camera` | 抽档位/工作距离，经 `transform_profile_u` 反解 U 位置并**受行程限制**；记录 `unreachable_tiers` |
| `_div_fracture_spec` | 抽 `plane_normal`（球面均匀）/`plane_point`（沿法向按母体顶点云等效半径偏移）/`n_events`/后端/`target_rms_mm`/`n_bands` |
| `_div_pattern_params` / `_div_palette` | 抽族参数（线宽/间距/复杂度/相位/方向）与配色 |
| `_div_observe_spec` | 抽视图数/交付分辨率/灯态/曝光/读出噪声/增益/对焦误差 |
| `_div_degradation_config` | 抽轴子集 + 每轴档位（**强制保留 level 0 恒等**），重建 `DiversityConfig` |
| `LineagePlan.variables` | 逐谱系变量表 |
| `plan_generation(..., diversity=)` | 规划期抽取"不需要母体"的部分，落盘 `<store>/reports/diversity_plan.json` |
| `run_generation(..., diversity=)` | 总开关 |

### 3.1 仍未接上的四处消费点（精确位置 + 代码）

这四处**没有**在 `synlab/pipeline.py` 里接上：该文件在本次工作期间被另一位写者持续改写
（实测 mtime 每 ~20 s 前进一次，会话内从 73 kB 增长到 133 kB），按并发纪律不在其上继续落笔。
`tests/a12/integration/run_diversity_lineages.py` 用四个具名适配器实现了同样的效果，
**每个适配器就是一处接线点**：

| # | `synlab/pipeline.py` 位置 | 现状 | 需要的改动 |
|---|---|---|---|
| 1 | `build_one_mother` 第 4 步 `fracture = fracture_event(mother, spec.fracture, rngs["cut"], event_id=event_id)` | 传的是**冻结** `FractureConfig`，平面字段为 `None` | `fracture_event(mother, lineage.variables["_fracture_spec"], rngs["cut"], event_id=event_id)`；并在第 1 步后调用 `_div_sample_lineage(...)` 补全需要母体几何的 `event` 项 |
| 2 | `build_one_mother` 第 7 步 `observe_spec = _resolve_observe_spec(spec, store)` | 返回配置投影的默认 spec | `observe_spec = lineage.variables["_observe_spec"] or _resolve_observe_spec(spec, store)` |
| 3 | 同处 `observe(physical, None, rngs, route=route, spec=observe_spec)`（以及端点那次） | `profile` 缺省 ⇒ 恒 `camera_profiles()[1]` | 加 `profile=lineage.variables["observation"]["camera"]["profile"]`（`profile` 是 `observe` 既有形参，签名不变） |
| 4 | `_build_pattern_recipe(mother, spec, rngs["pattern"], lineage.pattern_id)` | `payload["params"] = {}` ⇒ 全默认 | `payload["params"] = lineage.variables["pattern"]["params"]`，`payload["palette_id"] = lineage.variables["pattern"]["palette_id"]` |
| 5 | `build_one_mother(..., degrade_cfg=...)` 第 9 步 | 已参数化 | 传 `lineage.variables["_degrade_config"]` 而不是全局 `degrade_cfg` |

### 3.2 顺带发现并已上报的三处 `pipeline.py` 缺陷（不属于本任务范围）

会话期间实测到、并已发给该文件所有者（其中两处已被修好）：

1. `primary_fragment_id` **先读后赋**：第 7 步 `stamp_context(observation, ...get(primary_fragment_id, ...))`
   在第 ~1742 行使用、第 ~1758 行才赋值；Python 把它当整个函数的局部名 ⇒ **每条谱系在
   第 7 步必崩** `UnboundLocalError`（实测：mother/material/pattern/fracture(24.5 s)/
   clean_truth/physical 全部成功之后崩）。**已由所有者修复。**
2. `SCHEMA_PROVENANCE` 未导入：`_commit_provenance` 用它，但 `pipeline.py` 只从
   `synlab.roles` 导入了 `SCHEMA_FEATURE` / `SCHEMA_LABELS` ⇒ 第 8 步 `NameError`（实测 67.7 s）。
   **已由所有者修复。**
3. 第 10 步（模拟出土语境包）自撞自己的泄漏门：`_CONTEXT_FORBIDDEN_FIELDS` 含 `"kind"`，
   而 `build_context_pack` 的 `coexistents` 行带 `"kind": "fragment"` ⇒ 每条谱系
   `ErrorCode.LEAKAGE_DETECTED: ... ['kind']`（实测：observe 43.8 s + features 8.8 s 成功之后）。
   **已由所有者改为 `context_object_kind`。**
   本报告**没有**放宽这个门；运行器的源码修复会先做**结构性检测**，只有该冲突真的存在时才改写，
   且改写的是 pack 里的字段名，不是禁用清单。

---

## 4. 实测 after：`data/a12_diversity/store`

（见 §7 的对照表；本节填入运行结束后的数字）

---

## 5. 复现命令

```powershell
cd C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab

# 0) before 快照（23 个库 / 61 条谱系）——只读，不改任何库
.\.venv\Scripts\python.exe -B tests\a12\integration\diversity_metrics.py `
    --label before --out data\a12\reports\diversity_before.json

# 1) 上下文事实（硬件包线 / 相机可达域 / 花纹默认值 / 旧切面公式）
.\.venv\Scripts\python.exe -B tests\a12\integration\diversity_context.py

# 2) 变量化跑 ≥6 条谱系到新库（每次 1-2 条，逐谱系落盘；本机重负载会被杀）
.\.venv\Scripts\python.exe -B tests\a12\integration\run_diversity_lineages.py `
    --config configs/a12/diversity.yaml --spec configs/a12/next_experiment.yaml `
    --store data/a12_diversity/store --degrade configs/a12/degrade_diversity.yaml `
    --lineages 8 --batch 1

# 3) after 快照（只扫新库）
.\.venv\Scripts\python.exe -B tests\a12\integration\diversity_metrics.py `
    --label after --store data/a12_diversity/store `
    --out data\a12\reports\diversity_after.json

# 4) before→after 对照表
.\.venv\Scripts\python.exe -B tests\a12\integration\diversity_compare.py

# 5) after 库实际落地了哪些值 / 哪些轴仍然闭合
.\.venv\Scripts\python.exe -B tests\a12\integration\diversity_gaps.py

# 6) 断言（把本文主张变成可重跑的测试）
.\.venv\Scripts\python.exe -m pytest tests/a12/integration/test_diversity_variables.py -q
```

纯净性核验（未改冻结文件）：

```powershell
git -C . status --porcelain configs/a12/next_experiment.yaml configs/a12/degrade_diversity.yaml `
    configs/a12/camera_profiles.json synlab/fracture synlab/degrade synlab/observe `
    synlab/mothers synlab/patterns synlab/relations synlab/training frontend tools
```

---

## 6. 仍未多元的维度（如实列出，含原因）

| 维度 | 现状 | 原因 | 精确接线点 |
|---|---|---|---|
| **5–10 cm 近摄工作距离** | 三个注册档位最低 140 mm，**无档可达 50/100 mm** | `synlab/cameras/profiles.py::_TIER_SPECS` 的 `u_travel_mm` 只允许 `CAM_LOCAL_V3` 在 140–170 mm | 需要新的近摄档位（新 `_TierSpec`，例如 `sensor_width_mm` / `focal_length_mm` 按近摄重标定）——**属于相机注册表，不在本任务可写范围**；`diversity.yaml` 已能采样它，只是会被 `transform_profile_u` 如实拒绝并记录在 `unreachable_tiers` |
| **150 mm 工作距离** | `CAM_LOCAL_V3` 上限 170 mm、`CAM_MID_V3` 下限 190 mm，**150 mm 落空** | 同上；档位之间本身有 170→190 与 250→320 的空档 | 同上 |
| **文档包线 vs 注册表** | 文档 10/15/20/25 cm，注册表 140/190-250/320-380 mm | 两套声明并存且不一致 | 需要产品决策（以哪套为准）；本文不替它决定，只把两者都记录并标注来源 |
| **方位角/俯仰的逐谱系抖动** | 视图集合仍是 `azimuths = ceil(count/4)` 个固定角 + `N(0,0.35°)` 手腕抖动 | `synlab/cameras/viewframes.py:158` 的 `elevation = -22.5 + 45*layer/(layers-1)` 与 `:159` 的 `azimuth = 2*pi*k/azimuths` 都是**常量网格**；物件姿态 `T_WS`（`:146`，`scan_frame(rng)`）的随机旋转是**整体的**，不改变相邻视图的相对角 | 需要在此处注入逐谱系相位：`elevation = -22.5 + 45*layer/(layers-1) + elevation_phase_deg`，`azimuth = 2*pi*(k + azimuth_phase)/azimuths`。**该文件不在本任务可写范围**（`synlab/observe/**`），故只记录接线点 |
| **离焦 PSF 逐谱系变化** | `defocus_sigma_px` 实测**所有谱系都贴到上限 1.2** | 当前实现把"对焦偏移"抽在 profile 的景深内（`focus_offset_frac_of_dof ∈ [-0.6,0.6]`，LOCAL 档半景深 ≈ 4.6 mm），再按薄透镜换算到交付像素；f/2.4 下 4.6 mm 的离焦在 512 px 交付网格上已经是 **>1 px** 的模糊，于是每次都撞 `max_defocus_sigma_px` 上限 | 应改成"抽**模糊预算**（px）再反解偏移"，并用 `synlab/observe/render.py::circle_of_confusion_px`（模块自己的薄透镜定义，含 `sampling_px_per_mm`）做换算：抽 `coc_px ∈ [0.05, 1.5]`，取 `offset = coc_px / circle_of_confusion_px([w+1], ..., sampling_px_per_mm=D)[0]`，`sigma = coc_px/2`。代码片段已写在 `synlab/pipeline.py::_div_observe_spec` 的注释里，**但该文件在本次工作期间被另一位写者持续改写，未落笔** |
| **花纹族参数是否真的进了渲染** | `_commit_pattern` 的 `params` 已随变量变化 | 观测的 RGB 用 `synlab/observe/render.py::procedural_albedo`（**固定 seed `0x5EED`**，无材料/花纹入参），`routes.py:603 build_scene(...)` 不传 `albedo` ⇒ 渲染颜色**与花纹无关**，只与面数有关 | 需要让 `build_scene` 接收花纹的 `albedo` 通道（`synlab/patterns/api.py::_body_channels` 已经产出它）；**涉及 `synlab/observe/**`，不在可写范围** |
| **材料统计是否变化** | `material_profile.stats` 的多数键在 before 里就是常量 | 材料目录本身是常量表（`synlab/materials/catalogue.py`），本任务未改材料层 | 若要材料多元，需要在 `build_material_profile` 的入参上做变量；**`synlab/materials/**` 不在可写范围** |
| **规划层组合数** | 60/61（几乎一一对应） | 已由现有的平衡覆盖枚举保证 | 无需改动 |
| **`target_piece_range` / `secondary_probability`** | 抽到并**如实记录为声明值** | 本构建的 fracture 层没有"按目标片数迭代切"的实现（`next_experiment.yaml` 文件头第 (4)(5) 条已记载）；真正的二次破碎靠 `n_events=2` ⇒ `backend=secondary_fracture` | 若要按片数迭代，需要在 `synlab/fracture/**` 增加迭代切割（不在可写范围） |

---

## 7. before → after 对照表

（由 `tests/a12/integration/diversity_compare.py` 生成，本节粘贴其输出）

---

## 8. 边界声明

- before 快照扫描的是**当时磁盘上的库**；`data/a12`、`data/a12_smoke`、`data/a12_campaign`
  等在本次工作期间仍被其他进程写入（mtime 一直在变）。before 数字对应
  `diversity_before.json` 里的那一刻，不是"历史最早状态"。
- 图像级重复是**抽样**统计（默认 24 张），不是全量；分母写在 JSON 里。
- after 库的规模（谱系数）远小于 before 的 61 条，所以对照表的**分母不同**，
  表中每一行都标注了自己的分母。
- 本文没有放宽、也没有重新解释任何质量门。
