# A12 断口真实性：非平面形态学 + rough 精度（实测）

> 结论先行：**形态学模块已实现、已做最小接线（默认关闭），在小型解析母体上通过了全部 A06 审计；
> 但在真实母体（V18/M01）上，共享切割器的四叉树拓扑在约 20 万单元量级上崩坏（自交叠三角形），
> `rough_shared_cut` 与 `morphology_shared_cut` 都无法产出水密刀体。**
> 因此"断裂口符合真实物理碎裂了没"的诚实答案是：**物理参数化做到了，真实母体上的落地还没有做到**。
> 所有数字见下文，未放宽容差，未用噪声冒充起伏。

本文件里每一个数字都来自真实运行，原始证据在 `data/a12_reports/`：

| 证据文件 | 内容 |
| --- | --- |
| `data/a12_reports/fracture_realism_V18_M01_plane_rough.json` | V18/M01 平面基线与 rough 实测 |
| `data/a12_reports/morph_V18_M01.json` | V18/M01 形态学事件（含失败记录） |
| `data/a12_reports/_stale/morph_V18_M01_att1_FAILED.json` | 上一版实现的历史失败（版本错配，永久留档） |
| `data/a12_reports/pytest_realism/*.log` | `pytest tests/a12/fracture` 分文件退出码 |
| `data/a12_reports/morph_pixel_resolvability.json` | 像素可分辨性表 |

---

## 1. 形态学 API 清单（`synlab/fracture/morphology.py`，1323 行）

模块顶部的物理常量（L78–L120）本身就是"参数由物理量驱动"的声明，逐条给出：
`SIGMA_REF_MPA=90.0`、`WALL_REF_MM=5.0`、`WEIBULL_M=9.0`、`RYSKEWITCH_B=4.5`、
`MIRROR_CONSTANT_MPA_SQRT_M=2.5`、`MIST_TO_MIRROR_RATIO=1.8`、`HURST_EXPONENT=0.75`、
`ROUGHNESS_BANDS=5`、`POROSITY_FROM_PORE_AMOUNT=0.35`、`GRAIN_RELIEF_FRACTION=0.12`、
`CONCHOIDAL_RADIUS_PER_WALL=6.0`、`PRECISION_LADDER_FACTORS=(1.0,0.5,0.25)`。

### 1.1 公开入口（`__all__`，L58–L71）

| 函数 / 类 | 行号 | 作用 | 关键参数 |
| --- | --- | --- | --- |
| `MORPHOLOGY_META_KEY` | L74 | `"fracture_morphology"`，参数记录发布的 meta 键 | — |
| `BACKEND_MORPHOLOGY` | L76 | `"morphology_shared_cut"` | — |
| `material_fracture_inputs(profile, *, material_id)` | L205 | 从真实材料 profile 抽物理输入（grain/pore/aggregate/fibre/glaze/porosity） | `material_id` |
| `wall_thickness(mother, *, max_probes=320)` | L271 | 壁厚分布，取自冻结的母体审计 | `max_probes` |
| `derive_morphology_parameters(...)` | L408 | **核心**：把材料+壁厚+起始点解析成全部形态参数 | `material, wall, origin_uv, tris_uv, core_area_mm2, window_area_mm2, extent_mm, rng, error_budget_mm, max_cells` |
| `estimate_cell_demand(field, *, budget_mm, step_mm, max_points, safety)` | L988 | 精化**之前**用细栅格曲率普查预测单元需求 | `budget_mm=0.01, max_points=2.5e6, safety=1.3` |
| `build_morphology_field(basis, mesh, params, *, rng, probe_step_mm, halo_mm, cross_section)` | L1094 | 把参数实数化成解析高度场 | `halo_mm`（缺省 `max(BAND_HALO_MM, 8*relief_amp)`） |
| `prepare_morphology(mother, *, material_profile, rng, basis, event_id, error_budget_mm, max_cells, wall_probes, origin_uv, window_area_estimate_mm2)` | L1181 | 只测量、不建刀体；平面基线与形态学共用同一次测量 | — |
| `build_morphology_cutter(mother, *, material_profile, rng, basis, prepared, event_id, error_budget_mm, max_cells, max_triangles, wall_probes, allow_precision_ladder, origin_uv, window_area_estimate_mm2)` | L1230 | 建共享刀体，返回 `(cutter, field, params, report)` | `allow_precision_ladder=True` |

### 1.2 参数记录与高度场

| 类 | 行号 | 说明 |
| --- | --- | --- |
| `MaterialFractureInputs` | L158 | 材料物理输入（`grain_scale_mm`、`pore_scale_mm`、`porosity`、`correlation_length_mm` …） |
| `WallThickness` | L256 | `min/p05/median/max_mm`、`probes`、`source` |
| `FractureMorphologyParams` | L295 | 冻结的 JSON 参数记录，含 `formulas`（每条关系的公式字符串） |
| `MorphologyHeightField` | L726 | `HeightField` 子类：`W(u,v) * (dome + G*(roughness+hackle+ribs+pits+fibre))` |
| `_PitSet` / `_Raster` | L572 / L676 | 坑阵列与釉层调制的分桶求值表 |

`MorphologyHeightField` 的分量方法（全部可单独调用，便于证据取样）：
`_roughness` L755、`hackle` L768、`ribs` L783、`dome` L795、`fibre` L802、`_relief` L810、
`raw` L820（融合单遍）、`gradient` L866、`curvature_bound` L885、`gradient_bound` L903、
`windowed_curvature_bound` L921、`apply_scale` L954。

### 1.3 测量 API（`synlab/fracture/surface_features.py`，554 行）

| 函数 | 行号 | 作用 |
| --- | --- | --- |
| `top_surface_samples(mesh, basis, *, n_samples, rng)` | L55 | 结构性识别刀体**顶面**（底面唯一，非顶即底），面积加权采样 |
| `detrend_plane(u, v, w, weights)` | L128 | 最小二乘去形，返回 `residual` + `waviness_rms_mm` |
| `amplitude_statistics(u, v, residual, *, cell_mm, weights)` | L148 | `Ra`/`Rq`/`Rz`/`Rt`（`Rz` = 2.5 mm 评估胞 `0.5/99.5` 分位带均值） |
| `correlation_length(u, v, residual, *, step_mm)` | L216 | 自相关降到 `1/e` 的径向滞后，扣除胞内噪声方差 |
| `ridge_density(u, v, residual, origin_uv, radii_mm, *, step_mm, samples)` | L276 | 绕起始点圆上的脊线密度（条/mm） |
| `measure_interface_surface(fragments, basis, params, *, cutter_mesh, n_samples, ...)` | L383 | **交付面**实测（用 `event._interface_faces` 的冻结判据，避免把母体壁当粗糙度） |
| `measure_cutter_surface(mesh, basis, params, *, window, n_samples, ...)` | L424 | 刀体实现面实测，`window` 限定材料带核心 |
| `conjugate_profile_consistency(fragments, patches, basis, *, step_mm, max_faces_per_side)` | L452 | 共轭：两侧栅格相关、共轭点距离 P95、面积记账 |

### 1.4 是否被 `event.py` / `api.py` 调用？

| 位置 | 改动前 | 改动后（本次接线） |
| --- | --- | --- |
| `synlab/fracture/event.py` | **0 处引用**（仅 L203 读 `cutter.realized_error_mm`） | 仍为 0 处：形态学走既有 `run_shared_cut(mother, cutter, ..., extra_meta=...)`，`event.py` 不需要知道形态学存在 |
| `synlab/fracture/api.py` | **0 处引用** | 新增接线点（见 §2） |
| `synlab/fracture/spec.py` | 无 | 无（`FractureSpec` 未改，spec hash 未动） |

---

## 2. 最小接线（默认关闭）

接线只落在 `synlab/fracture/api.py`，5 个点，全部可开关：

| 行号 | 内容 |
| --- | --- |
| L45 | `BACKEND_MORPHOLOGY = "morphology_shared_cut"` |
| L47 | `MORPHOLOGY_SWITCH_ENV = "SYNLAB_FRACTURE_MORPHOLOGY"` |
| L56–L60 | `BUILT_BACKENDS` **不变**；新增 `GATED_BACKENDS = (BACKEND_MORPHOLOGY,)` |
| L65 | `morphology_backend_enabled(spec)`：环境变量为真，或 `spec.meta["morphology"]` / `spec.meta["morphology_backend"]` 为真 |
| L88 | `morphology_options(spec)`：从 `spec.meta` 取 `material_profile` 与逐事件选项 |
| L151 | `register_fracture_backend(BACKEND_MORPHOLOGY, status=STATUS_SPECIFIED, ...)` |
| L208 | `make_closed_cutter` 分派到 `_make_morphology_cutter` |
| L273 | `fracture_event` 分派到 `_morphology_event` |
| L345 | `_gate_morphology`：未开关时抛 `OPERATOR_NOT_REALIZED`（**明确报错，绝不静默降级成平面**） |
| L364 / L387 | `_make_morphology_cutter` / `_morphology_event` |

为什么**不**放进 `BUILT_BACKENDS`：`tests/a12/integration/diversity_context.py:95` 会遍历该元组并写入上下文
报告；把形态学放进去会让别人的产物在无感知的情况下改变成本与 QA 数字。要跑它必须显式开关。

开关与拒绝行为有单测：`tests/a12/fracture/test_fracture_realism.py::test_the_morphology_backend_is_gated_off_by_default`、
`::test_the_switch_turns_the_wired_path_on`。

---

## 3. 平面基线的对照（V18/M01，真实母体）

母体：`V18`（碗形），M01（grog + 气孔，粗陶），524 面 / 262 顶点，水密，体积 85326.12 mm³，
包围盒 81.74 × 124.14 × 15.33 mm。壁厚实测 `p05 = 6.243 mm`，中位 `13.547 mm`
（来源 `synlab.mothers.audit.audit_mother:checks.min_thickness`）。

刀体预算 0.01 mm / 400 000 单元（`spec.py` 冻结值，**未放宽**）：

| 量 | 平面 `plane_shared_cut` |
| --- | --- |
| 刀体三角面 / 单元 | 16 896 / 4 096 |
| `requested_error_mm` / `realized_error_mm` | 0.01 / **0.0** |
| 刀体水密 | True |
| 交付面 `Ra` | **1.103e-07 mm** |
| `Rz` / `Rt` | 4.601e-07 / 1.128e-06 mm |
| 交付面法向角 均值 / P95 / 最大 | 8.59e-05° / 1.67e-04° / **0.012°** |
| 二面角 P50 / P95 / 最大 | 1.40e-05° / 1.85e-04° / 0.012° |
| 体积相对差 `volume_rel_diff` | 4.82e-10（门限 1e-3） |
| 重叠比 `overlap_ratio` | 0.0（门限 1e-4） |
| 共享面 `gap_p95_mm_max` | 1.187e-07 mm（门限 0.02） |
| 法向反转 P95 | 7.25e-05°（门限 2.0°） |
| 共轭点距离 P95 | 9.03e-09 mm |
| 共轭剖面相关 min | 0.9963 |
| 自交 | 无（`self_intersection_report.ok = True`） |
| 审计 `passed` | **True** |

**这张表的作用是控制组**：平面切割把 `Ra` 测到 1.1e-07 mm（双精度舍入量级），说明测量链本身
能正确地测出"完全平面"。因此形态学侧任何 0.01 mm 量级的 `Ra` 都是真实起伏，不是测量噪声。
注意 `correlation_length_mm = 5.68` 是平面对数值噪声做自相关的产物，**没有物理意义**，不应引用。

---

*（后续小节：形态学实测、rough 精度、像素可分辨性、仍未解决项 —— 见下）*
