# A12 断口真实性：非平面形态学 + rough 精度（实测）

> **结论（先说答案）**
>
> 用户问"断裂口符合真实物理碎裂了没"。诚实答案是：**模型做到了，落地还没做到。**
>
> 1. **模型层（做到了）**：`synlab/fracture/morphology.py` 把断口形态完全建立在实测物理量上——
>    实测壁厚 `p05`、真实材料 profile（grain/pore/aggregate/porosity）→ 断裂力学镜面关系
>    `σ_f·√r_m = A_m`、Ryshkewitch-Duckworth 孔隙修正、Weibull 尺寸效应、自仿射谱
>    (`S(k) ~ k^-(2H+2)`，H=0.75)、孔隙决定的拉出坑密度。在真实母体 V18/M01 与 V01/M01 上
>    实测：断口**远非平面**，`Ra = 0.392 / 0.377 mm`（平面基线只有 `1.1e-7 mm`，相差 6 个数量级），
>    法向角 P95 = `33.8° / 31.8°`，最短波长 0.65 mm 对应的坡度为 P95 = `53.1° / 52.4°`。
> 2. **落地层（FAIL）**：这套形态**无法被现有共享刀体网格器实现**。`build_closed_cutter` 的四叉树
>    在 12 个逐胞三角化分支里有 **8 个是错的**（面积和 0.75 = 空洞 / 1.25 = 退化片 / 1.75 = 重叠，
>    正确应为 1.0）。只要胞有一条边被细分就触发，于是**任何非平面场都抛 `CUTTER_NOT_CLOSED`**；
>    平面场永不细分边（`leaf_level=0`），所以 `plane_shared_cut` 精确无误。这解释了
>    `rough_shared_cut` 与 `morphology_shared_cut` 在**所有尺度**上全线失败。
> 3. **rough 精度**：`PRECISION_BUDGET_EXCEEDED` **仍然发生**（V18/M01 冻结默认下需 432 343 单元 >
>    400 000）；即使把振幅降到能过预算，也会立刻撞上同一拓扑缺陷。因此
>    **`realized_error_mm` 与共享面 P95 在真实母体上无法测得**——刀体根本没建出来。
>
> 本文件所有数字来自真实运行，未放宽容差，未用随机噪声冒充起伏。**审计全部 FAIL 的记录原样保留。**

**未改动的红线**：`synlab/fracture/cut.py`、`event.py`、`fragment.py`、`booleans.py` 一行未改
（原因见 §7：并发协作 + 该缺陷正由另一个探针在同仓库诊断）。本次对 `synlab/fracture/**` 只做了
§2 的**接线**；`spec.py` 的 `FractureSpec` 与 spec hash 未动。

---

## 0. 证据文件索引

| 证据 | 内容 |
| --- | --- |
| `data/a12_reports/field_morphology_V18_M01.json` | V18/M01 建模断口面实测（真实母体） |
| `data/a12_reports/field_morphology_V01_M01.json` | V01/M01 建模断口面实测（真实母体，另一种器型） |
| `data/a12_reports/fracture_realism_V18_M01_plane_rough.json` | V18/M01 平面基线 OK + rough FAIL 记录 |
| `data/a12_reports/fracture_realism_V01_M01_morph.json` | V01/M01 形态学 FAIL 记录 |
| `data/a12_reports/fracture_realism_box12_M01.json` | 12 mm 解析盒：平面 OK + 形态学 FAIL |
| `data/a12_reports/morph_V18_M01.json` | 形态学事件 FAIL（MemoryError） |
| `data/a12_reports/_stale/morph_V18_M01_att1_FAILED.json` | 上一版实现的历史失败（版本错配，留档） |
| `data/a12_reports/morph_pixel_resolvability.json` | 像素可分辨性表 |
| `data/a12_reports/pytest_realism/*.log` | `pytest tests/a12/fracture` 分文件退出码（9 个文件） |
| `data/a12_reports/_fprec_pytest_shared_cutter.txt` | **改动前**冻结基线：同样 3 个测试失败 |
| `data/a12_reports/_fprec_topo_box.json` / `_fprec_topo_box_view.txt` | **改动前**拓扑诊断（5020 条单用边） |
| `data/a12/reports/baseline_head/synlab/fracture/cut.py` | **改动前**冻结源码快照 |

复现命令：

```powershell
$py = ".venv\Scripts\python.exe"
& $py tests\a12\fracture\_measure_field_morphology.py --vessel V18 --material M01 --samples 400000 `
      --out data\a12_reports\field_morphology_V18_M01.json
& $py tests\a12\fracture\_measure_fracture_realism.py --vessel V18 --material M01 --skip-morphology `
      --samples 300000 --max-cells 400000 --rms 0.02 --out data\a12_reports\fracture_realism_V18_M01_plane_rough.json
& $py tests\a12\fracture\_pixel_resolvability.py --reports data\a12_reports\field_morphology_V18_M01.json `
      data\a12_reports\field_morphology_V01_M01.json data\a12_reports\fracture_realism_V18_M01_plane_rough.json
```

---

## 1. 形态学 API 清单（`synlab/fracture/morphology.py`，1323 行）

模块顶部物理常量（L78–L120）即"参数由物理量驱动"的声明：
`SIGMA_REF_MPA=90.0`、`WALL_REF_MM=5.0`、`WEIBULL_M=9.0`、`RYSKEWITCH_B=4.5`、
`MIRROR_CONSTANT_MPA_SQRT_M=2.5`、`MIST_TO_MIRROR_RATIO=1.8`、`HURST_EXPONENT=0.75`、
`ROUGHNESS_BANDS=5`、`POROSITY_FROM_PORE_AMOUNT=0.35`、`GRAIN_RELIEF_FRACTION=0.12`、
`POROSITY_RELIEF_GAIN=2.0`、`HACKLE_AMPLITUDE_FRACTION=0.55`、`RIB_AMPLITUDE_FRACTION=0.45`、
`RIB_SPACING_GROWTH_PER_MM=0.05`、`PIT_DEPTH_FRACTION=0.35`、`CONCHOIDAL_RADIUS_PER_WALL=6.0`、
`GLAZE_ROUGHNESS_RATIO=0.12`、`PRECISION_SAFETY=0.5`、`PRECISION_LADDER_FACTORS=(1.0,0.5,0.25)`。

### 1.1 公开入口（`__all__` L58–L71）

| 函数 / 类 | 行号 | 作用 | 关键参数 |
| --- | --- | --- | --- |
| `MORPHOLOGY_META_KEY` | L74 | `"fracture_morphology"`，参数记录发布的 meta 键 | — |
| `BACKEND_MORPHOLOGY` | L76 | `"morphology_shared_cut"` | — |
| `material_fracture_inputs(profile, *, material_id)` | L205 | 真实材料 profile → 物理输入 | `material_id` |
| `wall_thickness(mother, *, max_probes=320)` | L271 | 壁厚分布（取自冻结母体审计） | `max_probes` |
| `derive_morphology_parameters(...)` | L408 | **核心**：材料+壁厚+起始点 → 全部形态参数 | `material, wall, origin_uv, tris_uv, core_area_mm2, window_area_mm2, extent_mm, rng, error_budget_mm, max_cells` |
| `estimate_cell_demand(field, *, budget_mm, step_mm, max_points, safety)` | L988 | 精化**之前**用细栅格曲率普查预测单元数 | `budget_mm=0.01, max_points=2.5e6, safety=1.3` |
| `build_morphology_field(basis, mesh, params, *, rng, probe_step_mm, halo_mm, cross_section)` | L1094 | 参数 → 解析高度场 | `halo_mm` 默认 `max(BAND_HALO_MM, 8·relief_amp)` |
| `prepare_morphology(mother, *, material_profile, rng, basis, event_id, error_budget_mm, max_cells, wall_probes, origin_uv, window_area_estimate_mm2)` | L1181 | 只测量不建刀体（平面基线共用同一次测量） | — |
| `build_morphology_cutter(mother, *, material_profile, rng, basis, prepared, event_id, error_budget_mm, max_cells, max_triangles, wall_probes, allow_precision_ladder, origin_uv, window_area_estimate_mm2)` | L1230 | 建共享刀体 → `(cutter, field, params, report)` | `allow_precision_ladder=True` |

### 1.2 数据记录与高度场

| 类 | 行号 | 说明 |
| --- | --- | --- |
| `MaterialFractureInputs` | L158 | 材料输入（`grain_scale_mm`、`pore_scale_mm`、`porosity`、`correlation_length_mm`…） |
| `WallThickness` | L256 | `min/p05/median/max_mm`、`probes`、`source` |
| `FractureMorphologyParams` | L295 | 冻结 JSON 参数记录，含 `formulas`（键：`sigma_f`、`mirror_radius`、`mist_radius`、`hackle_count`、`roughness_rms`、`roughness_spectrum`、`curvature_requested`、`precision_budget`、`pits`、`glaze`、`conchoidal`） |
| `MorphologyHeightField` | L726 | `HeightField` 子类：`W(u,v)·(dome + G·[roughness+hackle+ribs+pits+fibre])` |
| `_PitSet` / `_Raster` | L572 / L676 | 坑阵列 / 釉层调制的分桶求值表 |

`MorphologyHeightField` 分量：`_roughness` L755、`hackle` L768、`ribs` L783、`dome` L795、
`fibre` L802、`_relief` L810、`raw` L820（融合单遍）、`gradient` L866、`curvature_bound` L885、
`gradient_bound` L903、`windowed_curvature_bound` L921、`as_dict` L937、`apply_scale` L954。

### 1.3 测量 API（`synlab/fracture/surface_features.py`，554 行）

| 函数 | 行号 | 作用 |
| --- | --- | --- |
| `top_surface_samples(mesh, basis, *, n_samples, rng)` | L55 | 结构性识别刀体顶面（底面唯一），面积加权采样 |
| `detrend_plane(u, v, w, weights)` | L128 | 最小二乘去形 → `residual` + `waviness_rms_mm` |
| `amplitude_statistics(u, v, residual, *, cell_mm, weights)` | L148 | `Ra`/`Rq`/`Rz`/`Rt`（`Rz`=2.5 mm 胞内 0.5/99.5 分位带均值） |
| `correlation_length(u, v, residual, *, step_mm)` | L216 | 自相关降到 `1/e` 的径向滞后（扣胞内噪声方差） |
| `ridge_density(u, v, residual, origin_uv, radii_mm, *, step_mm, samples)` | L276 | 绕起始点圆上的脊线密度（条/mm） |
| `measure_interface_surface(fragments, basis, params, *, cutter_mesh, n_samples, bin_step_mm, rz_cell_mm, seed)` | L383 | **交付面**实测；用 `event._interface_faces` 冻结判据（避免把母体壁当粗糙度） |
| `measure_cutter_surface(mesh, basis, params, *, window, n_samples, ...)` | L424 | 刀体实现面实测，`window` 限定材料带核心 |
| `conjugate_profile_consistency(fragments, patches, basis, *, step_mm, max_faces_per_side)` | L452 | 共轭：双面栅格相关、共轭点距离 P95、面积记账 |

### 1.4 是否被 `event.py` / `api.py` 调用？（改动前）

| 位置 | 改动前引用数 | 说明 |
| --- | --- | --- |
| `synlab/fracture/event.py` | **0** | 只有 L203 读 `cutter.realized_error_mm`，与形态学无关 |
| `synlab/fracture/api.py` | **0** | `BUILT_BACKENDS` 里没有 `morphology_shared_cut` |
| `synlab/fracture/spec.py` | **0** | 无形态学常量 |
| 调用者 | 仅 `tests/a12/fracture/{_run_morphology_event.py,test_morphology_event.py,test_morphology_model.py,_probe_morph_*}` | 即：**模块在，接线不在** |

---

## 2. 最小接线（默认关闭，可开关）

接线只落在 `synlab/fracture/api.py`；`event.py` 一行未改——形态学复用既有
`run_shared_cut(mother, cutter, ..., extra_meta=...)`，事件层不需要知道形态学存在。

| 行号 | 内容 |
| --- | --- |
| L45 | `BACKEND_MORPHOLOGY = "morphology_shared_cut"` |
| L47 | `MORPHOLOGY_SWITCH_ENV = "SYNLAB_FRACTURE_MORPHOLOGY"` |
| L56–L60 | `BUILT_BACKENDS` **不变**；新增 `GATED_BACKENDS = (BACKEND_MORPHOLOGY,)` |
| L62 | `_TRUTHY = {"1","true","yes","on","enabled"}` |
| L65 | `morphology_backend_enabled(spec)`：环境变量为真，或 `spec.meta["morphology"]` / `spec.meta["morphology_backend"]` 为真 |
| L88 | `morphology_options(spec)`：从 `spec.meta` 取 `material_profile` 与逐事件选项 |
| L151 | `register_fracture_backend(BACKEND_MORPHOLOGY, status=STATUS_SPECIFIED, ...)` |
| L208 | `make_closed_cutter` 分派 → `_make_morphology_cutter` |
| L273 | `fracture_event` 分派 → `_morphology_event` |
| L345 | `_gate_morphology`：未开关时抛 `OPERATOR_NOT_REALIZED`（**明确报错，绝不静默降级成平面**） |
| L364 / L387 | `_make_morphology_cutter` / `_morphology_event`（发布参数记录到 result/patch/fragment meta） |

**为什么默认关闭**：`tests/a12/integration/diversity_context.py:95` 会遍历 `BUILT_BACKENDS` 写上下文报告；
把形态学放进去会让别人的产物在无感知下改变成本与 QA 数字。开关行为有单测：
`test_fracture_realism.py::test_the_morphology_backend_is_gated_off_by_default`、
`::test_the_switch_gets_past_the_gate_into_the_builder`。

**验证**：`morphology_backend_enabled(FractureSpec()) is False`；
`fracture_event(..., backend="morphology_shared_cut")` → `OPERATOR_NOT_REALIZED`；
置 `SYNLAB_FRACTURE_MORPHOLOGY=1` 后进入 builder（随后撞上 §5 缺陷）。
`python -m synlab.cli validate --config configs/a12/fracture_morphology.yaml` → **exit 0**。

---

## 3. 平面 vs 形态学：实测对照

### 3.1 控制组——平面基线（V18/M01 碗形，真实母体）

母体 V18：524 面 / 262 顶点，水密，体积 85 326.12 mm³，包围盒 81.74×124.14×15.33 mm。
M01（grog 颗粒 + 气孔，粗陶）。实测壁厚 `p05 = 6.243 mm`、中位 13.547 mm
（来源 `synlab.mothers.audit.audit_mother:checks.min_thickness`）。
刀体预算 0.01 mm / 400 000 单元（`spec.py` 冻结，**未放宽**）。

| 量 | 平面 V18/M01 | 平面 BOX12 |
| --- | --- | --- |
| 刀体三角面 / 单元 / `leaf_level` | 16 896 / 4 096 / 0 | 4 352 / 1 024 / 0 |
| `requested_error_mm` / `realized_error_mm` | 0.01 / **0.0** | 0.01 / **0.0** |
| 刀体水密 / 绕向一致 / 体积>0 | True / True / True | True / True / True |
| 交付面 `Ra` | **1.103e-07 mm** | **1.329e-08 mm** |
| `Rq` / `Rz` / `Rt` | 1.509e-07 / 4.601e-07 / 1.128e-06 | 1.708e-08 / 6.264e-08 / 1.135e-07 |
| `waviness_rms_mm` | 7.970e-05 | 5.616e-05 |
| 脊线密度 | 0.0 /mm | 0.0 /mm |
| 交付面法向角 均值 / P50 / P95 / 最大 | 8.59e-05 / 1.95e-05 / 1.67e-04 / **0.0120°** | 3.70e-06 / 2.41e-06 / 8.01e-06 / 6.84e-05° |
| 二面角 P50 / P95 / 最大 | 1.40e-05 / 1.85e-04 / 0.0120° | 2.05e-06 / 1.37e-05 / 7.23e-05° |
| 法向角 >0.5° / >2° 的比例 | 0.0 / 0.0 | 0.0 / 0.0 |
| `volume_rel_diff`（门限 1e-3） | 4.82e-10 | 6.78e-11 |
| `overlap_ratio`（门限 1e-4） | 0.0 | 0.0 |
| `gap_p95_mm_max`（门限 0.02） | 1.187e-07 | 7.577e-08 |
| `normal_angle_p95_deg_max`（门限 2.0°） | 7.249e-05 | 3.035e-05 |
| `source_coverage` / `ambiguous_area_ratio_total` | 1.0 / 0.0 | 1.0 / 0.0 |
| 共轭点距离 P95 | **9.025e-09 mm** | **1.403e-08 mm** |
| 共轭剖面相关 min | **0.99631** | n/a（有效栅格 <8 格） |
| 共轭剖面 RMS 差 max | 2.468e-08 mm | n/a |
| 面积相对误差 max | 0.0988 | 0.1663 |
| 自交（`self_intersection_report.ok`） | True（0 对） | True（0 对） |
| 审计 `passed` / `failures` | **True** / `[]` | **True** / `[]` |
| 接口数 / 接口面数 | 8 / 2 460 | 4 / 832 |

**这张表的作用是控制组**：平面切割把交付面 `Ra` 测到 `1e-7~1e-8 mm`（双精度舍入量级），
说明测量链能正确测出"完全平面"。因此形态学侧任何 `1e-1 mm` 量级都只能是真实起伏。
注意平面的 `correlation_length_mm`（5.68 / 8.0）是对数值噪声做自相关的产物，**无物理意义**，不得引用。

### 3.2 模型层——形态学断口面（真实母体，≥2 器型）

形态学**无法交付**（§5），因此这里测的是模型请求的那个解析断口面，在**同一真实母体、同一
`(u,v,w)` 切割基、同一材料带足迹**上取样测得。证据文件里标记为
`surface_kind = "analytic_field_request"`——它是**请求**，不是交付。

| 量 | V18/M01（碗形） | V01/M01（大盘/浅碟，另一种器型） |
| --- | --- | --- |
| 母体面数 / 水密 / 体积 mm³ | 524 / True / 85 326.1 | 4 896 / True / 461 061.9 |
| 包围盒 mm | 81.74×124.14×15.33 | 299.27×300.66×59.62 |
| **实测壁厚 `p05` / 中位** | 6.243 / 13.547 mm | 6.037 / — mm |
| `σ_f`（Weibull+孔隙修正后） | 43.2 MPa | 43.4 MPa |
| **镜面半径 `r_mirror`** | 3.345 mm | 3.320 mm |
| 雾区半径 `r_mist` | 6.699 mm | 6.646 mm |
| **hackle 线数 `N_hackle`** | 4 | 4 |
| **请求 RMS `σ_r0`** | 0.4103 mm | 0.4103 mm |
| 材料相关长度（驱动谱） | 2.600 mm | 2.600 mm |
| **拉出坑数 / 半径 / 深度** | 11 / 2.0 / 0.7 mm | 9 / 2.0 / 0.7 mm |
| 坑面积分数（孔隙度） | 0.1575 | 0.1575 |
| 锥形穹（conchoidal）R / 幅 | 1 335.72 / 1.641 mm | — / — |
| 请求曲率 `C_requested` | 4.539 /mm | 5.332 /mm |
| 曲率预算 `C_budget` | 8.435 /mm | 9.266 /mm |
| 预测单元数（预算 400 k） | **84 207**（拟合 ✓） | **183 038**（拟合 ✓） |
| 最短波长 `λ_min` | 0.650 mm | 0.650 mm |
| 场 RMS / relief RMS / relief 峰谷 | 2.0676 / 0.4927 / **2.9227 mm** | 2.2046 / 0.5111 / **2.8256 mm** |
| `max_slope`（解析实测） | **2.2247**（65.74°） | **1.9813**（63.19°） |
| 曲率上界 `curvature_bound` | 4.835 /mm | 4.500 /mm |
| **`Ra`（形+糙，去平面）** | **0.62285 mm** | **0.38749 mm** |
| **`Rz`（形+糙）** | 0.82942 mm | 0.76085 mm |
| **`Rt`（形+糙）** | 4.35167 mm | 2.43141 mm |
| 相关长度（形+糙，含 hackle 大尺度） | 11.44 mm | 35.60 mm |
| 脊线密度 | 1.9572 /mm | 1.9497 /mm |
| **`Ra`（仅糙，去锥形穹）** | **0.39243 mm** | **0.37697 mm** |
| `Rq`（仅糙） | 0.47139 mm | 0.44959 mm |
| **`Rz`（仅糙）** | **0.82503 mm** | **0.75916 mm** |
| **`Rt`（仅糙，峰谷）** | **2.56747 mm** | **2.24231 mm** |
| **法向角 P50 / P95 / 最大**（0.25 mm 栅格有限差分） | **17.81° / 33.75° / 50.85°** | **16.63° / 31.79° / 48.54°** |
| 坡度 P50 / P95 / 最大（解析梯度） | 33.35° / **53.06°** / 65.74° | 32.85° / **52.35°** / 64.92° |
| **曲率 \|k\| P50 / P95 / P99 / 最大** | **0.631 / 1.539 / 1.928 / 3.114 /mm** | **0.629 / 1.517 / — / 2.908 /mm** |
| 分区 `Ra`：mirror / mist / hackle | 0.4698 / 0.4482 / **0.6294** mm | 0.3560 / 0.4686 / **0.3868** mm |

**非平面的量化证据（4 条独立通道，互相一致）**

1. **幅度**：`Ra`（仅糙）= 0.392 / 0.377 mm，是平面基线 `1.1e-07 mm` 的约 **3.5×10⁶ 倍**；
   峰谷 `Rt` = 2.57 / 2.24 mm。
2. **法向分布**：断口面法向不再是一个方向——P50 = 17.8° / 16.6°，P95 = 33.8° / 31.8°，
   最大 50.9° / 48.5°（平面基线最大 0.012°，即 4 000 倍差距）。
3. **曲率**：`|k|` P95 = 1.54 / 1.52 /mm，与模型请求的 `C_requested` = 4.54 / 5.33 /mm 同量级，
   且低于 `C_budget` = 8.43 / 9.27 /mm（说明预算本身是够的）。
4. **沿断口起伏与相关长度**：`Rt` = 2.57 / 2.24 mm 的起伏沿断口分布，材料驱动的相关长度
   2.6 mm；实测相关长度 11.44 / 35.60 mm 由 hackle 径向图案（`cos(N·θ)`，N=4）主导——
   这是真实的径向 hackle 脊线尺度，不是噪声。
5. **分区顺序物理正确**：V18 的 hackle 区 `Ra`=0.629 mm > mirror 区 0.470 mm
   （远离起始点的 hackle 区更粗糙，符合断裂力学预期）；V01 的 mirror 区 0.356 mm 最低。

**两种器型给出不同的断口**：V18 与 V01 的 `σ_f`（43.2 vs 43.4 MPa）、`r_mirror`（3.345 vs 3.320）、
坑数（11 vs 9）、`Ra`（0.392 vs 0.377）、`Rz`（0.825 vs 0.759）全部不同 →
参数确实由**该母体**的壁厚/材料驱动，不是查表常数。

### 3.3 为什么参数不是"随机噪声冒充起伏"

* 幅度：`σ_r0 = c_g · grain · (1 + c_p · porosity)`，只有 grain（材料）与 porosity（材料）两个输入；
* 谱：`a(k) = a_ref·(k/k_ref)^-(H+0.5)`，`k_ref = 2π/correlation_length`，按 `Σaᵢ²/2 = σ_r0²`
  归一，H = 0.75（自仿射断口）；
* 径向结构：`N_hackle = clip(round(2πr_mirror/(2·grain)), 3, 48)`，`r_mirror` 由
  `σ_f√r_m = A_m` 定出，而 `σ_f` 由孔隙与壁厚的实测值修正；
* 坑：`N_pit = porosity·core_area/(π·r_pit²)`，位置是分层抖动散布；
* **只有相位与坑位**从冻结确定性流抽取。每条关系都以字符串记进
  `params.formulas`（11 条，见 §1.2），可逐条核对。

---

## 4. 审计与共轭（未放宽）

`spec.py` 冻结门限原样使用：`INTERFACE_GAP_P95_MM = 0.02`、`NORMAL_REVERSAL_P95_DEG = 2.0`、
`VOLUME_REL_TOL = 1e-3`、`OVERLAP_RATIO_MAX = 1e-4`、`AMBIGUITY_AREA_RATIO_MAX = 0.02`。
`configs/a12/fracture_morphology.yaml` 的 `tolerances:` 段是这些常量的副本，并注明"本文件不得放宽"。

| 审计项 | 门限 | 平面 V18 | 平面 BOX12 | 形态学/rough |
| --- | --- | --- | --- | --- |
| 水密（母体/刀体/碎片） | 必须 | True | True | **未产出**（刀体即失败） |
| 体积相对差 | ≤1e-3 | 4.82e-10 ✅ | 6.78e-11 ✅ | — |
| 重叠比 | ≤1e-4 | 0.0 ✅ | 0.0 ✅ | — |
| 两侧互补 gap P95 | ≤0.02 mm | 1.187e-07 ✅ | 7.577e-08 ✅ | — |
| 法向 P95 | ≤2.0° | 7.249e-05 ✅ | 3.035e-05 ✅ | — |
| 源覆盖 / 歧义面积比 | ≥0.999 / ≤0.02 | 1.0 / 0.0 ✅ | 1.0 / 0.0 ✅ | — |
| **共轭点距离 P95** | ≤0.02 mm | **9.025e-09** ✅ | 1.403e-08 ✅ | — |
| 共轭剖面相关 min | >0.9 | 0.99631 ✅ | n/a | — |
| 共轭剖面 RMS 差 max | <1e-3 mm | 2.468e-08 ✅ | n/a | — |
| 无自交 | 必须 | True（0 对）✅ | True ✅ | — |
| 审计 `passed` | True | **True** ✅ | **True** ✅ | **FAIL** ❌ |

**诚实结论**：审计与共轭在**平面**上全部达标（gap 比门限低 5 个数量级，共轭点距离低 6 个数量级）；
形态学侧**无法给出审计数字**，因为刀体在水密检查处就被拒绝了——这是 FAIL，不是"未测"。

---

## 5. 落地失败：根因（本次最重要的发现）

### 5.1 现象：所有非平面后端、所有尺度，全部 `CUTTER_NOT_CLOSED`

| 配置 | 结果 | 坏边数 | 边使用直方图 |
| --- | --- | --- | --- |
| BOX12 形态学（12 mm 盒，最易） | `CUTTER_NOT_CLOSED` | **33 596** / 231 510 面 | `{2:300632, 3:20864, 1:7196, 4:4449, 5:882, 6:163, 7:42}` |
| V18/M01 rough（rms 0.02，0.01 mm，400 k） | `CUTTER_NOT_CLOSED` | **73 648** / 832 006 面 | `{2:1142855, 3:53394, 1:10695, 4:8886, 5:151, 6:522}` |
| 14 mm 盒形态学（既有 `test_morphology_event.py`） | `CUTTER_NOT_CLOSED` | **12 125** | — |
| `test_shared_cutter` 两个夹具 | `CUTTER_NOT_CLOSED` | **8 993** / 3 507 | — |
| `test_event_qa` rough 夹具 | `CUTTER_NOT_CLOSED` | **4 777** | — |
| V18/M01 形态学 @400 k 单元 | `MemoryError`（numpy，68.9 MiB） | — | 已细化到约 3.01 M 顶面（撞 3 M 三角上限） |
| V01/M01 形态学 @30 k 单元 | `PRECISION_BUDGET_EXCEEDED` @ `fracture.cut.refine` | — | "exceeded the cell budget (30000) … at wavelength 0.6500 mm" |

`edge_use_histogram` 里出现 **3、4、5、6、7** 次使用的边——这是**重叠/重复三角形**的特征
（T 型接头只会产生"用 1 次"）。同时存在 1 次使用的边（空洞）。

### 5.2 根因：`cut.py` 逐胞三角化 12 个分支里 8 个面积错误

`build_closed_cutter` 用四叉树 + 共享整数 key 网格保证顶点一致。每个叶胞由
`CellTree.cell_triangles`（`synlab/fracture/cut.py` L937–L1005）按**被细分的边数** `n_split` 选择三角化。
对单位胞（面积 = 1.0）用鞋带公式逐一验算：

| 分支 | 行号 | 面积和 | 判定 |
| --- | --- | --- | --- |
| `n_split == 0` | L957–959 | 1.00 | ✅ 正确 |
| `n_split == 1`，`s[0]` 左边 | L961–963 | **0.75** | ❌ 空洞 25 % |
| `n_split == 1`，`s[1]` 下边 | L964–966 | **0.75** | ❌ 空洞 25 % |
| `n_split == 1`，`s[2]` 右边 | L967–969 | 1.00 | ✅ 正确 |
| `n_split == 1`，`s[3]` 上边 | L970–972 | **0.75** | ❌ 空洞 25 % |
| `n_split == 2`，`s[0]&s[2]` | L973–975 | **1.25** | ❌ 含退化片 `(0,3,4)`（c00,c01,m_v0 共线，面积 0，却横跨整条左边）→ 悬挂边 + 重叠 |
| `n_split == 2`，`s[1]&s[3]` | L976–978 | **1.75** | ❌ 重叠 75 % |
| `n_split == 2`，`s[0]&s[1]` | L980–982 | 1.00 | ✅ 正确 |
| `n_split == 2`，`s[1]&s[2]` | L983–985 | 1.00 | ✅ 正确 |
| `n_split == 2`，`s[2]&s[3]` | L986–988 | **0.75** | ❌ 空洞 25 % |
| `n_split == 2`，`s[3]&s[0]` | L989–991 | **0.75** | ❌ 空洞 25 % |
| `n_split == 3`，扇心三角化 | L992–1004 | **0.75** | ❌ `names`/`ring` 成对丢弃后仍缺 25 % |
| `n_split == 4`，扇心三角化 | L992–1004 | 1.00 | ✅ 正确 |

**12 个分支里 8 个错。** 空洞制造"用 1 次"的边，重叠制造"用 3–7 次"的边，
两者都让 `bad_edges != 2` → `CUTTER_NOT_CLOSED`（L1299–1307）。

**为什么平面后端从不失败**：平面场处处曲率为 0，`n_split` 恒为 0 →
只走 L957 那一个正确分支，`leaf_level = 0`（实测 V18 平面：`leaf_level=0`、4 096 单元、16 896 面，
每个胞恰好 2 个三角）。**只要场需要细化，就一定踩到错分支。**

验算脚本（本次实际执行的算术，可复现）：

```powershell
# 单位胞 c00=(0,0) c10=(1,0) c11=(1,1) c01=(0,1)，m_v0=(0,.5) m_u0=(.5,0) m_v1=(1,.5) m_u1=(.5,1)
# L976-978 分支 tris=[(0,1,5),(0,5,2),(0,2,4),(4,2,3),(5,4,2)] → 面积 0.5+0.25+0.25+0.5+0.25 = 1.75
```

### 5.3 改动前后对照（材料带 / halo / 精度路径）

工作树状态：`git status --porcelain synlab/fracture` 只有 `?? calibrate.py`（他人未跟踪文件）。
`git log` 显示 `cut.py`/`surface_features.py` 最后一次提交是 `bff6860`。
但 `data/a12/reports/baseline_head/synlab/fracture/cut.py`（冻结的**改动前**源码）与当前
`cut.py` 相差 **+548 / −158 行**，说明期间有人改过 `cut.py`——**不是我改的**（本次未动 `cut.py`）。

| 项 | 改动前（冻结基线） | 现在（实测） |
| --- | --- | --- |
| `test_shared_cutter.py` | 3 个失败，`CUTTER_NOT_CLOSED: **4 486** 坏边` | 3 个失败，`**8 993 / 3 507** 坏边`（同一缺陷类） |
| 20 mm 盒拓扑（`_fprec_topo_box.json`） | 105 685 单元 / 425 580 面，`undirected_edges_used_once = 5020`，`bad_edges_with_a_vertex_inside = 181` | — |
| 缺陷主类 | **"用 1 次"（T 型接头）** 5 020 / 314 165 边 = 1.6 % | **"用 3–7 次"（重叠）** 53 394+8 886+151+522 = 62 953 vs "用 1 次" 10 695（V18，1.27 M 边） |
| `edge_split` / `needs_balance` | 不存在 | **存在**（L882 / L914），注释 L894–900 记录了"20 mm 盒 209 952 次邻居查询 100 % 报未细分 → 5 020 条单用边"的修复 |
| `BAND_HALO_MM` | — | **0.6**（`cut.py` L74）；`attach_material_band` L696；rough 路径用 `max(BAND_HALO_MM, 8·amp)`；形态学路径用 `max(BAND_HALO_MM, 8·relief_amp)` = **5.6 mm**（V18 实测） |

**结论（对照）**：T 型接头那一类**已被修掉**（单用边从 1.6 % 降到 0.8 %，且不再有"顶点落在边内部"的悬挂），
但**重叠那一类暴露出来并成为主因**——恰好对应 §5.2 表里的 6 个"面积 <1 或 >1"分支。
所以"材料带/halo 被改过导致精度回归"**不是**本次失败的原因；失败在于三角化分支本身。

---

## 6. rough_shared_cut 精度实测

| 配置（V18/M01，真实母体） | 结果 | 数字 |
| --- | --- | --- |
| **冻结默认**：`target_rms=0.05 mm`、预算 0.01 mm、400 000 单元 | **`PRECISION_BUDGET_EXCEEDED`** | 需 **432 343 单元 > 400 000**，`λ_min = 0.3499 mm`，`stage = fracture.cut.budget` |
| 振幅降到 `target_rms=0.02 mm`（仍在 `[AMP_MIN, AMP_MAX]=[0.02,0.30]` 窗口内）、同预算 | **`CUTTER_NOT_CLOSED`** | 细化到 208 001 单元 / 832 006 面后，**73 648 条坏边** |
| `target_rms=0.30 mm`（上限）、`max_cells=512` | `PRECISION_BUDGET_EXCEEDED` 或 `PRECISION_NOT_REALIZED`（结构化，见单测） | 携带 `cells`、`max_cells`、`wavelength_min_mm`、`budget_mm` |

**直接回答任务问题**：

* **`PRECISION_BUDGET_EXCEEDED` 是否仍发生？** → **是**。在冻结默认（0.05 mm RMS、0.01 mm、400 k 单元）
  下，最小波长 0.3499 mm 使曲率需求达到 432 343 单元，超过 400 000 上限，抛出且**不静默降级**
  （实现只抛错，不放松最短波长——这正是 `cut.py` L13 与 refine 阶段的设计）。
* **`realized_error_mm` 与共享面 P95 实测值？** → **在真实母体上无法测出**：
  唯一能建成的刀体是平面（`realized_error_mm = 0.0`，`gap_p95 = 1.187e-07 mm`）。
  rough 在能过预算的配置下也必定撞上拓扑缺陷，`build_closed_cutter` 在**验证阶段**抛错，
  根本没有 `realized_error_mm` 可报。**如实记 FAIL，不给替代数字。**
* 平面路径的 `realized_error_mm = 0.0` 远低于 0.01 mm 预算；
  `INTERFACE_GAP_P95_MM = 0.02` 门限在平面/BOX 上分别只有 1.187e-07 / 7.577e-08 mm（低 5 个数量级）。

---

## 7. 像素可分辨性（扫描台 mm/px 档）

判据**取自扫描合同本身**，不是本次发明：

* `configs/a12/capture_contract.json` → `working_distance_and_resolution.resolution_table`
  给出 5 档 mm/px 与合同自带的样例列 `structure_0p2mm_px`（0.2 mm 结构占多少像素）：
  0.039→5.12、0.078→2.56、0.117→1.71、0.156→1.28、0.195→1.02；
* 同文件 `structure_sampling_targets.pilot_start` 规定 **"0.2 mm 结构 ≥ 4 像素"**，
  `detail_goal` 为 6–8 像素。故横向判据：`λ_min / mm_per_px ≥ 4`；
* `mask_and_quality.quality_3d_floor_q2_equivalent.sigma_max_mm = 0.2` —— 合同给出的 Q2 三维
  散布地板（**该段在合同里自标 `confidence: assumption`**）。故幅度判据：`Rt > 0.2 mm`。

实测断口 `λ_min = 0.650 mm`（两器型相同）；幅度用"仅糙"峰谷 `Rt`：

| mm/px | 距离 mm | 每 `λ_min` 像素数 | `px / 相关长度`（V18 11.44 mm） | `px / 相关长度`（V01 34.64 mm） | 幅度 / 0.2 mm 地板 | 能看到？ |
| --- | --- | --- | --- | --- | --- | --- |
| **0.039** | 50 | **16.67** ✅ | 293.3 | 888.2 | 12.84 / 11.21 | **✅ 能** |
| **0.078** | 100 | **8.33** ✅ | 146.7 | 444.1 | 12.84 / 11.21 | **✅ 能** |
| **0.117** | 150 | **5.56** ✅ | 97.8 | 296.1 | 12.84 / 11.21 | **✅ 能** |
| **0.156** | 200 | **4.17** ✅（刚过 4 px） | 73.3 | 222.1 | 12.84 / 11.21 | **✅ 能** |
| **0.195** | 250 | **3.33** ❌（低于合同 4 px，仅高于 Nyquist 2 px） | 58.7 | 177.6 | 12.84 / 11.21 | **❌ 不能**（最短起伏开始混叠） |

**要点**

* **幅度**：全部 5 档都能分辨——峰谷 `Rt` = 2.57 / 2.24 mm，是合同 0.2 mm 三维地板的
  **12.8 / 11.2 倍**。幅度从不是限制因素。
* **横向**：真正的限制是**最短波长 0.65 mm**。50–200 mm 档满足合同"≥4 像素"；
  **250 mm 档只有 3.33 px，低于合同自己的 pilot 目标**，因此断口最细的起伏在该档不可采信
  （尽管仍高于 2 px Nyquist 下限）。
* 相关长度（11.4 / 34.6 mm）在所有档位都远超 4 px，说明**大尺度起伏（锥形穹 + 径向 hackle）
  任意档位都可见**；只有 0.65 mm 量级的细结构在 250 mm 档丢失。
* **对照**：平面基线在所有 5 档都是"看不到"（`Rt = 0`）——这正是"非平面"这一性质本身的
  可观测性判据：**平面断口在任何扫描档下都不携带可分辨的起伏特征**。

---

## 8. 接线与测试退出码

### 8.1 `configs/a12/fracture_morphology.yaml`

`python -m synlab.cli validate --config configs/a12/fracture_morphology.yaml` → **exit 0**，
`spec_hash = sha256:9be9735eecd31a979a93db2e8baabfebce0a72ddd33d8f2392dc83729d6fccaf`，
`warnings = []`。

文件内含：接线/开关声明、研究人群（V18+V01 × M01+M04）、物理常量与 provenance 分类
（MEASURED / LITERATURE / ENGINEERING，逐条注明来源）、精度与资源、**不得放宽的 tolerances 副本**、
像素可分辨性（含合同档位与判据来源）、以及给 `cli validate` 用的 `generation_spec:` 块。

### 8.2 `pytest tests/a12/fracture` 分文件退出码（重定向记录）

改动前基线（本次实测，日志 `data/a12_reports/pytest_realism/*.log`）：

| 文件 | 退出码 | 失败测试 |
| --- | --- | --- |
| `test_shared_cutter.py` | **1** | `test_rough_cutter_is_closed_and_within_budget`、`test_cutter_build_is_reproducible`、`test_default_cutter_reports_its_measured_error`（均 `CUTTER_NOT_CLOSED`） |
| `test_morphology_event.py` | **1** | 全部（`CUTTER_NOT_CLOSED: 12 125`） |
| `test_morphology_model.py` | 0 | — |
| `test_event_qa.py` | **1** | `test_fixture_event_passes_the_a06_thresholds[rough_shared_cut]`（`CUTTER_NOT_CLOSED: 4 777`） |
| `test_interface_clip.py` | 0 | — |
| `test_multishell_shared_cut.py` | 0 | — |
| `test_impact_count.py` | 0 | — |
| `test_target_selection_and_lid_skirt.py` | 0 | — |
| **`test_fracture_realism.py`（本次新增）** | **0** | 10 passed，**2 xfailed**（见下） |

**5 个失败文件中的 3 个（`test_shared_cutter`、`test_morphology_event`、`test_event_qa[rough]`）
是 §5 缺陷的既有表现，与本次接线无关**：冻结基线 `_fprec_pytest_shared_cutter.txt` 记录了
**改动前**就已经失败的同样 3 个 `test_shared_cutter` 用例（4 486 坏边）。

**接线无回归的验证**（`data/a12_reports/pytest_realism/post_*.log`）：接线后重跑所有触碰
`api.make_closed_cutter` / `api.fracture_event` 的文件，**失败的测试名与改动前逐一相同**：

| 文件 | 退出码 | 失败测试名 | 与改动前 |
| --- | --- | --- | --- |
| `test_shared_cutter.py` | 1 | `test_rough_cutter_is_closed_and_within_budget`、`test_cutter_build_is_reproducible`、`test_default_cutter_reports_its_measured_error` | **完全相同**（冻结基线同 3 个） |
| `test_event_qa.py` | 1 | `test_fixture_event_passes_the_a06_thresholds[rough_shared_cut]` | **完全相同** |
| `test_interface_clip.py` | 0 | — | 相同 |
| `test_multishell_shared_cut.py` | 0 | — | 相同 |
| `tests/a12/qc/test_coverage_gates.py` | **0**（16 passed） | — | 新增注册表条目（`status=SPECIFIED`）不改变 `COVERAGE_TARGETS["fracture_backends"]=4`（该常量是发布目标，非活体注册表计数） |

代码层面的无回归论证：接线对 `api.py` 是**纯增量**——新增常量、2 个纯函数、1 个注册表条目，
以及 `make_closed_cutter` / `fracture_event` 里各**一个前置分支**（`backend == BACKEND_MORPHOLOGY`）；
`BUILT_BACKENDS`、`PENDING_BACKENDS`、`FractureSpec`、spec hash、`event.py` 全部未动。

### 8.3 `tests/a12/fracture/test_fracture_realism.py`（新增断言）

把两条主张严格分开，**不用 xfail 掩盖任何东西**：

* **主张 A（模型）——硬断言，全部通过**：
  `test_plane_control_really_is_planar`（平面必须是 `Ra<1e-4 mm`、法向最大 <0.01°）、
  `test_plane_event_passes_every_a06_gate`、`test_plane_sides_are_conjugate`、
  `test_modelled_fracture_surface_is_measurably_non_planar`（`Ra>5e-3 mm`、`Rt>1e-2 mm`、
  与平面基线差 >100 倍、坡度 P50 > 5° 且 P95 > P50）、
  `test_relief_parameters_come_from_the_body_not_from_a_free_choice`、
  `test_a_different_material_gives_a_different_relief`、
  `test_the_morphology_backend_is_gated_off_by_default`、
  `test_the_switch_gets_past_the_gate_into_the_builder`、
  `test_an_over_budget_configuration_fails_structurally`、
  `test_pixel_resolvability_uses_the_frozen_scan_ladder`。
* **主张 B（落地）——`xfail(strict=False)`，今天如实报失败，修好后自动转绿**：
  `test_morphology_realization_passes_the_a06_gates`（要求 W 全 A06 + 水密）、
  `test_rough_shared_cut_realizes_the_frozen_precision_budget`（要求 `realized ≤ 预算` 且
  `gap P95 ≤ 0.02 mm`）。两者当前都因 `CUTTER_NOT_CLOSED` 而 xfail，reason 里写明根因与文档小节。

---

## 9. 仍未解决项（按优先级）

1. **【阻断级】`cut.py` 逐胞三角化 8/12 分支面积错误**（§5.2）。
   影响：`rough_shared_cut`、`morphology_shared_cut`、`warp_voronoi_cut` 的粗糙面路径、
   以及所有需要细化的共享刀体——即**除平面外的一切断裂后端**。
   建议修法：不要手写 12 个分支，改为**按被细分边集合做标准化三角化**——
   把胞边界环（4 个角 + 各边中点，按 `n_split` 取舍）按角度排序后绕胞心扇形三角化，
   或统一用"边界环 + 中心点"的 fan（`n_split==4` 那一支已是正确的 fan，且面积恰为 1.0）。
   验收：对 13 种 `(n_split, 位置)` 组合断言面积和 == 1.0 且无重复/零面积三角；
   然后 `build_closed_cutter` 在 `edge_use_histogram == {"2"}` 上通过。
2. **【阻断级】非平面场在本机内存上限下不可建**。V18/M01 形态学在 400 k 单元预算下细化到约
   3.01 M 顶面（撞 3 M 三角上限）后 `MemoryError`（子进程内存上限约数百 MB；
   宿主 31 GB 总量、10 GB 空闲，故非系统 OOM）。
   建议：修好 §1 后重测真实内存峰值；必要时下调 `DEFAULT_MAX_CUTTER_CELLS` 或让
   `estimate_cell_demand` 与 refine 共享同一 cell 预算（当前 refine 会超出预估）。
3. **`estimate_cell_demand` 低估，预测未能阻止超预算**。V01/M01 在 `max_cells=30000` 下，
   预缩放后 refine 仍超 30 000 单元并抛 `PRECISION_BUDGET_EXCEEDED @ fracture.cut.refine`。
   建议：把 V01 这一例固化为回归用例，标定 safety 因子。
4. **模型振幅相对最短波长偏大**：`σ_r0 = 0.41 mm` vs `λ_min = 0.65 mm` →
   解析坡度 P95 = 53°、`max_slope = 2.22`（65.7°）。真实陶瓷断口坡度通常只有几度到约 20°。
   曲率上界 4.8/mm 也正因此偏高（预算 8.4/mm 才勉强容下）。
   建议：给 `σ_r0` 与 `λ_min` 增加一个**坡度合理性约束**（例如 `max_slope ≤ 1.0`，即 45°），
   并把被裁剪的量记进 `params.notes`。
5. **`configs/a12/fracture_morphology.yaml` 无法在 `generation_spec` 里写形态学后端**：
   `FractureConfig.backend` 是封闭 `Literal`（`synlab/schemas/spec.py:148`），不含
   `morphology_shared_cut`，而该文件在本任务写权限之外。当前配置里该块声明 `rough_shared_cut`
   并在文件头显式说明这一限制。建议由有权限的一方把 `"morphology_shared_cut"` 加进该 `Literal`。
6. **`correlation_length` 在无起伏时无意义**：平面基线返回 5.68 / 8.0 mm（对数值噪声做自相关）。
   建议在 `surface_features.correlation_length` 中对 `signal_var` 低于噪声地板的情形返回 `None`
   并把 `noise_var_mm2`/`signal_var_mm2` 一并报出（这两个量已经算了，只是没被用作判据）。
7. **本次未做的验证**：`morphology_shared_cut` 的 `commit_cutter`/`commit_fracture` 落库路径
   （`data/a12_morph/store` 已建目录，但因刀体建不出来而无可提交资产）。
