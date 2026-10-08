# Blender 渲染后端接入观测路线：12 视图 @ 长边 1024 px（plan 13.2 / G14.1 / R3）

状态：**接线完成，1024 px × 12 视图实测通过**（本机便携 Blender 5.2.2 LTS + Cycles，
`BLENDER_BIN=C:\Users\xiemo\Desktop\ShardForge\third_party\blender-5.2.2-windows-x64\blender.exe`）。

本文所有数字都是本机本轮实测（命令见 §9，原始产物在 `data/a12/reports/blender/1024_12/`），
没有计划值，也没有把软件光栅器的结果标成 Blender。

## 0. 结论速览

| 项 | 结果 |
|---|---|
| `renderer: blender` → 12 视图 @ 长边 **1024 px**（1024×768） | **达标**：12/12 视图真实 Cycles 渲染，`samples_used=32` |
| 每视图耗时 / 12 视图总耗时 | 15.46–17.35 s（均值 **16.21 s**）／**194.48 s**（route 端到端 219.7 s） |
| 产物大小 | 每视图 **45.0–45.8 MB**（20 个文件）／12 视图 **545.2 MB** |
| `id_map` 是否整数 | int32，全整数（exact pass 非整数像素 **0/786432**），背景恒为 −1，标签 ⊆ [0, 6624) |
| `depth_z` 与独立射线投射（解析几何）误差 | 12 视图全部：中位 **0.08–0.11 mm**、p99.9 **0.87–4.13 mm**；解析斜面上相位对齐后 **4.5e-4 mm** |
| `uncertain_mask` 覆盖率 | 帧 **26.5–31.4 %**，物体像素 **≈81 %**（详见 §7：主要是声明景深之外的像素） |
| 默认行为 | **未变**：`renderer: auto`（含 `synlab generate` 批量路径）仍走软件光栅器（§3） |
| 与软件光栅器对照 | 同帧同 K/T_WC；耗时 **62.6×**；深度中位差 0.074–0.134 mm，但光栅器在斜面尾部达 **48.6 mm**（§6） |

**未达标/风险项**（§8）：部署 mask 在 1024 px 上只覆盖物体像素的 ~10–13 %；声明景深仅
30 mm 而物体 z 跨度 ~100 mm，uncertain 因此必然覆盖大部分物体（这是声明光学的结论，不是渲染
bug）；另有三处**写入范围之外**的缺陷被实测暴露：Blender exact pass 的**半像素采样相位**、
软件光栅器的**屏幕空间线性 z 插值**，以及 PLY 轴向声明造成的**无姿态渲染 180° 翻转**
（观测路线每视图都传姿态，12 视图实测不受其影响）。

## 1. 接线点（最小改动，全部可回退）

改动只落在两个文件（`git diff --stat`）：`synlab/observe/routes.py`、`synlab/observe/api.py`。

| 位置 | 改动 | 说明 |
|---|---|---|
| `routes.py: ObsSpec` | 新增 `renderer="auto"`、`distortion_policy="error"`、`blender_config=None` | 配置驱动的渲染后端选择；默认值与接线前等价 |
| `routes.py: resolve_render_backend()` | 新增 | 把 `spec.observation.renderer` / 显式参数映射到 `BACKEND_SOFTWARE` / `BACKEND_BLENDER`；未知值 → `SCHEMA_INVALID`；`blender` 且本机无二进制 → `ENV_CAPABILITY_MISSING`（**不降级**） |
| `routes.py: frame_has_distortion()` / `distortion_pixel_effect_px()` / `render_frame_for_backend()` | 新增 | OpenCV 畸变策略（`error` 默认拒绝 / `undistort` / `ignore`），并记录被丢弃系数及其最大像素影响 |
| `routes.py: render_views(..., *, backend=None, blender_config=None)` | 新增关键字参数 | 解析后端 → 逐视图调用 `render_view(..., backend=...)`；`ViewBundle.backend`/`distortion` 记录实际后端 |
| `routes.py: route_ideal_visible / route_proxy_scan / route_photo_mvs(..., *, backend=None)` | 新增关键字参数 | 三条路线都能选 Blender；`backend=None` 时沿用 `spec.renderer` |
| `routes.py: resolve_target()` | 新增 MotherGeometry 分支 | 真实母体资产可直接解析为可渲染 `Target`（面标签按母体词表透传，不重标） |
| `routes.py: render_backend_name()/render_backend_class()` | 接受参数 | 观测元数据/`backend_report`/每视图 meta 记录**实际**后端；无参调用仍返回 `SOFTWARE_RASTERIZER` |
| `api.py: observe()` | 用 `resolve_render_backend()` 替换"只接受软件渲染器"的硬拒绝 | 显式 `renderer=` 参数优先于 `spec.renderer`；`auto`/`software_rasterizer` → 软件；`blender` → Blender worker |

调用签名未变：`pipeline.py` 仍调用 `observe(physical, None, rngs, route=route, spec=observe_spec)`
（`renderer=None`），`configs/**` 未改。`synlab/observe/{render.py,blender.py,imaging.py,quality.py,
features.py,spurious.py,audit.py}` 与 `pipeline.py`、`cameras/**`、`patterns/**`、`storage/**`、
`frontend/**`、`tools/**` **未改动**。

## 2. 配置用法

```yaml
# configs/**.yaml
observation:
  renderer: blender        # auto | software_rasterizer | blender  （默认 auto）
```

等价的程序接口（三条路线都支持）：

```python
from synlab.observe.api import observe
from synlab.observe.routes import ObsSpec, DISTORTION_POLICY_UNDISTORT
from synlab.observe.blender import BlenderBackendConfig

spec = ObsSpec(view_count=12, delivered_size=(1024, 768), max_render_pixels=1024 * 768,
               renderer="blender",
               distortion_policy=DISTORTION_POLICY_UNDISTORT,     # 见 §4
               blender_config=BlenderBackendConfig(samples=32))
obs = observe(physical, None, rngs, route="ideal_visible", spec=spec)
# 或显式优先：observe(..., renderer="blender")   （覆盖 spec.renderer）
```

后端证据落点：`obs.meta["renderer"] == "BLENDER_CYCLES"`、`obs.meta["renderer_requested"]`、
`obs.meta["renderer_class"] == "ADAPTER"`、`obs.backend_report["renderer_backend"]`，
每视图 `obs.views[i].meta["render_backend"]` 与 `...["distortion"]`，
渲染层 `render.meta["blender_version"|"manifest_path"|"samples_used"|"render_seconds"]`。

## 3. 默认未变的证据（硬约束）

1. `ObsSpec()` 默认 `renderer="auto"`、`distortion_policy="error"`、`blender_config=None`；
   `resolve_render_backend()`（无参）与 `render_backend_name()`（无参）仍返回 `SOFTWARE_RASTERIZER`。
2. 读**真实**生成配置 `configs/a12/next_experiment.yaml`（`renderer: auto`）→
   `pipeline._resolve_observe_spec()` 投影出的 `ObsSpec.renderer == "auto"` →
   `resolve_render_backend(spec=...) == SOFTWARE_RASTERIZER`。测试
   `test_generation_config_projection_still_selects_the_software_rasterizer` 断言这条链路。
3. `observe(...)` 不带 `renderer` 的真实调用（测试
   `test_observe_without_renderer_stays_on_the_software_path`）→ 每视图
   `render_backend == "SOFTWARE_RASTERIZER"`（用 spy 断言真正传给 `render_view` 的 `backend`）。
4. `auto` 路径逐视图调用参数与接线前一致（`backend=SOFTWARE_RASTERIZER` 与默认值同值），
   帧/成像链/几何通道不变：§6 的软件对照就是在接线后的代码上跑出来的，几何与
   `docs/a12/observe_evidence.md` 记录的软件光栅器行为一致。
5. `synlab validate --config configs/a12/next_experiment.yaml --json` → exit 0（STDOUT `status: OK`）。

## 4. OpenCV 畸变策略（不悄悄忽略）

Blender 只能渲染理想针孔；相机档 `CAM_*_V3` 声明 `OPENCV` + 5 个非零系数
（GLOBAL `[-0.041, 0.011, 0.0008, -0.0006, -0.0025]`，MID `[-0.033, 0.008, 0.0006, -0.0005, -0.0018]`）。
`ObsSpec.distortion_policy` 三选一，**默认 `error`**：

| 策略 | 行为 | 落盘证据 |
|---|---|---|
| `error`（默认，现状） | 结构化拒绝：`ENV_CAPABILITY_MISSING`（`observe.routes.render_frame_for_backend`），`measurements` 带系数与最大像素影响；**不渲染、不降级** | 实测 MID 帧 0.007 s 内拒绝，未启动 Blender 进程 |
| `undistort` | 渲染**去畸变后的针孔相机**（与 `cv2.undistort` 取 `K` 为新相机矩阵等价，`K` 不变），交付帧 `dist=None, camera_model="PINHOLE"` | `bundle.distortion["distortion_undistorted"]=True`、`distortion_coefficients`、`distortion_max_pixel_effect_px`；每视图 meta + 交付帧 meta |
| `ignore` | 照常渲染理想针孔，**记录被丢弃的系数**及其最大像素效应 | `render.meta["distortion_ignored"]=True`（适配器）＋观测 meta `distortion_note` |

本轮 1024 px 实测采用 **`undistort`**（交付的是无畸变针孔图，标定与实际像素一致）。
软件光栅器自身支持畸变，`distortion_policy` 对它**无影响**（帧原样传入），
测试 `test_distortion_is_never_silently_dropped_on_the_software_path` 断言这一点。
MID 档在 1024×768 网格上的畸变最大像素效应实测见 `1024_12/blender.json: coc_policy` 同级的
`bundle.distortion` 记录（GLOBAL 96×72 探针：2.32 px）。

## 5. 1024 px × 12 视图实测（V1.44 G14.1）

场景：真实母体 `V01`（`create_mother`，6624 面，水密，bbox 154.8×154.7×84.3 mm）→
`resolve_target` → 路线 `ideal_visible`；相机档 `CAM_MID_V3`（**批量管线默认档**：
`observe(profile=None)` → `camera_profiles()[1]`，工作距离 220 mm，fx@1024 = 700.63 px，
mm/px = 0.314）；渲染网格 = 交付网格 **1024×768**（长边 1024，`distortion_policy=undistort`），
`RenderSpec(supersample=1)`，Blender `samples=32`。

| # | 视图 | 秒 | 产物 MB | id 类数 | depth 有效 | uncertain（帧） | ROI | 部署 mask |
|---|---|---|---|---|---|---|---|---|
| 0 | CAM_MID_V3#v00 | 15.46 | 45.05 | 3546 | 0.3305 | 0.2677 | 0.0318 | 0.0423 |
| 1 | #v01 | 16.15 | 45.79 | 3663 | 0.3615 | 0.3138 | 0.0338 | 0.0330 |
| 2 | #v02 | 16.40 | 45.76 | 3667 | 0.3611 | 0.3133 | 0.0338 | 0.0332 |
| 3 | #v03 | 15.87 | 44.99 | 3557 | 0.3284 | 0.2652 | 0.0317 | 0.0425 |
| 4 | #v04 | 15.92 | 45.08 | 3541 | 0.3293 | 0.2674 | 0.0316 | 0.0415 |
| 5 | #v05 | 17.35 | 45.80 | 3667 | 0.3609 | 0.3128 | 0.0338 | 0.0333 |
| 6 | #v06 | 16.90 | 45.82 | 3666 | 0.3617 | 0.3138 | 0.0338 | 0.0332 |
| 7 | #v07 | 16.27 | 45.09 | 3561 | 0.3297 | 0.2656 | 0.0319 | 0.0427 |
| 8 | #v08 | 15.71 | 45.10 | 3554 | 0.3302 | 0.2676 | 0.0318 | 0.0419 |
| 9 | #v09 | 16.52 | 45.83 | 3665 | 0.3615 | 0.3139 | 0.0338 | 0.0331 |
| 10 | #v10 | 15.95 | 45.80 | 3662 | 0.3611 | 0.3133 | 0.0338 | 0.0332 |
| 11 | #v11 | 15.98 | 45.06 | 3549 | 0.3287 | 0.2657 | 0.0317 | 0.0423 |
| — | **合计/均值** | **194.48**（16.21/视图） | **545.17** | 3541–3667 | 0.3284–0.3617 | 0.2652–0.3139 | 0.0316–0.0338 | 0.0330–0.0427 |

每视图的渲染 pass 计时（worker 自报，视图 0）：RGB 32 spp **5.72 s**、exact geometry **0.18 s**、
AA geometry **3.40 s**、target-only **0.17 s**（视图 5：6.32 / 0.22 / 3.80 / 0.19 s），
进程启动+场景导入约 2.4 s，其余为读回/统计/落盘。
`manifest.json` 记录 `samples_requested = samples_used = 32`、Blender 版本 5.2.2 LTS、每个输出文件的
sha256 与字节数。

路线端到端（含 z 反投影、体素融合、Open3D 法向）：**219.7 s**，融合点云 **151 006** 点，
`normal_valid` 比例 **1.0**，`quality` 块为 `obs_est.v1`（`point_count`、`nn_spacing_*`、
`view_coverage_mean`、`roi_coverage_mean`、`blur_laplacian_*` 等，`oracle=false`）。

### 5.1 质量门逐项

| 需求 | 实测 | 判定 |
|---|---|---|
| 12 视图 | 12/12 视图，3 层 ×4 方位（`make_view_frames` 同一实现） | ✅ |
| 长边 1024 px | 交付 1024×768（渲染网格同尺寸，无二次重采样：`A = I`） | ✅ |
| 场景线性 RGB | `rgb_linear` float32；背景声明值 `[0.02,0.02,0.025]` 回读 `[0.019999998,…,0.024999993]`，最大绝对误差 **7.1e-09**（sRGB 编码替代方案距离 0.147） | ✅ |
| 整数 ID / 标签 | `id_map` int32、exact pass 非整数像素 **0**、背景 −1、可见类 **3541–3667**、标签上界 6623 < 6624 个面 | ✅ |
| 深度 z（相机系 mm） | 有效像素 0.328–0.362；z 5–95 % 分位 166.6–270.8 mm；与独立射线投射对照见 §5.2 | ✅ |
| 法向 | 路线级 Open3D 法向 `normal_valid=1.0`；逐像素由深度导出的法向参与对照（§6） | ✅ |
| 点云（8192 点起步） | 融合 **151 006** 点（V1.44 起步值 2048–8192，本视图缓存为其 18 倍；采样步长 `backprojection_stride=2` 是声明值） | ✅ |
| 断口 ROI | `roi = (id>=0) & (surface_tag==2)`；母体词表里 tag 2 = 口沿（**母体没有断口界面**，故这是口沿 ROI 而非断口 ROI）覆盖率 3.2–3.4 %；断口 ROI 需要碎裂件，见 §8 | ⚠️ 语义已声明 |
| quality | `estimate_quality` 实跑，`oracle_prefilled=false` | ✅ |
| 相机标定 | 每视图 `K`、`T_WC`、`dist=None`（undistort 策略）、`A = I`、`pixel_convention=opencv_pixel_center_0_0` | ✅ |

### 5.2 `depth_z` 与解析值/独立几何的误差

三条独立证据（都不依赖渲染器自证）：

1. **解析平面（1024×768，100 mm 立方体，fx=1200，正面 350.000 mm）**：
   Blender 正面深度最大绝对误差 **0.0 mm**（114 921 个面内像素），软件光栅器同为 **0.0 mm**；
   正面宽度 Blender 342 px（解析 342.86，−0.86 px）、软件 343 px（+0.14 px）——与
   `docs/a12/blender_backend.md` §6 记录的"轮廓相差 ≤1 px"一致。
2. **解析斜面（同一立方体旋转 45°(Z)+20°(X)，平面仍然解析可算）**：
   对每个三角面取"3×3 邻域同一面"的内部像素（124 467 个），用本项目自己的
   Möller–Trumbore 像素中心射线作参照：
   * 采样相位 **(i, j)**（像素角）时 Blender 深度与射线投射吻合到中位 **1.6e-05 mm**、
     均值 5.0e-05 mm、最大 **4.5e-04 mm**；
   * 在项目声明的像素中心约定 **(i+0.5, j+0.5)** 上：中位 0.055 mm、均值 0.197 mm、最大 2.385 mm；
   * 软件光栅器同一组像素：任何相位都 ≥0.29 mm（最好相位中位 0.294 / 均值 0.844），
     最大 **8.885 mm** —— 这是屏幕空间**线性 z 插值**（`w0*z0+w1*z1+w2*z2`，而非 1/z）在
     斜面大三角形上的固有误差，与相位无关。
3. **真实母体 12 视图**（步长 16 px，每视图 3072 条射线）：
   * 可见性（命中/未命中）与独立射线投射的分歧：Blender **1–4/3072（0.03–0.16 %）**；
   * 全部成对像素：中位 **0.074–0.134 mm**，p99.9 0.87–4.13 mm；
   * 由"误差/局部深度跨度"反推的**像素相位偏移中位 0.45–0.50 px**、p95 ≈0.50 px —— 与
     证据 2 的半像素发现一致；误差与局部深度梯度相关系数 0.26–0.68。

结论：**Blender 深度通道在解析平面/斜面上是精确的**（≤4.5e-4 mm），交付数组相对项目像素中心
约定存在**半像素采样相位**（写在该文档的"未达标项"里，因为修复点在写入范围之外：
`blender.py`/`render_worker.py` 的读回与采样约定）。12 视图路线实际拿到的是"中心约定"下的数值：
中位 0.07–0.13 mm、面内最大 ≤1.56 mm。

## 6. 与软件光栅器的对照（同帧、同 K/T_WC、同路线）

对照设置：同一 `V01`、同一组 12 个 `ViewFrame`（**逐视图断言 K、image_size、T_WC 完全一致**：
`compare.json: all_frames_identical = true`）、同一 `RenderSpec(supersample=1)` 与同一"声明景深"
CoC 阈值（软件按 f/1 约定 ×8，Blender 按声明 f/2.2，二者等价；见 §7）。软件侧使用**声明的无畸变
孪生档**（`dist=None`, `camera_model="PINHOLE"`），与 Blender 的 `undistort` 交付帧一致。

| 量 | Blender Cycles（32 spp） | 软件光栅器 | 差 |
|---|---|---|---|
| 交付尺寸 | 1024×768 | 1024×768 | 一致 |
| 每视图耗时 | 16.21 s（15.46–17.35） | **0.259 s**（0.24–0.29） | **62.6×** |
| 12 视图总耗时（渲染） | 194.5 s | **3.11 s** | 62.6× |
| route 端到端 | 219.7 s | 22.1 s | 9.9× |
| 每视图产物 | 45.0–45.8 MB（20 文件，含 EXR/npy/manifest） | 0（内存内，未落盘） | — |
| 物体像素占比 | 0.328–0.362 | 0.316–0.350 | Blender 轮廓多 1 px |
| id 类数/视图 | 3541–3667 | 3462–3677 | ≈ |
| 深度中位 | 237.5 mm（视图 0） | 238.8 mm | 1.35 mm（含轮廓与采样相位差） |
| 逐像素深度差（12 视图，25–27 万像素/视图） | 中位 **0.074–0.134 mm**、均值 1.58–2.38 mm、p99 17.3–26.2 mm、最大 18.0–74.2 mm；≤0.05 mm 的比例 6.5–44.8 %、≤0.5 mm 63.9–70.3 %、>5 mm 5.5–12.3 % | — | 尾部主要来自光栅器线性 z 插值（§5.2 证据 2）与轮廓像素 |
| 深度 vs 独立射线投射（全部成对） | 中位 0.074–0.134 mm、p99.9 0.87–4.13 mm | 中位 **0.004–0.013 mm**，但 >5 mm 的像素对 **18–129 个/视图**、最大 **17.7–48.6 mm** | 光栅器局部更准、尾部更差 |
| 可见性分歧（射线投射） | 0.03–0.16 % | 1.2–1.3 % | Blender 轮廓更准 |
| 逐像素法向（由深度导出，夹角） | — | — | 中位 **0.91–0.99°**、均值 1.8–2.2°、p95 5.4–6.7°、>5° 占 6.8–11.5 % |
| 融合点云点数 | **151 006** | **213 843** | 软件多 42 %（轮廓/混合像素规则不同） |
| 点云互近邻距离 | — | — | Blender→软件 中位 **0.353 mm**、p95 1.29 mm、最大 2.79 mm；软件→Blender 中位 0.633 mm、p95 4.19 mm、最大 5.24 mm（体素 0.628 mm） |
| `uncertain_mask`（帧 / 物体） | 0.265–0.314 / ≈81 % | 0.228–0.275 / ≈73 % | 规则不同（AA 混合 vs 超采样分歧） |
| 部署 mask（帧 / 物体） | 0.033–0.043 / 10–13 % | 0.067–0.081 / 21–25 % | 见 §8 |
| 法向有效性（路线级） | 1.0 | 1.0 | 一致 |
| 遮挡通道 | 有（`occlusion` / `target_visibility`） | 无 | 后端能力差异（已记录在 `blender_backend.md`） |

## 7. `uncertain_mask` 覆盖率的成因（实测分解）

worker 的 `channels.json` 给出逐规则计数（视图 0，1024×768，物体 259 915 px）：

| 规则 | 像素 | 说明 |
|---|---|---|
| `defocus_coc_gt_threshold` | **188 987** | CoC 超阈值 |
| `mixed_pass`（AA AOV 混合） | 110 931 | 密集网格（6624 面 / ~26 万物体像素）下相邻像素常跨面 |
| `depth_edge` | 0 | 深度台阶 |
| 合计 `uncertain` | 210 563（帧 26.8 %、物体 **81.0 %**） | 两条规则有重叠 |

景深是主因，而且这是**声明光学的真实结论**：`CAM_MID_V3` 声明 f/2.2、f=5.2 mm、
工作距离 220 mm → `thin_lens_dof` 给出景深 **[206.3, 235.6] mm（仅 30 mm）**，而物体 z 跨度
**166.6–270.8 mm（~104 mm）**。也就是说在这一档下大部分物体本来就落在声明景深之外。

同时发现渲染器/配置的**约定不一致**（与 `pipeline.py` 文档里记录的软件路径 f/1 问题同类）：

* 渲染器 CoC 公式用**像素焦距**（`f_px²/(N·z)·|z−z_f|/z_f`），在 1024 px、f/2.2 下，
  声明景深边缘对应 **67.25 px**；而 `0.75 px` 这一声明阈值只覆盖 z∈[219.4, 220.6] mm 的
  **±0.6 mm** 薄带 → 按"管线约定"只有 **0.18–0.28 %** 的物体像素算"确定"。
* 本轮因此把阈值**标定到声明景深**（`worker_threshold_px = max(CoC(z_near), CoC(z_far)) = 67.25`，
  软件侧等价 `147.94 px`，两者都记录在 `blender.json: coc_policy`），使"defocus 不确定"
  恰好等于"落在声明景深之外"。这是**声明值**，不是为了让数字好看。

因此 §5 表里的 uncertain 覆盖率可以读作：**81 % 的物体像素要么在声明景深之外、要么跨面混合**；
剩下约 19 % 才是"可安全监督"的像素，部署 mask（再腐蚀 1 px 且要求 `visibility>0`）只有 10–13 %。
这与 `docs/a12/observe_evidence.md` §7.5 记录的现象（软件路径下"确定"像素仅 13.5 %，SIFT 被饿到
2/12 注册）一致：**在 1024 px 档位上，掩码/景深策略比渲染后端本身更卡观测量**。

## 8. 未达标项与原因（不掩饰）

1. **部署 mask 覆盖率低（10–13 % 物体像素）**：成因见 §7（声明景深 30 mm ≪ 物体 z 跨度 104 mm，
   加上密集网格的 AA 混合规则）。这不是 Blender 后端引入的，但 1024 px 档位下它依然限制
   `photo_mvs` 的可用特征数。可选修法都在写入范围之外：调整 `coc_px_threshold` 的语义
   （渲染器公式的像素焦距约定）、放宽混合规则（用 exact pass 的整数标签而非 AA AOV 判混合）、
   或按 B9 用"多焦点档"拍多个景深层。
2. **Blender exact pass 的半像素采样相位**（§5.2 证据 2）：在声明像素中心约定下，斜面深度残差
   中位 0.055 mm、最大 2.39 mm；相位对齐后 4.5e-04 mm。影响：逐像素反投影的横向误差约
   0.5 px × 0.314 mm/px = **0.16 mm**（1024 px 档）。修复点在 `blender.py`/`render_worker.py`
   的读回/采样约定（写入范围之外），本轮只记录并提供可复现测量。
3. **`object_pose=None` 时的 PLY 轴向翻转**（写入范围之外，本轮新发现）：适配器把 PLY 轴声明为
   `forward=NEGATIVE_Y, up=Z`，Blender 的 PLY 导入器据此给对象 `matrix_world = diag(-1,-1,1)`
   （绕世界 Z 轴 180°）；worker 只在**给了姿态**时才覆盖 `matrix_world`。
   * 观测路线的每个视图都传 `object_pose`（`frame.meta["object_pose_T_WO"]`），因此**12 视图实测
     不受影响**（`probe_pose_flip.json`：按项目几何对照 0.90 mm，按 180° 翻转对照 2.11 mm）；
   * 不传姿态的直接 `render_view(..., backend="BLENDER_CYCLES")`（含 `blender_backend.md` 的
     立方体夹具）会渲染出 180° 旋转的物体：立方体因对称而看不出来，但 `id_map` 标签被置换
     （`probe_rotation_cases.json`：identity 立方体 1764/1764 个像素 id 与面序不符；
     45°(Z)+20°(X) 斜盒轮廓分歧 333/342、深度中位差 14.5 mm）。
   * 最小修法（二者之一）：`_export_object` 声明 `axis=("Y","Z")`；或无论是否给姿态都显式设置
     `matrix_world`。**本轮不改这两处文件**（写入范围限制）。
4. **`id_map` 与输入面序的对应关系未被既有测试覆盖**：`test_blender_backend.py` 只断言
   "类别 ⊆ range(n_faces)"，180° 翻转下仍成立。本轮的 `probe_rotation_cases.json` 给出了
   面序一致性测量；建议把"id_map 与输入面序一致"加入 Blender 后端的验收断言（需要先修第 3 条）。
5. **断口 ROI 未在真实断口上验证**：本轮用真实**母体**（V01）作目标，母体没有断口界面，
   `surface_tag==2` 是口沿；断口 ROI 需要碎裂件（`rough_shared_cut`，实测 28 s/次、接受率
   ~50 %，见 `docs/a12/observe_evidence.md`），不在本轮预算内。
6. **`photo_mvs` 的 1024 px 真实 COLMAP 运行未做重负载验证**：本轮只证明 Blender 后端能被
   `photo_mvs` 选中并产出 Blender 帧（`test_photo_mvs_route_can_select_blender`，SfM 阶段被
   有意 stub）。真实 pycolmap 全流程在 1024 px/12 帧下的耗时与注册率未测；`mvs_subset.py`
   也仍然固定走软件光栅器（`ObsSpec` 未暴露 renderer 参数），需要后续接线。
7. **Blender 时间成本**：62.6×/视图（16.2 s vs 0.26 s）。按 100 母体 × 12 视图估算渲染约
   5.4 CPU 小时（本机单进程），与 V1.44 §7 的"3.3–13.3 GPU 小时"算式同量级但基于实测而非算式；
   高吞吐烟雾循环仍应使用软件光栅器。
8. **磁盘**：12 视图产物 545 MB（工作目录 1.57 GB，含 EXR pack 与 per-pass npy）。
   按 A12.14 的 70/80/90 % 阈值需要在批量运行前确认保留策略。

## 9. 复现命令与产物

```powershell
# 0) 能力探针（doctor 的 backend:blender_render 与本路径同一实现）
.venv\Scripts\python.exe -m synlab.cli doctor --json

# 1) 测量工具自检（射线投射/法向对解析几何，0.0 mm）
.venv\Scripts\python.exe data\a12\reports\blender\render_1024_12.py --stage selftest

# 2) 单视图探针（1024 px / 32 spp / GLOBAL 档）
.venv\Scripts\python.exe data\a12\reports\blender\render_1024_12.py --stage probe --profile-index 0

# 3) 12 视图 @ 1024 px：Blender（~200 s）与软件对照（~25 s）
.venv\Scripts\python.exe data\a12\reports\blender\render_1024_12.py --stage blender  --views 12 --long-edge 1024 --samples 32 --profile-index 1
.venv\Scripts\python.exe data\a12\reports\blender\render_1024_12.py --stage software --views 12 --long-edge 1024 --profile-index 1
.venv\Scripts\python.exe data\a12\reports\blender\render_1024_12.py --stage compare

# 4) 解析夹具（平面/斜面；--tilt 用 45/20 度旋转盒）
.venv\Scripts\python.exe data\a12\reports\blender\render_1024_12.py --stage fixture --samples 32
.venv\Scripts\python.exe data\a12\reports\blender\render_1024_12.py --stage fixture --samples 32 --tilt

# 5) 接线测试
.venv\Scripts\python.exe -m pytest tests/a12/observe -q -p no:cacheprovider
```

产物（`data/a12/reports/blender/`）：

| 文件 | 内容 |
|---|---|
| `1024_12/blender.json`、`software.json` | 两个阶段的观测级摘要（后端、帧、id 类数、uncertain、点数、quality、耗时） |
| `1024_12/{blender,software}_views.jsonl` | 逐视图记录：wall/worker 秒、pass 秒、产物字节、id/depth/uncertain 统计、独立射线投射对照、worker 自检 |
| `1024_12/compare.json` | 逐视图对照、深度/法向一致性、点云互近邻、景深带分析 |
| `1024_12/fixture.json`、`fixture_tilted.json` | 解析平面/斜面深度证据 + 相位搜索 |
| `1024_12/{depth,normals}_{blender,software}_*.npy` | 对照所用的原始数组（每视图） |
| `1024_12/probe_axis_flip.json`、`probe_rotation_cases.json`、`probe_depth_phase.json`、`probe_pose_flip.json` | §8 第 2/3 条的探针证据（生成脚本在 `_scratch/`） |
| `_run_1024_*.log`、`_probe_1024_32spp.log` | 本轮运行的完整 stdout |
| `_pytest_observe_required.txt`、`_pytest_observe_counts.txt` | 验收测试命令的输出（退出码见 §10） |
| `_work/` | Blender worker 的原始工作目录（每视图 manifest/channels/EXR/npy，约 1.57 GB） |
| `render_1024_12.py`、`_scratch/` | 测量工具与探针脚本（自检、轴向/相位/姿态翻转探针） |

## 10. 测试

新增 `tests/a12/observe/test_renderer_dispatch.py`（24 项，实测 `24 passed in 13.95s`，exit 0；
其中 4 项为真实 Blender 渲染）：`auto`/`software_rasterizer`/
无参 → 软件（用 spy 断言真正传给 `render_view` 的 backend）；真实配置投影仍为软件；
`blender` → 真实 Cycles（断言 `blender_version`、`samples_used`、manifest 存在、`ADAPTER` 类）；
Blender 缺失 → `ENV_CAPABILITY_MISSING` 且不产生任何软件帧；三条路线都能选 Blender；
畸变三策略与默认拒绝；未知 renderer/策略结构化拒绝；母体资产可解析为 Target；
观测元数据 JSON 可序列化。需要真实 Blender 的用例在无 Blender 主机上 skip，不放宽断言。

```
# (a) 任务规定的验收命令 -> exit 0（_pytest_observe_required.txt 只含进度行，见下方注）
.venv\Scripts\python.exe -m pytest tests/a12/observe -q -p no:cacheprovider
# (b) 同一批测试、去掉 addopts 叠加以便记录通过数 -> exit 0
.venv\Scripts\python.exe -m pytest tests/a12/observe -q -p no:cacheprovider -o addopts="" -rs
# → 53 passed, 1 skipped in 58.47s（2026-10-02，本机空载；明细 _pytest_observe_counts.txt）
```

> 注 1：`pyproject.toml` 的 `addopts = "-q"` 与命令行 `-q` 叠加成 `-qq`，pytest 因此**不打印**
> 末尾的 `N passed` 行；退出码仍是权威判据（(a) 实测 exit 0）。
> 注 2：`-rs` 显示的 1 项 skip 是既有用例（`synlab/api/display.py::authority_to_display` 已修，
> `test_pixel_contract.py:115` 主动 skip），不是本轮新增的跳过。
> 注 3：本轮早前两次在**同时跑 1024 px Blender 重负载**时该套件出现过一次
> `test_source_dependency_audit_is_a_real_experiment` 失败，以及一次
> `Windows fatal exception: code 0x8007000e`（内存不足，`import trimesh` 阶段）。
> 空载重跑两次全部通过（(a)(b) 均 exit 0），且本文档 §6/§7 记录的“本机对重负载 Python 会直接
> 杀进程/匹配阶段不可逐位重复”是仓库既有结论，故判定为负载导致的抖动，与本次改动无关
> （改动只在 `observe/{routes,api}.py`，不参与 COLMAP 注册）。

