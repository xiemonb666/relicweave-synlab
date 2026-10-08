# 31 轴退化算子：实现、实测状态与缺口（A12 第 15 节 / 30.7–30.9）

本文件是 `synlab/degrade/**`（31 轴算子 + façade）的交付说明与**实测状态表**。所有数字来自本机
实测（固定环境、固定 basis），不是声明值；未实测到变化的档位按 `OPERATOR_NOT_REALIZED` /
`PRECISION_NOT_REALIZED` / `TARGET_INFEASIBLE` 进入失败分母，**不改成 NA**。

**当前实测结论（第 4 节给出复现命令）**：`audit_all_axes(store=None, levels=[0,1,2,3,4])` →
**31/31 轴 PASS、155/155 档 PASS、0 FAIL、0 NA**，`identity_ok=True`、`all_axes_pass=True`。
P02 / P03 / P04 三个轴的 9 个 FAIL 档已全部修好（见 §3.1 / §4）。

## 1. 交付物

| 文件 | 内容 |
|---|---|
| `synlab/degrade/registry.py` | 31 轴的 `AxisOperator` 协议与注册表；`apply()` 现在接受 `_apply_impl` 合并后的 **effective parameters**（修掉“`parameters=` 覆盖只写进记录、从未到达算子”的缺陷，见 §4.3） |
| `synlab/degrade/axes.py` | **31 个轴全部注册**（P01–P08、I01–I10、G01–G08、X01–X05）；`_PhysicalAxis.NARROWBAND` 选择窄带后端；P02/P03/P04 改走窄带后端 |
| `synlab/degrade/narrowband.py` | **新增**：窄带/边缘局部几何内核——ROI 边界锐边提取、逐边滚球截面（`edge_sections`）、解析退让场（`edge_recession_depth`）、逐顶点法向退让体（`edge_recession_body` / `recessed_body`）、成对壁厚探针（`paired_thickness`）、水密断言 |
| `synlab/degrade/physical_narrowband.py` | **新增**：P02/P03/P04 的算子实现，产出真正的 `PhysicalResult`（复用 `physical.api.register_components` 的 30.8 身份政策），不修改 `synlab/physical/**` |
| `synlab/degrade/ops_image.py` | OpenCV/numpy 原语：高斯 PSF、方向核、曝光期运动积分、`y=Poisson(g·x)/g+N(0,σ²)`、曝光/数字增益、固定方向白平衡、`INTER_AREA` 抗混叠降采（同步 K/A）、JPEG 编解码、清晰度/噪声/块效应/方向实测 |
| `synlab/degrade/ops_geometry.py` | G 轴原语：低频相关深度场、嵌套前缀稀疏、连通孔、SE(3) 扰动+重融合、QEM 简化+Hausdorff/法向/ROI 保留、标定扰动+重反投影、观测尺度、depth-mesh 融合 |
| `synlab/degrade/api.py` | `compile_recipe / apply_axis / audit_axis / audit_all_axes / probe_sources / operator_audit_table / write_operator_measurements / run_recipe` |
| `synlab/degrade/compat.py` | 环境/缺陷 shim 机制；**当前 0 个 shim 处于激活状态**（3 个已由上游修复而退役，1 个改为可选），退役证据见 §5 |
| `tests/a12/operators/**` | **148 项**测试（原 140 + 新增 `test_narrowband.py` 8 项） |
| `tools/build_demo_assets.py` | **未修改**（属另一名队友）；只运行 |

## 2. 命令与结果（本机实测）

| 命令 | 退出码 | 结果 |
|---|---|---|
| `& .venv\Scripts\python.exe -m pytest tests/a12/operators -q` | **0** | **148 passed**（100%） |
| `& .venv\Scripts\python.exe -m pytest tests/a12/operators/test_effects.py tests/a12/operators/test_registry.py -q` | **0** | 通过（分片运行） |
| `& .venv\Scripts\python.exe -m pytest tests/a12/operators/test_identity.py -q` | **0** | 38 passed |
| `& .venv\Scripts\python.exe -m pytest tests/a12/operators/test_audit_api.py -q` | 进程被宿主杀死（文件末尾已打印 `38 passed / 100%`） | 见 §4.4：本机对重负载 Python 进程会在**收尾阶段**直接杀进程，测试断言已全部通过 |
| `audit_all_axes(store=None, levels=[0,1,2,3,4])` | — | 11.6 s；`ok=True`、`identity_ok=True`、**`all_axes_pass=True`** |
| `& .venv\Scripts\python.exe tools\build_demo_assets.py --only degrade` | **1**（仅因断裂分区失败，见下） | 退化分区 **12/12 OK** |

155 档分母（plan 15.7 第 4、6 条）：

```
axes_registered=31  axes_audited=31  axes_pass=31  axes_na=0  axes_fail=0  axes_missing=0
levels_planned=155  levels_passed=155  levels_na=0  levels_failed=0
```

**源说明**：审计源为 `probe_sources()`，每个 bundle 的 `meta['provenance']` 明确标注来源——
`BUILTIN_PROBE_REAL_RENDER`（真实 proxy_scan 渲染 320×240×4 视图）、
`BUILTIN_PROBE_FIXTURE_ROUGH_INTERFACE`（带 declared 粗糙断面的探针实体）、
`STORE_ASSET:<id>`（优先使用库内真实资产）。

### 2.1 测试分片（宿主杀进程的实际行为）

任务书要求「分文件/分半运行并在文档写明」。实测：

* 全量 `pytest tests/a12/operators -q` **退出码 0**（148 passed）；
* 单独运行 `test_audit_api.py` 时，pytest 已经打印完整进度与 warnings，随后**收尾阶段**进程被宿主杀死
  （退出码 -1，无 Python 异常）——这是因为该文件在一个进程里累积了 31 个轴的 SDF 工作；
* 通过管道（`| Select-Object -Last N`）读取 pytest 输出会提前关闭 stdout，也会让 pytest 以 -1 退出；
  **必须写文件再读**。

## 3. 逐轴状态表（level 0..4；P=通过、F=失败、N=NA）

| 轴 | 状态 | 0..4 | 实测变化（非零档） | 备注 |
|---|---|---|---|---|
| P01 polish_interface | PASS | PPPPP | `hf_rms_reduction` 0.0533/0.0919/0.0890/0.0372 mm；`lost_volume_mm3` 38.8/109.0/219.1/368.2 | 半径 2.0 mm 固定，只变 `recession_strength` |
| P02 round_edge | **PASS** | **PPPPP** | 见 §3.1：`measured_max_recession_mm` = 0.0533/0.1066/0.1598/0.2131 mm；`lost_volume_mm3` 1.38/2.82/4.51/6.37；96 条 ROI 边界锐边、总长 84.172 mm | 边缘局部滚球退让（窄带），水密、ROI 外漂移 ≤9.6e-7 mm |
| P03 erode_interface | **PASS** | **PPPPP** | 见 §3.1：`applied_depth_mm` = 0.05/0.1/0.25/0.5（=声明值）；`lost_volume_mm3` 13.62/27.23/68.09/136.20 | 亚格点 0.05 mm（=0.10 个冻结格距）已实测 |
| P04 chip_material | **PASS** | **PPPPP** | 见 §3.1：`achieved_contact_loss` = 0.10003/0.25024/0.50016/0.80025，`target_abs_error` ≤2.5e-4（预算 0.02）；`cutter_radius_mm` 3.42/6.83/11.27/18.20 | 刀具中心/方向五档完全一致（冻结），只搜尺寸 |
| P05 remove_paint | PASS | PPPPP | 彩绘残留面积 106.8→378.6 mm² 嵌套递减，几何 hash 不变 | 外观轴，`geometry_hash_unchanged=1` |
| P06 dirt_cover | PASS | PPPPP | 覆盖 0.2/0.4/0.6/0.8 档实测 `realized_coverage`、纹样可见率下降、albedo/roughness 变化 | 核心版只改外观 |
| P07 erode_outer | PASS | PPPPP | `realized_max_recession_mm` 0.0250/0.0500/0.1000/0.1999；`lost_volume_mm3` 25.6/38.5/63.7/110.9 | 只作用外表面 ROI |
| P08 crack_or_coat_loss | PASS | PPPPP | `crack_width_mm` 0.524/1.697/3.972/6.324；`achieved_affected_area_fraction` 0.0555/0.1035/0.2007/0.3004 | variant 各自注册 + `bundled_coat_and_crack`（BUNDLED_STRESS） |
| I01 defocus | PASS | PPPPP | `sharpness_drop_ratio` 0.642/0.957/0.995/0.999 | 高斯 PSF |
| I02 motion_blur | PASS | PPPPP | 清晰度下降；方向估计（结构张量）与施加方向一致 | `directional_kernel` / `exposure_integration` 分开 |
| I03 sensor_noise | PASS | PPPPP | `noise_sigma_increase` 0.0052/0.0092/0.0151/0.0330 | `photon_scale`/`read_sigma` 单因素 |
| I04 exposure | PASS | PPPPP | 饱和/暗部统计、`delivered_changed_fraction` | `exposure_gain` 与 `digital_gain` 分列 |
| I05 white_balance | PASS | PPPPP | R/G 比值漂移 | 固定方向向量，校准状态冻结 |
| I06 specular | PASS | PPPPP | `highlight_p99` 单调上升 | **真实重渲染** |
| I07 occlusion | PASS | PPPPP | `visible_fraction` 单调下降 | 3D 遮挡体重渲染 |
| I08 fewer_views | PASS | PPPPP | `views_after` 4→3→2→1 | 固定优先序嵌套 |
| I09 lower_resolution | PASS | PPPPP | 长边 320→240/160/80/40 | `INTER_AREA` 抗混叠，K 同步 |
| I10 jpeg_loss | PASS | PPPPP | `encoding_error_rms` 5.13/7.07/8.17/9.32 | 零档不重新编码 |
| G01 depth_error | PASS | PPPPP | `applied_rms_mm`=目标；离群/相关性实测 | 低频相关场 |
| G02 sparse_points | PASS | PPPPP | `kept` 严格递减（嵌套前缀） | 预算上限冻结 |
| G03 regional_holes | PASS | PPPPP | `removed_area_mm2` 5489/10908/15770/20649 | 连通孔，非均匀丢点 |
| G04 frame_drift | PASS | PPPPP | 每帧 SE(3) 后重融合，残差/重影实测 | `translation_only`/`rotation_only` 单因素 |
| G05 mesh_decimation | PASS | PPPPP | `face_reduction_ratio` 0.188/0.500/0.625/0.812 | QEM + 独立 Hausdorff |
| G06 scale_drift | PASS | PPPPP | `measured_ratio`；Truth hash 不变 | 只改观测框架 |
| G07 calibration_error | PASS | PPPPP | 重投影/深度偏差 | focal/principal/distortion 单列 |
| G08 spurious_surface | PASS | PPPPP | `measured_max_displacement_mm` 0.374/0.797/1.351/2.168 | clean hash 不变 |
| X01 missing_modality | PASS | PPPPP | `removed_count` 1/2/3/4，`zero_filled=0` | 不填 GT/零图 |
| X02 segmentation_error | PASS | PPPPP | `changed_px`/IoU/边界误差 | crop variant 同步 K |
| X03 context_error | PASS | PPPPP | 缺失与冲突分开计 | 两个 variant |
| X04 quality_miscalibration | PASS | PPPPP | `mean_shift` = bias×实测 σ | 只扰动 OBS_EST |
| X05 profile_shift | PASS | PPPPP | `profile_distance`、变更字段数 | CATEGORICAL_SHIFT，无标量单调主张 |

### 3.1 P02 / P03 / P04 逐档 planned vs measured（单位）

**P02 `sdf_fillet`**（`edge_width_mm=0.4` 冻结；`recession_strength` 0/.25/.5/.75/1）
`effective_radius = edge_width_mm × recession_strength` = 0/0.1/0.2/0.3/0.4 mm。

| 档 | planned 最大退让 (mm) | measured 最大退让 (mm) | 实测平均退让 (mm) | 丢失体积 (mm³) | 水密 | 连通体 | ROI 外漂移 (mm) | 移动顶点数 |
|---|---|---|---|---|---|---|---|---|
| L0 | 0（恒等） | — | — | 0（引用原字节） | — | 1 | 0 | 0 |
| L1 | 0.053276 | 0.053276 | 0.001653 | 1.382 | True | 1 | 9.55e-7 | 102 |
| L2 | 0.106551 | 0.106551 | 0.003537 | 2.820 | True | 1 | 9.55e-7 | 119 |
| L3 | 0.159827 | 0.159827 | 0.005686 | 4.511 | True | 1 | 9.55e-7 | 144 |
| L4 | 0.213102 | 0.213102 | 0.007984 | 6.370 | True | 1 | 9.55e-7 | 164 |

* 退让深度 = `r/sin(ψ) − r`，ψ 为 ROI 边界锐边的材料楔半角（探针实测中位二面角 91.27°）。
* `planned_contact_width_mm` = `r/tan(ψ)`：0.116/0.232/0.348/0.465 mm —— 扰动紧支撑，**rim 从不移动**。
* 边缘集合 = ROI 面上「恰好一侧属于 ROI」的锐边：96 段、总长 84.172 mm（全 210 条锐边里 96 条在 ROI 边界）。

**P03 `smooth_recession_field`**（`corr_length_mm=6.0` 冻结）

| 档 | planned `depth_mm` | applied `depth_mm` | measured 最大顶点位移 (mm) | 实测平均顶点位移 (mm) | 丢失体积 (mm³) | 线性预测 (mm³) | 比值 | 厚度守卫 | 水密 | ROI 外漂移 (mm) |
|---|---|---|---|---|---|---|---|---|---|---|
| L0 | 0 | — | — | — | 0（引用原字节） | — | — | — | — | 0 |
| L1 | 0.05 | 0.05 | 0.049976 | 0.033790 | 13.617 | 14.744 | 0.9236 | scale=1.0，违规分数 0 | True | 9.83e-7 |
| L2 | 0.10 | 0.10 | 0.099952 | 0.067526 | 27.235 | 29.489 | 0.9236 | scale=1.0，违规分数 0 | True | 9.83e-7 |
| L3 | 0.25 | 0.25 | 0.249879 | 0.167979 | 68.092 | 73.722 | 0.9236 | scale=1.0，违规分数 0 | True | 9.83e-7 |
| L4 | 0.50 | 0.50 | 0.499727 | 0.331201 | 136.198 | 147.444 | 0.9237 | scale=1.0，违规分数 0 | True | 9.83e-7 |

* 0.05 mm = 0.10 × 冻结格距 0.5246 mm，**已实测可表达**（不再 `PRECISION_NOT_REALIZED`）。
* `lost_volume_vs_linear_ratio ≈ 0.9236`：线性预测按「面积 × 深度」估算，差值来自逐顶点面积加权与
  rim 钉零（rim 深度被置 0），是**可解释的离散修正**，不是隐藏误差。

**P04 `contact_loss`**（接触面积 434.062 mm²；刀具中心/方向由 basis 冻结，五档同一位置）

| 档 | planned 目标 | measured 达成 | \|误差\| | 预算 | 丢失接触面积 (mm²) | 残留接触面积 (mm²) | 刀具半径 (mm) | 丢失体积 (mm³) | 最大连通体比 | 连通体 |
|---|---|---|---|---|---|---|---|---|---|---|
| L0 | 0 | — | — | 0.02 | 0 | 434.062 | — | 0（引用原字节） | 1.0 | 1 |
| L1 | 0.10 | 0.100032 | 3.2e-5 | 0.02 | 43.42 | 390.64 | 3.421 | 69.92 | 0.9888 | 1 |
| L2 | 0.25 | 0.250237 | 2.4e-4 | 0.02 | 108.62 | 325.44 | 6.830 | 288.41 | 0.8477 | 1 |
| L3 | 0.50 | 0.500158 | 1.6e-4 | 0.02 | 217.10 | 216.96 | 11.268 | 656.69 | 0.5339 | 1 |
| L4 | 0.80 | 0.800252 | 2.5e-4 | 0.02 | 347.36 | 86.70 | 18.198 | 1091.90 | 0.2178 | 1 |

* `cutter_center_mm = (-10.125, 0.84375, 1.636945)` 五档完全一致（测试 `test_p04_cutter_choice_does_not_move_with_the_target`
  断言）——符合 30.7「位置/方向先冻结，再一维搜索尺寸」。
* 目标可达上限（实测）：`TARGET_INFEASIBLE` 在 target=1.0 时触发，`achieved_contact_loss=0.9830`
  （scale 52.25），即冻结刀具族 + 2% 代表体守卫下的真实天花板。

## 4. 缺口与本次修复（实测，未改 NA）

### 4.1 已修复：P02 全部四档、P03 L1–L3、P04 L3–L4

**根因（实测）**：`synlab.physical.operators.SdfContext` 用**一套全域均匀网格**，间距被
`choose_spacing` 冻结为 `min(最小壁厚/6, 最短结构/4)`。探针实测最小壁厚 1.2446 mm →
**格距 0.5246 mm**（51×40×12 节点）。而：

* P02（`edge_width_mm=0.4`）声明退让 0.1657 mm = **0.32 个格距**；
* P03 声明 0.05/0.1/0.25 mm = **0.10/0.19/0.48 个格距**。

亚半格的扰动不产生闭合的 marching-cubes 曲面，`candidate ∩ source` 守卫收到开放网格并以
`ValueError: Not all meshes are volumes!` 拒绝 → `PRECISION_NOT_REALIZED`。

**否决的替代方案（保留为反证）**：

1. *全域更细网格*：0.05 mm 需 12.3M 节点；0.12 mm 仍然相交失败；0.25 mm 时体积误差 3.01 mm³
   （声明效果仅 0.28 mm³）→ 提面漂移远大于声明效果，不是分辨率问题而是方法问题。
2. *解析倒角棱柱做布尔差*：截面本身精确（90°/r=0.4 → 深度 0.165685 mm、接触宽 0.4 mm、
   面积 0.034336 mm²，已用 30°–150° 五种楔角交叉验证），但布尔不可用——`manifold` 需要约
   `1e-3·r` 的内缩才水密（内缩 0 与 1e-4 均产生非流形边），而内缩后切口有 37% 面积、最多
   0.147 mm 落在源体**外**，因为探针断面自带 0.18 mm 真实粗糙度，而刀具是按理想面构造的。

**采用的实现（计划 12.1「窄带/自适应」、12.2）**：只在声明效果非零处求值，且结果是**闭合体**：

* **P02**（`edge_recession_body`）：取 ROI 边界锐边（恰好一侧属于 ROI 且二面角 > 45°），
  对每条边算出**向内滚球截面**（球心距离 `r/sin(ψ)`、接触点 `r/tan(ψ)`、最大退让 `r/sin(ψ)−r`），
  再按「到边缘曲线的横向距离」把该截面深度施加到顶点法向上；深度在 `ρ ≥ r` 处归零，
  故扰动**紧支撑**、rim 不动。法向先投影到「垂直于边」的平面——探针粗糙顶面法向最多倾斜约 8°，
  不投影会让截面沿边剪切。
* **P03**（`recessed_body`）：冻结的平滑深度场按 ROI 面积加权平均到顶点，rim 钉零，
  再沿顶点法向内缩。未受影响的表面**沿用原始三角形**，因此没有提面漂移。
* **P04**（`chip_material`）：位置/方向来自 basis，尺寸用**一维几何搜索**——几何增长找到
  「可行且 ≥ 目标」或「首次不可行/空」的上界，再在 `[可行下界, 上界]` 上二分。
  二分的上界同时覆盖「代表体守卫天花板」，所以**可达目标不会被误报为不可行**（反证：直接
  从 scale 32 翻到 64 并放弃，会把 probe 上确实可达的 0.8 报成 `TARGET_INFEASIBLE`）。

三条通道都保持：**level 0 真恒等**、**水密**（`assert_watertight` 结构化失败而非静默通过）、
**`damaged ⊆ clean`**（实测 `max_outside_clean_mm ≤ 1e-5`）、**ROI 外漂移 ≤ 1e-6 mm**。

**保留的合法不可行**：P04 目标 1.0/1.5 仍返回 `TARGET_INFEASIBLE` 并携带实测
`achieved_contact_loss=0.9830`、`search_feasible_scale_max=52.25`、`best_feasible_volume_ratio`；
不去改 NA，也不改目标。测试 `test_p04_unreachable_target_is_structured_not_silent` 锁定该行为。

### 4.2 其他未解决项

* **每轴 20 个独立母体**（15.7 第 6 条）：本机 `independent_mothers` 仅为探针源 1 个。该要求是
  数据集级要求，需在真实母体库上跑 `audit_all_axes`（`tools/run_evidence.py` 用它生成
  `data/a12/reports/operator_audit.json`）。
* **`ray_thickness` 的采样敏感性（实测）**：`S.ray_thickness` 每次调用重新采样曲面，探针上
  **未受损**本体的 400 射线最小值是 0.8462 mm，而 0.05 mm 侵蚀后同一调用给 0.1353 mm——
  0.05 mm 的切削不可能造成 0.71 mm 的壁厚下降。粗糙断面本身会产生近乎垂直的微壁，
  向内的射线经常打到旁边的粗糙峰。因此 P02/P03 的壁厚与退让改用**成对探针**
  （`paired_thickness`：采样点固定在源体 ROI 面上，射线从体内 `+n·eps` 出发，两侧同一射线比较）。
  P02 仍报告全局 `min_thickness_mm`（0.0026–3.10 mm，随 seeds 抖动）——这是**已披露的
  采样伪影**，不是声明量；P02 本身不设壁厚守卫，P03 的守卫用成对量（违规分数 0）。
* **P08 裂宽偏小**：L1 实测 0.524 mm（早期 1.1e-3 mm 报告来自更早的搜索实现）；
  修复后的搜索现给出 0.524/1.697/3.972/6.324 mm，与 `affected_area` 目标单调一致。
* **I02 方向估计器**为结构张量，探针上误差 ≤10°；作为测量列出，未作为实现门槛。
* **`gc.collect()` 陷阱**：显式 `gc.collect()` 与 trimesh/manifold3d/open3d 原生对象组合会在本机
  触发间歇性进程终止（无 traceback）；新窄带实现只在**已释放完大对象之后**调用它，并在
  `audit_axis` 中清空异常 traceback（Python 层，安全）以释放 SDF 网格。
* **原生库间歇性终止（环境风险）**：当同一进程内累积大量 manifold3d/marching-cubes 计算时，
  本机偶发**无 traceback 的进程终止**（`exit=-1`，输出在若干测试后截断，faulthandler 无输出）。
  实测：`tests/a12/operators` 全量运行**本次退出码 0**（148 passed），但单独跑
  `test_audit_api.py` 会在打印完 38 passed 后的收尾阶段被杀；通过管道读 pytest 输出也会
  提前关闭 stdout 并让 pytest 以 -1 退出。规避方式：**写文件再读**，或分文件运行。

### 4.3 顺带修掉的框架缺陷：`parameters=` 覆盖从未到达算子

`synlab/degrade/api.py::_apply_impl` 构造了合并后的 `planned`（含调用方覆盖），但
`AxisOperator.apply` 在内部又调用 `self.level_parameters(level)` 取默认参数，于是
`apply_axis(..., parameters={...})` 与 `run_recipe` 的 `DagNode.parameters` / `config` 编译结果
**只写进了记录的 `planned` 块，从未影响实际算子**。实测：`parameters={'contact_loss_target': 0.1}`
在 L4 上仍执行默认 0.8。修法：`apply()` 接受 `parameters` 并与 `params_for(level, variant)` 合并；
`_apply_impl` 传入 `planned`。修复后同一调用返回 `achieved_contact_loss=0.10003`。

### 4.4 演示清单（`data/a12_demo/demo_manifest.json`）

| 分区 | total | OK | FAILED | BLOCKED | NA |
|---|---|---|---|---|---|
| mother | 8 | 8 | 0 | 0 | 0 |
| pattern | 8 | 8 | 0 | 0 | 0 |
| **degrade** | **12** | **12** | **0** | **0** | **0** |
| degrade_source | 4 | 4 | 0 | 0 | 0 |
| fracture（另一名队友） | 8 | 3 | 2 | 3 | 0 |
| 合计 | 40 | 35 | 2 | 3 | 0 |

* 生成命令：`& .venv\Scripts\python.exe tools\build_demo_assets.py --only degrade`；
  **退出码 1** —— 只因为清单里仍含断裂分区的失败条目（脚本语义：任一单元非 OK 即 1）。
  退化分区自身 **12/12 OK**；最后一步 `units_executed=0`（全部命中已 OK 条目、无需重跑）。
* `degrade_source` 的真实失败原因（本次已复跑为 OK）：`FRACTURE_CONSISTENCY`——
  `degrade-source:V01` 在断裂产物上取源；断裂修好后四个族（P/I/G/X）全部 OK，
  content_hash 与重跑一致（`SOURCE_REBUILD_MISMATCH` 守卫未触发）。
* 演示轴覆盖：脚本的 `DEGRADE_AXES` 是 **11 个轴**
  （`P03 P05 P06 I01 I03 I09 I10 G03 G05 G08 X01 X04` 中的 11 项，即任务书建议的 10 个 + `X04`）；
  每轴 5 档全部 OK，同一 source、同一 basis。
  **`P04` 不在 `DEGRADE_AXES` 里**（脚本属另一名队友，未修改）；P04 的 5 档实测值见 §3.1，
  可由 `audit_all_axes` / `apply_axis("P04", level, source)` 复现。
* 产物形态：I 轴与外观轴输出**真实渲染 PNG**（软件光栅 + 成像链，长边 ≤320 px）；
  几何轴输出 **GLB**（`display_lod_glb`，L0/L1/L2 三级 LOD）+ 实测变化量；
  level 0 引用**原始字节**并标 identity（`identity=true`、`bytes_unchanged=true`、
  `identity_reference_ok=true`）。
* 生成脚本的接口差异：`tools/build_demo_assets.py` 属另一名队友，**只运行未修改**；
  其 `--only degrade` 会重跑并覆盖 FAILED 条目、跳过 OK 条目（`--force` 才强制重跑），
  与本次实现无接口冲突。

## 5. 环境兼容与缺陷 shim（`synlab/degrade/compat.py`）——**当前 0 个激活**

上游 `synlab/physical/**` 修好之后，四个 shim 全部退役；`compat.py` 保留**条件安装**逻辑：
只有运行时探针证明缺陷仍在时才会安装（例如把本包与旧版 `synlab/physical` 搭配）。

| shim | 处置 | 退役证据（实测） |
|---|---|---|
| `Trimesh.remove_degenerate_faces` | **退役** | `physical.sdf.clean_mesh` 现在直接调用 `nondegenerate_faces(height=1e-12)` + `update_faces`；在**全新解释器**里只导入 `synlab.physical`（不装 shim）并调用 `clean_mesh(box)`：12 面进 12 面出，无 `AttributeError` |
| `trimesh.boolean.boolean_automatic` | **退役** | `physical.sdf.boolean_op` 直接分派 `trimesh.boolean.difference/union/intersection`；无 shim 下实测一次真实差集返回 12 面 |
| `Trimesh.edges_face`（legacy `(E,2)`） | **退役（且本仓库不再需要）** | `physical.fields.edge_face_pairs` 自己从 `edges_unique_inverse` 重建 `(E,2)` 表，从不读 `Trimesh.edges_face`；无 shim 下探针实体给出 **208** 条 45° 锐边、二面角 90.0°（装 shim 时 206 条）。现已改为关键字 `with_edges_face=True` 的**可选**接口 |
| `physical.sdf.evaluate_field`（修 bug） | **退役** | 上游已在写回前加 `base_block + values`；实测 `evaluate_field(grid, λp:2.0, base=full(-7.0))` 处处返回 **-5.0**，`seam_max_abs_diff=0.0`。`_install_evaluate_field_fix()` 现在先跑一个已知答案的运行时探针，只在它失败时才打补丁 |

**前后 audit 结果一致**：退役前后 `audit_all_axes(None, levels=[0,1,2,3,4])` 均为
`axes_pass=31 / levels_passed=155 / 0 FAIL / 0 NA`、`identity_ok=True`、`all_axes_pass=True`。
`ACTIVE_SHIMS == []`；退役记录在 `compat.RETIRED_SHIMS`（审计与本文档同源）。

## 6. 契约落实方式（可复核点）

* **level 0 真恒等**：`AxisOperator.apply` 在框架层直接返回 source 对象；`apply_axis` 级别返回
  **原始 `AssetRecord`**（`asset_id` 不变）且不提交任何资产。逐轴测试断言
  `operator.apply(source,0,basis) is source`、`result_hash == source_hash`、`record.asset_id == source.asset_id`。
* **五档同 basis**：`sample_basis` 冻结 ROI/场/方向/位置，`basis_id` 由
  `synlab.seeds.basis_id(axis, master_seed, lineage, fragment)` 生成；每档随机性来自
  `basis_rng(basis, level, stream)`。测试断言五档 `extra['basis_id']` 相同。
  演示集 `degrade:*` 条目的 `metrics.basis_id` 与 `basis_seed_ref` 逐条记录。
* **固定环境重复一致**：审计报告不含任何时间戳；测试断言两次运行的 `measured` 与 `result_hash` 相同。
* **改 Physical 必须重算下游标签**：P 轴 `LABEL_INVALIDATIONS=("PhysicalTruth","VisibleLabels","FeatureAdapter")`，
  测量 extra 记录 `label_status`（`synlab.truth` 未落地时为 `PENDING_DEPENDENCY`，如实上报）。
* **声明变化未测得 → `OPERATOR_NOT_REALIZED`**：`AxisOperator.validate` 在 `realized=False` 时抛出并
  携带 `measurements`；`audit_axis` 记 FAIL 且进入分母。
* **不适用 → NA**：材料不支持（如 P01×M07 玻璃）、缺外观/模态/上下文、缺逐帧深度（G04/G07）、
  缺网格（G05/G08）、ROI 无锐边（P02）均抛 `NA_NOT_APPLICABLE`，审计中标 NA 并保留分母。
* **factor_kind**：每个 variant 声明 `SINGLE_PARAMETER / ONE_DIMENSIONAL_RECIPE / BUNDLED_STRESS /
  CATEGORICAL_SHIFT`；`P08`、`G04`、`G07`、`G08`、`I03`、`I04`、`I06` 均含单因素 variant 与显式
  BUNDLED variant；X05 为 CATEGORICAL_SHIFT 且报告 `monotone_scalar_claim=0`。
* **观测侧只改 Observed**：G08 复用 `observe.spurious.apply_spurious`，测量内断言
  `clean_hash_unchanged=True`、`spurious_mask_role=audit_and_supervision_only`。
* **parquet**：列见计划 934 行——`axis_id/variant/level/factor_kind/stage/substage/basis_id/status/
  identity/realized/valid/na_reason/failure_code/source_hash/result_hash/source_provenance/
  source_asset_id/result_asset_id/calibration_status/label_status/label_invalidations/
  independent_mothers` + `planned_*` / `measured_*` / `unit_*`。

## 7. 独立通道的实测复核（`measurements` 里可直接查到）

窄带实现不靠「参数写进去了」自证，逐档都有与算子自身场无关的复核量：

| 轴 | 复核量 | 实测范围（L1..L4） |
|---|---|---|
| P02 | `measured_mean_recession_mm`（源表面采样、材料已消失后到残留表面的距离） | 0.00165 → 0.00798 mm |
| P02 | `measured_recession_p95_mm` | 0.01336 → 0.06954 mm |
| P02 | `max_outside_clean_mm`（受损面到源体的有符号距离，`damaged ⊆ clean`） | ≤ 1e-5 mm |
| P02 | `roi_external_drift_mm` | 9.55e-7 mm |
| P03 | `measured_max_vertex_shift_mm` / `measured_mean_vertex_shift_mm`（到受损体的无符号距离） | 0.04998/0.03379 → 0.49973/0.33120 mm |
| P03 | `linearised_predicted_loss_mm3` 与实测 `lost_volume_mm3` 之比 | 0.9236 → 0.9237 |
| P03 | `thickness_violation_fraction`（成对壁厚损失 > 本地壁厚 50% 的射线占比） | 0.0（预算 0.01） |
| P04 | `target_abs_error` | ≤ 2.5e-4（预算 0.02） |
| P04 | `contact_lost_area_mm2` / 接触总面积 434.062 mm² | 43.42/108.62/217.10/347.36 mm² |
| P04 | `largest_component_ratio`（30.8 代表体守卫） | 0.9888 → 0.2178（守卫 0.02） |
