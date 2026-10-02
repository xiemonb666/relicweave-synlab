# 物理碎裂定量标定（`warp_voronoi_cut`）

本文件是**新后端 `warp_voronoi_cut` 的定量标定与精度审计**：片数律的数据点与拟合、单调性检验（含反例）、
逐点 A06 审计数值、1/4/8/16/32 片耗时与瓶颈、批产接入结果，以及仍未解决项。

* 仓库根：`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab`；解释器 `.venv\Scripts\python.exe`
* 全部数字都是**本机本轮实测**，原始 JSON 在 `data/a12_reports/`（文件名逐条给出）；Sections A–E 的表格由
  `python -m synlab.fracture.calibrate tables --inputs ...` **从原始 JSON 直接生成**
  （`data/a12_reports/fracture_calibration_tables.md`），不是手抄的。
* 拒绝（REFUSED）一律照实记录；**没有**为了通过而放宽阈值、重试换种子或丢弃反例。
* 阈值来源：`synlab/fracture/spec.py` 的冻结常量；`configs/a12/fracture_physics.yaml` 只允许复制，
  `synlab.fracture.physics.verify_against_spec` 在**放宽**时硬报错（§7）。
* 测量工具（本轮新增，`synlab/fracture/**` 与 `tests/a12/fracture/**`）：
  `synlab/fracture/calibrate.py`（仪器 + 拟合 + 单调性 + 表格渲染）、`synlab/fracture/calibration.py`
  （从真实母体测 `BodyStats`/`MaterialStats`）、`tests/a12/fracture/_run_calibration.py`（批产与
  validate）、`_run_series.py`（系列扫描）、`_run_acceptance.py`（接受率）、
  `_probe_volume_accounting.py` 与 `_probe_cell_watertightness.py`（体积损失根因）。

---

## 1. 片数律：公式与标定值

实现里的定律（`synlab/fracture/impact.py::count_model`）：

```
N = N0 * (U / U_ref)^beta * (V / V_ref)^alpha * (t_ref / t)^gamma
U = 0.5 * m * v^2 ,  m = rho * V          （撞击能量，来自实测质量与实测密度）
U_ref = 0.5 * rho_ref * V_ref * v_ref^2   （声明参考体在声明参考速度下的能量，rho_ref = 2.2 g/cm^3）
alpha = 1/(2m) + 0.5 = 0.5714             （Weibull 最弱链 + 几何项，m = 7）
gamma = 0.5                               （薄壁项）
V_ref = 339292 mm^3 (D200/t6/H90 碗) ,  t_ref = 6 mm ,  v_ref = 3130 mm/s (0.5 m 自由落体)
U_ref = 3.6564 J
```

| 参数 | 本轮采用值 | 来源 |
|---|---|---|
| `N0` | **2.5295** | **实测标定**：在全部 38 个实测点上、把下限 2 片当**删失（censored）**重解振幅 |
| `beta` | **0.588 ± 0.054 (1σ)** | **实测标定**：21 个未触底点上的最小二乘，R² 0.8632 |
| `alpha` | 0.5714 | **不是拟合**：钉在声明的 Weibull + 几何形式上（§3 说明为什么无法分离） |
| `gamma` | 0.5 | 同上 |
| 标定前 `N0` | 3.0 | 由 `calibrate_reference_energy` 反解 `U_ref` 得到——该写法使**振幅退化** |
| 标定前 `beta` | 0.65（ENGINEERING，声明区间 0.5–0.8） | 实测 0.588 落在 2σ 内 |

**为什么要重新定振幅（本轮的核心修正）**：旧写法让 `U_ref` 由 `N0` 解出，于是振幅是任意的；真实 V01 碗
（1.85e5 mm³，中位壁厚 4.08 mm）在 0.5 m 落高下实测 `n_raw` 只有 **1.273**，能量扫描里 h ≤ 500 mm 的
`n_raw` 全在 0.54–1.47，**低于下限 2**，而矩阵/尺度系列的点几乎全部压在下限——这正是"修复仍差的部分"。
本轮把 `U_ref` 固定成声明参考体的物理能量，只拟合 `beta`，再在全部实测点上删失重解 `N0`。

拟合结果（`configs/a12/fracture_calibration.json`）：

| 拟合 | 点数 | `N0` | `beta` | R²(ln N) | RMSE(ln N) | 平均\|误差\| | 最大\|误差\| |
|---|---|---|---|---|---|---|---|
| **未触底点**（实测 N > 2） | 21 | 2.0521 | **0.5880 ± 0.0537** | **0.8632** | 0.1806 | 0.59 片 | 3.93 片 |
| 全部点 + 下限删失 | 38 | 2.7718 | 0.3550 | 0.7913 | 0.2533 | 0.73 片 | 3.93 片 |
| **采用值**（beta ← 未触底拟合；N0 ← 全部点删失重解） | 38 | **2.5295** | **0.5880** | 0.7631 | 0.2699 | 0.89 片 | 3.93 片 |

**如实说明**：`beta = 0.588` 由 21 个未触底点定出（1σ = 0.054）；这些点覆盖 3 个不同整数片数档
（3/5/8）与 2 种落高系列，`alpha` 与 `beta` 在这批数据上**无法分离**，所以 `alpha` 保持声明值——这是
§3 单调性反例的结构性来源。最大误差 3.93 片出现在 V02/M01（最小器型，实测恒为 2 片，模型在 8 m 落高给
5.9 片），是"小件在高能量下仍不碎"这一实测事实与定律形式的偏差。

### A. 数据点（38 个实测点，40 行含 2 个拒绝；由仪器直接生成）

| # | 器型/材料 | 扫描 | 体积 mm³ | 中位壁厚 mm | 落高 mm | U J | n_raw | N_det | **N 实测** | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | V02/M01 | 矩阵 | 62249 | 4.256 | 500 | 0.672 | 0.391 | 2.000 | **2** | OK（触底） |
| 2 | V01/M01 | 矩阵 | 184888 | 4.081 | 500 | 1.995 | 1.469 | 2.000 | **2** | OK（触底） |
| 3 | V13/M01 | 矩阵 | 425691 | 11.658 | 500 | 4.594 | 2.357 | 2.357 | **2** | OK |
| 4–6 | V02/M04,V01/M04,V13/M04 | 矩阵 | 同上 | 同上 | 500 | 同上 | 同上 | 同上 | **2,2,2** | OK（材料不改变片数） |
| 7 | V01/M01 | 能量 | 184888 | 4.081 | 100 | 0.399 | 0.537 | 2.000 | **2** | OK（触底） |
| 8 | V01/M01 | 能量 | 184888 | 4.081 | 250 | 0.998 | 0.952 | 2.000 | **2** | OK（触底） |
| 9 | V01/M01 | 能量 | 184888 | 4.081 | 500 | 1.995 | 1.469 | 2.000 | **2** | OK（触底） |
| 10 | V01/M01 | 能量 | 184888 | 4.081 | 1000 | 3.990 | 2.265 | 2.265 | **2** | OK |
| 11 | V01/M01 | 能量 | 184888 | 4.081 | 2000 | 7.981 | 3.494 | 3.494 | **3** | OK |
| 12 | V01/M01 | 能量 | 184888 | 4.081 | 4000 | 15.961 | 5.388 | 5.388 | **5** | OK |
| 13–18 | V02/M01 | 能量 | 62249 | 4.256 | 100…4000 | 0.134…5.374 | 0.143…1.434 | 2.000 | **2**（六点全部） | OK（触底） |
| 19–24 | V13/M01 | 能量 | 425691 | 11.658 | 100/250/500/1000/2000/4000 | 0.92/2.30/4.59/9.19/18.37/36.75 | 0.86/1.53/2.36/3.64/5.61/8.65 | 2…8.65 | **2,2,2,3,5,8** | OK |
| 25 | V01/M01 ×0.5 | 尺度 | 23111 | 2.041 | 1000 | 0.499 | 0.266 | 2.000 | **2** | OK（触底） |
| 26 | V01/M01 ×0.75 | 尺度 | 78000 | 3.061 | 1000 | 1.683 | 0.931 | 2.000 | **2** | OK（触底） |
| 27 | V01/M01 ×1.0 | 尺度 | 184888 | 4.081 | 1000 | 3.990 | 2.265 | 2.265 | **2** | OK |
| 28 | V01/M01 ×1.5 | 尺度 | 623997 | 6.122 | 1000 | 13.467 | 7.927 | 7.927 | **8** | OK |
| 29–31 | V01/M01 | 落高 | 184888 | 4.081 | 2000/4000/8000 | 7.98/15.96/31.92 | 3.49/5.39/8.31 | 3.49/5.39/8.31 | **3,5,8** | OK |
| 32–33 | V13/M01 | 落高 | 425691 | 11.658 | 2000/4000 | 18.375/36.749 | 5.606/8.646 | 同 | **5,8** | OK |
| 34 | V13/M01 | 落高 | 425691 | 11.658 | 8000 | — | — | — | — | **REFUSED**（gap P95 0.0859 mm > 0.02；法向 65.6° > 2°） |
| 35–37 | V01/M04 | 落高 | 184888 | 4.081 | 2000/4000/8000 | 同 M01 | 同 M01 | 同 M01 | **3,5,8** | OK |
| 38–39 | V13/M04 | 落高 | 425691 | 11.658 | 2000/4000 | 同 M01 | 同 M01 | 同 M01 | **5,8** | OK |
| 40 | V13/M04 | 落高 | 425691 | 11.658 | 8000 | — | — | — | — | **REFUSED**（同 34 行） |

（完整逐行表见 `data/a12_reports/fracture_calibration_tables.md` 的 A 节与下列 JSON 的 `rows[*]`：
`fracture_calibration_{matrix,energy,energy_V02,energy_V13,size,heights}.json`。）

**同一条件的随机性如实保留**：`V13/M01 h=500` 在两个独立种子上实测 3 片与 2 片（早期一轮），本轮
（同一条种子序列）实测 2 片；片数是**随机量**（Weibull 因子 `log_sigma = 0.18`），标定文件不做取优。

### 与计划定量预算的对照

* 冻结的 `configs/a12/next_experiment.yaml` 与 `configs/a12/sandbox.yaml` 声明
  `fracture.target_piece_range`（sandbox [8,20]、pilot [12,28]）。**实测到不了**：真实器型
  （0.6e5–6.2e5 mm³）+ 真实落高（0.1–8 m）实测片数只有 **2–8**。8–20 片需要 8 m 以上落高
  （V01×1.5 在 1 m 落高已到 8 片，8 m 落高 `n_raw` 8.3），而这正是最容易被拒绝的区间。
* `configs/a12/fracture_physics.yaml` 的 `generation_spec.fracture.target_piece_range = [2, 32]` 与实测一致；
  本轮**没有**为了凑 [8,20] 而改阈值，只是把新后端的默认声明区间写成实测可达的 [2, 32]。

---

## 2. 单调性检验

| 检验 | 结论 | 反例 |
|---|---|---|
| **受控尺度系列**（同一器型 V01、同一落高 1000 mm、线性放大 0.5/0.75/1.0/1.5 倍，体积 2.3e4→6.2e5 mm³） | **单调不减，0 反例**（实测 2 → 2 → 2 → 8 片；`N_det` 0.266 → 0.931 → 2.265 → 7.927） | 无 |
| **落高系列（同一件、能量单调）** V01/M01 100→8000 mm | **单调不减**（2,2,2,2,3,5,8 片） | 无 |
| **同器型同材料重复**（V13/M01 h=500，不同种子） | **不稳定**：3 片与 2 片都出现过 | 有：同体积同能量给 2 与 3 |
| **模型自身按体积**（38 点） | **非单调**：7 处（含"检验设计"造成的混能量比较） | 见下 |
| **实测按体积**（跨器型，同一检验口径） | **非单调**：3 处 | 见下 |
| **模型/实测按能量** | **非单调**：2 处 | 见下 |

**实测反例（不改数据、不挑数据）**：

1. **跨器型按体积**：`V01/M04 h=8000`（1.85e5 mm³，**8.31 片**）vs `V13/M01 h=500`（4.26e5 mm³，
   **2.36 片**）——**更大的器型片数更少**。
2. **按能量**：`V13/M01 h=500`（4.59 J，2.36 片）vs `V02/M01 h=4000`（5.37 J，2.00 片）——能量更高、
   器型更小的件片数更少。
3. **检验设计本身的反例**：`V01/M01 h=4000`（5.39 片）vs `V01/M01 h=1000`（2.27 片）是**同体积不同能量**；
   把它算成"尺寸单调性反例"是没有意义的，这里照实列出并标注。

**结论**：

* **尺寸单调**在**受控实验**（同一器型等比放大）上成立且强：2 → 2 → 2 → **8** 片，`N_det` 严格单调增，
  这是本轮最重要的正面证据（旧标定下 1.5 倍放大点因 §5 的几何缺陷被拒，修复后可交付）。
* **能量单调**在同一件上成立（h 100→8000：2→8 片；未触底点拟合 R² 0.8632）。
* **跨器型"大件片数 ≥ 小件片数"不成立**，反例见上第 1 条。机理：固定落高下
  `N ∝ V^(alpha - beta) = V^(-0.017)`（几乎与体积无关，略偏负）；要让"大件更多"必须
  `alpha > beta ≈ 0.59`，即 Weibull 模数 `m ≲ 4.3`（`alpha = 1/(2m)+0.5`），低于陶质文献区间 5–11。
  **本轮拒绝这种反物理调整**，反例写进 `configs/a12/fracture_calibration.json`
  （`monotonicity.all_points_in_volume` / `all_points_in_energy`）与本节。

---

## 3. 精度审计全绿证明

审计器：`synlab.fracture.fragment.audit_fracture_result`（与平面后端**共用同一个**审计器）。事件在审计
不通过时**抛 `SynLabError` 拒绝**，所以下表每个 OK 点的数值都是真实算出来并强制检查过的。

**38 个 OK 点的最差值**（由 `calibrate tables` 从原始 JSON 生成，B 节）：

| 指标 | 冻结阈值 | 38 个 OK 点最差 | 判定 |
|---|---|---|---|
| 体积相对差 `volume_rel_diff` | ≤ 1.0e-3 | **9.06e-08** | 通过（差 4 个数量级） |
| 重叠比 `overlap_ratio` | ≤ 1.0e-4 | **0.0** | 通过 |
| 两侧 gap P95 `gap_p95_mm_max` | ≤ 0.02 mm | **1.97e-05 mm** | 通过 |
| 法向反向 P95 `normal_angle_p95_deg_max` | ≤ 2.0° | **1.67e-04 °** | 通过 |
| 来源覆盖 `source_coverage` | ≥ 0.999 | **1.000000** | 通过 |
| 歧义面积比 `ambiguous_area_ratio_total` | ≤ 0.02 | **0.0** | 通过 |
| 未匹配断面面积比（**新增诚实指标**） | 无冻结阈值 | **0.0** | 记录 |
| 共轭点距离 P95 `facet_conjugacy.max_vertex_distance_mm` | ≤ 1e-9 mm（包内容差） | **0.0**（`conjugate=true`，`one_sided_facets=0`） | 通过 |
| 最近面 P95 `nearest_surface_p95_mm_max` | 无冻结阈值（辅助） | **0.2471 mm**（V13/M01 h=2000） | 记录 |
| 共轭顶点同一性最小比 `vertex_identity_ratio_min` | 无冻结阈值（辅助） | **0.000**（同上点，辅助量） | 记录 |

另外对每个 OK 点都强制检查（`tests/a12/fracture/test_calibration_audit.py::test_every_measured_row_is_either_green_or_explicitly_refused`）：

* **水密**：`watertight_pieces == pieces`（38/38 点成立）；
* **正体积**：`positive_volume_pieces == pieces`（38/38）；
* **守恒**：`piece_volume_sum_mm3 ≈ mother_volume_mm3`（相对差 ≤ 1e-3，实测最差 9.06e-08）；
* **零重叠**：`overlap_ratio = 0.0`；
* **两侧互补**：`gap_p95_mm_max ≤ 0.02 mm` 且 `normal_angle_p95_deg_max ≤ 2°`（A06）；
* **共轭点距离 P95**：`facet_conjugacy.max_vertex_distance_mm = 0.0`、`one_sided_facets = 0`；
* **未匹配面积比**：0.0。

**辅助指标为什么没有冻结阈值（如实说明）**：`nearest_surface_p95_mm` 与 `vertex_identity_ratio` 是
`interface_distance_stats` 直接量的**几何辅助量**（顶点位置逐点比对 + `trimesh.nearest.on_surface`），
包含**母体表面顶点**；A06 的 gap 量的是**接口采样点**在共面投影下的残差，两者不是同一个量
（V13/M01 h=2000：gap P95 = 1.6e-14 mm 而最近面 P95 = 0.247 mm，后者与粗糙度幅值上限 `amp_max_mm = 0.30`
同量级）。冻结预算只约束前者；本轮**没有**用辅助量替代或放宽任何阈值，建议下一步给 `nearest_p95`
一个基于幅值的阈值并纳入 A27（§5.2 第 5 条）。

**被拒绝的点（照实记录，不当作通过）**：C 节共 2 个，均为 `FRACTURE_CONSERVATION_FAIL`、
`interface gap p95 0.0859 mm > 0.02 mm; normal reversal p95 65.6° > 2.0°`（V13 在 8000 mm 落高，
M01/M04 各一次）。早一轮（本轮修复前）还有体积差 0.22–0.66 的多种拒绝，见 §5.1 的修复前后对比。

---

## 4. 耗时表：1 / 4 / 8 / 16 / 32 片（CPU、单母体）

母体 V01/M01（1.85e5 mm³、4128 面、中位壁厚 4.081 mm），单进程，`facet_refinement = fan`。
原始表：`data/a12_reports/fracture_calibration_stage_V01.json`。

| 目标片数 | 建胞数 | 建胞 s | 胞网格化 s | 布尔 s | 审计+装配 s（残差） | **事件总耗时 s** | 状态 |
|---|---|---|---|---|---|---|---|
| 1 | — | — | — | — | — | — | **ERROR**：`build_partition` 抛 `IndexError: index 1 is out of bounds for axis 0 with size 1`（`voronoi_frag.voronoi_cells` 在只有 1 个种子时邻居查询返回自身、候选集为空）。1 片不是合法输入（`min_pieces = 2`），**耗时不存在** |
| 4 | 4 | 0.357 | 0.015 | 0.060 | 0.366 | **0.798** | OK |
| 8 | 8 | 0.394 | 0.026 | 0.115 | 0.696 | **1.231** | OK |
| 16 | 16 | 0.515 | 0.062 | 0.209 | — | **0.970** | REFUSED（体积差 0.1164；时间是拒绝前的真实计算时间） |
| 32 | 32 | 0.750 | 0.117 | 0.393 | — | **1.900** | REFUSED（体积差 0.1262 + 覆盖 0.99869 < 0.999） |

**瓶颈分解**（同一次运行，按阶段实测）：

* **建胞（加权 Voronoi + 半空间裁剪）是最大且增长最快的阶段**：0.357 → 0.750 s，约线性；4 片占 45%、
  16 片占 53%、32 片占 39%（16/32 片事件总时间里有被拒绝前的部分，占比按同一次运行计算）。
* **布尔（`manifold3d` 三角交）第二**：0.060 → 0.393 s（4 片 8%、32 片 21%）。
* **审计 + 装配**（接口配对、`nearest.on_surface`、逐面来源审计、守恒/重叠/距离测量）：4 片 0.366 s、
  8 片 0.696 s——在可交付区间（4/8 片）它是**最大的一块**（46%/57%）；16/32 片因事件被拒，
  审计阶段未计入。
* **胞网格化可忽略**：0.015 → 0.117 s（<5%）。

**与平面基线对比**（同母体、同审计器、`data/a12_reports/fracture_acceptance.json`，各 8 次独立种子）：

| 后端 | 目标片数 | 运行数 | 接受率 | 中位耗时 s | 最大耗时 s |
|---|---|---|---|---|---|
| `plane_shared_cut`（基线） | 4 | 8 | **1.000** | 5.818 | 6.700 |
| `plane_shared_cut`（基线） | 6 | 8 | **1.000** | 5.306 | 5.655 |
| `warp_voronoi_cut` | 4 | 8 | **0.750** | 1.189 | 1.274 |
| `warp_voronoi_cut` | 6 | 8 | **0.875** | 1.314 | 1.510 |

即：**新后端比平面基线快 4–4.5 倍**（1.2 s vs 5.8 s，同一条审计链），代价是接受率 0.75–0.875（§5.2）。

**CUDA**：本机 torch 是 CUDA 版，但这条链路**没有任何张量算子**——建胞是 numpy 半空间裁剪、布尔是
`manifold3d` 的 C++ 标量算法、审计是 trimesh 的 CPU 最近面查询，因此**没有**现成 GPU 路径。
可加速路线（**本轮不实现**，只说明）：(a) 按胞多进程并行建胞/布尔/审计（受"重负载进程被杀"限制，
只能 2–4 进程）；(b) 用 CUDA 重写胞三角剖分与法向统计这类纯顶点算子（占比 <5%，收益很小）；
(c) 真正吃 GPU 的是**观测渲染**与物理层，不是断裂。结论：**断裂不是 GPU 瓶颈，是几何算法瓶颈**。

---

## 5. 本轮修好的问题与仍未解决项

### 5.1 修好：胞刀具不闭合 → `manifold3d` 返回空交集 → 整胞体积丢失

**症状（修复前）**：部分种子的 `warp_voronoi_cut` 事件体积差 0.22–0.66、`interface_count = 0`——
整胞材料消失；接受率只有 **31.25%**（16 次 5 次通过）。这也是修复前 2 谱系批产只接受 1 条的原因。

**根因（实测）**：`voronoi_event._displaced_cell_mesh` 的焊缝量子是 `FACET_QUANTUM_MM = 1e-9 mm`，而胞拐角
是**每个面各自做半空间裁剪**产生的，两面对同一拐角的描述相差约 1e-6 mm；同一位置留下两个顶点后，
边只被一个三角形使用，网格不闭合，`manifold3d` 对非流形操作数**返回空交集**（静默体积损失）。
实测（`_probe_cell_watertightness.py`，8 个种子 × 4 胞）：

| 焊缝容差 | 不闭合胞数 |
|---|---|
| 1e-6 mm（旧默认） | **10 / 32** |
| 1e-5 mm | 1 / 32 |
| **1e-4 mm（本轮采用）** | **0 / 32** |
| 1e-3 mm | 0 / 32 |

**修复**：`voronoi_event.py` 在网格化后按配置容差再做一次按位置合并；
`configs/a12/fracture_physics.yaml:tolerances.cell_merge_tol_mm = 1.0e-4`（比最短被审长度小三个数量级：
最短面边 > 1 mm、gap 预算 0.02 mm）。**这是本轮唯一改动的容差，方向是消除假的不闭合。**

**修复后实测（同一批扫描，全部重跑）**：

* 40 行测量里 **38 行 OK、2 行拒绝**（修复前同一批扫描里 V01×1.5、V13 h≥1000 多点被拒）；
* **受控尺度系列的 1.5 倍放大点现在可交付**（6.24e5 mm³ → 8 片，体积差 1e-8 量级）；
* V13 的 1000/2000/4000 mm 落高点从"全部拒绝"变成 **3/5/8 片全绿**；
* V02/M01 的 2/4/6/8 胞分区**全部闭合、逐点零体积损失**；
* 2 谱系批产从 1/2 接受变成 **2/2 接受**（§6）。

### 5.2 仍未解决（诚实清单）

1. **高片数区仍有不闭合的胞**：实测 V01 的 2/3/4/6/8/16 胞全闭合，**12 胞有 2 个不闭合**
   （`fracture_cell_watertightness_V01.json`）。根因在 `voronoi_frag.cell_hull_facets`：相邻胞的公共面
   由各自裁剪得到，多边形在**位移前**就可能不闭合（实测 `_facet_corner_mesh` 在位移前即 non-watertight）。
   仅加大焊缝容差治不了根；正确修法是让相邻胞的公共面用**共享平面标签裁剪成同一多边形**——属于
   `voronoi_frag` 核心几何，**本轮未改**。
2. **接受率不是 1.0**（4 片 0.75、6 片 0.875，合计 **0.8125**）。拒绝分两类：
   (a) 上述不闭合胞导致的体积差；
   (b) **接口 gap/法向超预算**（V01 4 片 seed 23：gap P95 **0.1235 mm**、法向 **105.5°**；seed 47：
   0.0520 mm / 91.3°），即少数 patch 上两侧断面不是同一张面。
   生产影响：这类谱系被判 `failed`（不进数据集），不会静默入库；本轮**没有**换种子重试或放宽阈值。
3. **跨器型"大件片数更多"不成立**（§2），定律净指数 `alpha - beta = -0.017`。
4. **`alpha` 不可分离**：未触底点只有 3 个整数片数档（3/5/8）、2 种落高系列，`alpha` 与 `beta` 互相补偿；
   要分离需要**中间尺度**的可交付事件（本轮的 1.5 倍点只给 1 个新高档）。
5. **`nearest_surface_p95` 无冻结阈值**（最差 0.247 mm，与 `amp_max_mm = 0.30` 同量级）：建议下一步
   按幅值定阈值并纳入 A27 审计。
6. **1 片不是合法输入**：`build_partition(mesh, 1)` 抛未结构化的 `IndexError`；生产路径因
   `min_pieces = 2` 不会走到，但效率扫描写 1 会崩。本轮只记录，未改 `voronoi_frag`。
7. **V13 的 8 m 落高不可交付**（gap P95 0.0859 mm / 法向 65.6°）：V13 中位壁厚 11.66 mm、含盖/裙边
   多壳结构，高能量下多壳布尔路径的失败率高于单壳 V01/V02。
8. **壁厚测量的样本敏感性（本轮新发现）**：V13 的厚度分布是强双峰（min 7.05 / median 11.66 / max 170.6 mm），
   中位壁厚随采样面数变化（全 844 面采样 = 27.2 mm，等距 400 面 = 11.7 mm），而它直接进入定律的
   `(t_ref/t)^0.5` 项。当前实现固定用 400 面等距采样（`synlab.fracture.calibration.body_stats_of`），
   同一实现下**完全可复现**（连测三次同值），但**跨实现/跨采样数不可比**。建议下一步把"壁厚统计量"
   连同采样参数一起写进事件 meta（当前 `body.provenance` 只写来源）。

---

## 6. 批产接入（`data/a12_fcal/store`）

### 配置改动（只改 `configs/a12/fracture_physics.yaml`，**未碰冻结的 `next_experiment.yaml`**）

```yaml
generation_spec.fracture.backend: warp_voronoi_cut     # 默认后端；validate 的就是它
backends:
  default: warp_voronoi_cut
  baseline: plane_shared_cut                          # 基线保留、仍注册、仍可选
  implemented: [plane_shared_cut, rough_shared_cut, secondary_fracture, warp_voronoi_cut]
```

切换方式：改生成 spec 的 `fracture.backend`（或本文件 `backends.default`）；流水线运行时只读 spec。

### 代码接线（`synlab/fracture/**`，最小改动）

* `synlab/fracture/api.py`：`fracture_event` 新增 `warp_voronoi_cut` 分支 → `_voronoi_event`
  （从真实母体测 `BodyStats`/`MaterialStats` → 读 `configs/a12/fracture_physics.yaml` →
  调 `run_voronoi_event`）。后端专属输入走 `FractureSpec.meta`
  （`physics_config_path` / `drop_height_mm` / `target_pieces`），冻结 dataclass 的字段集合未改。
* `synlab/fracture/voronoi_event.py`：仅加 §5.1 的顶点合并与 `open_cutters` 诊断（无行为阈值放宽）。
* 新增 `synlab/fracture/calibration.py`、`synlab/fracture/calibrate.py`（测量与拟合）。

### `synlab.cli validate`

```powershell
& .venv\Scripts\python.exe -m synlab.cli validate --config configs\a12\fracture_physics.yaml --json
# 退出码 0
# status OK | spec_hash sha256:255aaf15da2d8edd965db8e8884e8665cf20d0cd09a953b1ac05068228ccc03f
# expanded.fracture_backend = warp_voronoi_cut | warnings = []
```

（原始输出：`data/a12_reports/fracture_validate.json`；与用户给的事实一致——该 hash 只由
`generation_spec:` 块决定，所以**不能用它证明标定值变更**，标定值请看 `configs/a12/fracture_calibration.json`。）

### 批产实测（整条 DAG：母体 → 材料 → 纹样 → 断裂 → clean truth → 物理 → 观测 → 特征/标签/上下文）

| 运行 | 谱系 | attempted / accepted / failed | 片段 | 断裂阶段 s | 全链 s | 产物 |
|---|---|---|---|---|---|---|
| `b1`（1 谱系，清库后） | `LIN0000_V02_M01_PAT02` | **1 / 1 / 0** | 3 | 1.54 | 31.7 | 21 资产 |
| `b2`（2 谱系） | `LIN0000_V02_M01_PAT02`, `LIN0001_V02_M01_PAT01` | **2 / 2 / 0** | 3 / 2 | 1.54 / 1.52 | 96.6 | 60 资产 |

读回证明（`_run_calibration.py verify`，从 store 的资产元数据读，不靠假设）：

* `data/a12_reports/fracture_batch_b1_verify.json`：`fragment_backends = {"warp_voronoi_cut": 3}`，
  21 资产、1 谱系；
* `data/a12_reports/fracture_batch_b2_verify.json`：`fragment_backends = {"warp_voronoi_cut": 8}`，
  60 资产、2 谱系；
* `data/a12_fcal/store/reports/coverage.json`：`planned 2 / attempted 2 / accepted 2 / quarantined 0 /
  failed 0 / complete true`，`fracture_backend = warp_voronoi_cut`；
* `data/a12_fcal/store/reports/coverage_rows.json`：`backend = warp_voronoi_cut`、`fragments = 3 / 2`、
  `accepted = 1`，含真实阶段耗时（fracture 1.54 / 1.52 s、physical 21.5 / 49.2 s、observe 6.2 / 8.9 s）。

**故障率如实预告**：接受率 0.8125 意味着生产里约 1/5 谱系会因 §5.2 的几何缺陷被判
`FRACTURE_CONSERVATION_FAIL`（`failed`，不进数据集）。本轮两次批产全绿是因为 `target_pieces` 落在 4–6；
**没有**为凑绿而调阈值或重试。

---

## 7. 阈值没有被放宽

`configs/a12/fracture_physics.yaml` 的 `tolerances:` 与冻结 spec 逐项相等（gap 0.02 mm、法向 2°、
体积 1e-3、重叠 1e-4、歧义 0.02），`verify_against_spec` 在任一被**放宽**时抛 `SCHEMA_INVALID`
（唯一例外是数值合并容差 `cell_merge_tol_mm`，见 §5.1；它的方向是减少假的几何失败，且比最短被审长度
小三个数量级）。`synlab.cli validate` 退出码 0（§6）。

---

## 8. 测试

| 命令 | 退出码 | 结果 |
|---|---|---|
| `pytest tests/a12/fracture/test_count_calibration.py -q` | **0** | 8 passed（片数律、单调性、标定文件自洽、可复现拟合、阈值不放宽） |
| `pytest tests/a12/fracture/test_calibration_audit.py -q` | **0** | 13 passed（38 个实测点的 A06 逐点审计、拒绝机制、耗时表、共轭、闭合指示器） |
| `pytest tests/a12/fracture/test_voronoi_backend_contract.py -q` | **0** | 10 passed（注册表、façade 派发、A06、同种子可复现、拒绝不可修复） |
| 上述 3 个文件 + `test_impact_count.py` 一起 | **0** | 42 passed |
| `pytest tests/a12/fracture -q`（整个目录） | **1** | 本轮新增的 **31 个用例全绿**；失败/报错全部落在**本轮未触碰**的模块（`cut.py` 的 `rough_shared_cut` / `morphology_shared_cut` 路径：`CUTTER_NOT_CLOSED`「37285/12125/8993… 条边非 2 面」、`PRECISION_NOT_REALIZED`「0.010323 mm > 0.01 mm」），与 `docs/a12/fracture_fix_evidence.md` 未解决项 1/2 是同一批真实失败；本轮**未**改这些模块、**未**放宽预算 |

原始日志：`data/a12_reports/_fcal_pytest_{count,audit,voronoi2,scope2,fracture}.log`。
