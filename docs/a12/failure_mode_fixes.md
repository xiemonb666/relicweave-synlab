# A12 批产接受率：三个真实缺陷的根因、修法与实测

本文件记录 next-experiment 批产（`tools/batch_generate.py` +
`configs/a12/next_experiment.yaml`）中**记入真实分母**的三类失败：根因、代码位置、修法、
before/after 实测数字，以及**未解决项**。

配置从未改动：`configs/a12/next_experiment.yaml` 的 sha256 =
`sha256:8186653101612cbc20e9eeba3f60ffbc241e3d1e3ebd690fdecb60746ab1fb16`
（`tools/batch_generate.py --status` 实测输出）。`tools/batch_generate.py`、`synlab/storage/**`、
`synlab/qc/**`、`synlab/observe/render.py`、`frontend/**`、`data/a12_demo/**` 均未改动。
另一个写者当时仍在跑同一批产（`data/a12/reports/next_experiment_batches.json` 持续增长），
因此本次验证规模压到最小（隔离 store 内 6 条谱系 + 单母体复现），未重跑整批。

---

## 0. 复算入口（所有数字都可从留档复算）

| 用途 | 文件 |
| --- | --- |
| 失败类 1：48 条谱系逐器型 schema 校验 | `data/a12/reports/failure_fix_validate_params48.py` → `failure_class1_param_validation.json` |
| 失败类 1：4 条真实跨器型反例（负对照） | `data/a12/reports/failure_fix_schema_negative_control.py` → `failure_class1_negative_control.json` + `.txt` |
| 失败类 2：真实母体上的 pattern 阶段复现 | `data/a12/reports/failure_fix_class2_repro.py` → `failure_fix_class2_repro.txt` |
| 失败类 3：属性来源与连通分量普查 | `data/a12/reports/failure_fix_class3_rootcause.py` → `failure_class3_rootcause.txt` |
| 失败类 3：P 轴 `NA → 可用` 实测 | `data/a12/reports/failure_fix_class3_axis_evidence.py` → `failure_class3_axis_evidence.json` |
| 失败类 3：pipeline 真正打到的碎片 | `data/a12/reports/failure_fix_class3_pipeline_target.py` → `failure_class3_pipeline_target.json` |
| 失败类 3：V10 连通分量普查 | `data/a12/reports/failure_fix_class3_fragment_probe.py` → `failure_class3_fragment_probe.txt`、`failure_fix_v10_components_after_skirt_fix.txt` |
| before/after 接受率与三类计数 | `data/a12/reports/failure_fix_acceptance_compare.py` → `failure_mode_before_after.json` + `.txt` |
| 每次批产调用的 run 归属 | `data/a12/reports/failure_fix_runs.py` → `failure_fix_runs.txt` |
| 计划稳定性（批产 params vs 当前 plan） | `data/a12/reports/failure_fix_plan_drift.py` → `failure_fix_plan_drift.json` |
| physical 阶段既有 QA 基线 | `data/a12/reports/failure_fix_physical_stage_baseline.json` |
| 第四类失败（observe，非本次范围）复现 | `data/a12/reports/failure_fix_class4_real_params.py` → `failure_class4_pat08_real_params.json` + `.txt` |
| fix 后 pattern/接缝审计 | `data/a12/reports/pytest_patterns_after_class2_fix.txt` + `_exit.txt` |
| fix 后 mothers+fracture 套件 | `data/a12/reports/pytest_mothers_fracture_after_fix.txt` + `_exit.txt` |
| 旧树（commit `e392c12`）对照 | `data/a12/reports/pytest_fracture_baseline_head.txt` |
| 回归测试 | `tests/a12/patterns/test_patterns_open_chart_and_glyph_width.py`、`tests/a12/fracture/test_target_selection_and_lid_skirt.py`、`tests/a12/mothers/test_sampling_and_store.py` |

---

## 1. 失败类 1（最多，4 例 `MOTHER_INVALID`）：参数字典跨器型

### 症状（ledger 原文，`run_c8e819f2f7599078`，10:43:23）

```
LIN0000_V12_M03_PAT05  V12: invalid parameters: 4 validation errors for BasinParams
                       depth_ratio  Extra inputs are not permitted [input_value=0.3463430657289447]
                       rim_flare    Extra inputs are not permitted [input_value=0.32823968601938175]
LIN0001_V08_M03_PAT06  V08: 4 errors for AmphoraParams (depth_mm, base_width_ratio, ...)
LIN0002_V18_M10_PAT02  V18: 11 errors for BrickParams (diameter_mm, wall_mm, ...)
LIN0003_V07_M05_PAT08  V07: 3 errors for BottleParams (with_handle, handle_thickness_mm, ...)
```

### 根因

`plan_generation` 把**目录顺序**的 vessel 列表交给采样器，而谱系走的是 permutation 顺序
（另一写者已修：`order` 只抽一次、把 `picked` 的 vessel 序列传给采样器；本次未回退这三处，
见 `synlab/pipeline.py::plan_generation` 注释与 `_sample_parameter_sets` 的文档串）。
在采样器这一层还缺两道**机制性**保证：

1. `sample_parameters` 返回的字典没有被"逐器型"确定性校验过（只有 `require_feasible=True`
   时才会经由 `create_mother → canonical_params` 间接校验；`require_feasible=False` 的分析门
   路径完全不校验）；
2. `_sample_parameter_sets` 用 `except Exception` 兜底成 `{...: [{}]}`，即**任何**采样异常都
   会被替换成原型中点参数，真实原因被吞掉。

### 修法（正确的层，不放宽 schema，不吞异常）

`synlab/mothers/api.py`

* 新增 `declared_fields(vessel_id)`／`declared_only(vessel_id, params)`／
  `params_model_ok(vessel_id, params)`：直接构造该器型自己的 pydantic 模型做确定性校验，
  违规时**返回**模型原文错误（`extra_forbidden`），由调用方决定 —— 不吞、不删字段、
  不放宽 `extra="forbid"`。
* `sample_parameters`：每个候选在通过解析门/构建门之后，再投影到 `declared_fields` 并过
  `params_model_ok`；未通过者以 `SCHEMA_INVALID:<模型原文>` 记入 `rejected`，采样报告新增
  `declared_fields`／`schema_gate`／`schema_rejections`。

`synlab/pipeline.py::_sample_parameter_sets`

* 仍**逐器型**调用 `sample_parameters(vessel, n, rng)`（rng 消费顺序不变，因此同种子下
  计划不变，实测见 §4.1）；
* 去掉 `except Exception` 兜底：采样失败（如 `TARGET_INFEASIBLE`）会抛出结构化错误，
  不再静默降级为原型参数；
* 每条即将投产的参数字典都用 `params_model_ok` 复验，失败即抛
  `MOTHER_INVALID`（带 `declared_fields`），绝不用别器型的字段或缺省字典顶替。

### 复现证明

* **48/48 通过**：`plan_generation(spec, max_mothers=48)`（真实规划，含真实采样门）
  逐条构造其器型模型 → `planned=48 validated=48 passed=48 pass_rate=1.0`，
  `foreign_field_rows=0`（`failure_class1_param_validation.json`；`spec_hash=sha256:aa231f9c…`）。
* **负对照（证明校验不是空转）**：ledger 里的 4 条真实跨器型字典全部被 `params_model_ok`
  判否，且 `create_mother` 仍以 `ErrorCode.MOTHER_INVALID` 拒绝（`extra="forbid"` 未放宽），
  同时每个器型自己的参数仍全部通过（`failure_class1_negative_control.json`，4/4）。

---

## 2. 失败类 2（`UNEXPECTED`，pattern 阶段）：两个独立缺陷

两个缺陷都在 **mother→material 之后、pattern 阶段**，`stages={'mother':…, 'material':0.0}`
就中断，因此此前一直被记成同一个 `UNEXPECTED`。用**真实母体**（store 里该谱系已提交的
mother 资产 + 其真实 params）逐条复现：

### 2a `TypeError: float() argument must be … not 'NoneType'`（6 例，V21/PAT16、V23/PAT06）

根因：`synlab/patterns/builders.py::field_context` 直接 `float(recipe_meta["chart"]["x_period_mm"])`。
`ChartFrame.as_dict()` 对**非 u 周期**的平面 chart（V21 `panel_plane`、V23 `figurine_plane`）
写真值 `x_period_mm = None`，而构建路径本来就把开 chart 归一化到轮廓弧长
（`BuildContext.x_period_mm = frame.x_period_mm or frame.s_span_mm`）。于是
`build_pattern` 成功、`evaluate` 必炸：

```
patterns/api.py:641  ctx = field_context(meta, palette, WarpField.from_dict(meta.get("warp")))
patterns/builders.py:1400  x_period_mm=float(recipe_meta["chart"]["x_period_mm"])
TypeError: float() argument must be a string or a real number, not 'NoneType'
```

修法：`builders.py` 新增 `effective_x_period_mm(chart_meta)`，与构建路径**同一规则**
（有 `x_period_mm` 用其值，否则用 `s_range_mm` 跨度），两者都没有时抛结构化
`SCHEMA_INVALID` 而不是 `float(None)`；`field_context` 改用它。场语义不变：`u` 仍是周期轴、
`s` 仍是轮廓弧长；平面 chart 的周期仍等于构建时用的同一数值。

### 2b `ValueError: operands could not be broadcast together with shapes (685,984) (685,985)`（3 例，V23/PAT12）

根因：`plan_raster` 把 texel 吸附成 `px_per_mm = width_px / width_mm`（使整数列正好覆盖一个
周期），而 `builders.build_glyph` 的 `cov/edge/rgb` 画布按 `plan` 的整数尺寸
（本次 685×984）建立，`glyphs.layout_text_run` 却重新用毫米推导列数：

```
width_px = ceil(tile_width_mm * px_per_mm)
实测 tile_width_mm = 122.92036697484887, px_per_mm = 8.00518273917405
     tile_width_mm * px_per_mm = 984.0000000000001   （比冻结整数高 1.1368683772161603e-13）
     ceil(...) = 985                                  ← 画布比 plan 宽 1 列
builders.py:1002  cov = np.maximum(cov, layout.mask)   ← (685,984) vs (685,985)
```

修法（最小改动、保持既有场语义）：`layout_text_run` 新增可选 `width_px`，`build_glyph` 明确
传入 `plan["width_px"]`（布局画布与冻结 plan **同一整数**）；毫米推导路径保留，但允许一个
texel 千分之一以内的舍入容差，使 `ceil` 不再吃掉 1 ulp。

### 复现证明

`failure_fix_class2_repro.py` 用真实母体重放 4 个组合（修前 2 个必炸、1 个同因、1 个对照）：

| 谱系 | 器型/材料/纹样 | 修前 | 修后 |
| --- | --- | --- | --- |
| `LIN0001_V21_M06_PAT16` | V21/M06/PAT16 (`panel_plane`, PAT16 复合层) | `TypeError: float(None)` @ `evaluate` | `evaluate OK` |
| `LIN0002_V23_M07_PAT12` | V23/M07/PAT12 (glyph, 984 列) | `broadcast (685,984) vs (685,985)` @ `build_glyph` | `build+evaluate OK`，`raster_plan.width_px=984`、`raster.shape=[685,984]` |
| `LIN0003_V23_M11_PAT06` | V23/M11/PAT06 (`figurine_plane`) | `TypeError: float(None)` @ `evaluate` | `evaluate OK` |
| `LIN0000_V10_M11_PAT15` | V10/M11/PAT15（对照，修前已 OK） | OK | OK（未回归） |

接缝/尺度审计：`pytest tests/a12/patterns -q` → 见 §4.3（退出码 0），新增回归用例
`tests/a12/patterns/test_patterns_open_chart_and_glyph_width.py`（8 项，含 984/985 的实测算术）。

---

## 3. 失败类 3（3 例 `NA_NOT_APPLICABLE`）：断面属性"缺失"的真实来源

### 症状

```
LIN0004_V10_M06_PAT03  ErrorCode.NA_NOT_APPLICABLE
physical.fields: "fragment carries no interface face attribute
                  (face_interface_id/face_origin_kind); P-axis interface operators are not
                  applicable to this body"
（stages={'mother':0.7,'material':0.0,'pattern':0.1,'fracture':17.4,'clean_truth':0.2}）
```

### 根因：属性没有"丢失"，是那个连通分量本来就没有新断面

`failure_fix_class3_rootcause.py` 用 store 里该谱系的真实 params 复现整条链，实测：

* 该母体（V10 带盖壶）**本身就是 3 个互不相连的闭合体**（`split_components`）：
  `#0` 盖 768 面/394 820 mm³（z=354.08–581.77）、`#1` 壶身 4224 面/281 673 mm³（z=5.11–216.60）、
  `#2` 256 面/13 045 mm³；
* `plane_shared_cut` 只切到壶身，于是切后 4 个 fragment 里 **2 个一刀未碰**：
  `…_E01-m`（就是那个盖，394 820 mm³，`origin_kind` 全为 0=mother_surface、
  `interface_id` 全 -1，到最近断面面心的最小距离 **143.4 mm**）与 `…-p__+1c1`；
* `physical.fields.roi_faces(kind="interface")` 的两条通道（`face_interface_id >= 0`、
  `face_origin_kind == ORIGIN_INTERFACE`）在这两个分量上都是空 → 抛 `NA_NOT_APPLICABLE`
  （**这是正确的判定**，不是异常滥用）；
* 但 `pipeline._pick_fragment` 只按"非 tiny 最大体积"选目标，于是**恰好选中了那个盖**
  （394 820 > 168 026 > 113 647），整个谱系因此被判失败。

属性链路上游（`fracture/cut.py` 通道重映射、`booleans` 焊接、`fragment.build_interface` 标签）
经查**没有丢失**：`fragment.make_fragment` 的 `origin_kind` 按顶点多数票写全，
`event._write_interface_ids` 只给"配对进 patch"的面写 `interface_id`，`roi_faces` 对
`origin_kind` 有回退——两条通道在有断面的分量上都非空（实测 330/658、329/686）。

副因（同一批真实缺陷，已修）：V10 的**盖裙**在 `_lid_part` 里漏了一次平移，被留在世界原点，
成了壶底下方一个多余的独立体（z=-5.06–1.69，13 045 mm³）——它与壶体/盖都不相连，
既污染母体几何，也让 fracture 多出一个"无断面"碎片。

### 修法

1. `synlab/pipeline.py`
   * 新增 `_fragment_interface_faces(fragment)`，与 `roi_faces` 的接受规则**完全一致**
     （两条通道任一非空即可）；
   * `_pick_fragment` 改为"**非 tiny 且真正带断面的最大碎片**"；若整个事件确实没有任何碎片
     带断面，则退回原"最大体积"规则——**不伪造属性**，此时 `NA_NOT_APPLICABLE` 依旧如实给出；
   * `build_one_mother` 把目标选择写成真实测量 `row["physical_target"]`
     （fragment_id / 体积 / 两条通道的面数 / 事件里带断面的碎片数）。
2. `synlab/mothers/vessels/group_composite.py::_lid_part`：盖裙平移到 `z_lid_base`
   （`z_lid_base = 0` 的调用者行为不变）。实测该分量由 z=-5.06–1.69 变为
   349.02–355.77（= 盖基面 354.08 ± 1.5/0.5×seat），不再悬在壶底之下。

### 实测证据（`failure_class3_axis_evidence.json`）

| | 修前规则 | 修后规则 |
| --- | --- | --- |
| 目标碎片 | `…_E01-m`（未碰过的盖，394 820.4 mm³） | `…_E01-p`（178 117.3 mm³） |
| `roi_faces(kind="interface")` | **NA_NOT_APPLICABLE**（"no interface face attribute"） | **可用**：329 个 ROI 面，`roi_source="face_interface_id"` |
| P03 退化算子 | 无法执行 | `apply_damage` 成功：2 个 component，`lost_volume_ratio=0.00876815`，`recipe.basis_source="degrade.registry"` |

诚实说明：同一次 `audit_physical` 的判定仍是 **FAIL**——但这是**本构建既有的批级现象**，
与本次改动无关：store 里已有 `physical_result` 8 条中 6 条 `QA_FAIL`，失败码为
`NON_POSITIVE_VOLUME`/`NOT_WATERTIGHT`（P03 level 1 削掉的零体积碎屑），失败谱系
`lost_volume_ratio` 0.0040–0.0074 与本次 0.0088 同量级。见 §5 未解决项。

---

## 4. 接受率：before / after（真实分母）

### 4.1 隔离验证不与队友抢数据

fix 后的"after"测量用**同一个** `tools/batch_generate.py` + 同一冻结 config，但写到隔离目录：

```
python tools/batch_generate.py --config configs/a12/next_experiment.yaml \
  --root data/a12/reports/failure_fix_store \
  --ledger data/a12/reports/failure_fix_batches.json \
  --batch 6 --only 1,2,3,4,9,10
```

`--only 1,2,3,4,9,10` = 4 条曾经失败的谱系（1=V21/PAT16、2=V23/PAT12、3=V23/PAT06、
4=V10/PAT03）加 2 条对照组（9=V04/PAT02、10=V07/PAT08）。**没有**改动队友的 store 与
`next_experiment_batches.json`，也没有重跑整批。

计划未漂移（关键安全检查）：把队友在跑的 ledger 里每行 `(lineage_id, vessel, material,
pattern)` 与本次修复后的规划逐条比对 → **12/12 完全一致、0 处不一致**；不一致只出现在
`plan_generation` 被队友修好**之前**的旧 plan 行（旧映射 `LIN0001_V08_M03_PAT06` 等）。
即本次改动不改变同种子下的谱系映射（采样路径的 rng 消费序列未变）。

### 4.2 before（真实 ledger，`failure_fix_acceptance_compare.py` 复算）

按 `run_id` 分组可把每次批产调用分开（一个 run = 一份已加载的代码状态，
`failure_fix_runs.txt`）：

| run_id | 时间窗 | attempted | accepted | 备注 |
| --- | --- | --- | --- | --- |
| `run_e69efa4cbcab8b94` | 10:28–10:42 | 6 | 5 | 旧 plan；1 例 `PRECISION_NOT_REALIZED` |
| `run_c8e819f2f7599078` | 10:43 | 4 | 0 | **失败类 1 × 4**（旧 plan 跨器型映射） |
| `run_1f0eb1ef0c60a503` | 10:48–10:52 | 6 | 2 | 类 2 × 3、类 3 × 1 |
| `run_bdc7b25bd6c6f835` | 10:53–11:00 | 12 | 4 | 类 2 × 6、类 3 × 2（重试同 4 条谱系） |
| `run_92f4b8e5e36c5687` | 11:01–11:08 | 6 | 2 | 类 2 × 3、类 3 × 1 |

**修复前的可比口径**（当前 plan 的三次 run，10:48:35–11:08:18）：
`attempted=24, accepted=8 → 33.3%`，其中
**失败类 2 = 12 次**（3 条独立谱系：V21/PAT16、V23/PAT12、V23/PAT06，各重试 4 次）、
**失败类 3 = 4 次**（1 条独立谱系 V10/PAT03 重试 4 次）、失败类 1 = 0（已由计划的
"被选 vessel 序列"修复挡掉，其 4 次出现在更早的旧 plan run 里）。

全量 ledger 口径（含旧 plan 行）同一时刻快照：`attempted=43, accepted=21 → 48.8%`，
类 1 × 4（4 条谱系）、类 2 × 13（4 条谱系）、类 3 × 4（1 条谱系）、其它（精度）× 1。
数字随队友继续产数据而增长，`failure_fix_acceptance_compare.py` 可随时重算。

### 4.3 after（修复后）

| 来源 | attempted | accepted | 接受率 | 三类计数 |
| --- | --- | --- | --- | --- |
| **隔离验证 6 条谱系**（`failure_fix_store`，`--only 1,2,3,4,9,10`） | **6** | **6** | **100%** | 类 1 = 0、类 2 = 0、类 3 = 0 |
| 队友同一批产的 fix 后 run（`run_e031b5651fb7f7ff`、`run_c1bf35c0ae7b0387`、`run_c75cafbb10b008c4`；快照 11:46） | 13 | 10 | 76.9% | 类 1 = 0、类 2 = 3（两个**新到达**谱系：`LIN0016_V19_M04_PAT08`、`LIN0019_V12_M05_PAT11`，见 §5.7/§5.9）、类 3 = 0 |

隔离验证逐条（`failure_fix_batches.json`，run `run_2703b03b77f58bb0`，总 1167 s，
每条母体 194.6 s）：

| # | 谱系 | 器型/材料/纹样 | 修复前 | 修复后 |
| --- | --- | --- | --- | --- |
| 1 | `LIN0001_V21_M06_PAT16` | V21/M06/PAT16 | `UNEXPECTED`（类 2a） | **OK** 131.9 s，frag=2 obs=12 r2=1 |
| 2 | `LIN0002_V23_M07_PAT12` | V23/M07/PAT12 | `UNEXPECTED`（类 2b） | **OK** 198.2 s，frag=2 obs=12 r2=1 |
| 3 | `LIN0003_V23_M11_PAT06` | V23/M11/PAT06 | `UNEXPECTED`（类 2a） | **OK** 221.9 s，frag=2 obs=12 r2=1 |
| 4 | `LIN0004_V10_M06_PAT03` | V10/M06/PAT03 | `NA_NOT_APPLICABLE`（类 3） | **OK** 130.0 s，frag=4 obs=12 r2=1 |
| 5 | `LIN0009_V04_M01_PAT02` | V04/M01/PAT02 | OK（对照） | **OK** 238.5 s |
| 6 | `LIN0010_V07_M10_PAT08` | V07/M10/PAT08 | OK（对照） | **OK** 179.1 s |

类 3 的谱系在真实 pipeline 里打到的碎片（`failure_fix_class3_pipeline_target.json`）：
`LIN0004_V10_M06_PAT03` → `damaged=LIN0004_V10_M06_PAT03_E01-p`（带断面的那一块），
而不是修复前那块"没被切到的盖"。P03 的审计状态仍是 `FAIL`
（`DAMAGED_NOT_SUBSET_OF_CLEAN`、`NON_POSITIVE_VOLUME`、`NOT_WATERTIGHT`，见 §5.2）。

**计划稳定性**（`failure_fix_plan_drift.json`）：当前工作树重新规划 120 条谱系，
与队友已提交的批产母体参数逐条比对 → **20/20 完全一致**，即本次修复**没有改变**
同种子下的计划（谱系三元组 120/120 一致）。
注意：`failure_class1_param_validation.json` 是 `max_mothers=48` 的计划快照，
其**参数值**与 120 目标计划天然不同（每个器型抽样个数不同 ⇒ LHS 流不同），
因此不能拿它逐值对比批产；三元组对比才是口径。

### 4.4 测试与审计退出码

| 命令 | 结果 |
| --- | --- |
| `pytest tests/a12/patterns -q` | **退出码 0**（226 项，`pytest_patterns_after_class2_fix_exit.txt` = `exit=0`） |
| `pytest tests/a12/mothers tests/a12/fracture -q` | **退出码 1**，但失败集合与旧树**完全相同**：当前树 3 FAILED + 3 ERROR，全部落在 `tests/a12/fracture/test_shared_cutter.py` 与 `test_event_qa.py`；在修复前的 commit `e392c12` 上跑同两个文件得到**同样的 3 FAILED + 3 ERROR**（逐条同名，`pytest_fracture_baseline_head.txt`）。根因是 `tests/a12/fracture/fixtures.py::thin_bowl_mother` 的 `trimesh.boolean.difference(..., engine="manifold")` → `ValueError: Not all meshes are volumes!`（fixture 级，与本次三处修改无关，且这三个文件都不在本次改动范围内）。`tests/a12/mothers` 14 项全绿；本次新增/改动文件的测试全绿（patterns 8 项、fracture 5 项、mothers 新增 4 项） |

---

## 5. 未解决 / 如实保留

1. **`PRECISION_NOT_REALIZED`（1 例，`LIN0004_V05_M01_PAT01` 旧 plan）**：`fracture.backend`
   的 manifold 布尔（`boolean intersection failed … Not all meshes are volumes!`）。
   本次不在三类之内，未修；该行仍留在分母里。
2. **physical 阶段 `QA_FAIL`（批级既有）**：store 现有 8 条 `physical_result` 中 6 条 FAIL，
   失败码 `NON_POSITIVE_VOLUME` + `NOT_WATERTIGHT`，来源是 P03 level 1 削出的零体积碎屑
   (`comp#c2…` DEBRIS, volume 0.0)。它不阻断谱系接受（`label_bundle` 仍 QA_PASS），
   但物理等级未被审计确认；未修（属 `synlab/degrade/**`/`synlab/physical/**` 语义问题，
   不在本次三类缺陷范围）。
3. **V10 母体几何（真实缺陷，未改）**：`monotone_radius_control_points`
   （`synlab/mothers/vessels/common.py:146`）会把"半径先增后减"的轮廓点**全部丢弃**，
   于是 V10 壶身在肩部（z=216.60）就被截断，`z_rim_target_mm=357.45` 丢失，盖因此悬空
   137 mm（`profile_metrics.z_rim` vs `z_rim_target_mm` 实测）。这是**全局**轮廓规则，
   任何"口沿收窄"的器型都受影响；修它等于改动所有器型的几何、chart、几何哈希与既有审计
   基线（且队友正在用同一批 plan 产数据），因此本次**只**修了同源、局部、可证伪的
   盖裙平移 bug，并把这处如实记录在此。
4. **盖裙仍是独立壳**：`_lid_part` 用 `trimesh.util.concatenate` + `cleanup`，裙与盖体积重叠
   但拓扑上仍是两个闭合壳（`split_components` 仍会给出一个 256 面的分量）。
   本次只保证它落在盖的坐标系内（不再悬在壶底），未改成布尔并集（会改变 V10 几何与体积）。
5. **验证规模受 CPU 约束**：队友的批产在跑（同机 2 物理核），after 验证只跑 6 条谱系
   （隔离 store）而不是整批 120；`plan_generation` 每次调用本身要跑真实采样门，故未反复重跑。
6. **归属口径**：run 的代码状态按 `run_id` 分组 + 时间窗推断（`run_92f4b8e5…` 之后的一次
   调用为 fix 后代码）。`run_id` 由 git dirty diff 哈希派生，任何写者的工作区改动都会改变它，
   因此 run_id 变化**不能**用来判断某一处 fix 是否已加载；`failure_fix_runs.txt` 给出全部
   证据以便独立复核。计划是否漂移另有独立证据（§4.3 的 20/20 参数一致）。
7. **第四类失败（observe 阶段，不在本次写入范围，未修）**：
   `LIN0016_V19_M04_PAT08`（V19/M04/PAT08，19.75 s，ledger 11:39:07）报
   `IndexError: index 1024 is out of bounds for axis 1 with size 1024`。
   ledger 的 `stages` 只到 `physical`（说明 physical 块已跑完），用当前 plan 的**真实参数**
   重放（`failure_fix_class4_real_params.json`）确认炸点在观测阶段：

   ```
   synlab/observe/api.py:129   route_proxy_scan(target, camera, spec, cam_rng, backend=backend)
   synlab/observe/routes.py:949  depth = _carve_holes(depth, hole_count, rng, min_radius_px=3, max_radius_px=7)
   synlab/observe/routes.py:1063 out[yy[disc], xx[disc]] = np.nan      ← index 1024 vs size 1024
   ```

   即 proxy_scan 路线挖孔时，某个孔盘越过了 1024 宽的深度图边界（列索引 == W）。
   修法很小（在 `_carve_holes` 里把盘坐标裁进图像范围），但 `synlab/observe/**` 属另一写者、
   不在本次允许写入范围，故**只记录不修**。它独立于本次三类修复：该谱系位于 index 16，
   在修复前从未被批产走到（队友最新 run 才第一次到达）。
8. **`LIN0004_V10_M06_PAT03` 的 P03 审计多一条 `DAMAGED_NOT_SUBSET_OF_CLEAN`**：
   该谱系以前在 P 轴之前就失败，所以这是它第一次真正跑完 P03；审计口径属
   `synlab/physical/**`，未在本次范围内改动。
9. **第五类失败（physical 阶段，不在本次写入范围，未修）**：
   `LIN0019_V12_M05_PAT11`（V12/M05/PAT11，ledger 11:44:22）报
   `ValueError: all the input array dimensions except for the concatenation axis must match
   exactly … the array at index 0 has size 3 and the array at index 12 has size 4`，
   `stages` 无 `physical` 键 ⇒ 炸点在 physical 块内。用当前 plan 的真实参数重放
   （`failure_fix_class5_v12_attribution.py` / `.txt`）确认：

   ```
   synlab/physical/api.py:446  apply_damage → assemble_damage_bodies
   synlab/physical/api.py:261  close_numerical_pinholes(part)
   synlab/physical/api.py:172  candidate.faces = np.vstack([mesh.faces] + patch)   ← (N,3) vs (N,4)
   ```

   即"数值针孔"补片数组有 4 列（四边形）却与 (N,3) 三角形面表 `vstack`。
   **与本次 class-3 目标选择无关**：同一条谱系在"旧规则（最大体积）"和"新规则"下
   报出**同一个**错误与同一段 traceback（`failure_class5_LIN0019_attribution.json`）。
   修法在 `synlab/physical/api.py`（生成补片时三角化，或写入前裁剪到 3 列），
   该文件不在本次允许写入范围，故只记录。
10. **fix 后窗口的 after 数字（快照 11:46）**：
    队友 fix 后 run（`run_e031b5651fb7f7ff`、`run_c1bf35c0ae7b0387`、`run_c75cafbb10b008c4`）
    `attempted=13 accepted=10 → 76.9%`，其中类 1/类 3 均为 0，3 次失败全部是上面 #7/#9
    两个**新到达谱系**（index 16/19，修复前批产从未走到）；隔离 6 条谱系 6/6 = 100%。
    全量 ledger（47 行，含旧 plan 行）= 23/47 = 48.9%，可作为"修复前计入分母"的完整口径。
