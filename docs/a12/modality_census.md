# `relicweave-synlab` 数据模态能力普查（A12 modality census）

> **性质**：只读普查。所有数字来自真实产物（`sqlite` / `npz` / `glb` / `parquet` / `tar` / `npz` shard）的实测读取，
> 探针脚本与原始输出保存在 `data/a12/reports/modality_census/`。
> **口径**：每个结论都给出「代码位置」或「真实产物路径 + 真实计数」。无则写 **无**。
> 数量级一律给分母。不使用「应该可以」这类表述。
>
> 生成时间：本次普查会话。仓库根 `C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab`；
> 解释器 `.venv\Scripts\python.exe`（Python 3.12.14，numpy 2.5.3）。
> 本次普查**未修改任何代码/配置/既有数据**，只新增 `docs/a12/modality_census.md` 与 `data/a12/reports/modality_census/**`。

---

## ⚠️ 并发写入者警告（读数字前必读）

本次普查期间**有另一个 agent 会话正在实时改动本仓库**。实测证据：

- `git status --porcelain` = **44** 个改动路径，含 `synlab/pipeline.py`、`synlab/physical/api.py`、
  `synlab/fracture/{api,booleans,cut,event}.py`、`synlab/degrade/__init__.py`、
  `synlab/relations/multi_event.py`、`frontend/**`（这些**不是**本次普查改的）。
- `synlab/storage/export.py` 在普查过程中增长了约 136 行。
- **`data/a12_trainable/store/metadata.sqlite` 在普查期间从 176 行长到 252 行**
  （同一进程内在不同时刻读到 `assets` 表 = 176，随后 = 252；磁盘资产目录同步 176 → 252）。
  同目录下 `runs` 表从 5 行变 6 行。

**因此本文件的所有数字都是"某个时刻的字节快照"**，其中：
- `data/a12`（主库 894 件）、`data/a12_demo`（276 件）、`data/a12_exports` 两个训练包的
  结构性与数值性结论**稳定**（普查期间重复读取一致）；
- 涉及 `data/a12_trainable` 的**计数**请视为"普查时点值"，重算前需重新快照。

所有探针脚本对**既有数据只读**，均在 `data/a12/reports/modality_census/` 留下可复算的 `.txt` / `.out`。

---

## 0. 普查范围与分母

| 项 | 真实值 | 证据 |
|---|---|---|
| `data/` 下走查的 `metadata.sqlite` 存储库 | **21** 个 | `probe_07_global_stores.py` |
| 这些库中 `assets` 表总行数 | **2189** | `probe_07_global_stores.txt` |
| 主库 `data/a12/metadata.sqlite` | **894** assets | `probe_02_sqlite_census.txt` |
| 主库资产目录 `data/a12/assets/` | 894 个目录，全部有 `meta.json`；**789** 个有 `arrays.npz`；**139** 个有 `relations.bin` | `probe_01_meta_census.txt` |
| `data/a12/store/` | **空壳**（`store.sqlite` 0 字节，5 个子目录 0 文件）——**不是**有效存储 | `probe_01` / 目录列举 |
| 主库资产在磁盘上占 | 15.8 GB（`data/a12` 全部） | 目录统计 |

**重要结构事实**：`meta.json` 把角色元数据包在顶层 `"meta"` 键里，而 `metadata.sqlite.assets.meta_json`
列存的就是这个内层对象。所以读字段必须走 `json.loads(meta_json)`，而不是 `meta.json` 的顶层键。

> 复算：
> ```powershell
> $py = ".venv\Scripts\python.exe"
> & $py data\a12\reports\modality_census\probe_01_meta_census.py
> & $py data\a12\reports\modality_census\probe_02_sqlite.py
> & $py data\a12\reports\modality_census\probe_07_global_stores.py
> ```

---

## 1. 3D 模型

### 1.1 权威网格（authoritative mesh）

| role | schema | unit | frame | n | 数组键 | 面数量级 |
|---|---|---|---|---|---|---|
| `mother_mesh` | `synlab.mother.v1` | `mm` | `W_mm` | **71** | `mesh.vertices`, `mesh.faces`, `mesh.face__surface_tag`, `mesh.face__component_id`, `mesh.face__source_triangle` | 500–6472 面/件 |
| `fragment_mesh` | `synlab.fragment.v1` | `mm` | `W_mm` | **154** | `mesh.vertices`, `mesh.faces`, `mesh.face__origin_kind`, `mesh.face__interface_id`, `mesh.face__ambiguous`, `mesh.face__side`, `mesh.face__source_tri`, `mesh.face__source_triangle` | 48–7544 面/件，合计 **472 868** 面 |
| `physical_component` | `synlab.physical.v1` | `mm` | **`F_mm`** | **55** | 两套布局：39 件为扁平 `vertices`/`faces`/`face__origin_kind`；16 件为 `payload.mesh.*` | 合计 **3 446 247** 面 |

**结论**：权威 3D 网格**可产出**，且是毫米 / 右手 / Z-up（`FRAME_WORLD = "W_mm"`，`synlab/roles.py:69`）。
`physical_component` 用构件局部帧 `F_mm`（`FRAME_FRAGMENT`，`synlab/roles.py:70`）——**不是世界帧**，用之前必须做刚体对齐。

**法线 / UV / 贴图 / 面属性**：
- **法线**：权威 npz **不存** 顶点或面法线。法线是下游按需重算的
  （`payload.normals` / `normals` 出现在 `obs_fused_geometry` 32 件与 `obs_result` 37 件里）。
- **UV / 贴图**：权威网格**无 UV**。UV 只出现在展示层派生 GLB 上（27 件带 `TEXCOORD_0` + 1 张纹理，见 §1.2）。
- **面属性**：`mother_mesh` 有 `surface_tag`（词汇表 `{0:outer_wall,1:inner_wall,2:rim,3:foot,4:base,5:attachment,6:interface}`，见 `synlab/patterns/fixtures.py:45-49`）；
  `fragment_mesh` 有 `origin_kind` / `interface_id` / `ambiguous` / `side` / `source_tri`；
  `physical_component` 有 `origin_kind`，但**全部被写成 2（ambiguous）**——见 §3.3（严重缺陷）。

### 1.2 展示派生（`display_lod_glb`）

- **只存在于 `data/a12_demo/store/metadata.sqlite`**：**118** 件。主库 `data/a12/metadata.sqlite` 里 **0** 件。
- schema `synlab.display_glb.v1`，unit **`m`**，frame **`Y_up_m`**（毫米/Z-up 经 `T_display_authority` 一次性转换；
  `authority_to_display` 对角为 `[1000, 0, -1000 ...]` → 即 mm→m 且 Z-up→Y-up）。
- **格式**：不是磁盘上的 `.glb` 文件。**全仓库 `data/` 下 `.glb` / `.gltf` 文件数 = 0**。
  真实载荷是 blob 里的 `assets/<asset>/glb.bin`，经 `synlab/api/routers/showcase.py` 以
  `model/gltf-binary` 提供。文件真实存在：236 个 `files_json` 路径全部存在，中位 8 595 B，最大 644 452 B。
- **面数**：118 个 GLB 共 **908 999** 三角面。
- **L0/L1/L2 的真实状态**（`probe_13_glb_groups.txt`）：
  - `lod_levels` 键组合：`{('L0',): 35, ('L0','L1','L2'): 56, ('body','wall'): 27}`
  - **L1/L2 在 56 件里只是"测量值"**，`lod_notes` 明确写 `L1/L2 measured only (not exported as scene nodes)`（44 条）
  - 另 35 件的 L1/L2 被 **跳过**：`ModuleNotFoundError: No module named 'fast_simplification'`
  - 即：**GLB 里只有 L0 几何**；`fast_simplification` 未安装，四边面简化降级链不可用。
- **法线 / UV / 贴图 / 面属性**（实读 GLB 二进制）：
  - 面属性集：`('POSITION',) : 113`、`('NORMAL','POSITION') : 79`、`('NORMAL','POSITION','TEXCOORD_0') : 27`
    → **106/118 个 primitive 带法线；27 个带 UV**；`textures` 计数 `{0: 91, 1: 27}`（27 件有 1 张烘焙贴图）。
  - 材质分组实读：`{['<no-material>']: 61, ['None']: 35, ['<no-material>','None']: 8, ['synlab_display_neutral_body']: 8, ['synlab_display_new_fracture_surface','synlab_display_original_surface']: 6}`
    → **只有 6 个 GLB 真正同时带"新断面"与"原母体表面"两个 primitive**（其余 display_lod_glb 不带断面分组）。
- **数量级**：118 件 GLB 覆盖 40 条 demo 清单条目（8 母体 / 8 纹样 / 12 退化 / 4 断裂…），
  真实 `data/a12_demo/demo_manifest.json` 状态：`OK 36 / FAILED 1 / BLOCKED 3`。

### 1.3 缺口（§1）

- `L1`/`L2` 简化**未物化**（缺 `fast_simplification`）——`probe_13`。
- 权威网格**无法线、无 UV、无 PBR 材质**；只有 `display_lod_glb` 才有。
- 主库 `data/a12` 完全没有展示层资产（0 件 `display_lod_glb`）。
- **没有"断面单独成件"的 3D 资产**（见 §3）。

> 复算：
> ```powershell
> & $py data\a12\reports\modality_census\probe_03_role_fields.py
> & $py data\a12\reports\modality_census\probe_08_lod.py
> & $py data\a12\reports\modality_census\probe_12_glb.py
> & $py data\a12\reports\modality_census\probe_13_glb_groups.py
> ```

---

## 2. 2D 图像

### 2.1 观测路线与真实产出

代码里定义了 3 条路线（`synlab/observe/routes.py:74-95`）：

| 常量 | 值 | input_profile | evidence_class | claim_boundary |
|---|---|---|---|---|
| `ROUTE_IDEAL_VISIBLE` | `ideal_visible` | `SENSOR_UPPER_BOUND` | `SENSOR_UPPER_BOUND` | 不能支撑手机 RGB 部署主张 |
| `ROUTE_PROXY_SCAN` | `proxy_scan` | `SENSOR_PROXY` | `STRESS_PROXY` | 需真实标定才能做扫描主张 |
| `ROUTE_PHOTO_MVS` | `photo_mvs` | `PHONE_RGB` | `REAL_PIPELINE_SYNTHETIC_INPUT` | 合成渲染上的真 SfM/稠密流程；REAL_CAPTURE 仍 pending |

**真实产出只有一个后端、一条路线**：`probe_07_global_stores.txt` 统计全 21 个存储库中
`obs_result` = **114** 件，
- `backend_report.route` = `proxy_scan` × 114（100%）
- `meta.renderer` = `SOFTWARE_RASTERIZER` × 114（100%）
- `meta.renderer_class` = `CUSTOM_GAP` × 99，`None` × 15
- **Blender 后端在存储库里 0 件产出**。

### 2.2 通道（channel）清单

`obs_result`（主库 37 件，412 个视图帧）**每帧**都带这 12 个通道（出现次数 412/412）：

| 通道 | 形状 / 类型 | 语义（代码位置） |
|---|---|---|
| `rgb` | `[H,W,3] uint8` | 交付视图（经 ISP + 可选 JPEG 往返） |
| `rgb_linear` | `[H,W,3] float32` | 场景线性辐射（`synlab/observe/routes.py:553-556`） |
| `depth_z` | `[H,W] float32` | **相机 z，mm**（不是射线长度），NaN/无效由 mask 分开 |
| `id_map` | `[H,W] int32` | 逐面整数标签，−1 = 背景，**禁止插值**（`render.py:594`） |
| `surface_tag` | `[H,W] int16` | 面属性 tag 图（−1 = 无命中） |
| `deployment_mask` | `[H,W] bool` | 部署可获取 mask |
| `roi` | `[H,W] bool` | 研究 ROI |
| `uncertain_mask` | `[H,W] bool` | 无法归属到单一表面的像素（混合/景深/深度边） |
| `K` | `[3,3] float64` | 内参 |
| `T_WC` | `[4,4] float64` | 相机位姿（`T_AB` 把 B 映到 A） |
| `dist` | `[5] float64` | OpenCV 畸变系数 |
| （集合级）`points`/`normals`/`point_valid`/`normal_valid` | `[N,3]`/`[N]` | 融合点云（每资产 1 份，37/37） |

### 2.3 分辨率与视图数（真实分布）

- 视图数：**12 视图 × 33 件**、**4 视图 × 4 件**（`probe_11_imagery.txt`）
- RGB 分辨率（`obs_result`）：`(768,1024,3)` × **396** 帧、`(192,256,3)` × **16** 帧
- `feature_bundle` 的编码器输入 `global_rgb`：`(12,768,1024,3)` × 33、`(4,192,256,3)` × 8
- `obs_view`（交付/像素变体）分辨率：`(96,128,3)` × 167、`(72,96,3)` × 4、`(48,64,3)` × 4、`(24,32,3)` × 4、`(12,16,3)` × 4

### 2.4 真实噪声 / 畸变 / 曝光 / 模糊

| 效果 | 是否真实存在 | 实测数字 |
|---|---|---|
| **畸变** | **是** | 412/412 帧的 `dist` 有非零系数（`probe_11`）。相机档位 `configs/a12/camera_profiles.json` 给出 `f_number=8.0`、`calibrated=false`、`status=STRESS_UNCALIBRATED` |
| **模糊** | **是** | `obs_view` 的 `optics_domain=SENSOR_LINEAR` ×32 帧；RGB Laplacian 方差中位 **0.425**（min 0.164 / max 1.149，n=412，越低越模糊）。PSF 走 `synlab/observe/imaging.py:142 _gaussian_psf` / `:149 _motion_psf` / `:180 _disc_psf` |
| **噪声** | **是** | Poisson(g·x)/g + 读噪声：`synlab/observe/imaging.py:285-288`。等级表 `synlab/observe/realism.py:88-93`：`photon_gain (0,16000,8000,4000,1000)`、`read_sigma (0,0.002,0.004,0.008,0.016)` |
| **曝光** | **是** | `ImagingSpec.exposure_ev`（`:228` 在光子前施加）。等级 `(0,0.5,1.0,1.5,2.0)` EV。实测质量通道 `underexposed_fraction` 达 **0.855–0.967**，`overexposed_fraction` 0.038–0.236，`mean_level` 0.034–0.199（`probe_14`）→ **合成图整体很暗** |
| **白平衡** | **是** | `WB_DIRECTION` 固定方向增益，`white_balance = 1 + dev·dir`（`realism.py:193-195`），`wb_deviation ∈ (0,0.025,0.05,0.1,0.2)` |
| **JPEG** | **是** | `synlab/observe/imaging.py:385` cv2 `IMWRITE_JPEG_QUALITY`；等级 `(100,90,75,60,40)`；`obs_view` 有 4 件 `jpeg_quality` 变体 |
| **去噪/锐化/响应曲线** | **代码可做，实测未在库里物化** | `imaging.py:325 denoise`、`:333 sharpening`、`:340-356 camera_response`（LINEAR/BT709/SRGB/POWER）。`obs_view` 实测 `encoding` 全部 `LINEAR`（183/183），即未走非线性响应 |
| **不确定像素** | **是** | `uncertain_mask` 412 帧，真值像素 **43 186 588 / 312 213 504 = 13.83%** |
| **部署 mask 覆盖** | **是** | 平均 **0.1444**（412 帧，min 0.0000，max 0.7815）→ 交付视图平均只有 14% 像素可用 |

### 2.5 Blender 后端 vs 软件光栅后端（真实差异）

| 项 | 软件光栅 | Blender 5.2.2（Cycles） |
|---|---|---|
| 二进制定位 | 进程内 | `C:\Users\xiemo\Desktop\ShardForge\third_party\blender-5.2.2-windows-x64\blender.exe`，**存在**（`Test-Path = True`），build `d13f752e3b9c`，内置 Python 3.13.13 |
| 能力探测 | — | `docs/a12/env_report.json` `backend:blender_render = PASS`；`docs/a12/backend_capabilities.json` 记 `cycles_engine=CYCLES`、`denoiser=OPENIMAGEDENOISE` |
| 通道 | 12 通道/帧（§2.2） | 另有 `visibility.npy`、`target_visibility.npy`、`occlusion.npy`、`object_index.npy`、`aa_face_id_raw.npy`、`aa_surface_tag_raw.npy`、`depth_z_aa_mm.npy`、`pass_*.exr`（`data/a12/reports/blender/work_channels/channels.json`） |
| **断面 tag（rim=2）** | **0 像素**（见 §3.2） | **有**：`work_channels/surface_tag.npy` 144×192 中 `tag=2` 占 **14.81%**（4 096 px），`aa_surface_tag_raw` 的 AA 混合值覆盖 0…2 |
| 畸变 | 直接支持（`dist` 为真系数） | 理想针孔，**不能**表达 OpenCV 畸变；策略 `error`（默认拒绝）/`undistort`/`ignore`（`routes.py:131-148`） |
| 存储库产出 | 114/114 | **0**（只在 `data/a12/reports/blender/work_*/` 里有工作目录与报告） |

> `docs/a12/backend_capabilities.json` 与 `env_report.json` 的 `limitations` 里仍写
> "Blender is absent … no binary" —— 这**与同一份 `env_report.json` 里 `backend:blender_render = PASS` 自相矛盾**，
> 且与磁盘事实（二进制存在）不符。**这是文档陈旧，不是能力缺失**。

### 2.6 缺口（§2）

- 生产库里 **只有 `proxy_scan` + 软件光栅**；`ideal_visible` 与 `photo_mvs` 在存储库中 **0 件**。
- **无真实相机照片**（见 §8）。
- `photo_mvs` 唯一一次真实运行**失败**：`data/a12_realistic/control_ideal/observe/ideal_visible/LIN0002_V23_M07_PAT12/STOP-SFM`
  → `failure_code = "STOP_SFM"`, `failure_reason = "incremental_mapping returned no reconstruction"`,
  `real_capture = false`, `gt_poses_used/gt_depth_used/gt_scale_used = false`。
- `obs_view` 只有 `LINEAR` 编码，从未物化 gamma/JPEG 之后的**交付态**图像（`obs_view` 的 `encoding` 全 `LINEAR`）。

> 复算：
> ```powershell
> & $py data\a12\reports\modality_census\probe_11_imagery.py
> & $py data\a12\reports\modality_census\probe_06_rim.py
> & $py data\a12\reports\modality_census\probe_14_quality.py
> & $py -c "import numpy as np; s=np.load(r'data/a12/reports/blender/work_channels/surface_tag.npy'); u,c=np.unique(s,return_counts=True); print(dict(zip(u.tolist(),c.tolist())))"
> ```

---

## 3. 断口专项数据（本节最详细）

### 3.1 能做到：断面的**几何真值**

`fragment_mesh` 的角色元数据与面属性是完整的断面真值载体。

**实测（`probe_05_fracture.txt`，分母 = 154 件 `fragment_mesh`）**：

| 项 | 实测值 |
|---|---|
| 总面数 | **472 868** |
| `origin_kind == 1 (INTERFACE)` 面数 | **189 864**（占 **40.15%**） |
| `origin_kind == 2 (AMBIGUOUS)` 面数 | **0**（0.00%） |
| 总表面积 | **11 305 949.3 mm²** |
| 断面面积 | **1 826 657.0 mm²**（占 **16.16%**） |
| 单件断面面积 mm² | min 0.000 / 中位 **5 032.9** / 均值 11 861.4 / max 54 893.2 |
| 单件断面面占比 | 0.0000 – 0.9911 |
| 单件面数 | 48 – 7 544（中位 3 251） |
| `interface_id` 取值 | `−1`（128 件出现，母体表面）+ `0…24`；`interface_id = 0` 出现在 118 件 |
| `face__side` | 出现在 79 件，取值 `{−1, 1}` |
| `source_tri` 有负值（SDF 新生面、无 clean 重心来源）的资产 | **128 / 154** |

**每个断面的法向与粗糙度**：`clean_truth` 的 `iface_normals_a` / `iface_normals_b` 逐样本给出断面法向
（`[N,3] float64`）；`iface_normal_p95_deg` 给出成对法向夹角 p95。**实测**：
`normal_angle_p95_deg_max` 中位 **2.599e-4°**、最大 **5.707e-3°**（容差 2.0°，`synlab/fracture/spec.py:51` 一带）。
注意：这是**成对断面法向一致性**核验值，**不是**剖面粗糙度 Ra/Rq 之类的粗糙度谱——**没有**粗糙度标量或脊线（ridge/crest）提取。

**配对断口对应关系与面积**：证明成立。
- `clean_truth` 的 `corr_*` 数组给出逐采样点配对：
  `corr_point_a/b`、`corr_normal_a/b`、`corr_bary_a/b`、`corr_face_a/b`、`corr_index_a/b`、
  `corr_interface_id`、`corr_residual_mm`、`corr_valid`、`corr_ambiguous`、`corr_association_code`、`corr_fragment_ids`
  （55/55 件都有；单件样本数 250–1 834）
- 断面级面积：`iface_id`、`iface_area_mm2`、`iface_gap_p95_mm`、`iface_normal_p95_deg`、
  `iface_ambiguity_ratio`、`iface_offset`、`iface_points_a/b`、`iface_normals_a/b`
  ，以及 `iface_common_clip_area_mm2`、`iface_pair_common_clip_area_mm2`（各 51/55 件）
- 实测：55 件 `clean_truth` 的 `fracture_qa.interface_count` 合计 **573**（单件 min 3 / 中位 9 / max 25）；
  逐件 `sum(iface_area_mm2)` 合计 **428 358.8 mm²**（min 291.46 / 中位 2 873.7 / max 38 216.3）；
  `iface_common_clip_area_mm2` 合计 **410 286.4 mm²**
- 配对关系的显式结论：`relations` 合计 **191** 条，`{R2: 56, R1: 131, UNKNOWN: 4}`；
  `relations.bin`（139 个文件，86 495 B）是 JSON 数组，例如
  `[{"a":"LIN0019_V12_M05_PAT11_E01-m","b":"...-p","kind":"R2","interface_id":0,"area_mm2":761.335…,"valid":true,"loss_mask":true,"reason":"shared_new_fracture_surface;structurally_valid_cut_face"}]`

### 3.2 **做不到**：断面在 2D 图像里**完全不可见**

这是本次普查**最严重的发现**。

`surface_tag` 的映射是 `ORIGIN_TO_TAG = {0:0, 1:2, 2:6}`（`synlab/observe/routes.py:98-102`），
即 `ORIGIN_INTERFACE → tag 2 = rim`（新断面）。渲染器确实会写 tag 缓冲（`synlab/observe/render.py:357`）。

**但全库实测结果是 0 个 rim 像素**（`probe_06_rim.txt`）：

| 数据集 | 总像素（分母） | `tag=-1` | `tag=0 (outer_wall)` | **`tag=2 (rim)`** |
|---|---|---|---|---|
| 37 件 `obs_result`（全部路线 `proxy_scan`，全 12 视图） | **312 213 504** | 221 347 167 (70.8961%) | 90 866 337 (29.1039%) | **0** |
| 45 件 `label_bundle` 的 `label__surface_tag_map__*` | **313 786 368** | 222 600 101 (70.9400%) | 91 186 267 (29.0600%) | **0** |

`meta.meta.surface_tag_names` 声明了 `{"0":"outer_wall","2":"rim","6":"attachment"}`（37/37 件都声明），
**但 `rim` 通道从来没有一个像素**——**声明的断面通道是空的**。

**根因链（两个独立缺陷叠加）**

缺陷 1 —— **物理损伤把面来源标注全部抹掉**。`synlab/physical/api.py:522-531`：

```python
if outcome.mesh is not None and geometry_changed:
    from ..storage.mesh_io import with_face_attrs
    for component in components:
        if component.meta.get("is_contamination"):
            origin = np.full(len(component.mesh.faces), 2, dtype=np.uint8)
        else:
            origin = np.full(len(component.mesh.faces), 2, dtype=np.uint8)   # ← 全写 2 (AMBIGUOUS)
        with_face_attrs(component.mesh, origin_kind=origin)
```

两个分支把 `origin_kind` 一律写成 **2 = `ORIGIN_AMBIGUOUS`**，注释却写着"face-level provenance of
the new surface"——实际上**每个面都变成"来源不明"**。实测（55 件 `physical_component`，**3 446 247** 面）：

```
face__origin_kind value histogram over 3446247 faces: {2: 3446247}
INTERFACE (val==1) faces = 0 (0.0000%)
```

缺陷 2 —— **实际渲染用的目标连 `origin_kind` 都没有**。这是把 §3.2 推到"精确 0"的那一环：

- `ORIGIN_TO_TAG = {0: 0, 1: 2, 2: 6}`（`synlab/observe/routes.py:98-102`），所以缺陷 1 若直接进入渲染，
  tag 图里应当出现 **6**（attachment），而不是 0。
- 但实测 tag 直方图**只有 −1 与 0，连 6 都没有**。
- 而 `routes.py:351-355` 的兜底是：
  ```python
  elif face_origin_kind is not None and face_origin_kind.shape[0] == n:
      surface_tag = np.vectorize(lambda k: ORIGIN_TO_TAG.get(int(k), 6), otypes=[np.int16])(face_origin_kind)
  else:
      surface_tag = np.zeros(n, dtype=np.int16)          # ← 无面属性时整块归 0
  ```
  → **只有当渲染目标的 `face_origin_kind` 为 `None` 时，整块 mesh 的 `surface_tag` 才会全是 0**，
  从而产生实测的 `{−1, 0}` 直方图。
- `ORIGIN_MOTHER_SURFACE(0)` 与 `ORIGIN_INTERFACE(1)` 都不会被映到 0 以外的值，
  所以"只有 tag 0"这一观测**唯一可由"渲染输入没有面来源属性"解释**。

**因此**：不是"断面被画成了别的颜色"，而是**断面根本没有被渲染**——
渲染目标携带的面来源属性在进入渲染前就丢失了。

**连锁证据**：
- `physical_component` 的 `payload.appearance.interface_region` 掩码实测**真值比例为 0.00000**
  （8 件带该键，全部全 0）
- `tag_map` 用的是**跨步抽样**而非多数表决（`synlab/observe/render.py:562`
  `tag_map = buffers["tag"][::factor, ::factor].copy()`），所以"细碎面被平均掉"**不能**解释 0——
  若断面真在渲染缓冲里，抽到的任何超采样点都会落上 tag 2。

**结论**：断面**有权威 3D 真值，但在所有已物化的 2D 观测与标签里既无法定位、也无法分割、更未参与渲染**。

### 3.3 做不到：断面**没有**单独的 3D 资产或图像资产

- **断面单独成件（独立 asset）**：**无**。全库 21 个存储库中不存在 role 为"断面/interface mesh"的资产；
  断面只作为 `fragment_mesh` 的面属性子集存在。没有 `export_interface_mesh()` 之类的导出函数
  （`grep "fracture_surface|new_fracture_surface|export.*interface"` 只命中展示分色与 truth ROI 代码）。
- **断面单独渲染的 2D 图像**：**无**。`photo_mvs` 的 `STOP-SFM`/`ideal_visible` 帧目录里都是完整视图。
- **断面法向**：**有**（`iface_normals_a/b`，§3.1）。
- **断面粗糙度**：**无**标量/谱。只有 `corr_residual_mm` 与 `iface_gap_p95_mm`（几何间隙），
  以及 `payload-appearance.texel_roughness`（**材质粗糙度**，不是断面形貌粗糙度）。
- **断面脊线 / 棱线（ridge / crest line）**：**无**。全库无脊线提取产物。
- **配对断口的对应关系与面积**：**有**（§3.1）。

### 3.4 断面在展示层（唯一"成件"的地方）

`display_lod_glb` 里有 **6** 个 GLB 真正把断面拆成独立 primitive + 独立材质
（`synlab_display_new_fracture_surface` / `synlab_display_original_surface`），
对应 `demo_manifest.json` 里 4 条 `OK` 的 `fracture:*` 条目（每条 2 个碎片 → 但只有 6 个 GLB 带双 primitive，
另有 8 个 GLB 用 `synlab_display_neutral_body`，其余不带分组）。

元数据里还有**显式的权威核对块**（例：`asset_b50819155e25ffe898c9`）：

```json
"surface_groups": {
  "new_fracture_surface":      {"area_mm2": 4406.025839578021, "faces": 1164, "material": "synlab_display_new_fracture_surface"},
  "original_mother_surface":   {"area_mm2": 81954.74955239795, "faces": 2446, "material": "synlab_display_original_surface"}},
"surface_group_authority": {
  "faces_total": 3610, "area_total_mm2": 86360.77539197597,
  "origin_kind_counts": {"0": 2446, "1": 1164},
  "interface_id_counts": {"-1": 2952, "0": 113, "1": 106, ...},
  "new_surface_definition": "origin_kind == ORIGIN_INTERFACE(1) 或 interface_id >= 0",
  "origin_interface_vs_interface_id_conflicts": 506,     ← 注意：有 506 个面两个定义不一致
  "vertices_spanning_surface_groups": 209 }
```

即：**展示层是真的按权威面属性分组的**，并且自己记录了 `origin_kind` 与 `interface_id>=0`
两种定义之间的冲突数（此处 506 / 3610 = 14.0%）。`tests/a12/showcase/test_display_shading.py:236-320`
用逐三角比对证明 primitive 与权威分组**逐字节一致**。

### 3.5 断裂后端的真实成熟度（`a12_demo` 40 条清单）

| 后端 | 状态 |
|---|---|
| `plane_shared_cut` | **OK** ×3（V01 / V13 / V04），每件 2 碎片，带完整 `fracture_qa` |
| `secondary_fracture` | **OK** ×1（V01，3 碎片） |
| `rough_shared_cut` | **FAILED** ×1：`PRECISION_BUDGET_EXCEEDED`（"cutter refinement exceeded the cell budget (400000) while chasing a 0.01 mm budget at wavelength 0.2193 mm; the shortest wavelength is not relaxed"，实测 cells 2 408 599） |
| `rough_shared_cut`（另一件） | **BLOCKED**：`PROCESS_KILLED`（"被系统杀死…连续被杀 3 次"，无 Python 异常） |
| `warped_partition` | **BLOCKED**：`OPERATOR_NOT_REALIZED`（"conformal shared-PLC warp stage (gmsh) is not implemented in this build"） |
| `fracture_modes` | **BLOCKED**：`OPERATOR_NOT_REALIZED`（同上，注册为 MISSING） |

→ **非平面（真实起伏）断裂面在当前构建里不可产出**；只有平面共享切（`plane_shared_cut`）与二次破碎可用。

### 3.6 断面专项：能做到 / 做不到（一句话版）

**能做到**：断面面属性（`origin_kind=1` / `interface_id≥0`，154 件 / 472 868 面中的 189 864 面）、
断面逐点法向与几何间隙、配对断口的逐样本对应关系、逐 `interface_id` 的断面面积、
成对断面面积一致性核验（`interface_pair_common_clip_area_mm2`）、
以及断面在**展示 GLB 里作为独立 primitive + 独立材质**（仅 6 个 GLB）。

**做不到**：断面在 **任何已物化的 2D 图像 / 标签图里出现**（rim 像素 = 0 / 312 213 504）；
断面作为**独立 3D 资产**（单独成件的 mesh asset）；
断面**形貌粗糙度**与**脊线**；
**非平面**（起伏/共形）断裂面本身；
把 `physical_component` 的断面来源信息**保留下来**（被 `physical/api.py:528-530` 全写成 ambiguous）。

> 复算：
> ```powershell
> & $py data\a12\reports\modality_census\probe_05_fracture.py
> & $py data\a12\reports\modality_census\probe_06_rim.py
> & $py data\a12\reports\modality_census\probe_12_glb.py
> # 断面全 ambiguous 的根因：synlab/physical/api.py:522-531
> ```

---

## 4. 退化与磨损（31 轴）

### 4.1 轴表（真实注册表，代码内省）

`synlab/degrade/axes.py:2591-2596` 注册 **31** 个轴：`P01..P08`, `I01..I10`, `G01..G08`, `X01..X05`。
代码里的 stage 常量有 **7 个**（`synlab/degrade/registry.py:39-45`）：
`PHYSICAL, SCENE, OPTICS, SENSOR, ISP, GEOMETRY_OBS, FEATURE_PROTOCOL`。

**实测 stage 直方图（`probe_09_axes.txt`）**：

```
{'GEOMETRY_OBS': 8, 'OPTICS': 3, 'SENSOR': 1, 'ISP': 4, 'SCENE': 2, 'PHYSICAL': 8, 'FEATURE_PROTOCOL': 5}
```

→ 需求里列的 6 个 stage（PHYSICAL/OPTICS/ISP/SCENE/GEOMETRY_OBS/FEATURE_PROTOCOL）合计 **29** 轴；
另有 `SENSOR`（1 轴：`I03`）不在该列表内。**共 31 轴 / 7 stage。**

每个轴**都声明 5 档**（level 0..4），level 0 的参数是恒等值（如 `psf_sigma_px=0.0`、`keep_fraction=1.0`）。

### 4.2 各 stage 分别改变什么模态

| stage | 轴 | level 参数（首档 → 末档） | 改变的模态 |
|---|---|---|---|
| `PHYSICAL` | P01 边缘磨损(半径) | `recession_strength 0.0→1.0`（radius 2.0 mm） | 3D 几何（`physical_component`，`F_mm`） |
| | P02 边缘倒角(SDF fillet) | `recession_strength 0.0→1.0`（edge 0.4 mm） | 3D 几何 |
| | P03 平滑风化凹陷 | `depth_mm 0.0→0.5`（corr 6 mm） | 3D 几何 + 断面 ROI |
| | P04 接触损失 | `contact_loss_target 0.0→0.8` | 3D 几何 |
| | P05 釉/彩绘剥落 | `retained_fraction 1.0→0.0` | 3D 几何 + 表面外观 |
| | P06 污垢 | `coverage 0.0→0.8`（层厚 0.3 mm） | 外观/几何 |
| | P07 外壁风化 | `depth_mm 0.0→0.2` | 3D 几何 |
| | P08 裂纹/涂层损失 | `affected_area 0.0→0.3` | 3D 几何 |
| `GEOMETRY_OBS` | G01 深度误差 | `target_rms_mm 0.0→1.0` | 观测几何 |
| | G02 稀疏 | `keep_fraction 1.0→0.0625` | 观测几何（点数） |
| | G03 连通空洞 | `retained_coverage 1.0→0.2` | 观测几何（洞） |
| | G04 位姿漂移 | `translation 0.0→2.0 mm` / `rotation` | 观测几何（外参） |
| | G05 QEM 简化 | `max_error_mm 0.0→0.1` | 观测几何（面数） |
| | G06 尺度比误差 | `ratio_error 0.0→0.05` | 观测几何（尺度） |
| | G07 标定误差 | `focal_ratio 0.0→0.03` | 观测几何（内参） |
| | G08 伪影 | `height_mm 0.0→2.2` | 观测几何（伪面） |
| `OPTICS` | I01 高斯 PSF | `psf_sigma_px 0.0→4.0` | 图像 |
| | I02 运动模糊 | `length_px 0.0→15.0` | 图像 |
| | I04 曝光增益 | `exposure_ev 0.0→2.0` | 图像 |
| `SENSOR` | I03 光子/读出噪声 | `photon_gain 0.0→1000`，`read_sigma 0.002→0.016` | 图像 |
| `ISP` | I05 白平衡偏移 | `wb_deviation 0.0→0.2` | 图像 |
| | I08 视图优先级裁剪 | `keep_fraction 1.0→0.0833` | 图像集合（视图数） |
| | I09 抗锯齿降采样 | `resize_scale 1.0→0.125` | 图像分辨率 |
| | I10 JPEG | `jpeg_quality 100→40` | 图像编码 |
| `SCENE` | I06 光照/BRDF 尺度 | `saturation_target 0.0→0.4` | 场景光照 → 图像 |
| | I07 遮挡体重渲 | `target_coverage 0.0→0.6` | 场景遮挡 → 图像 |
| `FEATURE_PROTOCOL` | X01 分支缺失 | `missing_rate 0.0→1.0` | 特征/协议 |
| | X02 边界/掩码误差 | `boundary_px 0.0→5.0` | 特征/协议 |
| | X03 上下文缺失/冲突 | `missing_rate 0.0→0.5` | 特征/协议（**不是考古上下文**，见 §5） |
| | X04 估计偏差 | `bias_sigma 0.0→0.35` | 特征/协议 |
| | X05 留出工作条件 | `preset_index 0→4` | 特征/协议（4 个 heldout preset） |

### 4.3 level 0 恒等：**成立**（实测，非引用测试）

`probe_10_level0_identity.py` 对**全部 31 轴**逐轴做了独立验证（不使用仓库测试，用 `probe_sources()`
真实探针 bundle + 独立 SHA-256 载荷指纹）：

| 判据 | 结果 |
|---|---|
| 操作符 `apply(src, 0, basis, None)` 返回源对象本身 | **31/31 True** |
| `measurement.identity is True` | **31/31** |
| `measurement.result_hash == measurement.source_hash` | **31/31** |
| **载荷字节指纹不变**（独立计算，含所有 ndarray 的 shape/dtype/bytes） | **31/31** |
| `measurement.measured == {}` | **31/31** |
| level-0 参数仍被声明（`planned` 非空） | **31/31** |
| store 资产数变化（level 0 不得提交） | before=4 → after=4，**delta = 0** |
| 违反完整恒等契约的轴 | **无** |

代码依据：`synlab/degrade/api.py:262-269`（level 0 直接返回源 hash，`support="IDENTITY_LEVEL0"`，
`identity_contract="source asset reference/bytes returned unchanged"`）。

### 4.4 物化了哪些轴与档位（真实计数）

跨全部 21 个存储库扫描带 `axis_id` 的资产（`probe_09_axes.txt`）：

- **有 ≥1 个物化档位的轴：28 / 31**
- **从未物化的轴：`P02`、`P04`、`P08`**（0 件）
- level 0 被物化的轴（6 个）：`G03, G05, G08, I01, I03, I09, I10, P03, P05, P06`
  —— 准确地说，level 0 出现在 `display_lod_glb`（G03/G05/G08/P03/P05/P06）与 `obs_view`（I01/I03/I09/I10/P03/P05/P06）
- `factor_kind` 直方图：`SINGLE_PARAMETER 172 / ONE_DIMENSIONAL_RECIPE 101 / CATEGORICAL_SHIFT 8 / None 208`
- `origin_role` 直方图：`degradation_source 232 / physical_component 13 / obs_view 16 / obs_fused_geometry 12 / feature_bundle 8 / None 208`

**P 族（物理磨损）物化的真实计数**（按 `(axis, level, role)`）：

| 轴 | level | role | 件数 |
|---|---|---|---|
| P01 | 1,2,3,4 | `physical_component` | 各 2 |
| P03 | 1 | `physical_component` / `physical_result` | **79** / **56** |
| P03 | 0,2,3,4 | `physical_component` | 各 1–2 |
| P05 | 1,2,3,4 | `physical_component` | 各 3 |
| P05 | 0..4 | `obs_view` | 各 2 |
| P06 | 1,2,3,4 | `physical_component` | 各 3 |
| P07 | 1,2,3,4 | `physical_component` | 各 2 |
| **P02 / P04 / P08** | — | — | **0** |
| P03 | 1 | `display_lod_glb` / `physical_result` | 1 / 56 |

**I 族（成像）物化的真实计数**（role = `obs_view`，另有 `display_lod_glb`）：

| 轴 | level 0 | level 1–4 | 变体 |
|---|---|---|---|
| I01 | 1 件 | 各 4 件 | `gaussian_psf` |
| I02 | — | 各 2 件 | `directional_kernel` |
| I03 | 1 件 | 各 4 件 | `photon_scale` |
| I04 | — | 各 2 件 | `exposure_gain` |
| I05 | — | 各 2 件 | `fixed_direction_wb` |
| I06 | — | 各 4 件 | `fixed_light_specular_profile` |
| I07 | — | 各 4 件 | `occluder_rerender` |
| I08 | — | 各 2 件 | `nested_priority_prefix` |
| I09 | 1 件 | 各 4 件 | `antialiased_downsample` |
| I10 | 1 件 | 各 4 件 | `jpeg_quality` |

**G 族**：G01/G02/G04/G06/G07 各 level 1–4 × 2 件（`obs_fused_geometry`）；G03/G05/G08 各 level 0–4 × 1–3 件（`obs_fused_geometry` + `display_lod_glb`）。

**X 族（特征协议）**：`degrade_measurement` 各 4 档 × 1 件（`X01..X05`，共 **20** 件，`qa_status = QA_PENDING`）；
`feature_bundle` 各 4 档 × 1–2 件。变体 `{X01:presence_removal, X02:boundary_error, X03:missing_context, X04:regression_bias, X05:held_out_preset}`。

### 4.5 缺口（§4）

- **P02 / P04 / P08 三个物理轴完全没有物化档位**（0 件，尽管代码已实现）。
- `degrade_measurement` 20 件全部 `QA_PENDING`（未通过 QA）。
- 只物化了**单一变体**：每族只跑了 `default_variant`（如 G01 只跑 `correlated_depth_error`，
  未跑 `outlier_only` / `lowfreq_only`）。`factor_kind` 直方图里 `CATEGORICAL_SHIFT` 只有 8 件。
- **没有多轴组合（recipe）的物化产物**：`run_recipe`（`synlab/degrade/api.py:158`）在库里无对应资产；
  `configs/a12/degrade_recipes/` 只有 2 个配方文件（`paired_edgewear_blur_bump.yaml`、`paired_plane_levels.yaml`）。

> 复算：
> ```powershell
> & $py data\a12\reports\modality_census\probe_09_axes.py
> & $py data\a12\reports\modality_census\probe_10_level0_identity.py
> ```

---

## 5. 出土上下文 / 场景上下文

### 5.1 结论

> **无。** 本系统**不产出任何**考古/出土语境数据：无遗址、无探方、无层位、无共存物、
> 无同批次分组、无比例尺参照物、无土层/土样、无地块。

### 5.2 证据：关键字普查（22 个存储库、2 206 个资产、6 977 条 `meta` 键路径）

> 原始输出：`data/a12/reports/modality_census/probe02_keywords.txt`（由上下文探针生成）

**命中 0 条键路径**：`site`、`trench`、`stratum`、`batch`、`findspot`、`locus`、`square`、
`coordinate_ref`、`scale_ref`、`scalebar`、`soil`、`earth`、`matrix`、`deposit`、`parcel`、`plot`、
`coexist`、`environment`、`episode`。

**假阳性（已排除）**：
- `lot`（144 条路径）是 `blotch` 的子串（`pattern_recipe` 的 `bands.blotch.*`）。
- `layer`（255 条路径）= **真值层**，不是层位。代码：`synlab/truth/api.py:422,671`（`"layer": LAYER_CLEAN`）、
  `:798,821`（`LAYER_PHYSICAL`）、`:1025,1046`（`LAYER_VISIBLE`）。
  带该键的 role：`clean_truth` 112、`physical_truth` 93、`visible_labels` 88、`physical_result` 57。
  其余 `layer` 命中是材料层（`synlab/materials/layers.py:235`）与纹样 `aux_layers`。

### 5.3 最近似的替代（明确的"不是同一件事"）

| 替代物 | 真实内容 | 与"出土上下文"的差距 |
|---|---|---|
| `observation.context` / `payload.context` | **只有 4 个键**：`route`、`input_profile`、`n_views`、`scale_valid`。写出位置 `synlab/degrade/api.py:629-632`。实测值：`route="proxy_scan"` 49/49、`input_profile="SENSOR_PROXY"` 41 / null 8、`n_views=4` 49/49、`scale_valid=true` 45 / null 4 | 这是**采集/传感器上下文**，不是出土语境 |
| `X03` 轴的 "context" | 把上面那个 4 键 dict 当不透明字典：`missing_context` 把键置 `None`，`conflicting_context` 把某键值交叉赋给下一键（`synlab/degrade/axes.py:2343-2357`）。8 件 `degrade_measurement`，`measured` 报 `keys_total=4.0`、`keys_missing 1–4`、`keys_conflicting 0/1` | **不是**考古上下文 |
| `obs_view` 的 `payload.scene.*` | `light`（值是符号字符串 `"ObsSpec.resolved_light"`，64 次）、`occluders`（**硬编码标量 0**，64 次，`synlab/degrade/api.py:923`）、`occluder_capacity=6`、`occluder_count ∈ {1,2,3,4}`、`occluder_radius_mm ∈ {3.9,4.8,5.7,6.6}`、`occluder_directions`（6×3 单位向量）、`target_coverage ∈ {0.15,0.3,0.45,0.6}`。16/48 件 `obs_view` 带完整遮挡参数集 | 遮挡体是**匿名 icosphere**（`synlab/degrade/api.py:829`），`face_id=-1`、`is_target=0`（`:867-870`），**不持久化对象身份**，只留数量/半径/方向 |
| `relation_pool` / `query_roster` 的分组 | `gallery`、`pool_meta`、`fragment_records`、`lineage_ids`、`splits`、`lineage_cluster` | 分组维度是**谱系 / 划分**（19 个 lineage cluster；split ∈ {train, dev, confirm}），**不是"同批次 / 同出土单位"** |
| `episode_trace` | 契约存在于代码（`synlab/roles.py:54 ROLE_EPISODE`、`:21 SCHEMA_EPISODE`；`synlab/episodes/env.py`）。代码默认：`DEFAULT_BUDGET={max_actions:6, max_seconds:600.0, candidate_pool_size:50}`、`STOP_ACTION="STOP"`、8 种动作 `STOP/U_MOVE/LOCAL_FRACTURE_FRAME/ADD_AZIMUTH/ADD_ELEVATION/TOGGLE_LIGHT/TOGGLE_POLARIZATION/RECLAMP_FLIP` | **真实产物：0 件**。全部 22 个库中 role=`episode_trace` 的资产 **0**；每张 `api_episodes` 表 **0 行**；`docs/a12/registry.json` 92 条记录中无 episode/env 条目 |

### 5.4 尺度参考（"比例尺"这一项单独说）

- 相机档位 `configs/a12/camera_profiles.json` 里 **3** 个 profile（GLOBAL_V1 / MID_V1 / LOCAL_V1），
  **全部** `"calibrated": false`、`"calibration_refs": []`、`"status": "STRESS_UNCALIBRATED"`。
- 几何尺度是**虚拟设定的**（`depth_z` 单位 mm 由渲染器构造，`routes.py:910` 注释
  `renderer depth is in mm by construction`；`scale_valid=True`）。
- `photo_mvs` 的 `STOP-SFM` 里 `gt_scale_used = false`，且 `scale_valid` 在缺失真实标定时**不成立**。
- 无"画面里的比例尺参照物"（scale bar / 已知尺寸标块）。

---

## 6. 元数据与契约

### 6.1 三处交叉核对（`synlab/schemas/**` + `synlab/roles.py` + 真实 `meta.json`）

| role | store `schema` | store `unit` | store `frame` | n（主库） | 代码交叉核对结论 |
|---|---|---|---|---|---|
| `fragment_mesh` | `synlab.fragment.v1` | `mm` | `W_mm` | 154 | 一致（`roles.py:35,10,66,69`；写入 `pipeline.py:1041-1044`） |
| `mother_mesh` | `synlab.mother.v1` | `mm` | `W_mm` | 71 | 一致（`roles.py:28,6`；`pipeline.py:1008-1011`） |
| `pattern_channels` | `synlab.pattern.v1` | `mm` | `W_mm` | 59 | 一致（`roles.py:32,7`） |
| `pattern_recipe` | `synlab.pattern.v1` | `mm` | `W_mm` | 59 | 一致；**无 arrays.npz**（0/59） |
| `clean_truth` | `synlab.truth.clean.v1` | `mm` | `W_mm` | 55 | 一致（`roles.py:36,11`） |
| `physical_component` | `synlab.physical.v1` | `mm` | `F_mm` | 55 | 一致（`roles.py:37,14,70`） |
| `material_profile` | `synlab.material.v1` | `mm` | `W_mm` | 50 | 一致 |
| `obs_view` | `synlab.obs.v1` | **`px`** | `S_mm` | 48 | 一致（`roles.py:41,15,67,71`） |
| `feature_bundle` | `a12.obs.v1` | `mm` | `S_mm` | 45 | 一致（`roles.py:44,16`；`pipeline.py:1152` 显式 `unit=UNIT_MM, frame="S_mm"`） |
| `label_bundle` | `synlab.labels.v1` | `1` | `W_mm` | 45 | 一致（`pipeline.py:1238`） |
| `provenance` | `synlab.provenance.v1` | `1` | `none` | 45 | 一致（`pipeline.py:1249`） |
| `physical_truth` | `synlab.truth.physical.v1` | `mm` | `W_mm` | 43 | 一致（`roles.py:39,12`） |
| `visible_labels` | `synlab.truth.visible.v1` | `mm` | `W_mm` | 41 | 一致（`roles.py:40,13`） |
| `obs_result` | `synlab.obs.v1` | `mm` | `S_mm` | 37 | 一致 |
| `obs_fused_geometry` | `synlab.obs.v1` | `mm` | `S_mm` | 32 | 一致 |
| `physical_result` | `synlab.physical.v1` | `mm` | `F_mm` | 30 | 一致 |
| `degrade_measurement` | `synlab.measurement.v1` | `1` | `S_mm` | 20 | 一致（`roles.py:18,49`） |
| `qa_report` | `synlab.qa.v1` | `1` | `none` | 2 | 一致（`roles.py:24,59`） |
| `relation_pool` | `synlab.pool.v1` | `1` | `W_mm` | 2 | 一致（`roles.py:19,52`） |
| `query_roster` | `synlab.roster.v1` | `1` | `W_mm` | 1 | 一致（`roles.py:20,53`） |

**未在 `data/a12` 出现但已在代码注册的 role**：`cutter_mesh`（`roles.py:34`）、
`mvs_result`（`:63`）、`episode_trace`（`:54`）、`train_checkpoint`、`train_metrics`、
`diagnostic_report`、`operator_audit`、`coverage`、`run_spec`。

### 6.1b ⚠️ 三处真实契约不一致（实测，非风格问题）

我把 `synlab/roles.py` 的词表与两处真实产物的 `assets` 表做了集合差（`probe_16_contract_mismatch.py`）：

| 不一致 | 真实内容 | 证据 |
|---|---|---|
| **schema 未声明** | `roles.py` 声明 20 个 `SCHEMA_*`；产物里出现 **3 个未声明**：`synlab.labels.v1`（45 件）、`synlab.provenance.v1`（45 件）、`synlab.display_glb.v1`（118 件） | 主库 + demo 库 |
| **unit / frame 未声明** | `roles.py` 只有 3 个 `UNIT_*`（`1/mm/px`）与 5 个 `FRAME_*`；产物里 **`m`（118 件）与 `Y_up_m`（118 件）未声明**，另有 **`none`（111 件：provenance 107 + qa_report 4）未声明** | demo 库 + 主库 |
| **一个 schema id 跨两种单位** | **`synlab.obs.v1` 同时覆盖 `unit=px`（48 件 `obs_view`）与 `unit=mm`（69 件 `obs_result`+`obs_fused_geometry`）**；`synlab.pattern.v1` 覆盖 2 个 role（`pattern_recipe` / `pattern_channels`） | `probe_16` |
| **已声明但零资产** | 主库中 0 件的声明 schema：`synlab.camera_profile.v1`、`synlab.checkpoint.v1`、`synlab.coverage.v1`、`synlab.cutter.v1`、`synlab.episode.v1`、`synlab.report.v1` | `probe_16` |

→ **`roles.py` 的"防止语义漂移"目标未完全达成**：`synlab.labels.v1` / `synlab.provenance.v1` /
`synlab.display_glb.v1` 三个 schema 与 `m` / `Y_up_m` / `none` 三个 unit/frame 值都在产物里真实使用，
却不在该文件中声明。（`synlab/roles.py` 的 `__doc__` 自述为
"Asset role and schema identifiers shared across modules (prevents semantic drift)"。）

> ⚠️ **复算最大的坑**：`meta_json` 里**点号路径被存成扁平字符串键**
> （如 `"payload.context.route"` 是一个顶层键，不是嵌套字典），
> 且**只有 `obs_result` 这一个 role 把载荷包在顶层 `"meta"` 键下**
> （实测 `obs_result` **37/37** 嵌套，其余 19 个 role **全部 0**）。
> 任何递归/嵌套字典搜索会**静默返回空**。本文件的 §2 写法（对 `obs_result` 走 `mj["meta"]`）
> 与 §3/§4 写法（对其余 role 平铺读）正是为此。

### 6.1c 真值层的两个"硬编码失效"信号

| 字段 | 真实观测 | 含义 |
|---|---|---|
| `history.association_kind` | `clean_truth` **55/55 = `EXACT_SURVIVOR`**、`physical_truth` **43/43**、`visible_labels` **41/41**；而 `label_bundle` **45/45 = `UNKNOWN_MAPPING`** 且 `historical_R2=[]` 45/45 | 三层真值里这个字段是**写死的**，不携带信息；只有 `label_bundle` 写了另一个常量值 |
| `visible_labels.truth_incomplete` | **`QA_FAIL` ⟺ `truth_incomplete=True`（23 件）**，**`QA_PASS` ⟺ `False`（18 件）**，完全一一对应 | 该字段由 `truth/api.py:1059` 的 `bool(views) and sum(visible_valid)==0` 决定，即 **56.1% 的 visible_labels 根本没有可见有效样本**——这解释了 §6.2 的 23/41 QA_FAIL |
| `association_counts.VERIFIED_RECESSION` | `physical_truth` **43/43 = 0**、`visible_labels` **41/41 = 0** | 该关联分支从未被执行 |

**frame 词表**（`synlab/roles.py:69-73`）：`W_mm`(世界 mm) / `F_mm`(构件 mm) / `S_mm`(扫描 mm) /
`C_mm`(相机 mm) / `pixel_cv_center`（像素中心，OpenCV 约定，左上像素中心 = (0,0)）。
GLB 展示层另加 `Y_up_m`（`display_lod_glb` 专用，unit `m`）。

### 6.2 QA 状态真实分布（主库 894 件）

`QA_PASS` 多数；**`QA_FAIL` / `QA_PENDING` 的真实计数**：

| role | QA_PASS | QA_FAIL | QA_PENDING |
|---|---|---|---|
| `visible_labels` | 18 | **23** | — |
| `physical_result` | 16 | **14** | — |
| `pattern_channels` / `pattern_recipe` | 5 | **1** | 53 |
| `obs_view` | — | — | 48 |
| `obs_fused_geometry` | — | — | 32 |
| `physical_component` | — | — | 55 |
| `degrade_measurement` | — | — | 20 |
| 其余（fragment_mesh、mother_mesh、clean_truth、physical_truth、obs_result、feature_bundle、label_bundle、provenance、material_profile、relation_pool、query_roster、qa_report） | 全部 PASS | — | — |

→ **`visible_labels` 有 23/41 = 56.1% 失败**；`physical_result` 有 14/30 = 46.7% 失败。
`probe_03_role_fields.txt` 有逐 role 明细。

### 6.3 provenance / 真值分层

**`provenance` role（45 件，全 QA_PASS）**：每个资产携带
- `code_fingerprint`：`{commit, dirty, git, source_tree_hash, diff_hash, untracked}`（6 子键 × 45 件）
- `backend_fingerprints`：`{cv2, gmsh, manifold3d, open3d, pycolmap, scipy, torch, trimesh}`（8 个包 × 45 件）
- `seed_ref`、`spec_hash`、`params`、`run_id`
- **无 arrays.npz**（0/45）——纯元数据角色。

**三层真值分离**（`synlab/roles.py:11-13`）：

| 层 | role | schema | 真实数组内容 | 真实字段 |
|---|---|---|---|---|
| clean | `clean_truth` | `synlab.truth.clean.v1` | 29 个数组键；**含完整断面几何**：`iface_id/area_mm2/gap_p95_mm/normal_p95_deg/ambiguity_ratio/offset/points_a/points_b/normals_a/normals_b` + 2 个 common-clip area + `corr_*`（11 个） | `event_id, mother_id, fragment_ids, relations, relations_json, relation_count, r2_count, history{association_kind,event_id,historical_R2}, event_tree{backend,cutter,cutter_hash,children,interfaces,minus,plus,parent_id,mother_volume_mm3,fragment_volume_mm3}, fracture_qa{...26 键}, patch_evidence, layer, truth_hash, truth_incomplete, correspondence_truncated, mother_area_mm2, r2_area_threshold_mm2, cutter_ref` |
| physical | `physical_truth` | `synlab.truth.physical.v1` | **只有 `corr_*`（17 键）；无任何 `iface_*`（0/43）** | `damage{axis_id,geometry_changed,level,recipe_id,variant}, residual{conservation_ok,damaged_volume_mm3,lost_volume_mm3,lost_volume_ratio,source_volume_mm3,fragments,identity}, survivor_patches(25 槽), association_counts{EXACT_SURVIVOR,UNKNOWN_MAPPING,VERIFIED_RECESSION}, mate_present, clean_truth_ref, current_fit_valid, layer, truth_hash, truth_incomplete` |
| visible | `visible_labels` | `synlab.truth.visible.v1` | **只有 2 个数组键**：`visible_correspondence_projected_counts`、`visible_correspondence_visible_counts` | `per_view{CAM_MID_V3#v00..v11}`, `observation_id`, `physical_truth_ref`, `history{association_kind,historical_R2,mate_present}`, `association_counts`, `layer, truth_hash, truth_incomplete` |

→ **断面几何只在 `clean_truth` 层存在**；`physical_truth` 与 `visible_labels` 都丢失了断面级数组。
这与 §3.2 的 2D 结果互相印证。

### 6.4 `loss_mask` 语义（实测）

**契约语义**（`synlab/truth/api.py:510-616`）：
- `R1` / `UNKNOWN` 分支一律 `loss_mask = False`（`:510,514,518,521,525,530`）
- `R2`（真实共享新断面）→ `loss_mask = True`（`:588`）
- `TINY_CONTACT` → `valid=True` 但 `loss_mask=False`（`:591,595`）
- 即：**`loss_mask` = "这一对是真实的共享断裂面，应参与损失"**；未知/无对应的一律屏蔽。

**实测值计数**：
- `research/relations.parquet`（150 行 × 12 列）：`loss_mask` 与 `valid` **完全相同**，
  `False=117 / True=33`，而 `kind` 也是 `R1=117 / R2=33` → **`loss_mask ≡ valid ≡ (kind=="R2")`**
- `labels/clean.parquet`（258 行）：`loss_mask` `False=124 / None=97 / True=37`
- `labels/physical.parquet`（189 行）：`False=95 / None=68 / True=26`
- `labels/visible.parquet`（64 行 × 8 列）：**根本没有 `loss_mask`/`valid`/`kind` 列**

**`FORBIDDEN_FEATURE_FIELDS` 与泄漏防护**：定义在 `synlab/roles.py:87-93`（33 个禁止字段：
`parent_id, object_id, bag_id, seed, interface_id, relation, historical_R2, mate_present, truth_pose,
T_WF, clean_hidden_surface, gt_thickness, gt_normal, gt_curvature, damage_strength, spurious_mask,
hard_case_tag, lineage_id, mother_id, fragment_id, event_id, split, variant, axis_id, level, ...`）。
`feature_bundle` 里有 **41/45 件**带 `dropped_forbidden_fields`，**8 件**带 `leak_repair` 块
（`{dropped, kept_observation_fields, schema, source_asset_id}`）。

---

## 7. 训练可用形态

### 7.1 导出包清单（真实大小）

| 包 | 文件数 | 总大小 | 内容 |
|---|---|---|---|
| `data/a12_exports/next_experiment/training_package` | **548** | **1 447.1 MB** | `deploy/geometry/shard_0000..0003.npz`、`deploy/obs/shard_0000..0003.tar`、`deploy/tokens/shard_0000..0003.npz`、`deploy/zarr/<24hex>/{points,normals,point_valid,normal_valid,scale_valid,frame_id}`、`deploy/queries.parquet`、`research/labels/{clean,physical,visible}.parquet`、`research/relations.parquet` |
| `data/a12_exports/closed_loop/training_package` | **56** | **4.0 MB** | 同上 + `research/labels/{correspondence,quality}.parquet` |

### 7.2 表格（parquet）真实行/列

| 文件（next_experiment） | 行 | 列 |
|---|---|---|
| `deploy/queries.parquet` | **86** | 9：`query_id, lineage, mother, fragment, gallery, historical_N_G, status, has_observation, applicability` |
| `research/labels/clean.parquet` | **258** | 15：`label_layer, asset_id, lineage, split, passed, fragment_id, role, detail, candidate_id, kind, area_mm2, valid, loss_mask, reason, unique_source_triangle` |
| `research/labels/physical.parquet` | **189** | 同 15 列 |
| `research/labels/visible.parquet` | **64** | 8 列（无 kind/valid/loss_mask） |
| `research/relations.parquet` | **150** | 12：`query, candidate, kind, area_mm2, valid, loss_mask, pool_id, split, lineage_cluster, eligible_as_negative, has_observation, reason` |

| 文件（closed_loop，另一套） | 行 | 列 |
|---|---|---|
| `research/labels/correspondence.parquet` | **3 587** | 19：`label_layer, fragment_a, fragment_b, index_a, index_b, weight, sample_valid, ambiguous, association_code, residual_mm, interface_id, relation_kind, lineage, split, source_kind, source_ref, asset_id, valid, reason` |
| `research/labels/quality.parquet` | **12** | 25：含 `samples, projected, depth_ok, id_ok, not_uncertain, deployment_ok, visible, visible_rate, depth_ok_rate, id_ok_rate, not_uncertain_rate, deployment_ok_rate, target_channel, target_unit, target_value` |
| `research/labels/clean.parquet` | 27 | 15 |
| `research/labels/physical.parquet` | 27 | 15 |
| `research/labels/visible.parquet` | 12 | 8 |
| `research/relations.parquet` | 3 | 12 |
| `deploy/queries.parquet` | 6 | 9 |

**真实数据样例**（`relations.parquet` 首行）：
`{"query":"LIN0000_V10_M11_PAT15_E01-m","candidate":"...-p","kind":"R2","area_mm2":22938.87,"valid":true,"loss_mask":true,"reason":"shared_new_fracture_surface;structurally_valid_cut_face"}`
——`area_mm2` 是**真实断面面积**，即配对断口的面积真值在训练表里**可用**（虽然 2D 图里看不到断面）。

### 7.3 数组（shard）真实形状

`deploy/geometry/shard_0000.npz`（next_experiment）：48 个键，命名 `<opaque24>__<channel>`：

```
2d233618af9243f6739f2aef__points        (89082, 3)   float32
2d233618af9243f6739f2aef__normals       (89082, 3)   float32
2d233618af9243f6739f2aef__point_valid   (89082,)     bool
2d233618af9243f6739f2aef__normal_valid  (89082,)     bool
2d233618af9243f6739f2aef__scale_valid   (89082,)     bool
2d233618af9243f6739f2aef__frame_id      (89082,)     int32
... 共 8 个 opaque 实体 × 6 通道
```

`deploy/tokens/shard_0000.npz`：40 个键，`<opaque>__{tokens, token_valid, token_view, token_input, tile_valid}`：

```
2d233618af9243f6739f2aef__tokens        (576, 256)   float32
2d233618af9243f6739f2aef__token_valid   (576,)       bool
2d233618af9243f6739f2aef__token_view    (576,)       int32
2d233618af9243f6739f2aef__token_input   (576,)       float32
2d233618af9243f6739f2aef__tile_valid    (12, 768, 1024) bool
```

**不透明命名**：`deploy_index.json` 的 `note` 明确写
`"opaque-name map for the deployment view; contains no label and no split"`，
`obs/index.json` 的 `opaque_naming = "sha256(asset fragment id)[:24]"`。

### 7.4 `deploy/obs` 的发布-视图白名单（关键契约）

`deploy/obs/index.json`（原文）：

```json
{"channels": ["tiles.npy (uint8 RGB)", "valid.npy (deployment mask)", "view_pos.npy (u position mm)"],
 "forbidden_channels": ["depth_z", "id_map", "surface_tag", "uncertain_mask", "roi", "K", "T_WC", "dist"],
 "opaque_naming": "sha256(asset fragment id)[:24]",
 "schema": "synlab.obs_index.v1"}
```

→ **交付给模型输入的只有 RGB + 部署 mask + 相机 u 位置**；深度、ID、表面 tag、K/T 全部被禁止。
tar 内成员：next_experiment 的 4 个 shard 分别为 24/24/24/12 个 `.npy`，closed_loop 的 shard 为 9 个；
只含 `.npy`（`probe_04_packages.txt`）。
`deploy/geometry/index.json` 声明的 arrays：`["points","normals","point_valid","normal_valid","scale_valid","frame_id"]`。
`deploy/tokens/index.json`：`encoder_id="identity_rgb_blockmean"`、`token_dim=256`，
每实体 `tokens=576`（12 视图 × 48 = 576；4 视图时 192）。

### 7.5 zarr（**完整且可读**，实测）

`deploy/zarr/<24hex>/{points,normals,point_valid,normal_valid,scale_valid,frame_id}/zarr.json`
每个 opaque 组 **6** 个数组描述 + 1 个组描述。`zarr.json` 共 219 个。
**块数据真实存在**：`next_experiment` 有 **328** 个块文件 / 45 095 093 B；`closed_loop` **18** 个 / 132 337 B。
真实路径例：`56af3b4c1137751192c649b4/points/c/0/0`（6 440 B）、`.../frame_id/c/0`（34 B）、
`.../normal_valid/c/0`（19 B）。用 `zarr 3.4.0` 真实 `open_group` 回读成功，
且与同源的 npz **逐字节一致**（例：`03ff40a3…__points` vs zarr `points` → identical=True）。
→ **zarr 是可用副本，不是"只有元数据"**。
（`*_valid` 块只有 19–26 B、`frame_id` 块 34–323 B，独立印证 §7.7 的退化内容。）

### 7.6 loader 能读进来的张量（实测 + 代码）

代码位置：`synlab/storage/export.py` `class TrainingPackage`（普查时点 `:1583`）、
`synlab/qc/loader_probe.py::probe_training_package`（`:262`）。

| 阶段 | 张量 | 形状（next_experiment 真实） | dtype |
|---|---|---|---|
| A 逐碎片 | `global_rgb` | `[64,12,3,768,1024]` | f32 |
| | `pixel_valid` | `[64,12,768,1024]` | bool |
| | `points` | `[64,217855,3]` | f32 |
| | `normals` | `[64,217855,3]` | f32 |
| | `local_tokens` | `[64,576,256]` | f32 |
| | `quality` | `[64,1,1]` | f32 |
| | `scale_valid` | `[64]` | bool |
| B 批次 | `pair_index` | `[36,1,2]` | i64 |
| | `pair_valid` / `pos_mask` / `neg_mask` / `excluded_mask` | `[36,1]` | bool |
| | `labels_relation` | `[36,1]` | i8 |
| | `corr_weight` | `[36,1,576]` | f32 |
| | `quality_target` | `[64,1,1]` | f32 |
| | `lineage_cluster` | `[64]` | i64 |

`closed_loop` 包的真实形状：`[6,4,3,192,256]` / `[6,192,256]` / `[6,4158,3]`，token budget 192。

**关键loader 事实**：
- **能读两个包**：shard 名来自 `entry["shard"]`、前缀来自 `entry["opaque"]`，
  **没有**任何 `glob` / `iterdir` / shard 数量字面量（`grep glob|iterdir|rglob` 无命中）。两包均 PASS。
- **完全不读 zarr**：`loader_probe.py` 与整个 `synlab/training/` 里 `zarr` 出现 **0** 次。
  368 个块文件只被哈希校验、从不解析 → 约 45 MB 纯配重，想用需要**新写一个 reader**。
- `deploy/deploy_index.json` **没有任何 loader 读它**（只有 `synlab/qc/data_quality.py` 当计数器用）。
- `token_pixel` / `token_retrieval` 被留成 **全 −1 哨兵值**。
- 真实 probe 结果：`loader_probe_summary.json` = `ok/PASS`、`files_checked 547`、`relations 150`、
  `queries 86`、`kinds {R1:117, R2:33}`、`batch_fragments 64`、`n_points 217855`。
  **`data/a12/reports/loader_probe.json` 是 0 字节**（对 nx 包大小 MemoryError），
  其真实内容残留在 `data/a12_exports/_scratch/numbers.txt:44-49`。
- ⚠️ `probe_training_package(max_fragments=16)` 会把 nx 从 86 queries **静默截断**到 16
  （`batch_fragments 64`），而 `synlab/training/smoke.py` 未透出这个截断开关。

### 7.7 导出包的两个**静默数据缺陷**（本次普查独立复算确认）

我用独立探针 `probe_15_export_defects.py` 直接读了 shard 字节，**不使用**任何队友脚本：

**D1 — `tokens` 是 rank-1 的伪广播（token 维度是假的）**
- 写入代码：`export.py`（普查时点 `:262-274`）`tokens[:,k] = flat if k==0 else flat*(1-1e-6*k)`，
  `flat` 是 768 维 block-mean RGB 向量。
- 我的独立验证：**15/15 个碎片**满足 `tokens == flat[:,None]*(1-1e-6*arange(256))[None,:]`，
  最坏绝对误差 **5.028e-08**（float32 精度内）；`tokens[:,0] == token_input` 在 **25/25** 数组上精确成立。
- 奇异值：`sv[0]` ≈ 11.3–161.3，**`sv[1]` ≈ 0.84–6.1 ×10⁻⁷**，`sv[1]/sv[0]` 最大 **6.77e-09**。
- **精确表述**：数值秩（按 `sv > sv0·n·eps` 判据）算出来是 256，但 `sv[1]` 比 `sv[0]` 小 **9 个数量级**，
  所以**有效秩是 1**——255 列只是同一向量的缩放副本。
- 后果：`local_tokens [64,576,256]`（batch 里最大的张量）携带的信息量等于**一个 768 维 block mean**。
- 行动：**不要把 `tokens` 当 256 维特征**；用 `token_input`（真实 rank 内容）或修 writer。

**D2 — `view_pos.npy` 全零（声明的相机位移通道是死的）**
- `obs/index.json` 声明 `channels = ["tiles.npy (uint8 RGB)", "valid.npy (deployment mask)", "view_pos.npy (u position mm)"]`。
- 我的独立验证：**31/31** 个成员（next_experiment 28 + closed_loop 3）全部
  `min = max = absmax = 0.0`，`nonzero = 0`。
- 写入代码 `meta_view.get("u_position_mm", 0.0)` 静默取默认值。
- 后果：**没有相机滑移/位置通道**，尽管索引文件声明它有。

**D3 — `frame_id` 是行号计数器，不是坐标系、不是相机 id**
- 写入代码（普查时点 `:539`）：`frame_id = (np.arange(n_points) % views).astype(np.int32)`。
- 我的独立验证：**31/31** 个 `frame_id` 数组精确等于 `arange(n) % n_views`
  （nx `%12`、cl `%4`；distinct value 数分别为 12 / 4）。
- 后果：`frame_id[i] = i mod n_views` 是行索引的确定性函数 → **信息量为 0**。
  把它当视角标签用是**误读**。

**D4 — `valid.npy` 极稀疏且极不均匀**（与 §7.4 的 `forbidden_channels` 契约相印证）
- `valid` 真值比例：nx 四个 shard = **0.000648 / 0.000386 / 0.179365 / 0.264235**；cl = **0.003627**。
- `valid` 与"tiles 非黑"并不等价（一致率 0.783–0.906，IoU 塌到 **0.001224 / 0.005320**），
  且部分视图**整幅为空**。

### 7.8 `data/a12_trainable`：**没有任何训练**，且被判定为 `not_trainable`

> ⚠️ 该目录在普查期间被并发写入（`assets` 176 → 252 行）。以下为**普查时点**快照。

- 布局：`config_sha256.txt` + `logs/`（45 文件）+ `negatives/`（65 文件，含 `library.json` 252 KB 与
  `meshes/mesh_*.npz`）+ `reports/`（`batch_driver.json`、`neg_run.json`）+ `store/`（11.3 GB）+ `tools/`（5 个驱动脚本）。
- **零训练产物**：`data/` 下 `.pt/.pth/.ckpt/.safetensors/.onnx` 一共只有 **7** 个，全部是
  3 步 smoke 的 checkpoint（`data/a12/reports/real_package_smoke_step3.pt` 537 658 B +
  `data/a12/reports/scratch/run{A..F}/`），**没有一个在 `a12_trainable` 里**。
- `store/releases` **空**（`releases` 表 0 行）→ 从未冻结发布；`runs` 表全部 `status=PENDING`。
- 质量判定（真实产物 `data/a12/reports/data_quality_data__a12_trainable__store.json`）：
  **`verdict = "not_trainable"`、`trainable = false`**；
  `counts {QA_FAIL 2, QA_PASS 91, QA_PENDING 21}`；
  15 项检查 = **4 PASS / 4 FAIL / 6 MISSING / 1 NOT_APPLICABLE**；
  `first_cause = semantics.mask_semantics`（`33/65` 记 `coc_units_v2`，`<missing>` 32）。
  其余 FAIL 含 `semantics.damage_semantics`、`semantics.obs_semantics`、
  `0 effective queries: 0 encodable positive pairs, 0 eligible legal negatives`。
- 生产台账 `data/a12_trainable/reports/batch_driver.json`：`target_accepted = 10`，
  `accepted_before = []`，`accepted_after = [LIN0009_V04_M01_PAT02, LIN0010_V07_M10_PAT08,
  LIN0011_V17_M12_PAT09, LIN0012_V03_M02_PAT01]` → **实际上只产出 4 条**（接受率 4/10 = 40%），
  4 次 invocation（exit code 1/1/1/0，wall 347.8 / 387.4 / 202.0 / 491.5 s），
  `disk_delta_bytes_total = 11 152 723 877`，`stop_reason = "max_invocations_reached"`。
- **唯一一次真实训练**是 3 步 CPU smoke（`data/a12/reports/training_smoke.json`）：
  `status = "PIPELINE_OK_DATA_INSUFFICIENT"`，`package` = closed_loop 训练包（3 998 691 B），
  checkpoint 537 658 B、`extra_step_digest_equal = true`、参数 digest `sha256:cd165c2d…` 四者相等、
  `extra_step_grad_norm_live == extra_step_grad_norm_resumed == 5.900482177734375`。
  结论：**流水线可信，数据是瓶颈**。

> 复算：
> ```powershell
> & $py data\a12\reports\modality_census\probe_15_export_defects.py
> & $py data\a12\reports\modality_census\probe_04_packages.py
> & $py -c "import json,pathlib;d=json.loads(pathlib.Path(r'data/a12/reports/data_quality_data__a12_trainable__store.json').read_text(encoding='utf-8'));print(d['verdict'],d['trainable'],d['counts'],d['first_cause'])"
> & $py -c "import json,pathlib;d=json.loads(pathlib.Path(r'data/a12_trainable/reports/batch_driver.json').read_text(encoding='utf-8'));print(d['target_accepted'],d['accepted_after'],d['stop_reason'])"
> ```

---

## 8. 不可产出或受限的模态

| 模态 | 状态 | 原因（真实证据，非推测） |
|---|---|---|
| **真实实拍照片（REAL_CAPTURE）** | **无** | `mvs_subset.json`：`real_capture = "REAL_CAPTURE:PENDING"`；`STOP-SFM`：`data_scope="SYNTHETIC"`、`source_kind="SYNTHETIC_RENDER"`、`real_capture=false`。`env_report.json` `limitations`：`"no real capture dataset"` |
| **真实相机标定** | **无** | `configs/a12/camera_profiles.json`：3/3 profile `calibrated=false`、`calibration_refs=[]`、`status=STRESS_UNCALIBRATED`。`mvs_subset.json`：`real_calibration_ok=false`、`real_calibration="PENDING"`。`pixel_contract.json` 的 `colmap_real_library` 只是**数值往返**核对（`forward/reverse_max_error_px = 0.0`），不是对真实相机的标定 |
| **稠密 MVS 点云** | **无** | `pycolmap 3.11.1` **`has_patch_match_stereo = false`**（`backend_capabilities.json` / `mvs_subset.json.capability_probe`）。`mvs_subset.json`：`dense_points = 0`、`depth_maps = 0`、`failure_code = "MVS_NOT_AVAILABLE"`、`dense_status="MVS_NOT_AVAILABLE"`。稀疏仅 **107** 点、2/4 帧注册（`registered_fraction = 0.5`）、`reprojection_error_px = 0.14823556911992625` |
| **真实物理尺度** | **无** | 尺度是渲染器构造的虚拟 mm（`routes.py:910` `scale_valid=True ... renderer depth is in mm by construction`）。`STOP-SFM`：`gt_scale_used = false`。**无比例尺参照物** |
| **真实光照照片 / 真实环境 HDR** | **无** | `obs_view` 的 `payload.scene.light = "ObsSpec.resolved_light"` 是**符号字符串**；`occluders` **硬编码 0**（`synlab/degrade/api.py:923`）；遮挡体是匿名 icosphere（`:829`）。软件光栅光照模型是 **Lambert + ambient**，代码自述"View-dependent term is omitted on purpose … No specular claim is made"（`synlab/observe/render.py:321-323`） |
| **真实土层 / 土壤 / 埋藏环境** | **无** | §5.2 关键字普查 0 命中（`soil`/`earth`/`matrix`/`deposit` 全 0） |
| **出土语境（遗址/层位/共存物/批次）** | **无** | §5 |
| **非平面（起伏/共形）断裂面** | **无** | `warped_partition` = `OPERATOR_NOT_REALIZED`、`fracture_modes` = `OPERATOR_NOT_REALIZED`，理由"conformal shared-PLC warp stage (gmsh) is not implemented in this build"。`rough_shared_cut` = `PRECISION_BUDGET_EXCEEDED`（cells 2 408 599 > 400 000 预算）与 `PROCESS_KILLED`（连续被杀 3 次） |
| **断面在 2D 图像中的可见性** | **无** | §3.2：rim(tag=2) 像素 = **0 / 312 213 504**（`obs_result`）与 **0 / 313 786 368**（`label_bundle`） |
| **断面形貌粗糙度 / 脊线** | **无** | 全库无粗糙度谱或脊线提取产物；只有几何间隙与法向一致性核验 |
| **断面作为独立资产** | **无** | 21 个存储库中无断面 mesh asset role |
| **L1/L2 网格简化（GLB）** | **受限** | `fast_simplification` 未安装 → 35 件 `lod_notes` 记 `ModuleNotFoundError`；另 56 件 L1/L2 只测量未导出 |
| **Blender 后端的存储库产物** | **无** | 全库 `obs_result` 的 `meta.renderer = SOFTWARE_RASTERIZER` × 114（100%）。Blender 只在 `data/a12/reports/blender/work_*/` 有工作目录 |
| **`ideal_visible` / `photo_mvs` 的存储库产物** | **无** | 全库 `obs_result.route = proxy_scan` × 114（100%） |
| **真实 GPU 训练** | **无（受限）** | `env_report.json`：`"CPU-only wheel on this host; GPU work must be scheduled elsewhere or left PENDING"`；`mvs_subset.json` `has_cuda=false`。本机 GPU 存在（`NVIDIA GeForce RTX 5060 Laptop GPU, 8151 MiB`）但 torch 是 CPU wheel |
| **任何可用的真实训练** | **无** | `data/a12_trainable` 被判定 `not_trainable`（`data_quality_data__a12_trainable__store.json`）；`store/releases` 空；`runs` 全 `PENDING`；全仓库唯一真实训练是 **3 步 smoke**（`training_smoke.json`，`PIPELINE_OK_DATA_INSUFFICIENT`） |
| **合法负样本（legal negative）** | **无** | `relations.parquet`：`eligible_as_negative = False` **150/150**、`has_observation = False` **150/150**；R2 对中**只有一侧被渲染**（nx 16 with-obs / 48 without）；结果 `effective_queries = 0`，权重 1.0 的主任务 `rank` **零监督**，reason `no_legal_negative_in_exported_relations` |
| **token 维度信息（256 维）** | **无（有效秩 = 1）** | 独立复算：`tokens[:,k] = flat*(1-1e-6*k)`，最坏绝对误差 5.028e-08，`sv[1]/sv[0] ≤ 6.77e-09`，`tokens[:,0] == token_input` 25/25 |
| **相机位移/位置通道（`view_pos`）** | **无（全零）** | 声明单位 mm，实测 **31/31** 成员 `absmax = 0.0`、`nonzero = 0` |
| **视角身份标签（`frame_id` / `token_view`）** | **无（是行号计数器）** | 实测 `frame_id == arange(n) % n_views` **31/31**；`frame_id[i] = i mod n_views` 信息量为 0 |
| **zarr 的可用读取路径** | **数据在，loader 不读** | 368 个块文件 / 45 227 430 B 真实存在且可 `open_group` 回读、与 npz 逐字节一致；但 `loader_probe.py` 与整个 `synlab/training/` 中 `zarr` 出现 **0** 次 |
| **`episode_trace`（主动观察 episode）** | **无产物** | 22 个库中 0 件；`api_episodes` 表 0 行 |
| **`cutter_mesh` / `mvs_result` 资产** | **无产物** | 代码注册（`roles.py:34,63`），全库 0 件 |
| **16-bit / 浮点交付图像、非遗失压缩** | **受限** | `data_contract.md` 与 `imaging.py:20` 明确禁止把 gamma/JPEG 数据当线性源；`obs_view` 实测 `encoding` 全为 `LINEAR`，从未物化交付态非线性图像 |
| **真实材质测量（密度/孔隙/各向异性）** | **受限** | `material_profile` 55 件里 `mechanics_status` 存在，但 `stats` 的 `ideal_depth_separate`/`missing_measurement_allowed`/`missed_measurement_ratio` 出现次数极少（2/2/1），`provenance.note` 记 `source_kind` |

---

## 总表：模态 × 可产出性 × 证据路径 × 数量级 × 缺口

| # | 模态 | 可产出性 | 证据路径（真实） | 数量级（分母） | 主要缺口 |
|---|---|---|---|---|---|
| 1 | 3D 权威母体网格 | **可** | `data/a12/metadata.sqlite` role `mother_mesh`；`data/a12/assets/<id>/arrays.npz` | 71 件；500–6 472 面/件；`mm`/`W_mm` | 无法线/UV/PBR；主库无展示层 |
| 2 | 3D 权威碎片网格（含断面面属性） | **可** | role `fragment_mesh` | 154 件；**472 868** 面；断面 **189 864** 面（40.15%） | 无独立断面资产；无脊线/粗糙度 |
| 3 | 3D 物理损伤构件 | **部分（来源标注损坏）** | role `physical_component` | 55 件；**3 446 247** 面；`origin_kind==2` **100%** | `physical/api.py:528-530` 全写 ambiguous；`F_mm` 局部帧 |
| 4 | 展示 GLB（L0） | **可**（仅 demo 库） | `data/a12_demo/store` role `display_lod_glb`，`assets/<id>/glb.bin` | 118 件；**908 999** 三角面；`m`/`Y_up_m` | 磁盘无 `.glb`，只走 blob；主库 0 件 |
| 5 | 展示 GLB（断面独立 primitive） | **部分** | 同上，材质 `synlab_display_new_fracture_surface` | **6 / 118** 个 GLB 带双 primitive | 其余 112 件不带断面分组 |
| 6 | 展示 LOD L1/L2 | **不可** | `lod_notes`：`ModuleNotFoundError: No module named 'fast_simplification'` | 35 件被跳过；56 件只测量 | 缺依赖 |
| 7 | 2D 观测 RGB（交付） | **可** | role `obs_result`/`obs_view`，`arrays.npz` 的 `v0xx.rgb` | 主库 37 件 / 412 帧；`(768,1024,3)`×396 + `(192,256,3)`×16 | 仅 `proxy_scan`+软件光栅；部署 mask 平均仅 **14.4%** |
| 8 | 2D 深度图（相机 z, mm） | **可** | `v0xx.depth_z` `[H,W] float32` | 412/412 帧 | 只在 research 侧；deploy 包**禁止**（`obs/index.json` `forbidden_channels`） |
| 9 | 2D ID / surface_tag / ROI / uncertain 掩码 | **可** | `v0xx.{id_map, surface_tag, roi, uncertain_mask}` | 412/412 帧；uncertain 占 **13.83%**（43 186 588/312 213 504） | 均在 deploy 包 `forbidden_channels` 内 |
| 10 | **断面在 2D 中的可见性（rim）** | **不可** | `probe_06_rim.txt` | **0 / 312 213 504** 与 **0 / 313 786 368** | 根因 `synlab/physical/api.py:528-530` |
| 11 | 真实噪声/畸变/曝光/模糊 | **可** | `synlab/observe/imaging.py:142,149,180,285-288,311-356,385`；`obs_view` 的 `units.*` | 412/412 帧有非零 `dist`；`underexposed_fraction` 0.855–0.967；Laplacian 中位 0.425 | 光照模型只 Lambert+ambient，无镜面 |
| 12 | 相机标定 | **不可（虚拟档位）** | `configs/a12/camera_profiles.json` | 3/3 `calibrated=false`；`STRESS_UNCALIBRATED` | 无真实标定 |
| 13 | 2D `ideal_visible` / `photo_mvs` 产物 | **不可** | `probe_07_global_stores.txt` | 库内 **0 / 114**；`photo_mvs` 唯一运行为 `STOP_SFM` 失败 | `incremental_mapping` 无重建 |
| 14 | Blender 后端产物 | **可跑，未入库** | `docs/a12/backend_capabilities.json` `blender_render=PASS`；`data/a12/reports/blender/work_channels/surface_tag.npy` | 库内 **0 / 114**；Blender 侧 rim 占 **14.81%** | 未接入生产生成 |
| 15 | 断面几何真值（面积/法向/间隙/配对） | **可** | role `clean_truth` 的 `iface_*`（10 键）+ `corr_*`（11 键） | 55 件；`interface_count` 合计 **573**；断面面积合计 **428 358.8 mm²** | `physical_truth`/`visible_labels` 层丢失 `iface_*` |
| 16 | 配对断口关系（R2/R1） | **可** | `relations.bin`（JSON）；`clean_truth.relations`；`relations.parquet` | 主库 191 条 `{R2:56, R1:131, UNKNOWN:4}`；导包 150 行 `{R2:33, R1:117}` | `loss_mask ≡ valid ≡ (kind=="R2")`，信息冗余 |
| 17 | 31 轴退化（几何/图像/协议） | **部分** | `synlab/degrade/axes.py:2591-2596`；`probe_09_axes.txt` | 31 轴注册；**28/31** 有物化档位；level 0 实测恒等 **31/31** | `P02/P04/P08` 零物化；每族只跑默认变体；无多轴 recipe 产物 |
| 18 | 出土/场景上下文 | **不可** | §5；22 库 2 206 资产 6 977 键路径普查 | 考古类关键字 **0** 命中 | `context` 只有 4 个采集键；`episode_trace` 0 件 |
| 19 | 元数据/契约/QA | **可** | `metadata.sqlite.assets`；`synlab/roles.py`；`synlab/schemas/runtime.py` | 20 role 三方一致；`QA_FAIL`：`visible_labels` 23/41、`physical_result` 14/30 | `pattern_recipe`/`provenance` 无 arrays |
| 20 | provenance / 真值分层 | **可** | role `provenance`；`clean_truth`/`physical_truth`/`visible_labels` | 45 件 provenance（8 后端指纹 + git 指纹）；三层真值分离 | 断面只在 clean 层 |
| 21 | 训练包（表/数组/分片） | **可** | `data/a12_exports/next_experiment/training_package` | **548 文件 / 1 447.1 MB**；parquet 86/258/189/64/150 行；geometry 168 键 / tokens 140 键 | `tokens` 有效秩 = 1；`view_pos` 全零；`frame_id` 是行号；zarr 有数据但 loader 不读 |
| 22 | 训练包（deploy 视图） | **可** | `deploy/obs/index.json` | 白名单 3 通道；禁止 8 通道（含 `depth_z`/`id_map`/`surface_tag`/`K`/`T_WC`） | 部署侧无法获得断面信号（因为源就没渲染出来）；`valid` 真值率低至 **0.000386** |
| 23 | 主动观察 episode | **不可** | `synlab/episodes/env.py`；`roles.py:54` | **0** 件资产；`api_episodes` 0 行 | 只有契约与动作空间 |
| 24 | 真实物理尺度 / 比例尺 | **不可** | §5.4 | 3/3 相机档位未标定；无比例尺参照物 | — |
| 25 | 可用训练 / 合法负样本 | **不可** | `data_quality_data__a12_trainable__store.json`；`relations.parquet`；`training_smoke.json` | verdict **`not_trainable`**；`eligible_as_negative` False **150/150**；唯一真实训练 = **3 步 smoke** | 主任务 `rank`（权重 1.0）零监督；`effective_queries = 0` |

---

## 附：本次普查产出的探针与原始输出

全部位于 `data/a12/reports/modality_census/`：

| 文件 | 内容 |
|---|---|
| `probe_01_meta_census.py` / `.txt` | 894 个 `meta.json` + `arrays.npz` 全量角色/形状/dtype 普查 |
| `probe_02_sqlite.py` / `probe_02_sqlite_census.txt` | 21 张表结构 + 894 行 assets 的 role/schema/unit/frame/QA 分布 |
| `probe_03_role_fields.py` / `probe_03_role_fields.txt` | 逐 role 的 meta 键与数组形状（1 016 行） |
| `probe_04_packages.py` / `.txt` | 两个训练包的完整树、parquet 列/值、npz 通道、tar 成员、zarr 描述 |
| `probe_05_fracture.py` / `probe_05_fracture.txt` | 断口专项：面属性、面积、法向、间隙、配对、`obs_result` tag 直方图 |
| `probe_06_rim.py` / `probe_06_rim.txt` | rim 像素 = 0 的证明（逐路线、逐视图、含 `label_bundle`） |
| `probe_07_global_stores.py` / `probe_07_global_stores.txt` | 21 个存储库全局 role 普查 + 观测后端普查 |
| `probe_08_lod.py` / `probe_08_lod.txt` | `display_lod_glb` 全字段普查 |
| `probe_09_axes.py` / `probe_09_axes.txt` | 31 轴注册表内省 + 物化档位真实计数 |
| `probe_10_level0_identity.py` / `probe_10_level0_identity.txt` | **实测** level-0 恒等：31/31，载荷字节不变，store delta=0 |
| `probe_11_imagery.py` / `probe_11_imagery.txt` | 2D 通道、分辨率、视图数、噪声/畸变/曝光/模糊实测 |
| `probe_12_glb.py` / `probe_12_glb.txt` | 实读 118 个 GLB 二进制：primitive/材质/accessor/节点/纹理 |
| `probe_13_glb_groups.py` / `probe_13_glb_groups.txt` | GLB 材质组合、LOD 完整性、UV/烘焙块 |
| `probe_14_quality.py` / `probe_14_quality_crosscheck.txt` | `obs_result` ↔ `feature_bundle` 质量通道逐值交叉核对 |
| `probe_15_export_defects.py` / `probe_15_export_defects.txt` | **独立复算**导出包缺陷：`tokens` 有效秩、`view_pos` 全零、`frame_id == arange%views` |
| `probe_16_contract_mismatch.py` / `probe_16_contract_mismatch.txt` | 契约词表集合差、`meta` 嵌套陷阱、`truth_incomplete` 与 QA 的一一对应 |
| `probe_ctx_contract.md` | 上下文与契约专项报告（由上下文探针生成，含 `probe02_keywords.txt` 等原始输出） |
| `probe_train_export.md` / `sub_loader_findings.md` | 训练导出包与 loader 专项报告（由导出包探针生成，含 `p1..p6`、`partB_*` 原始输出） |

### 一键复算全部

```powershell
$root = "C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
$py   = "$root\.venv\Scripts\python.exe"
$out  = "$root\data\a12\reports\modality_census"
1..16 | ForEach-Object {
  $n = "{0:d2}" -f $_
  $f = Get-ChildItem "$out\probe_${n}_*.py" -EA 0 | Select-Object -First 1
  if ($f) { & $py $f.FullName *> "$out\rerun_${n}.txt" }
}
```

### 单点抽查（最小复算集）

```powershell
# 断面在 2D 里是否可见（核心结论）
& $py $out\probe_06_rim.py

# 断面全 ambiguous 的根因
Select-String -Path "$root\synlab\physical\api.py" -Pattern 'np.full\(len\(component.mesh.faces\), 2'

# level-0 是否真恒等（31 轴）
& $py $out\probe_10_level0_identity.py

# 导出包三个缺陷
& $py $out\probe_15_export_defects.py

# 训练是否可训
& $py -c "import json,pathlib;d=json.loads(pathlib.Path(r'$root/data/a12/reports/data_quality_data__a12_trainable__store.json').read_text(encoding='utf-8'));print(d['verdict'],d['trainable'])"
```

> **诚实性声明**：本文件中的每个数字都可在上表任一探针脚本中复算。
> 未做的验证（如 zarr 块数据完整性、Blender 后端端到端入库）在正文中已标注为待验证/未产出，
> 未以推测填补。
