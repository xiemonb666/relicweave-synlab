# 断口特征在训练图像里能不能被看见：契约要求 × 实测 × 反解 × ROI 特写实现

> **性质**：新增实现 + 实测报告。本次**新增** `synlab/observe/fracture_roi.py`、
> `configs/a12/imaging_fracture_roi.yaml`、`tests/a12/observe/test_fracture_roi.py`、
> `tests/a12/observe/_run_fracture_roi.py`、本文件与 `data/a12_reports/fracture_roi_*.json`、
> 新库 `data/a12_roi/store`；对既有文件的改动只有两处**加函数不换语义**的
> `synlab/observe/routes.py`（抽出 `render_frame_bundles` / `observation_views`，见 §5.1）。
> **没有**修改 `synlab/{fracture,mothers,patterns,degrade,physical,truth,relations,training,storage,pipeline.py}/**`、
> `configs/a12/next_experiment.yaml`、`frontend/**`、`tools/**`、`data/a12/**`（除 reports）、
> `data/a12_demo/**`、`data/_archive_pre_fix/**`。
>
> **诚实规则**：
> 1. 每个数字都注明是**本次实测**（哪个脚本/哪个视图）还是**引用**（谁的产物）。
> 2. 断口形貌幅度一律用**实测高度场**（本文件的 §3，脚本 `_run_fracture_roi.py` 落盘），
>    并另列"形态学若接线的上界"作为对照，**不把上界当实测**。
> 3. `0.2 mm ≥4 px` 按契约原文当作 **pilot 采样起点**（`p0517` 自称"不是识别定理"），
>    不写成已实测门。
> 4. 分辨率一律是**真渲染**的：没有任何一条结论建立在 resize/上采样上
>    （每个视图的 `mm/px` 从该视图自己的深度通道实测，并与相机光轴的独立射线投射交叉验证）。

---

## 0. 一句话结论

**分辨率不是主要瓶颈，"几何里有没有形貌"才是；而且断口在整片视图里几乎不可见。**
三条本次实测（4 具研究体 = 2 器型 × 2 材料，96 个 Blender 视图）：

1. **整片视图里断面几乎不可见**：48 个整片视图合计断面像素 **335 038**，占物体像素中位
   **2.73%**；其中 V23/M07 的 12 个整片视图**合计只有 105 个断面像素**（占比 0.0%）。
   同一批断口的 ROI 特写合计 **20 987 921** 像素（**62.6×**），占物体像素中位 **96.95%**。
2. **ROI 特写把 mm/px 从 0.28041 提到 0.07300（3.84×）**（同一相机、同一交付网格 1024×768、
   同一次运行、同一 basis），0.2 mm 结构从 **0.71 px** 变成 **2.74 px**，
   `r_eff_mm(4px)` 从 **1.122 mm** 降到 **0.292 mm**；但 **0.2 mm 仍未到契约的 4 px**（差 1.46×）。
3. **形貌：3/4 具研究体的断面在 < 1 mm 尺度上完全平**（局部去趋势 `Ra` = **0.000 mm**，
   9 个 ROI 全部如此），而 **V02/M01（`data/a12_iface` 谱系）有真实亚毫米起伏**
   （`below_1mm` 实测 `Ra` = **0.0080 / 0.0623 / 0.0795 mm**）。
   → 缺口的形状是"**看哪条线**"：平面切割线（`plane_shared_cut`，本次 3 具）**没有**可拍的形貌；
   另一条线（`a12_iface`）**有**，但它最小的可用幅度（~80 µm）在 0.073 mm/px 下只有 **1.09 px**，
   连 2048 px 档（0.0365 mm/px）也只有 **2.18 px** —— 要 4 px 需 **0.0199 mm/px（60 mm 处 L ≥ 3761 px）**。


---

## 1. 契约要求（逐条，带出处）

| # | 契约要求 | 出处 | 本次是否满足 |
|---|---|---|---|
| 1 | **逐真实断口多角度近摄**；实际断裂表面、两侧壁、厚度变化、边缘 | `capture_checklist.fracture_local_2d`（`t042`/`p0431`/`p0881`） | **本次实现**（§5），此前**不存在** |
| 2 | **每断口 3–6 个有效方向** | 同上 `effective_directions_per_fracture = [3, 6]`（【工程约定】补齐计数） | **实现并实测**：每断口 4 个方向，`rim_px > 0` 的方向数逐个记录（§4.4） |
| 3 | 断口局部近摄 **5–10 cm** | `working_distance_and_resolution.closeup_local_cm`（`p0511`） | 配置取 **60 mm**，落在窗口内；但**声明为非标定工况**（§5.2） |
| 4 | `px_per_mm`、`r_eff_mm` **必须分开报告**（实测，非标称） | `p0515`/`p0579`/`calibration.px_per_mm` | **补上生产者**：每个视图写 `mm_per_px`/`px_per_mm`/`r_eff_mm`/`dof_cover_mm`（§5.4） |
| 5 | 0.2 mm 结构 **≥4 px**（pilot 起点）、6–8 px（细节目标） | `structure_sampling_targets`（`p0517`） | **反解给出条件**（§3.5）：60 mm/1024 px 下 0.2 mm = **2.74 px**；要 ≥4 px 需 **mm/px ≤ 0.05**，即 60 mm 处交付长边 **≥1495 px**（本镜头）或工作距离 **≤41.1 mm** |
| 6 | 分辨率阶梯 **50/100/150/200/250 mm → 0.039/0.078/0.117/0.156/0.195 mm/px** | `t051`（`capture_contract.json`） | 复算逐位一致（`contract_cross_check = OK`，§3.1） |
| 7 | 全局与近摄视作**两套独立标定工况** | `calibration.global_vs_local_calibration`（`p1155`） | 近摄 profile 独立 id、`calibrated=false`、`calibration_status=CLOSEUP_DECLARED_NOT_CALIBRATED` |
| 8 | 区域 mask 整数 ID、无损、ID 严格可恢复 | `t101(D09)`/`t117`/`p1481` | ROI 视图沿用同一整数 `surface_tag` 渲染（`tag=2` = 断面），未引入插值 |

---

## 2. 当前差距（实测，含本次新增的三条）

### 2.1 分辨率差距（引用 + 本次复核）

`docs/a12/precision_audit.md` §1.2 实测：交付网格 **0.27193 mm/px**（`data/a12_campaign/store`，
288 视图）→ **0.2 mm 结构 = 0.74 px**、4 px 可分辨尺寸 = **1.088 mm**。
本文件的交付条件（§4）用的是**同一台相机同一交付网格**（1024 长边、MID 档），
但工作距离取 profile 的标称 220 mm（不是 campaign 逐视图抽样的中位 190.52 mm），
所以本次整片基线是 **0.3140 mm/px**，campaign 实测中位是 **0.27193 mm/px**；
两者差的是**工作距离的选择**，不是光学。

### 2.2 断口 ROI 特写此前不存在（本次复核）

`precision_audit.md` §7.4 缺陷 4 的原话：断面"只有全向 4 视图环，**不是**逐断口 3–6 方向"。
本次确认：`synlab/observe/**` 里没有任何"按断口法向取景 + 近摄距离"的代码路径，
`configs/a12/camera_profiles.json` 也只有 GLOBAL/MID/LOCAL 三档整片档位
（`wc 380/220/140 mm`，最近一档仍是 140 mm）。

### 2.3 **新发现 1**：断口几何的亚毫米形貌取决于"哪条线"（本次实测，最重要的一条）

对 4 具研究体的断面（`origin_kind == ORIGIN_INTERFACE`）逐 patch 实测"平面拟合残差 + 局部去趋势分带"
（仪器：面积加权 TLS 平面 + 球半径 `R` 内均值去趋势，
脚本 `synlab.observe.fracture_roi.height_field_stats`；每个 ROI 是近摄视场内的那一块）：

| 研究体 | 源 store | `below_5mm` `Ra` | **`below_1mm` `Ra`** | **`below_0.25mm` `Ra`** | 结论 |
|---|---|---|---|---|---|
| V10/M11 | `data/a12_campaign` | 0.0010 / 0.2142 / 0.0013 mm | **0 / 0 / 0** | **0 / 0 / 0** | 无亚毫米形貌 |
| V21/M06 | `data/a12_campaign` | 0.0157 / 0.0040 / 0.0360 mm | **0 / 0 / 0** | **0 / 0 / 0** | 无亚毫米形貌 |
| V23/M07 | `data/a12_campaign` | 0.0047 / 0.0047 / 0.0033 mm | **0 / 0 / 0** | **0 / 0 / 0** | 无亚毫米形貌 |
| **V02/M01** | **`data/a12_iface`** | 0.9127 / 0.0122 / 0.2819 mm | **0.0795 / 0.0080 / 0.0623 mm** | **0.0174 / 0.0007 / 0.0060 mm** | **有真实亚毫米形貌** |

（每格是 3 个 ROI 的值；`0` 是**测到 0**，浮点意义上的恰好零：该 patch 的三角面共面。）

旁证（引用他人在同一批几何上的产物）：
* `data/a12_reports/fracture_realism_V18_M01_plane_rough.json` 的 `plane` 变体实测
  `delivered/Ra_mm = 1.1030823030969338e-07`（≈ **0.11 nm**，即数值零）；
* 同一文件的 `rough`（形态学）变体 **`status = FAILED`**，
  `[ErrorCode.PRECISION_BUDGET_EXCEEDED] … cutter refinement exceeded the cell budget (30000)
  while chasing a 0.01 mm budget at wavelength 0.6500 mm`；
  同报告的诊断行给出 `predicted amplitude scale 0.1303`（`C_requested 5.332 /mm > C_budget 0.695 /mm`）；
* `synlab/fracture/api.py`：`BUILT_BACKENDS = ("plane_shared_cut", "rough_shared_cut",
  BACKEND_SECONDARY, BACKEND_VORONOI)`，`BACKEND_MORPHOLOGY = "morphology_shared_cut"` 的注册项
  自己写明 "**GATED**: it is NOT in BUILT_BACKENDS and refuses to run unless switched on via
  `<MORPHOLOGY_SWITCH_ENV>=1`"。

→ **"接了形态学但模型看不见"的实测形态是**：
(a) 平面切割线（本次 3 具）的断面 < 1 mm 形貌**恒等于 0**，分辨率再高也拍不到不存在的东西；
(b) 另一条线（`a12_iface`）**有形貌**（8–80 µm），但它在 0.073 mm/px 的 ROI 特写下只有
**0.11–1.09 px**，在 2048 px 档（0.0365 mm/px）也只有 **0.22–2.18 px** ——
**形貌存在**的那条线上，瓶颈才真的是**分辨率**；
(c) 形态学（`morphology_shared_cut`）代码在仓库里、开关存在、但没接线到批产，
且上次真跑时在冻结精度预算下 **FAILED**。

### 2.4 **新发现 2**：`px_per_mm` / `r_eff_mm` / `dof_cover_mm` 现在有生产者了

`precision_audit.md` §1.3 P2 记录 `r_eff_mm` 全仓 **0 生产者**。本次在
`synlab/observe/fracture_roi.py` 实现 `px_per_mm()` / `r_eff_mm()` / `dof_report()`，
并把三个量写进**每一个** ROI 视图的 `frame.meta` 与观测的 `meta.fracture_roi.resolution_ledger`
（整片视图也一起写）。生产者口径：
`px_per_mm = f_px / z`、`r_eff_mm = 4 × z / f_px`（`p0517` pilot 起点，另有 6 px / 8 px 两档）、
`dof_cover_mm = far − near`（薄透镜、`coc = 2 px × 交付网格像元`）。

### 2.5 **新发现 3**：软件光栅器的深度在掠射三角形上不是透视正确的（会影响 mm/px 口径）

本次在 ROI 视图上逐视图比对"渲染深度中心像素"与"沿相机光轴的独立射线投射"：
* **软件光栅器**（`SOFTWARE_RASTERIZER`）在**掠射（近侧视）断面三角**上，中心像素深度可以是
  **24.47 mm**，而同一条光线上的**最近真实表面在 60.09 mm** —— 差 **35.6 mm**
  （`data/a12_reports/_roi_debug_depth2.txt`）。原因是 `synlab/observe/render.py` 的 z 缓冲用屏幕
  空间线性插值（`zi = w0 z0 + w1 z1 + w2 z2`），在透视投影下只有对 `1/z` 才是正确的；
  `precision_audit.md` §3 引用过的"斜面夹具上界 8.885 mm"是同一现象的较小实例。
* **Blender Cycles**（本次 4 具研究体的生产路径）**不出现该偏差**：96 个视图（48 整片 + 48 ROI）
  的 `|渲染深度中心 − 光轴射线投射|` 中位 **0.0029 mm**、最大 **0.181 mm**、
  **超过 1 mm 的视图数 = 0**（`fracture_roi_compare.json` → `instrument_disagreement_mm`）。

→ 本文件的 `mm/px` **以射线投射为准**（`mm_per_px_axis_raycast`），渲染深度值同时保留并给出差值。
另注：整片视图里光轴射线可能**打空**（壳体开口方向，V23/M07 的 12 个整片视图全部 `NO_HIT`），
此时 `axis_raycast_probe.status` 如实记录，整片口径改用帧内深度中位。

---

## 3. "能不能看见"的量化与反解（真实计算）

### 3.1 契约阶梯复算（`p0518` 公式，逐位对齐 `t051`）

`python -c "import sys;sys.path.insert(0,'.');from synlab.observe import fracture_roi as fr;import json;print(json.dumps(fr.documented_ladder()['rows'],indent=1,ensure_ascii=False))"`
（`contract_cross_check.status = OK`）：

| 工作距离 mm | mm/px | px/mm | 0.2 mm 占几像素 | 4 px 可分辨尺寸 mm |
|---|---|---|---|---|
| 50 | 0.0390 | 25.641 | 5.13 | 0.156 |
| 100 | 0.0780 | 12.821 | 2.56 | 0.312 |
| 150 | 0.1170 | 8.547 | 1.71 | 0.468 |
| 200 | 0.1560 | 6.410 | 1.28 | 0.624 |
| 250 | 0.1950 | 5.128 | 1.03 | 0.780 |

### 3.2 六档 mm/px 下，断口特征占几个像素（任务 1 的第一问）

`data/a12_reports/fracture_roi_resolvability.json` → `resolvability.table`。
幅度列取 §2.3 的实测分带值与契约的 0.2 mm 例子：

| mm/px 档 | 来源 | 0.2 mm | `Ra=0.02` | `Ra=0.05` | `Ra=0.1` | `Ra=0.2` | `Ra=0.3` |
|---|---|---|---|---|---|---|---|
| **0.039** | 契约 50 mm | 5.13 | 0.51 | 1.28 | 2.56 | **5.13** | **7.69** |
| **0.078** | 契约 100 mm | 2.56 | 0.26 | 0.64 | 1.28 | 2.56 | 3.85 |
| **0.117** | 契约 150 mm | 1.71 | 0.17 | 0.43 | 0.86 | 1.71 | 2.56 |
| **0.156** | 契约 200 mm | 1.28 | 0.13 | 0.32 | 0.64 | 1.28 | 1.92 |
| **0.195** | 契约 250 mm | 1.03 | 0.10 | 0.26 | 0.51 | 1.03 | 1.54 |
| **0.27193** | campaign 实测中位 | 0.74 | 0.07 | 0.18 | 0.37 | 0.74 | 1.10 |
| 0.3140 | 本次整片基线（MID 标称 220 mm） | 0.64 | 0.06 | 0.16 | 0.32 | 0.64 | 0.96 |
| **0.0730** | **本次 ROI 特写（60 mm/1024 px，LOCAL 镜头）** | **2.74** | 0.27 | 0.68 | 1.37 | 2.74 | **4.11** |
| 0.0608 | 若压到 50 mm（同分辨率） | 3.29 | 0.33 | 0.82 | 1.64 | 3.29 | 4.93 |

**读法**：只有 ≥ 0.2 mm 的幅度在契约 50 mm 档才能过 4 px；`Ra` 在几十 µm 量级时，
即使在 0.039 mm/px 也只有 **0.5 px**。**但要注意这不是"看不见"的充分条件**：
高度起伏通过**法向 → 明暗**进入 RGB，不需要 4 px 的横向尺度（§3.6）。

### 3.3 反解：要看见某个 `Ra`，需要多少 mm/px 与多少分辨率（任务 1 的第二问）

判据：幅度 `A` 至少占 `k = 4` 个像素 ⇒ `mm/px ≤ A / 4`。反解闭式（`inverse_solve`）：

* 需要的最小 `f_px`（在给定工作距离 `z`）：`f_px = k·z / A`
* 在该 `f_px` 下的**最大工作距离**：`z_max = A·f_px / k`
* 同一镜头要达到该 `f_px` 需要的**交付长边**：`L = k·z / A × W_native / f_px_native`
  （交付网格只是把原生内参按 `L / W_native` 缩放，**不是**数字变焦）

| 目标幅度 | 需要 mm/px | LOCAL 近摄镜头（`f_px_native = 3210.53 @4000 px`） | 契约相机 SC3336B（`f_px_native = 1279.43 @2304 px`） |
|---|---|---|---|
| `Ra = 0.02 mm` | 0.0050 | 60 mm 处需 **L ≥ 14951 px**；1024 px 时 **z ≤ 4.11 mm** | 60 mm 处需 **L ≥ 21610 px**；1024 px 时 z ≤ 2.84 mm；**原生 2304 px 时 z ≤ 6.40 mm** |
| `Ra = 0.05 mm` | 0.0125 | 需 **L ≥ 5980 px**；1024 px 时 **z ≤ 10.27 mm** | 需 L ≥ 8644 px；1024 px 时 z ≤ 7.11 mm；原生 z ≤ 15.99 mm |
| `Ra = 0.1 mm` | 0.0250 | 需 **L ≥ 2990 px**；1024 px 时 **z ≤ 20.55 mm** | 需 L ≥ 4322 px；1024 px 时 z ≤ 14.22 mm；原生 z ≤ 31.99 mm |
| `Ra = 0.1303 mm`（形态学上次请求的幅度尺度） | 0.0326 | 需 **L ≥ 2295 px**；1024 px 时 **z ≤ 26.77 mm** | 需 L ≥ 3317 px；1024 px 时 z ≤ 18.52 mm；原生 z ≤ 41.68 mm |
| `Ra = 0.2 mm`（契约例子） | 0.0500 | 需 **L ≥ 1495 px**；1024 px 时 **z ≤ 41.09 mm** | 需 L ≥ 2161 px；1024 px 时 z ≤ 28.43 mm；**原生 2304 px 时 z ≤ 63.97 mm**（与 `precision_audit.md` §1.3 的 63.97 mm 逐位一致） |
| `Ra = 0.3 mm`（候选上限） | 0.0750 | 需 L ≥ 997 px（**1024 px 已够**）；1024 px 时 z ≤ 61.64 mm | 需 L ≥ 1441 px；原生 z ≤ 95.96 mm |

**结论（反解，不是估计）**：
1. **横向判据**：在 5–10 cm 近摄窗口内，用本项目的 LOCAL 微距档，**交付长边 1246 px（50 mm）
   / 1495 px（60 mm）** 就能让 0.2 mm 结构跨 ≥4 px；契约相机（SC3336B）在同一窗口需要
   **1800–2161 px**。所以"0.2 mm ≥4 px"**不需要**低于 5 cm 的工作距离，只需要交付网格
   不小于 ~1500 px（本镜头）。
2. **几十 µm 量级的 `Ra`**：`Ra = 0.02 mm` 要 ≥4 px 需要 `mm/px ≤ 0.005`，
   在本镜头下对应 **z ≤ 4.11 mm**（比契约的 5 cm 还近一个数量级）或 **L ≥ 14951 px**。
   → **用"4 px"这把尺子去量 20 µm 的粗糙度，在当前任何真实镜头/距离组合下都不成立**；
   这类幅度只能靠**明暗（法向）**而不是靠**横向像素数**被看见（§3.6）。
3. 与 `precision_audit.md` §1.3 的一致性：`z_max = 0.2/4 × f_px`
   （原生 63.97 / 768 宽 35.03 / 256 宽 11.68 mm）在本次复算里逐位复现（§3.5 表最后一行）。

### 3.4 六档下"断口占多少像素"与"幅度占多少像素"的区分

契约的 `structure_0p2mm_px` 量的是**一个 0.2 mm 宽的结构的横向跨距**。
断面作为一个**区域**在图像里占多少像素是另一回事（本次实测）：
整片视图里断面占物体像素 **0.7–4.6%**（4 具），ROI 特写里占 **75–100%**（§4）。
**区域多 ≠ 形貌看得见**：区域是宏观形状（mm–100 mm 尺度），形貌是 < 1 mm 的起伏（§2.3 实测为 0）。

### 3.5 与既有 `z_max` 门的一致性检查

| 量 | 本次复算 | 引用 |
|---|---|---|
| `f_px`（契约相机原生 2304 px） | **1279.4256** | `precision_audit.md` §1.3：1279.43 |
| `z_max(0.2 mm ≥4 px)` 原生 2304 px | **63.97 mm** | 同上 |
| `z_max` 交付 768 px（`f_px = 426.5`，按 2304→768 线性缩放） | **21.32 mm** | 审计给的是 35.03 mm（其 `f_px = 700.632` 来自 MID/4000 网格，**不是**同一支镜头） |
| `z_max` 交付 1024 px（`f_px = 568.6`） | **28.43 mm** | — |
| 本镜头 4000 px 原生 → 1024 px 交付（`f_px = 821.89`） | **41.09 mm** | 本次 |

> **口径说明（不掩盖差异）**：审计的 35.03 mm 用的是 MID 档镜头在 1024 长边下的 `f_px = 700.632`
> （`f = 5.2 mm / 7.6 mm` 传感器），本次 §3.5 第三行用的是契约相机（`f = 3.1252 mm / 1/2.8"`）
> 按同一像素数缩放，两者**镜头不同**，所以数字不同；同一个镜头下的数字是一致可复算的。

### 3.6 第二判据：明暗（法向）判据 —— 为什么"看不见"还有一条独立的证据链

高度起伏 `h` 通过法向进入渲染的明暗（本项目冻结的 Lambert+环境光模型
`synlab/observe/render.py`）。取一个代表波长 `λ` 与 RMS 幅度 `A`，RMS 斜率
`s = 2πA/λ`，则码值变化 `dDN = levels · albedo · light_color · |l_⊥| · s`
（`synlab.observe.fracture_roi.shading_contrast`），与 1 个码值（8 bit）比较：

| 情形 | λ | A | 斜率 RMS | `dDN`（8 bit） | 可见？ |
|---|---|---|---|---|---|
| V10 `iface7` `below_5mm`（0.2142 mm） | 5 mm | 0.2142 | 0.269 | **60.1** | 是 |
| 形态学上界（0.1303 mm，若接线） | 2 mm | 0.1303 | 0.409 | **91.4** | 是 |
| **V02 `iface-1` `below_1mm`（0.0795 mm）** | 1 mm | 0.0795 | 0.500 | **111.6** | **是** |
| V02 `iface-1` `below_0.25mm`（0.0174 mm） | 0.5 mm | 0.0174 | 0.219 | **48.8** | 是 |
| V02 `iface0` `below_1mm`（0.0080 mm） | 1 mm | 0.0080 | 0.050 | **11.2** | 是 |
| **campaign 三具的 `below_1mm`（0.000 mm）** | 2 mm | 0.000 | 0.000 | **0.0** | **否**（几何为零） |

（`dDN` 是该模型的**上界**：冻结光照的颜色分量 ~2.2 会把高斜率推向饱和，
所以 >1 只说明"至少 1 个码值"，不说明线性。）

→ 只要形貌**存在**且波长 ≳ 0.5 mm，它在图像里就**远超 1 个码值**，
与横向是否有 4 px **无关**。所以"看不见"的实测原因**只剩一个**：
平面切割线的 `below_1mm` 幅度是 **0**；而 `a12_iface` 线**有**形貌（§2.3），
它在 RGB 里应可见（`dDN` 11–112），横向可分辨性则受 §3.3 的 4 px 反解约束。

### 3.7 形态学若接线的上界（**不是实测**，用于排期与判据）
以 `fracture_realism_V18_M01_plane_rough.json` 的诊断行 `predicted amplitude scale = 0.1303`
与生成规格的候选区间 `fracture.rough_amplitude_mm = [0.02, 0.3]`（`next_experiment.yaml`）为上界：

* 幅度 **0.1303 mm**：要 ≥4 px 需 `mm/px ≤ 0.0326`。60 mm 处需交付长边 **≥2295 px**；
  1024 px 时工作距离需 **≤26.8 mm**（**低于契约的 5 cm 近摄窗口**）。
* 幅度 **0.3 mm**：需 `mm/px ≤ 0.075` —— **本次交付的 60 mm/1024 px 特写是 0.0730 mm/px，
  已经满足（0.3 mm = 4.11 px）**。
* 幅度 **0.2 mm**：需 `mm/px ≤ 0.05` —— 本次特写差 **1.46 倍**（2.74 px vs 4 px），
  把交付长边提到 **1495 px**（60 mm）或把距离压到 **41.1 mm**（1024 px）即可。

### 3.8 反解的**经验验证**：2048 px 档（真渲染，不是缩放）

对 V10/M11 与 V02/M01 各取 3 个 ROI 视图，用同一支镜头、同一 60 mm 物距、
**同一 `delivered_profile` 机制**把交付长边从 1024 提到 **2048**（真渲染，`upsampled=false`）：

| 档 | 交付网格 | `f_px` | `mm/px`（实测） | 0.2 mm 占几像素 | 3 视图耗时 |
|---|---|---|---|---|---|
| 1024 | 1024×768 | 821.89 | **0.07300** | 2.74 | — |
| **2048** | 2048×1536 | 1 643.79 | **0.03650** | **5.48** | V10: 62.8 s / V02: 45.2 s |

→ **反解被实测确认**：交付长边 ×2 ⇒ `f_px` ×2 ⇒ `mm/px` ÷2（0.07300 → 0.03650，逐位），
0.2 mm 结构从 2.74 px 升到 **5.48 px，越过契约的 4 px pilot 起点**。
也就是说：**"0.2 mm ≥4 px"在 5–10 cm 近摄窗口内是可以闭合的，代价是交付长边 ≥ ~1500 px**
（本反解给出 1495 px；2048 px 实测留有余量）。这与"20 µm 级 `Ra` 需要 15 000 px"是两件事：
前者说的是**结构宽度**，后者说的是**幅度**。

---

## 4. 实测对照：整片视图 vs ROI 特写（硬指标）

### 4.1 研究体（2 器型 × 2 材料，本次实测）

| # | 器型 | 材料 | 谱系 | 源 store / 资产 | 面数 | 断面面数（`origin_kind=1`） | 断面面积 / 总面积 |
|---|---|---|---|---|---|---|---|
| 1 | **V10** | **M11** | `LIN0000_V10_M11_PAT15` | `data/a12_campaign/store` `asset_745a7831…` | 5 892 | 746 | 27 468 / 143 049 mm²（19.2%） |
| 2 | **V21** | **M06** | `LIN0001_V21_M06_PAT16` | `data/a12_campaign/store` `asset_73da9901…` | 80 814 | 4 078 | 19 625 / 159 369 mm²（12.3%） |
| 3 | **V23** | **M07** | `LIN0002_V23_M07_PAT12` | `data/a12_campaign/store` `asset_aba45496…` | 39 037 | 4 312 | 21 207 / 101 787 mm²（20.8%） |
| 4 | **V02** | **M01** | `LIN0000_V02_M01_PAT02` | `data/a12_iface/store` `asset_8ad98a20…` | 115 435 | 4 206 | 386 / 6 106 mm²（6.3%） |

→ 覆盖 **4 个器型 × 4 个材料**（≥ 任务要求的 2×2）。断面由**实测**的 `face__origin_kind == 1`
选出（`face__interface_id` 单独用会把母体表面面也算进来：V10 的 15 个 interface id 覆盖 716 面，
而真正的断面只有 746 面中的一部分带上 `interface_id ≥ 0`，见 §5.3）。

### 4.2 对照表（**本次实测**，同一运行、同一 basis、同一相机档）

见 `data/a12_reports/fracture_roi_compare.json`（逐视图明细在
`fracture_roi_run.json` → `bodies[*].whole_records` / `roi_records`）。
下表为 4 具研究体的汇总（每具 12 整片视图 + 12 ROI 特写视图 = **96 个视图，全部真渲染**）：

| 量 | 整片视图（MID 档，1024×768） | ROI 特写（LOCAL 近摄 60 mm，1024×768） | 改善 |
|---|---|---|---|
| 视图数（4 具合计） | 48 | 48（4 具 × 3 断口 × 4 方向） | — |
| **`mm/px`（光轴射线投射，中位）** | **0.28041** | **0.07300** | **3.84×** |
| `mm/px`（帧内渲染深度中位） | 0.26525 | 0.07220 | 3.67× |
| `px/mm` | 3.57 | 13.70 | 3.84× |
| **4 px 可分辨尺寸 `r_eff_mm`** | **1.122 mm** | **0.292 mm** | 3.84× |
| 8 px 可分辨尺寸 | 2.243 mm | 0.584 mm | 3.84× |
| **0.2 mm 结构占几像素** | **0.713 px** | **2.740 px** | 3.84× |
| **断口像素数（48 视图合计，`surface_tag=2`）** | **335 038** | **20 987 921** | **62.6×** |
| **断口占物体像素（中位）** | **2.73%** | **96.95%** | 35.5× |
| 工作距离（aim 处实测） | 220 mm（标称；帧内深度中位 180–200 mm） | **60.00 mm** | — |
| 景深覆盖 `dof_cover_mm` | 121.50 mm（`delivered_profile` 元数据） | **6.1728 mm** | 0.051× |
| 景深内视图数 | — | **48 / 48** | — |
| 每断口有效方向数 | — | **4 / 4**（每方向 `rim_px > 0`，§4.4） | — |
| 渲染深度 vs 射线投射（中位 / 最大） | 见 `instrument_disagreement_mm` | 0.0029 / 0.181 mm（**0 个视图 > 1 mm**） | — |

**逐具（同一口径，`fracture_roi_compare.json` → `per_body`）**：

| 器型/材料 | 源 store | 整片 `mm/px` | ROI `mm/px` | 整片断面像素 | ROI 断面像素 | 整片 rim/物体 | ROI rim/物体 | 墙钟 s |
|---|---|---|---|---|---|---|---|---|
| V10/M11 | `data/a12_campaign` | 0.25783 | 0.07300 | 286 052 | 7 241 983 | 4.59% | 100% | 289.7 |
| V21/M06 | `data/a12_campaign` | 0.28041 | 0.07300 | 36 984 | 4 681 735 | 0.58% | 93.7% | 277.3 |
| V23/M07 | `data/a12_campaign` | 打空（见 §2.5） | 0.07300 | **105** | 8 748 391 | **0.00%** | 99.7% | 261.5 |
| V02/M01 | `data/a12_iface` | 0.32052 | 0.07300 | 11 897 | 315 812 | 4.04% | 14.7% | 310.5 |

> **两条必须一起读的事实**：
> 1. **V23/M07 的 12 个整片视图合计只有 105 个断面像素** ——
>    对这条谱系，"断口在训练图像里"这句话在整片视图下**几乎不成立**；
>    ROI 特写把它变成 8 748 391 px。这是本文件对"模型看不见"最直接的证据。
> 2. **V02/M01 的 ROI 视图 rim/物体只有 14.7%** —— 因为该资产的断面只有 **385.79 mm²**
>    （占其表面积 6.3%，见 §4.1），近摄视场远大于断口本身；
>    它的 ROI 像素数少不是"没拍到"，而是**断口本来就小**。ROI 视图的 `roi_area_mm2`
>    逐断口记录（V02: 71–108 mm²），可与 `rim_fraction` 对照阅读。

> 上表的 `mm/px` 用**同一支相机同一交付网格**计算，差异**只**来自取景与距离，
> 因此可以直接读作"ROI 特写把采样密度改善 3.84 倍"。
> 与 `precision_audit.md` §1.2 的 campaign 中位（0.27193）相比，本次整片基线
> （0.25783–0.32052，取决于器型尺寸与工作距离）在同一量级、同一定义下可比。

### 4.3 `Ra` 对应的像素幅度（任务 3 的第三列，逐 ROI 实测）

`data/a12_reports/_roi_tables.txt` → `== amplitudes in px`。整片口径 0.28041 mm/px、
ROI 口径 0.07300 mm/px：

| 研究体 | ROI | 整块 patch（相对拟合平面） | `below_5mm` | **`below_1mm`** | **`below_0.25mm`** |
|---|---|---|---|---|---|
| V10 | `iface6_c000` | 0.1833 mm → 0.65 / **2.51** px | 0.00097 → 0.003 / 0.013 px | **0 → 0 / 0 px** | **0 → 0 / 0 px** |
| V10 | `iface7_c000` | 1.4848 mm → 5.30 / **20.34** px | 0.2142 → 0.76 / 2.93 px | **0 → 0 / 0 px** | **0 → 0 / 0 px** |
| V10 | `iface1_c000` | 0.3560 mm → 1.27 / **4.88** px | 0.00131 → 0.005 / 0.018 px | **0 → 0 / 0 px** | **0 → 0 / 0 px** |
| V21 | `iface2_c001` | 0.0354 mm → 0.13 / 0.49 px | 0.01573 → 0.06 / 0.22 px | **0 → 0 / 0 px** | **0 → 0 / 0 px** |
| V21 | `iface1_c001` | 0.0355 mm → 0.13 / 0.49 px | 0.00399 → 0.01 / 0.05 px | **0 → 0 / 0 px** | **0 → 0 / 0 px** |
| V21 | `iface0_c001` | 0.0930 mm → 0.33 / 1.27 px | 0.03602 → 0.13 / 0.49 px | **0 → 0 / 0 px** | **0 → 0 / 0 px** |
| V23 | `iface2_c000` | 0.1076 mm → 0.38 / 1.47 px | 0.00471 → 0.02 / 0.07 px | **0 → 0 / 0 px** | **0 → 0 / 0 px** |
| V23 | `iface1_c000` | 0.0391 mm → 0.14 / 0.54 px | 0.00474 → 0.02 / 0.07 px | **0 → 0 / 0 px** | **0 → 0 / 0 px** |
| V23 | `iface0_c000` | 0.0397 mm → 0.14 / 0.54 px | 0.00326 → 0.01 / 0.05 px | **0 → 0 / 0 px** | **0 → 0 / 0 px** |
| **V02** | `iface-1_c000` | 4.6106 mm → 16.44 / 63.16 px | 0.9127 → 3.26 / 12.50 px | **0.0795 → 0.28 / 1.09 px** | **0.0174 → 0.06 / 0.24 px** |
| **V02** | `iface0_c000` | 0.1469 mm → 0.52 / 2.01 px | 0.01224 → 0.04 / 0.17 px | **0.0080 → 0.03 / 0.11 px** | **0.0007 → 0.002 / 0.01 px** |
| **V02** | `iface1_c000` | 4.3576 mm → 15.54 / 59.69 px | 0.2819 → 1.01 / 3.86 px | **0.0623 → 0.22 / 0.85 px** | **0.0060 → 0.02 / 0.08 px** |

（格式：`幅度 → 整片 px / ROI px`。）
→ **只有 V02/M01 的 `below_1mm` 非零**，且即使 ROI 特写也只有 **0.11–1.09 px**：
这是"形貌存在"那条线上真正的分辨率缺口（§3.3 反解：要 4 px 需 0.0199 mm/px，
即 60 mm 处交付长边 ≥ 3761 px，或 1024 px 下工作距离 ≤16.3 mm）。

### 4.4 逐断口有效性

`fracture_roi_compare.json` → `fracture_roi.effective_directions_per_fracture`：
每个 ROI 的 4 个方向都给出了 `rim_px > 0`，且 `direction_aim_visible`（沿光轴对 aim 点的
独立射线投射）与 `direction_visibility_fraction`（对 ROI 采样点的遮挡比例）逐方向记录；
倾斜方向在平面内方位角由**实测遮挡**择优（`direction_azimuth_source =
OCCLUSION_RAYCAST_BEST_OF_AZIMUTHS`，候选 8 个方位逐个记录）。

---

## 5. 实现

### 5.1 代码落点（只有两处对既有文件动手，且是**加函数**）

| 文件 | 改动 | 为什么不能不动 |
|---|---|---|
| `synlab/observe/routes.py` | 新增 `render_frame_bundles(target, frames, spec, rng, …)`：把 `render_views` 的循环体抽成"给定帧列表 → 渲染 + 成像链"的单一实现；`render_views` 现在只负责 `make_view_frames` 然后调用它。新增 `observation_views(bundles, spec)` = 原 `_obs_views` 的公开入口 | ROI 视图必须走**同一条** scene/light/render/imaging 路径，否则"同一 basis"只是口号；复制一份循环会让两条路径将来漂移 |
| `synlab/observe/fracture_roi.py`（**新文件**，1 581 行） | 本文件实现全部新能力 | — |

行为不变性：`render_views` 的帧列表、`spec.derivation`、`_rescaled_frame`、成像链参数、
`ViewBundle` 字段都未改，`tests/a12/observe` 全部原有测试仍通过（§8）。

### 5.2 近摄相机工况（`closeup_profile` / `delivered_profile`）

* 沿用 **LOCAL 档镜头**（`f = 6.1 mm`、`f/2.4`、`7.6 mm` 传感器、`4000×3000` 原生网格）的
  焦距/畸变/光圈，物距改为配置的 **60 mm**（`u_position_mm` 记 `70 + (140−60) = 150 mm`）。
* **交付网格 = 相机网格**：`delivered_profile` 把 `K` 与 `image_size` 一起缩放到 1024×768，
  于是 `spec.derivation` 的 crop/resize 是恒等（`A = I`），`fx == fy` 精确成立
  （Blender worker 的硬要求），渲染网格与交付网格**同一张图**。
* **诚实标注**：5–10 cm 物距**超出**三档 profile 声明的 U 行程
  （`camera_profiles.json`：GLOBAL −100…−40 / MID −30…30 / LOCAL 40…70 mm），
  因此 `meta.calibration_status = "CLOSEUP_DECLARED_NOT_CALIBRATED"`、
  `u_travel_exceeded = true`、`pending` 里写明"仓库里没有 5–10 cm 的靶标图像"。
  这与 `p1155`"近摄是独立标定工况"一致：**渲染几何是精确的，真实台架标定没有被声称**。

### 5.3 断口 ROI 的判定（`fracture_rois`）

1. 取 `origin_kind == ORIGIN_INTERFACE` 的面（断面），按 `interface_id` **再**按连通分量切成 patch
   （`interface_id == -1` 的面仍是断面，默认保留并把 id 原样记录；配置可关）。
2. 面积 / 面数下限过滤（默认 25 mm² / 24 面）。
3. 每个 patch 取**中位点（medoid）为 aim**，按近摄视场半宽 `footprint_radius_mm` 裁出"相机真正
   看到的那一块"，作为 ROI：`area_mm2` / `radius` / `height` 都描述**这一块**，
   整块 patch 作为 `parent_*` 保留。
4. 法向 = aim 处面法向（与 patch 平面法向同号）；**正负号由遮挡实测决定**
   （两个候选相机位置各打一轮射线，取 ROI 采样点可见比例高的一侧），
   仪器写进 `normal_sign_source`。
5. 高度场 = 采样点到 ROI 面积加权平面的有符号距离；`height_field_stats` 给出
   整块平面残差 + 各 `R`（球半径内均值去趋势）分带统计（`Ra`/`Rq`/`Rz`/`Rt`/`p95`）。

### 5.4 视图与分辨率账本

* 每个断口 `directions = 4` 个方向：`0°`（沿法向）+ `±35°` + `55°`（配置可到 6 个，
  校验器强制：`θ = 0` 或 `|θ| ∈ [30, 60]`）。
* 每个视图 `frame.meta` 写入：`view_family = FRACTURE_ROI`、`fracture_roi_id`、
  `interface_id`、`direction_offset_deg`、`direction_in_plane_deg`、`direction_aim_visible`、
  `camera_centre_mm`、`roi_aim_mm`、`mm_per_pixel`、`px_per_mm`、`r_eff_mm`（4/6/8 px 三档）、
  `dof_cover_mm`、`dof_near_mm`、`dof_far_mm`、`delivered_long_edge_px`、`f_px_delivered`、
  `upsampled=false`、`digital_zoom_applied=false`。
* 观测层 `meta.fracture_roi.resolution_ledger.per_view` 汇总**每个视图实测**的
  `mm_per_px_measured`（渲染深度中位）、`mm_per_px_at_centre`（aim 像素）、
  **`mm_per_px_axis_raycast`（独立射线投射）**、`px_per_mm_measured`、`r_eff_mm_4px/8px`、
  `rim_px`、`object_px`、`rim_fraction_of_object`、`focus_error_mm`、`depth_centre_within_dof`。
* **新增视图而不是替换**：`append_roi_views` 返回一个新 `ObservationResult`，
  `views = 整片视图（原样，顺序不变） + ROI 视图`，并写
  `views_added_not_replaced = true`、`view_family_counts`。
* **通道落在两处**（因为 store 只回写视图自己的 `meta`，不回写 `frame.meta`）：
  ① `view.meta["resolution"]`（每视图的实测 `mm_per_px_*` / `px_per_mm_*` / `r_eff_mm_4px|8px` /
  `dof_cover_mm` / `focus_error_mm` / `depth_centre_within_dof` / 交付网格 / `f_px_delivered` /
  深度-射线差）与 `view.meta["fracture_roi_view"]`（`fracture_roi_id` / `interface_id` /
  方向角 / 方位来源 / `capture_feasible` / 遮挡实测 / `rim_px` / `object_px`）；
  ② 观测级 `meta.fracture_roi.resolution_ledger.per_view`（同一批数字的汇总，
  外加整片族的对应记录）。→ **读一个视图就能知道它的真实 mm/px，不必回到渲染现场。**

### 5.5 开关与配置

* `configs/a12/imaging_fracture_roi.yaml`（**新文件**）：
  `fracture_roi.enabled` 默认 **false**；`synlab.cli validate --config
  configs/a12/imaging_fracture_roi.yaml` → **exit 0**（本次实测，见 §8）。
  该文件用 `generation_spec:` 嵌套块做 schema 校验（与 `fracture_morphology.yaml` 同一约定），
  并把 `storage.root` 指向 **`data/a12_roi`**，所以 ROI 研究**不会覆盖任何生产资产**。
* 校验器 `validate_config` 失败即 `SCHEMA_INVALID`（未知键、方向数不在 3–6、
  倾角不在 0 或 ±[30,60]、物距不在 5–10 cm、分辨率档 < 64 px 等）。
* 默认关闭意味着：一个没有点名 ROI 的批产运行，**逐字节**与没有这个特性时相同
  （`test_the_shipped_configuration_is_off_by_default` 断言）。

---

## 6. 耗时与显存（Blender CUDA，实测）

见 `data/a12_reports/fracture_roi_timing.json`（逐具分解 + `nvidia-smi` 采样的显存）。
后端 = **Blender Cycles**（`third_party/blender-5.2.2-windows-x64/blender.exe`，5.2.2 LTS，
`device=GPU`、`compute_device_type=AUTO`、`gpu_require=true`，`samples=16`），
每个视图一次 worker 调用（真实渲染，无复用）。

| 阶段 | 视图数 | 合计秒 | 每视图秒 |
|---|---|---|---|
| 整片 12 视图 × 4 具 | 48 | **426.08** | 8.88 |
| ROI 特写 12 视图 × 4 具 | 48 | **347.17** | 7.23 |
| 高分辨率档（2048 px，1 具 3 视图 + V02 复算 3 视图） | 6 | **108.03** | 18.0 |
| **合计** | **102** | **881.28**（14 min 41 s） | 8.64 |
| 墙钟/具（含 ROI 计划、测量、落盘） | — | 261.5–310.5 | — |

**显存**（`nvidia-smi --query-gpu=memory.used`，0.25 s 采样，采样数 828–约 2 000/具）：

| 具 | min MiB | mean MiB | **peak MiB** |
|---|---|---|---|
| V10/M11 | 74 | 270 | **1 126** |
| V21/M06 | 63 | 214 | **910** |
| V23/M07 | 61 | 232 | **904** |
| V02/M01（115 435 面） | 66 | 1 198 | **8 012** |

> **口径与诚实边界**：`memory.used` 是**整卡占用**，不是本作业的分配；
> 采样窗口覆盖同一台机器上**并行运行的其它作业**（本次运行期间有其它 agent 在跑
> torch/Blender）。所以 V02/M01 的 8 012 MiB 峰值（本卡 8 151 MiB）
> **不能**读作"ROI 渲染需要 8 GB"：同一作业在其它三具研究体上的峰值是 **904–1 126 MiB**，
> 而 V02 的网格面数是其它具的 1.4–19.6 倍。要一个干净的数字需要独占 GPU 复跑（未做）。
> `fracture_roi_timing.json` 保留 min/mean/peak 与采样数，不把峰值写成"需求"。

**并发故障（如实记录）**：4 具连续跑时，第 4 具的第一次尝试在**第 71 次 Blender 调用**上
失败：`RuntimeError: Error: Failed to retain CUDA context (Unknown error)`（Blender worker
的 CUDA 上下文错误，不是本项目断言）。用 `--only 3` 在**新进程**里复跑该具即成功（exit 0），
结果合并进同一份报告（`fracture_roi_run.json` → `resumed_from`）。
→ 这是"每进程 Blender 调用数"上的稳定性问题，不是渲染结果问题；`_run_fracture_roi.py`
为此加了 `--only <index>` 的断点续跑开关。

---

## 7. 训练侧影响与最小可跑实验（任务 4）

### 7.1 ROI 特写进入导出包后 `rank` 任务能看到什么新信息

前提（引用，不是本次实测）：`data/a12_exports/trainable/next_experiment/training_package`
的关系表里 `eligible_as_negative = 1560`、`R0:1560 / R1:24 / R2:28 / UNKNOWN:106`、
`tokens` 有效秩 256、`frame_id` 匹配 98.75%（`precision_audit.md` §6.2）。
在此基础上，ROI 视图带来的是**每对负例的"断口证据质量"变化**：

1. **断面在视图里的占比**从 0.7–4.6% 变成 75–100%（本文件 §4.2 实测）。
   `rank` 的候选负例（`R0`：同器非邻接）此前靠"整片视图里看不见断口"来区分，
   现在同一断口在 ROI 视图里**填满画面**：负例对的断口**外观差异**第一次成为可学信号，
   而不是被 0.3 mm/px 的整片视角抹平成几个像素。
2. **`mm/px` 改善 4.30 倍**（0.3140 → 0.0730），`r_eff_mm` 从 1.256 mm 降到 0.292 mm。
   对 `rank` 的直接含义：**配对几何残差的可测下限**（`p0517` 的 4 px 口径）
   从 1.26 mm 降到 0.29 mm —— 小于 R1/R0 负例之间典型的 0.5 mm 级位置差，
   也就是说**断口局部几何第一次有机会进入"可判别"区间**（此前 1.26 mm 的可辨下限大于
   多数负例对的真实差异）。
3. **每断口 3–6 个方向的近摄**给了 `rank` 一个**同一断口的多视角一致性约束**：
   同一边的 4 个方向里，正确配对应当在整个方向集上一致；错误配对只在整片视角里"看起来像"。
   这是**新监督维度**（多视图一致性），此前 12 个整片视图都是围绕整片的环，
   没有任何两个视图对**同一个断口**形成窄基线多视角。
4. **诚实边界（必须一起读）**：以上三条**没有**改变"断口 < 1 mm 无几何"这一事实（§2.3）。
   ROI 视图让**宏观断口形状**（form：mm–100 mm 尺度，实测 `Ra` 0.0056–1.485 mm）第一次清晰可见，
   但 **< 1 mm 的粗糙度仍是 0**。因此 ROI 视图对 `rank` 的帮助首先是
   "断口的宏观形状/边缘/厚度变化"，不是"断口粗糙度纹理"。

### 7.2 消融假设（可证伪，带预期方向）

| # | 消融 | 假设 | 预期指标变化 | 与 `docs/a12/ablation_experiments.md` 的对齐 |
|---|---|---|---|---|
| A | **A-ROI-1**：整片 12 视图 ± ROI 特写（每断口 4 方向） | ROI 视图提供"断口占画面 75–100%"的窄基线多视角 | `rank` 任务的 **AUC/Recall@1 提高**；配对残差 P95 下降；对 `R0` 负例的假阳下降 | 对齐该文件的**视图/证据族**消融组（组 id 以 `docs/a12/ablation_experiments.md` 现表为准；若该表未列此组，按同格式新增 `ABL_ROI_VIEWS`） |
| B | **A-ROI-2**：ROI 视图数 0 / 3 / 4 / 6 | 方向数越多一致性约束越强，但收益递减 | `rank` 指标随方向数单调不降，3→4 有增益、4→6 增益变小 | 同上（剂量-响应组） |
| C | **A-ROI-3**：ROI `mm/px` 0.0730 vs 0.0365（2048 px 档） | 分辨率翻倍只影响"横向可辨"，而 < 1 mm 无几何 ⇒ **收益应接近 0** | `rank` 指标**基本不变**（这是本文件 §2.3 的核心可证伪预测） | 同上（分辨率组） |
| D | **A-ROI-4**：接线形态学（`morphology_shared_cut`）后 ROI 视图 | 只有几何里有形貌，ROI 才能带来纹理级信号 | `rank` 指标**显著提高**；且 ROI 视图的贡献从"宏观形状"转为"形貌纹理" | 与形态学组的接线实验同一批次 |

> **预期方向的诚实标注**：A/B 的方向有本文件 §4.2 的实测支撑（断面占比与 `mm/px`）；
> C 的方向是 §2.3 的直接推论（`below_1mm` 的 `Ra` 实测为 0，所以提高分辨率不会产生新信号）；
> D 的方向依赖形态学接线，其**当前状态是 FAILED**（§2.3），所以 D 是"条件满足后才成立"的预测。

### 7.3 最小可跑实验建议

1. **数据**：用本文件的 `data/a12_roi/store`（4 具 × (12 整片 + 12 ROI) = 96 视图）作为
   ROI 分支的最小数据；对照组就是**同一 store 里同一资产的 12 个整片视图**（无需另跑）。
2. **导出**：把 ROI 视图按现有 `deploy/obs/index.json` 的通道约定写进导出包
   （`tiles` / `valid` / `view_pos`），并在 `roi` 通道写 `fracture_roi_id` 与
   `direction_index`（`deploy` 侧只给 RGB+mask+u，ROI 的 id 属于研究标签，
   不要进部署输入 —— 这是 `t104` 的权限边界）。
3. **任务**：`rank`（配对排序）＋ 关系头；指标沿用现有 `R0/R1/R2` 分母与
   `eligible_as_negative` 口径（`D10`：`kind ∈ {R1,R0} ∧ loss_mask`）。
4. **对照**：A（视图族）用同一 backbone 同一 seed，只切换视图族；
   C（分辨率）用同一视图族的两档 `mm/px`。
5. **停止条件**：C 组若与 A 组指标差 < 1 个标准误，即验证 §2.3 的预测
   （"看不见"的根因不是分辨率），此时**唯一**该做的工单是接线形态学（D 组）。

---

## 8. 复算命令与退出码（本次实测）

工作目录 = `C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab`，解释器 = `.venv\Scripts\python.exe`。

| # | 命令 | 产出 | 退出码 |
|---|---|---|---|
| 1 | `python -m synlab.cli validate --config configs/a12/imaging_fracture_roi.yaml` | `OK` + `spec_hash sha256:643eecbb…` | **0** |
| 2 | `python tests/a12/observe/_run_fracture_roi.py --bodies 4 --samples 16 --extra-rung 2048` | `data/a12_reports/fracture_roi_{run,compare,resolvability,timing}.json` + `data/a12_roi/store` | 1（第 4 具 CUDA 上下文故障，见 §6） |
| 2b | `python tests/a12/observe/_run_fracture_roi.py --only 3 --samples 16` | 断点续跑第 4 具并合并进同一报告（`resumed_from`） | **0** |
| 3 | `python -m pytest tests/a12/observe/test_fracture_roi.py -q` | 24 passed | **0** |
| 4 | `python -m pytest tests/a12/observe -q --tb=no` | 327 项，1 failed（既有）/ 1 skipped / 325 passed | 1（基线同样为 1） |
| 5 | `python data/a12_reports/_roi_tables.py`（只读汇总） | 打印 §4.2/§4.3/§6 的表格数字 | 0 |
| 6 | `python data/a12_reports/_roi_patch_probe.py` / `_roi_fracture_stats.py`（只读探针） | `_roi_patch_probe.json/.txt`、`_roi_fracture_stats.json/.txt` | 0 |

---

## 9. 测试

`tests/a12/observe/test_fracture_roi.py`（**新文件**，24 个用例）断言：

* **ROI 视图数 3–6**：每断口生成 `directions` 个视图，`directions ∈ [3,6]` 之外一律 `SCHEMA_INVALID`
  （2 与 7 两个反例）；
* **`mm/px` 被记录**：每个视图的 `frame.meta` 有 `mm_per_pixel`（= `z/f_px`）、`px_per_mm`、
  `r_eff_mm = 4 mm_per_pixel`、`r_eff_mm_8px`、`dof_cover_mm`；观测层 `resolution_ledger.per_view`
  对每个视图给出实测 `mm_per_px_axis_raycast` / `px_per_mm_measured` / `r_eff_mm_4px`；
* **与整片同 basis**：`append_roi_views` 后 `views[:n_whole]` 与整片视图 id 序列逐位相同
  （新增而非替换）、`view_family_counts` 两类分别计数、ROI 视图来自同一 tier 的近摄条件；
* **可关闭**：默认配置 `enabled=false`；`append_roi_views` 传空 ROI 列表时视图数不变、
  `FRACTURE_ROI` 计数为 0；
* **契约形状**：未知配置键、方向数、倾角窗口（0 或 ±[30,60]）、物距窗口（5–10 cm）越界即拒绝；
* **反解自洽**：`inverse_solve` 的结果代回前向公式恰好得到 `k` 个像素；
  `required_long_edge_px` = `required_f_px × W_native / f_px_native`；
* **实测优先**：`mm_per_px_axis_raycast` 的 ROI 中位 **小于** 整片中位；
  渲染网格不小于交付网格（`f_px_delivered ≤ f_px_native`，即**不上采样**）；
* **几何为零是真结论**：平面切割夹具的 `below_1mm` / `below_0.25mm` 的 `Ra` 实测为
  `0 ± 1e-9`（不是"没测"，是测到 0）；非平面夹具则给出非零。

结果（本次实测）：
```
python -m pytest tests/a12/observe/test_fracture_roi.py -q   →  24 passed   exit 0
python -m pytest tests/a12/observe -q  --tb=no -p no:warnings
     →  327 项（1 skipped / 1 failed / 325 passed）   exit 1
```

### 9.1 全目录回归（含既有测试）

| 运行 | 结果 | 退出码 |
|---|---|---|
| 改动**前**（基线，`_roi_baseline_pytest.txt`） | 2 个既有失败：`test_mvs_subset.py::test_source_dependency_audit_is_a_real_experiment`、`test_synthetic_extras.py::test_loader_list_and_modality_are_machine_readable` | 1 |
| 改动**后**（第一次，`_roi_pytest_observe.txt`） | 同样这 2 个失败；`test_fracture_roi.py` 的 24 项全通过 | 1 |
| 改动**后**（复跑，`_roi_pytest_observe_final.txt`） | 327 项：**1 failed**（只剩 `test_synthetic_extras` 那条）、1 skipped、325 passed | 1 |

> 三条必须一起读：
> 1. 两个失败**都与本次改动无关**，且基线就有；`test_renderer_dispatch` / `test_pixel_contract` /
>    `test_blender_backend` / `test_fracture_surface_signal` / `test_coc_units` /
>    `test_carve_holes_bounds` / `test_realism_config_and_bridge` / `test_fracture_roi` 全部通过。
> 2. `test_mvs_subset::test_source_dependency_audit_is_a_real_experiment` 在两次复跑里
>    **一次失败一次通过** → 它是**不稳定**的（不是本次改动造成，也不是本次修好的）。
> 3. `tests/a12/observe` 的基线本来就是 **2 failed**；本次**没有**把它们变绿，也不声称变绿。

---

## 10. 仍未解决项（不用估计值填充）

| # | 未解决项 | 为什么还没解决 | 谁能解决 |
|---|---|---|---|
| 1 | **断口 < 1 mm 的形貌在几何里恒为 0** | 形态学后端 `morphology_shared_cut` 是 GATED（不在 `BUILT_BACKENDS`），且其 rough 变体在冻结的 0.01 mm 预算 / 30000 cell 预算下实测 **FAILED（PRECISION_BUDGET_EXCEEDED）**。ROI 视图、分辨率、工作距离都改变不了这一点 | `synlab/fracture/**` 的接线与精度预算（**本次写入范围外**）；最小路径：抬高 `max_cutter_cells` 或在冻结预算内降低请求曲率，然后用本文件的 ROI 管线复测 |
| 2 | **真实 5–10 cm 内参标定** | 仓库里没有 5–10 cm 的靶标图像；契约 `p1155` 把近摄列为独立工况。本次只把**渲染几何**做到精确并标注 `CLOSEUP_DECLARED_NOT_CALIBRATED` | 扫描台建成后的标定板实验（重投影 RMS ≤0.2 px 的验收判据见 `precision_audit.md` §4.3） |
| 3 | **近摄物距超出声明 U 行程** | `camera_profiles.json` 三档的 `u_travel_mm` 都到不了 5–10 cm 物距（LOCAL 最近 140 mm） | 需要把"近摄"表示为一个**新档位**（含其 U 行程与 focus group），这是 `configs/a12/camera_profiles.json` + `synlab/cameras/profiles.py` 的改动（**本次写入范围外**） |
| 4 | **0.2 mm ≥4 px 与 5–10 cm 近摄的可同时成立性** | 本镜头 **60 mm 处需交付长边 ≥1495 px**；契约相机在同窗口需 1800–2161 px。若坚持 1024 px，则 0.2 mm 只能到 2.74 px（差 1.46×） | 交付网格规格的裁决（训练图长边 1024 → 1536/2048 的代价见 §6 的高分辨率档实测） |
| 5 | **软件光栅器的透视深度 bug** | `render.py` 的 z 缓冲用屏幕空间线性插值，掠射三角形上实测偏 **35.6 mm**（§2.5）。本次用射线投射绕开并把差值记录，**没有修渲染器** | 渲染器的透视正确深度插值（`1/z` 插值）；修它会改变既有 store 的深度字节，需要单独裁决 |
| 6 | **`Ra` 的"真实台架对照"** | 合成侧没有真实断口的高度场测量（`REAL_CAPTURE:PENDING`）。本文件的 `Ra` 全部是**合成网格的自测值** | 真实采集后的表面轮廓仪/共聚焦测量 |
| 7 | **ROI 视图进入导出包** | 本次只产出到 `data/a12_roi/store` 的 `obs_result`；导出包（`sync/export`）**没有**改动（写入范围外） | `synlab/storage/export.py` 的通道扩展 + `tools/` 的打包脚本，按 §7.3 的通道约定 |

---

## 附：与既有文档的关系

| 既有文档 | 本文与它的关系 |
|---|---|
| `docs/a12/precision_audit.md` §1/§7 | 本文**引用**其 mm/px（0.27193）、`z_max`（63.97/35.03/11.68）、rim 占比（4 999 163 px / 5.32%）与"缺 fracture_local 视图环"的判定；本文**新增**的是（a）实测高度场分带、（b）反解表、（c）ROI 视图实现与对照、`px_per_mm`/`r_eff_mm`/`dof_cover_mm` 生产者 |
| `docs/a12/fracture_surface_signal.md` | 该文回答"断面在 2D 里有没有信号"（有：6.3% 面积 → 2D 可见）；本文回答"**断口的形貌**能不能被看见"（< 1 mm 不能，因为几何为零） |
| `docs/a12/fracture_realism.md` | 该文记录形态学的实现与实测（含 rough 变体 FAILED）；本文引用其诊断行（`predicted amplitude scale 0.1303`）作为"若接线"的上界，并把它明确标为**非实测** |
| `docs/a12/ablation_experiments.md` | 本文 §7.2 的 A/B/C/D 四组按该文件的组格式给；若该表未列视图族/分辨率组，按同格式新增 `ABL_ROI_VIEWS` |
| `configs/a12/capture_contract.json` | 本文每条要求都带 `source` 指针；未改契约本身 |
