# A12 母体几何全局缺陷审计（本轮只调查与出方案，不改几何代码）

审计对象：`relicweave-synlab` 全部 **24 个已注册器型**（V01..V24），每个器型**单独进程**构建一次
真实母体，读取冻结公开接口（`create_mother` / `audit_mother`）的实测结果。

被测代码状态（`data/a12/reports/mother_geometry_audit.json` 的 `code_state` 字段已固化）：

| 项 | 值 |
| --- | --- |
| git HEAD | `c311269`（*fix: mask CoC units, damage legality, vessel sampler validation and physical targeting*） |
| `synlab/mothers/**` 工作区 | **干净**（`git status --porcelain -- synlab/mothers` 为空；该目录最后改动是 `4f51a00`） |
| `synlab/mothers/vessels/common.py` | `sha256:4a343247d84cfeb4529d5445144317576d8c958d39301139f41e4009342da680` |
| `synlab/mothers/geometry.py` | 见 JSON `code_state.file_hashes` |
| 本轮写入 | 只写 `docs/a12/mother_geometry_audit.md`、`data/a12/reports/**`、`tests/a12/mothers/test_mother_geometry_audit.py`；**未改任何 `synlab/**`** |

> 注意：审计过程中队友提交了 `c311269`（HEAD 由 `807b71d` 变为 `c311269`）。该提交**没有触及
> `synlab/mothers/**`**，`common.py` 的哈希与两处缺陷行号（158、214）在审计前后完全一致，因此本报告的
> 实测结论对当前 HEAD 仍然成立；报告同时固化文件哈希，便于日后核对。

---

## 0. 结论摘要

1. **线索成立（复核为真）**：`synlab/mothers/vessels/common.py:146` 的
   `monotone_radius_control_points` 确实会把"半径先增后减"的肩部/颈部控制点**全部丢弃**。
   冻结谱系 `LIN0004_V10_M06_PAT03` 实测 `z_rim = 216.6014 mm`，参数声明 `z_rim_target_mm = 357.4524 mm`，
   **短 140.8510 mm**；壶身止于肩部（`216.6014` 与 `z_shoulder = t_b/2 + 0.6h = 216.6014` 逐位相等），
   盖与壶身之间**实测空隙 132.4234 mm**（到盖基面 137.48 mm）。
2. **但同一个文件里还有一处影响面更大的缺陷，与本线索同源**：`wall_points` 末尾的夹逼
   （`common.py:212-216`）把**任何上升的壁面**压成常量半径。15 个调用它的器型**全部**命中：
   例如 V17 花盆请求 `r_start 55.8 → R 90.0`，实际返回 5 个点全为 `62.640 mm`。
   两个守卫互斥——`wall_points` 禁止上升、`monotone_radius_control_points` 禁止下降——
   **它们的交集只剩"等半径"中线**，这就是"全局"二字的准确含义。
3. **24 器型逐个实测归因**：真正轮廓算法缺陷 **(a) 16 例**（15 例 A1 + V22 的 A3；其中 7 例同时含 A2）、
   参数/几何语义不符 **(b) 1 例**（V23）、设计如此或与声明相符 **(c) 7 例**。
   **没有把偏差一律算成缺陷**：V13/V14/V18/V19/V20/V24 与各自声明一致；V15 的"矮"是浅灯盏的设计；
   V21 的 z 尺寸本就不是 `thickness_mm`（不可比），已如实标注为 `n/a`。
4. **现有 QA 闸门看不见这些缺陷**：24/24 `audit_mother` 全部 `ok=True`、`watertight=True`、
   自交 0、最小厚度达标。原因很直接——闸门检查"是不是闭合可用的实体"，不检查"实体是否符合它自己
   声明的参数"。因此缺陷在批产里静默通过。
5. **最小修法只动 `common.py` 两处**。在进程内模拟该修法（不改仓库文件）后实测：
   24 器型**仍然全部可建、全部 QA 通过**；7 个颈部器型高度恢复；V10 冻结谱系
   `z_rim 216.6014 → 357.7600`（目标 357.4524），盖的空隙由 **+137.48 mm 变为 −1.686 mm（座入过盈）**。

---

## 1. 复核线索：V10 与同族复合器型的数值链

### 1.1 两处缺陷的准确位置

| 编号 | 位置 | 规则 | 实际后果 |
| --- | --- | --- | --- |
| **A1** | `common.py:212-216`（`wall_points` 末尾） | `if out and rr > out[-1][0]: rr = out[-1][0]` | 返回半径被强制**非增**；由于所有调用点都传 `R_mm > r_start_mm`，第一个采样点胜出，整段壁面变成**常量半径** |
| **A2** | `common.py:157-159`（`monotone_radius_control_points`） | `if row[0] < kept[-1][0] - 1e-9: continue` | 半径小于历史最大值的控制点被**丢弃**；"肩部 → 口沿收窄"整段消失，母体止于肩部 |

两处都在初始提交 `3fa9805` 就存在（`git log -S "rr > out[-1][0]"` 与 `git log -- common.py`
都只有 `3fa9805` / `4f51a00`），不是队友本轮引入的。

**关于"会不会折墙"的澄清（这条决定了最小修法是否安全）**：`monotone_radius_control_points` 的文档
把半径单调当成防折手段，但 `geometry.py::pchip_curve` 把 `r(t)`、`z(t)` 都建成**弦长参数 t 的函数**，
`t` 严格递增，所以"半径先增后减"在参数域上是普通函数图像，**不可能**让中线自我折叠。真正的折墙
守卫在 `build_shell_profile` 内部、并且是实测的：`offset_clearance()`（顶点内切半径）、
`curvature_margin`（局部曲率半径 vs 半厚）、`_self_intersects()`。也就是说 A1/A2 是**在真正的守卫
之外多加的一道过度约束**，删掉它们不会失去折墙保护。

### 1.2 V10 数值链（冻结批产真实参数，逐点可复算）

参数来自 store 里该谱系的真实记录（`data/a12/reports/mother_geometry_audit/s04_frozen_repro.json`）：

```
base_mm=10.649771173028173  height_mm=352.12756141776987  diameter_mm=222.77854733012697
belly_ratio=0.68991973127168  mouth_ratio=0.30098125744230925  wall_mm=2.8443414248422236
lid_height_ratio=0.568826035425881  lid_seat_mm=3.3710449924909853  knob_diameter_mm=64.43440084462063
```

派生量（构建器自己的算术，非本报告假设）：

```
t_b/2            = 5.3248855865140865
z_shoulder       = t_b/2 + 0.6*h = 216.60142243717602      ← 当前几何的实际顶部
z_rim_target     = t_b/2 + 1.0*h = 357.45244700428395      ← 参数声明的目标
r_belly          = 0.5*222.77854733012697*0.68991973127168 = 76.8497 mm
r_mouth          = r_belly * 0.30098125744230925           = 23.130 mm
r_base           = 0.55*r_belly                            = 42.2673 mm
```

**输入控制点 → 输出控制点 → 几何**（`s12_chain_exact.json`，V10 `[CURRENT]`）：

```
wall_points(r_start=42.2673, R=76.8497, z_start=11.716, z_rim=216.6014, count=4, exponent=0.62)
  → 4 个点，半径跨度 r_span = 0.000000 mm：
     (56.909,  63.735) (56.909, 114.691) (56.909, 165.646) (56.909, 216.601)
     56.909 = 42.2673 + (76.8497-42.2673) * 0.25**0.62     ← 只剩第一个采样点

builder 追加的肩/颈段（r_belly → r_mouth，半径逐点下降）：
     (53.467, 251.814) (41.408, 287.027) (31.647, 322.240) (23.130, 357.452)

shell_profile 收到的 ctrl IN (9):
     (0.000,  5.325) (23.247, 11.715) (56.909, 114.691) (56.909, 165.646) (56.909, 216.601)
     (53.467, 251.814) (41.408, 287.027) (31.647, 322.240) (23.130, 357.452)

monotone_radius_control_points → ctrl OUT (5)，丢弃 4 个：
     (0.000,  5.325) (23.247, 11.715) (56.909, 114.691) (56.909, 165.646) (56.909, 216.601)
     丢弃：(53.467,251.814) (41.408,287.027) (31.647,322.240) (23.130,357.452)  ← 整条颈部

生成几何（build_shell_profile 实测）：
     profile.z_rim    = 216.6014 mm     (= z_shoulder，逐位相等)
     profile.z_bottom =   5.1051 mm
     profile.r_max    =  58.3842 mm     (中线 56.909 + 半厚/口沿)
     z_rim_target     = 357.4524 mm
     短差             = 140.8510 mm
```

同一个数值链也解释了"为什么 V10 的顶部反而更宽"：`top_over_max_radius_ratio = 1.000`，
即母体在**自己顶部最宽**，与 `mouth_ratio = 0.30`（口沿应为腹部半径的 30%）完全相反。

### 1.3 与队友实测数字的逐项对齐（含一处口径差）

| 队友记录 | 本报告实测 | 是否一致 |
| --- | --- | --- |
| 壶身 4224 面 / 281 673 mm³（z=5.11–216.60） | 4224 面 / **281 673.542** mm³ / z=[5.1051, 216.6014] | ✅ 完全一致 |
| 盖 768 面 / 394 820 mm³（z=354.08–581.77） | 768 面 / **394 831.653** mm³ / z=[354.0814, 581.7653] | ✅ z 逐位一致；体积差 11.6 mm³（0.003%，源于 warp 的 rng 流不同，本报告用独立种子） |
| 盖裙 256 面 / 13 045 mm³（局部修好后 z=349.02–355.77） | 256 面 / **13 045.551** mm³ / z=[349.0248, 355.7669] | ✅ 一致，**盖裙平移修复在 HEAD 上已生效**（不再出现在壶底之下） |
| "盖因此悬空 137 mm" | 见下 | ⚠️ 口径差，见说明 |

**"悬空 137 mm"的精确口径（两个数都对，但指的不是同一个东西）**：

* 壶身顶面 `216.6014` → 盖**基面** `354.0814`：**137.48 mm**（队友引用的数）；
* 壶身顶面 `216.6014` → 盖组件**最低点（裙底）** `349.0248`：**132.4234 mm**（真正的"空气间隙"，
  本报告 `max_positive_gap_mm` 一列用的就是这个口径）；
* 声明目标短差：`357.4524 − 216.6014 = 140.8510 mm`（第三个数，衡量"母体自身矮了多少"）。

三个数分别对应"盖离壶身多远 / 空气多厚 / 母体欠高多少"，报告里分开列示，避免后续引用串口径。

### 1.4 同族复合器型同样中招（不是 V10 独有）

用同一批 store 真实参数重放（`s04_frozen_repro.json`）：

| 谱系 | 器型 | 声明目标 z_rim (mm) | 实测 z_rim (mm) | 短差 (mm) | 备注 |
| --- | --- | --- | --- | --- | --- |
| `LIN0004_V10_M06_PAT03` | V10 带盖壶 | 357.4524 | 216.6014 | **140.8510** | 盖悬空 132.42 mm |
| `LIN0006_V09_M09_PAT03` | V09 壶 | 302.4642 | 182.0457 | **120.4186** | 颈/流/柄高度全丢 |
| `LIN0014_V16_M07_PAT10` | V16 香炉 | 365.9070 | 254.4300 | **111.4769** | 5 条足 + 11 个通气孔，足与体分离 |
| `LIN0000_V10_M11_PAT15` | V10 带盖壶 | 213.8546 | 156.0770 | **57.7776** | 口沿比 `mouth_ratio=0.948` 本该接近直筒，仍短 57.8 mm |

**这些都通过了 QA**（四次重放 `audit_ok=True`、`failures=[]`）。

---

## 2. 24 器型实测（每器型单独进程）

### 2.1 症状判据（机械化、可复算，写在 JSON 的 `symptom_rules` 里）

| 代号 | 判据 |
| --- | --- |
| `S1_profile_truncated` | `z_rim_target_mm − profile.z_rim > max(2.0 mm, 1% × 目标)`（15 个走 `shell_profile` 的器型） |
| `S2_extent_short` | `声明 z 尺寸 − 实测本体 z 跨度 > max(2.0 mm, 1%)`（不走 `shell_profile` 的器型） |
| `S3_neck_lost` | 存在被丢弃的肩/颈点（`monotone` 丢弃数 > 0）**且**本体在自己顶部十分位的半径 ≥ 自身最大半径的 98% |
| `S4_wall_flat` | `wall_points` 返回的半径跨度 = 0，而请求的目标半径 `R > r_start`（壁面无法变宽） |
| `S5_floating_part` | 相邻两个连通体之间存在 > 1 mm 的**正**间隙（悬空） |
| `S6_other_geometry_defect` | 轮廓辅助函数之外的独立几何缺陷（当前仅 V22） |

"声明 z"的来源逐器型标注在 JSON 的 `declared_source` 字段：15 个器型用构建器**自己记录**的
`profile_metrics.z_rim_target_mm`；其余用构建器自己的算术（如 V14 = `z_top + 0.35t + knob_h + 0.5t`，
V19 = `thickness_mm + side_lip_mm`，V20 = `length_mm + tail_lift_mm + tail_drop_mm`）。
V21 的 `thickness_mm` 是法向厚度而非 z 尺寸，**判为不可比、记 `n/a`**（不硬凑成一个偏差）。

### 2.2 器型 × 症状表

<!-- 由 data/a12/reports/mother_geometry_audit/s08_analyse.py 生成，勿手改数字 -->

| vessel | family | declared z (mm) | measured (mm) | shortfall (mm) | bodies | max gap (mm) | top/max r | wall radius flat at (mm) | symptoms | attribution |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V01 碗 | revolve | 84.59 | 85.23 | -0.64 | 1 | 0.0 | 1.0 | 75.34 | S4_wall_flat | A1_wall_points_collapse |
| V02 深盘 | revolve | 37.25 | 37.8 | -0.55 | 1 | 0.0 | 1.0 | 41.96 | S4_wall_flat | A1_wall_points_collapse |
| V03 浅碟 | revolve | 17.25 | 18.17 | -0.92 | 1 | 0.0 | 1.0 | 84.84 | S4_wall_flat | A1_wall_points_collapse |
| V04 杯 | revolve+attachment | 98.25 | 98.25 | 0.0 | 2 | -67.18 | 1.0 | 54.14 | S4_wall_flat | A1_wall_points_collapse |
| V05 高足杯 | revolve+revolve | 209.0 | 209.0 | 0.0 | 2 | -101.57 | 1.0 | 54.31 | S4_wall_flat | A1_wall_points_collapse |
| V06 罐 | revolve | 183.25 | 138.54 | 44.71 | 1 | 0.0 | 1.0 | 70.35 | S1_profile_truncated, S3_neck_lost, S4_wall_flat | A1_wall_points_collapse, A2_monotone_drops_neck |
| V07 瓶 | revolve | 243.25 | 41.75 | 201.5 | 1 | 0.0 | 1.0 | 71.01 | S1_profile_truncated, S3_neck_lost, S4_wall_flat | A1_wall_points_collapse, A2_monotone_drops_neck |
| V08 双耳瓶 | revolve+attachment | 233.25 | 130.67 | 102.58 | 3 | 34.19 | 1.0 | 66.79 | S1_profile_truncated, S3_neck_lost, S4_wall_flat, S5_floating_part | A1_wall_points_collapse, A2_monotone_drops_neck |
| V09 壶 | revolve+attachment | 183.25 | 134.51 | 48.74 | 2 | -63.87 | 1.0 | 65.28 | S1_profile_truncated, S3_neck_lost, S4_wall_flat | A1_wall_points_collapse, A2_monotone_drops_neck |
| V10 带盖壶 | revolve+lid | 173.25 | 123.07 | 50.18 | 3 | 40.18 | 1.0 | 66.65 | S1_profile_truncated, S3_neck_lost, S4_wall_flat, S5_floating_part | A1_wall_points_collapse, A2_monotone_drops_neck |
| V11 坛 | revolve | 213.25 | 188.01 | 25.24 | 1 | 0.0 | 1.0 | 104.8 | S1_profile_truncated, S3_neck_lost, S4_wall_flat | A1_wall_points_collapse, A2_monotone_drops_neck |
| V12 盆 | revolve | 73.5 | 74.25 | -0.75 | 1 | 0.0 | 1.0 | 65.67 | S4_wall_flat | A1_wall_points_collapse |
| V13 盒 | prism | 70.0 | 70.0 | 0.0 | 1 | 0.0 | 1.0 | n/a | - | C_design_or_match |
| V14 盖 | revolve | 59.65 | 59.65 | -0.0 | 1 | 0.0 | 0.195 | n/a | - | C_design_or_match |
| V15 灯盏 | revolve+spout | 35.0 | 36.15 | -1.15 | 1 | 0.0 | 0.949 | 36.03 | S4_wall_flat | A1_wall_points_collapse |
| V16 香炉 | revolve+attachment | 149.25 | 119.96 | 29.29 | 7 | 0.64 | 1.0 | 69.67 | S1_profile_truncated, S3_neck_lost, S4_wall_flat | A1_wall_points_collapse, A2_monotone_drops_neck |
| V17 花盆 | revolve+pierced | 122.0 | 123.28 | -1.28 | 1 | 0.0 | 1.0 | 62.64 | S4_wall_flat | A1_wall_points_collapse |
| V18 砖 | prism | 45.0 | 45.02 | -0.02 | 1 | 0.0 | 1.0 | n/a | - | C_design_or_match |
| V19 平瓦 | prism | 26.0 | 33.12 | -7.12 | 1 | 0.0 | 0.829 | n/a | - | C_design_or_match |
| V20 弧瓦 | arc_band | 250.0 | 250.0 | 0.0 | 1 | 0.0 | 1.0 | n/a | - | C_design_or_match |
| V21 曲面板 | curved_shell | n/a | 74.0 | n/a | 1 | 0.0 | 0.993 | n/a | - | C_design_or_match |
| V22 碑板 | prism | 38.0 | 6.0 | 32.0 | 1 | 0.0 | 1.0 | n/a | S2_extent_short, S6_other_geometry_defect | A3_stele_bevel_intersection |
| V23 小雕像 | superquadric | 180.0 | 169.68 | 10.32 | 1 | 0.0 | 0.427 | n/a | S2_extent_short | B1_figurine_height_semantics |
| V24 装饰构件 | superquadric | 90.0 | 97.66 | -7.66 | 1 | 0.0 | 0.452 | n/a | - | C_design_or_match |

> `max gap` 为负值表示两个连通体**相互嵌入**（例如 V04 的圈足、V05 的柄/足、V09 的流/柄），
> 不是悬空。`wall radius flat at` 为 `n/a` 表示该器型不调用 `wall_points`。
> 每器型的体积、bbox、水密性、`audit_mother` 逐项检查、连通体清单、轮廓半径表（12 个 z 分位）
> 都在 `data/a12/reports/mother_geometry_audit.json` 的 `vessels.<VID>` 里，另有单器型的
> `data/a12/reports/mother_geometry_audit/parts/<VID>.json`。

**实测量化影响（A1，宽度而非高度）**：15 个 `wall_points` 器型的**壁面中线**都停在"第一个采样点"的
半径，本体永远达不到参数声明的半径。下表两个比例分别对应"壁面中线 / 声明 R"与"本体实测 `profile.r_max` /
声明 R"（后者含外侧偏置半厚，且当某个肩部点侥幸存活时会向外张开，例如 V11）：

| 器型（参数来源） | 声明 R (mm) | `wall_points` 返回的常量半径 (mm) | 本体实测 `profile.r_max` (mm) | 中线/R | r_max/R |
| --- | --- | --- | --- | --- | --- |
| V10 带盖壶（冻结谱系） | 76.8497 | 56.9090 | 58.3842 | **74.0%** | 76.0% |
| V07 瓶（原型参数） | 95.0000 | 71.0060 | 72.9372 | **74.7%** | 76.8% |
| V11 坛 | 175.7500 | 104.7967 | 139.2934 | **59.6%** | 79.3% |
| V17 花盆 | 90.0000 | 62.6400 | 65.8400 | **69.6%** | 73.2% |
| V01 碗 | 95.0000 | 75.3385 | 77.3693 | **79.3%** | 81.4% |
| V12 盆 | 95.0000 | 65.6677 | 68.1677 | **69.1%** | 71.8% |
| V02 深盘 | 57.9781 | 41.9585 | 44.1585 | **72.4%** | 76.2% |
| V15 灯盏 | 42.5000 | 36.0278 | 38.4856 | **84.8%** | 90.6% |
| V16 香炉 | 90.0000 | 69.6699 | 80.1778 | **77.4%** | 89.1% |
| V03 浅碟 | 95.0000 | 84.8448 | 86.7046 | **89.3%** | 91.3% |

即：**碗不再是碗、盆不再是盆、坛的腹部只有声明值的六成**，而高度往往是"对的"——所以只看高度
（例如只对比 bbox 高度）根本发现不了。注意 V11 的 `r_max`（139.29）明显大于它的壁面常量半径
（104.80）：因为肩段第 1 个点（138.3）恰好大于塌陷后的壁面半径而被**侥幸保留**，于是本体在肩部
向外张成一个"喇叭口"后被截断——这也说明修复前的中线**既不单调增也不单调减**，
不能只用"被压成圆柱"一句话概括。

---

## 3. 归因（分三类，逐条带证据）

### (a) 真正的轮廓算法缺陷 —— 16 例

**A1 `wall_points` 上升壁面塌陷（15 例：V01–V12、V15、V16、V17）**

* 证据 1（调用点追踪，`s05_trace.json`，把构建器真实调用参数与方法返回值一起记录）：
  **15 个 `wall_points` 调用点全部** `out_r_span = 0.0000`。
* 证据 2（直接调用，`s02_chain.json`）：`wall_points(r_start=12, R=40, z_start=0, z_rim=50, count=6, exp=0.75)`
  → 6 个点全为 `r = 19.304`（连 `r_start=12` 都不是，而是**第一个采样点**的值）。
* 证据 3（规范化反例）：`monotone_radius_control_points` 对**上升**的中线点**一个不丢**
  （控制组 `(0,0)(20,5)(40,30)(55,60)(60,90)` 原样返回），说明两个守卫方向相反、互斥。
* 归因结论：这是**算法缺陷**（代码与它自己的文档一致，但与全部 15 个调用点的意图相反）。

**A2 `monotone_radius_control_points` 丢弃颈部（7 例：V06、V07、V08、V09、V10、V11、V16）**

* 证据：`s05_trace.json` 中这 7 个器型的 `monotone` 丢弃数分别为 2/3/3/2/3/2/2（其余器型为 0）；
  `s12_chain_exact.json` 给出 V10（9→5，丢 4 点）与 V07（8→5，丢 3 点）的逐点前后对照。
* 量化：短差 V06 44.71、V07 201.50、V08 102.58、V09 48.74、V10 50.18（原型）/140.85（冻结谱系）、
  V11 25.24、V16 29.29 mm。
* 连带症状：V08（耳）与 V10（盖）出现 `S5_floating_part`——部件按**声明的** `z_rim` 定位，
  而本体被截断在肩部，于是部件悬空 34.19 mm / 40.18 mm（冻结 V10 谱系 132.42 mm）。
* 归因结论：算法缺陷。注意"颈部丢失"与"A1 塌陷"**共同**决定截断位置：截断发生在
  "最后一个半径 ≥ 历史最大半径的点"。V10 冻结参数下壁面塌陷到 56.909，颈段 53.467/41.408/31.647/23.130
  全部小于它，于是全丢、顶部正好落在 `z_shoulder`；而 V10 原型参数（`mouth_ratio=0.62`）下颈段首点
  64.07 > 56.909 被保留，截断位置变成 123.07 而非 105.25。**两个缺陷耦合，不能只按其中一个预测数值。**

**A3 V22 碑板的"倒角"实际是截断（1 例：V22）—— 与本线索无关的独立缺陷**

* 证据：`data/a12/reports/mother_geometry_audit/parts/V22.json` —— 声明 z 尺寸 38.0 mm
  （`thickness_mm`），**实测 z 跨度 6.0 mm = `bevel_mm`**；体积 271 476 mm³ ≈ 6 × 147.77 × 307.51，
  正好是"6 mm 薄板"而不是 38 mm 厚的碑板。
* 机制（`group_extrude.py:447-454`）：倒角体只挤出 `bevel` 高、放在 `z = thickness − bevel`，
  然后与整块板做 **`boolean_intersection`** → 交集就是那块 6 mm 板，32 mm 材料被丢掉。
  倒角应当是"差集/带削角的并集"，不是交集。
* 归因结论：算法缺陷，但**独立于 A1/A2**，只影响 V22，且只在该次抽样 `bevel_mm > 0` 时触发。

### (b) 参数与几何语义不一致 —— 1 例

**B1 V23 小雕像：`height_mm` 不是实测总高（V23）**

* 证据：声明 180.0 mm，实测本体 z 跨度 **169.68 mm**（短 10.32 mm，5.7%）。
* 机制（`group_composite.py:841-859`，纯算术，可复算）：躯干竖直方向 `c = 0.5*torso_h`，随后整体
  平移 `+0.5*torso_h + 0.15*head_h`，于是**底面抬离 z=0 有 `0.15*head_h = 6.48 mm`**；头部放在
  `head_c = 躯干顶 + 0.30*head_h`、半高 `0.5*head_h`，于是**顶端比声明矮 `0.05*head_h = 2.16 mm`**；
  合计 `0.20*head_h = 8.64 mm`（与实测 10.32 mm 同量级，差额来自超二次曲面的采样与实际锥化）。
* 归因结论：**语义不符**，不是轮廓算法缺陷；`height_mm` 目前是"名义高度"，实测总高系统偏小约 5.7%。

### (c) 设计如此 / 与声明相符 —— 7 例

| 器型 | 实测 | 判定依据 |
| --- | --- | --- |
| V13 盒 | z 70.00 vs 声明 70.00 | 完全一致 |
| V14 盖 | z 59.65 vs 声明 59.65 | 完全一致；`top/max r = 0.195` 是因为盖子向上收成把手，**设计如此** |
| V18 砖 | 45.02 vs 45.00 | 差 0.02 mm |
| V19 平瓦 | 33.12 vs 26.00 | 实测**更大**（`slope_mm=9` + `camber_mm=3` 抬高了一端），声明口径本身不含坡度 |
| V20 弧瓦 | 250.00 vs 250.00 | 声明 = `length_mm + tail_lift_mm + tail_drop_mm`，逐位相等 |
| V21 曲面板 | z 跨度 74.0 | `thickness_mm` 是**法向厚度**而非 z 尺寸（z 跨度 = 挠度 + 厚度 + warp），**不可比、记 n/a** |
| V24 装饰构件 | 97.66 vs 90.00 | 超二次体以原点为中心，z 跨度 2c = 90；实测 97.66（含重复场/调制）**更大**，达标 |

另外两类"看着像偏差、其实不是"的情况，明确**不计入缺陷**：

* **`z_rim` 是顶面坐标、不是高度**：15 个器型的 `z_rim_target − z_bottom` 天然比 `z_rim_target` 小
  `t_b/2`（例如 V02 的 37.25 vs 跨度 34.55）。这是口径，不是缺陷，本报告因此对这类器型只用
  **profile 口径**（`z_rim_target_mm` vs `profile.z_rim`）判断欠高。
* **多连通体不等于悬空**：V04/V05/V09/V10 的 `n_bodies > 1` 是"闭合壳相互嵌入"（间隙为负）。
  V15 灯盏"矮"（35 mm 深）是浅灯盏的设计，其 `-1.15 mm` 表示实测略高于声明。

---

## 4. 修复方案（本轮不改代码；以下方案可直接执行）

### 4.1 最小修法（只动 `synlab/mothers/vessels/common.py` 两处）

**P1 — `wall_points`：删掉末尾的降半径夹逼。**

```python
# 现状（common.py:212-216）
out: list[tuple[float, float]] = []
for rr, z in pts:
    if out and rr > out[-1][0]:
        rr = out[-1][0]
    out.append((rr, z))
return out

# 最小修法：采样点即结果（负半径已在 append 时用 max(rr, 0.0) 挡住）
return [(float(rr), float(z)) for rr, z in pts]
```

同时把函数 docstring 里"returned radii are monotonically non-increasing in z"一句改成事实描述
（半径随形状指数上升，`flare_mm` 可越过 `R_mm`），否则文档与代码继续互相矛盾。

**P2 — `monotone_radius_control_points`：把"半径不得回落"换成"z 必须前进"。**

```python
# 现状（common.py:157-159）：半径小于历史最大值就丢弃
for row in pts[1:]:
    if row[0] < kept[-1][0] - 1e-9:
        continue
    kept.append(row)

# 最小修法：中线必须在 z 上前进（真正会让 PCHIP 退化的是重复/倒退的参数点）
for row in pts[1:]:
    if row[1] <= kept[-1][1] + 1e-9:
        continue
    kept.append(row)
```

保留原有的"少于 3 点则报 `MOTHER_INVALID`"、"首点落到轴上"、"半径退化"三条守卫不变。
函数的**名字与职责需要一并改名/改文档**（例如 `advancing_control_points`），否则下一个人还会按
"monotone radius"的字面意思把半径单调加回来。

**为什么这样改是安全的**：折墙的真正守卫是 `geometry.py::build_shell_profile` 里**实测**的三道
（`offset_clearance` 顶点内切半径、`curvature_margin` 局部曲率半径、`_self_intersects`），
它们会在真的折叠时报 `MOTHER_INVALID` 并带上测量值；P1/P2 只是移除了在它们之外多加的过度约束。
**A3（V22）与 B1（V23）需要各自独立的小修**，不要混进同一个提交：
A3 把 `boolean_intersection([solid, chamfer])` 改为在整厚上做 `footprint.buffer(-bevel)` 的削角
（或对倒角体做差集）；B1 二选一——要么把 `height_mm` 定义成实测总高（把 `0.15*head_h` 的地面间隙
与 `0.05*head_h` 的顶部差额补进构建器），要么把字段改名为 `nominal_height_mm` 并把实测总高另记一字段。

### 4.2 修法实测模拟（进程内替换，不改仓库文件；`s11_fix_simulation.json`）

用与审计**完全相同的参数与种子**重建 24 器型：

| 器型 | 修前 profile z_rim | 修后 profile z_rim | 声明目标 | 修后短差 | 修后 QA |
| --- | --- | --- | --- | --- | --- |
| V06 罐 | 138.54 | **184.33** | 183.25 | −1.08 | ok |
| V07 瓶 | 41.75 | **245.40** | 243.25 | −2.15 | ok |
| V08 双耳瓶 | 130.67 | **234.38** | 233.25 | −1.13 | ok |
| V09 壶 | 134.51 | **184.93** | 183.25 | −1.68 | ok |
| V10 带盖壶 | 123.07 | **173.81** | 173.25 | −0.56 | ok |
| V11 坛 | 188.01 | **214.82** | 213.25 | −1.57 | ok |
| V16 香炉 | 119.96 | **150.08** | 149.25 | −0.83 | ok |
| V17 花盆 | 123.28 | 123.51 | 122.00 | −1.51 | ok |
| V01 碗 | 85.23 | 85.59 | 84.59 | −1.00 | ok |

* **24/24 仍然全部可建、全部 `audit_mother ok=True`、无新增失败**（原型参数点）。
* 宽度恢复：V01 `r_max 76.76 → 101.39`（声明 R=95）、V11 `→ 176.55`（声明 175.75）、
  V17 `→ 93.07`（声明 90.0）、V16 `→ 91.03`（声明 90.0）。
* **冻结谱系**（同参数、同种子）：

| 谱系 | 修前 z_rim | 修后 z_rim | 目标 | 盖/部件间隙 | geometry_hash |
| --- | --- | --- | --- | --- | --- |
| `LIN0004_V10_M06_PAT03` | 216.6014 | **357.7600** | 357.4524 | +137.48 → **−1.686 mm（座入）** | `fcaf1f14…` → `460aa23c…` |
| `LIN0006_V09_M09_PAT03` | 182.0457 | **305.9518** | 302.4642 | 连通体 2 → **1**（流/柄与壶身并上） | `f6a5558e…` → `efa5aa83…` |
| `LIN0014_V16_M07_PAT10` | 254.4300 | **366.9047** | 365.9070 | 足与体不再分离 | `a8423b90…` → `b6451ee6…` |

### 4.3 影响面清单（会改变什么）

**(1) 代码**：`synlab/mothers/vessels/common.py`（P1、P2 必改）；可选但不建议同批：
`synlab/mothers/vessels/group_extrude.py`（A3）、`group_composite.py`（B1）、
`synlab/mothers/api.py`（`_pre_gate` 的解析门与新闸门）。

**(2) 母体几何与哈希**：15 个 A1 器型的**全部**参数组合几何改变（半径轮廓），其中 7 个 A2 器型
连高度都变；`geometry_hash`、面积/体积/bbox、`profile_metrics`（`z_rim`、`r_max`、
`thickness_*`）全部改变。A1∪A2 之外的 9 个器型（V13/V14/V18/V19/V20/V21/V22/V23/V24）几何不变。

**(3) chart**：`revolve_charts` 的 `x_period_mm = 2π·r_max`、`area_mm2` 与 **profile arclength 表**
都来自轮廓，因此 15 个器型的 body chart 全部改变（周期、面积、`s` 参数化）。**依赖 `u = θ/2π`、
`s = arclength` 的所有下游（纹样栅格、退化算子的 chart 采样、观测图）随之改变。**

**(4) 冻结数据（实测清点，`s09_frozen_inventory.json` / `s10_release_coverage.json`）**：

* `data/a12/**`、`data/a12_exports/**`、`data/a12_demo/**` 中**带 vessel_id 的资产记录共 107 条**：
  * A1 受影响器型 **72 条**（V01 20、V02 17、V03 4、V04 4、V05 3、V06 2、V07 5、V08 2、V09 2、
    V10 7、V11 1、V12 3、V16 1、V17 1；**不含** V13/V14/V18/V19/V20/V21/V22/V23/V24）；
  * A2 受影响器型 **20 条**（V06 2、V07 5、V08 2、V09 2、V10 7、V11 1、V16 1）；
  * 其余 **35 条**属几何不受 A1/A2 影响的器型：V13 14、V14 2、V18 1、V19 3、V21 5、V23 10
    （V20/V22/V24 在 store 里目前没有带 vessel_id 的记录）。
* **12 个已冻结 release**，其中 `closed_loop` 的 8 个（`rel_8049cf187288_1790879886`、
  `rel_852ab2a1e4c3_1790880811`、`rel_852ab2a1e4c3_1790905541`、`rel_852ab2a1e4c3_1790909555`、
  `rel_852ab2a1e4c3_1790909572`、`rel_852ab2a1e4c3_1790909619`、`rel_b06f9f7e9508_1790880513`、
  `rel_fda083aa68a8_1790880205`）含 **V01、V02** → **受 A1 影响**；
  `cl_fresh` 的 2 个与 `pilot_gate` 的 2 个只含 V02 → 同样受 A1 影响。
  **目前没有任何 release 含 A2 器型**（这点很重要：A2 修好不会使已有 release 失效，
  但 A1 会）。命名清单见 `s10_release_coverage.json`。
* 基线文件：`data/a12/reports/_baseline/acceptance_summary_before.json`（含 `summary_hash`）、
  仓库根 `_baseline_acceptance.json`（UTF-16 编码，含基线验收结果）——**A1 修好后必须重算**。
* 既有审计报告（`data/a12/reports/failure_fix_store/**`、`l0_after_fix/**`、`mvs/**` 等）里的
  母体相关数字与 `geometry_hash` 会与实际几何不再对应（**历史记录不必删，但要标记为改前快照**）。

**(5) 测试**：`tests/a12/mothers/test_vessels.py`（几何哈希确定性、参数影响力）、
`test_sampling_and_store.py`（哈希往返）、`tests/a12/patterns/**`（多处 `geometry_hash` 前后一致性）
不受"确定性"影响，但**其数值基线需要按新几何重跑**；本轮新增的
`tests/a12/mothers/test_mother_geometry_audit.py` 里 5 个 `xfail(strict=True)` 会在修复后变成
**XPASS → 硬失败**，这正是"必须把断言转正"的提醒。

**(6) 采样/计划漂移（必须显式验证）**：`sample_parameters(..., require_feasible=True)` 会**真的构建
并审计**每个候选（`api._build_gate`），所以修复后若某些抽样点因为真实斜率/颈部而触发
`curvature_margin`/`offset_clearance` 拒绝，LHS 的**接受集合会变**，进而**谱系参数集与数量都会变**。
本轮只在 24 个原型参数点上验证了"没有新拒绝"，**不足以断言计划不漂移**——迁移步骤里必须实测比对。

### 4.4 迁移步骤（按顺序执行）

1. **落修法**：一个提交只做 P1+P2（`common.py`），提交信息写清"几何语义变更：壁面可上升、
   颈部不再被丢弃"。**同一提交**里把受影响 15 个器型的 `register_vessel(..., version="1.0")`
   升到 **`"1.1"`**——`_wrap_assembly` 会把 `registry_version` 写进每个母体 meta，
   这是最省事的"新旧可区分"标记；`REGISTRY.fingerprint()` 随之改变，API/清单能直接看出注册表换版。
2. **自检**：跑 `tests/a12/mothers/test_mother_geometry_audit.py` —— 预期 5 个 `xfail` 变成
   **XPASS**（严格模式会报错），把它们改成普通断言；再跑
   `data/a12/reports/mother_geometry_audit/s03_audit_vessel.py V01..V24`，
   对照 `s11_fix_simulation.json` 的修后数值（短差应落在 ±2.5 mm 内、`S3/S4` 全部消失）。
3. **计划漂移实测**：用同一 master seed 重跑规划，与旧计划的谱系三元组
   （`LIN*_V*_M*_PAT*`）与**逐参数**比对；把差异写成 `plan_drift_after_geometry_fix.json`。
   三元组变了就必须走 step 4 的新 release，**不能**复用旧 `lineage_id`。
4. **重生成产物**（按依赖顺序，每步都要重新记录 `geometry_hash`）：
   母体（`mother_mesh`）→ 纹样（`patterns`，含 chart 栅格）→ 断裂/碎片（`fracture`）→
   物理等级（`physical`）→ 观测（`observe`）→ 真值（`truth`）→ 导出与 release。
   建议写到**新的 store 根**（例如 `data/a12_exports/<profile>_geomv2/store`），不要就地覆盖旧 store。
5. **新 release**：发布新的 `rel_*`（`manifest_hash` 自然变化）；把受影响的 12 个旧 release
   标记为 **superseded**（保留 manifest 与 `frozen_at`，只加一个"superseded_by"注记），
   **不要**原地改写旧 manifest——冻结语义要求它们可复现。
6. **重算基线**：`_baseline_acceptance.json` 与
   `data/a12/reports/_baseline/acceptance_summary_before.json` 重新生成，旧文件保留为
   `acceptance_summary_before_geomv1.json`。
7. **A3/B1 单独排期**：若同一轮做，V22 的体积/厚度与 V23 的总高都会变，需要各自的影响面复核
   （V22 无 release 命中，V23 也无；但两者都在 `data/a12` 的资产里有记录）。

### 4.5 旧数据如何区分（三条独立标记，任一即可判定）

| 标记 | 位置 | 改前 | 改后 |
| --- | --- | --- | --- |
| `registry_version` | 每个母体 meta（`_wrap_assembly`） | `1.0` | `1.1` |
| `profile_metrics` 一致性 | 每个母体 meta | `z_rim ≪ z_rim_target_mm`（V06/V07/V08/V09/V10/V11/V16） | 两者相差 ≤ 2.5 mm |
| `geometry_hash` | 资产 meta / release manifest | 见 `s04_frozen_repro.json` | 见 `s11_fix_simulation.json` |

建议顺手在 `shell_profile` 的 `profile.metrics` 里增加一个**显式**字段
`z_rim_shortfall_mm = z_rim_target_mm − z_rim`（纯记录、不改几何），让"参数与几何是否一致"
成为资产里可直接查询的一列，而不必靠人重算。

---

## 5. 仍未解决项 / 需要人工确认设计意图

**必须由人确认设计意图的器型（本报告按"参数字面语义"判定，可能与实物意图不同）**：

1. **V02 深盘**：`wall_angle_deg=62` 经 `r_top = min(R, r_base + depth/tan(ang))` 得 `r_top=57.98 < R=95`。
   修好后盘壁会从 39.9 张到 57.98，**口沿仍是 116 mm 而不是 190 mm**。这到底是"深盘"就应如此，
   还是 `wall_angle_deg` 的口径不对（应从水平量还是从竖直量）？需要人确认。
2. **V15 灯盏**：`flare_mm=0.06*R`、`R=42.5`，修好后本体会张到 42.5（直径 85，与 `diameter_mm` 一致）。
   确认"灯盏最大直径 = `diameter_mm`"是设计意图。
3. **V07 瓶**：修好后颈部很长（`neck_length_ratio=0.32`，颈段占高度 32%），
   且实测会**略超**声明 2.15 mm（口沿 bulge）。确认超差容忍度（当前判据 2.5 mm）。
4. **V22 碑板**：`thickness_mm=38` 与 `bevel_mm=6` 同时存在时，期望是"38 mm 厚带削角的碑板"
   还是别的？本报告按字面判定为缺陷（实测只有 6 mm）。
5. **V23 小雕像**：`height_mm` 是"含地面间隙的名义高度"还是"实测总高"？决定 B1 是缺陷还是改名问题。
6. **V21 曲面板**：`thickness_mm` 与 z 跨度的口径确认（本报告判为不可比，未计入任何偏差）。

**其它未解决项（如实保留）**：

* **V10 盖裙仍是独立壳**：修好 A1 后盖会座入壶口（−1.686 mm 过盈），但 `_lid_part` 的
  `trimesh.util.concatenate` + `cleanup` 仍留下一个独立的 256 面壳（`n_bodies=3`）。
  要真正合并需改成布尔并集，会再次改变 V10 几何与体积——**本轮不做**。
* **V16 的足同样是独立壳**：`_foot_part` 用 `concatenate([cylinder, cone])`，默认参数下
  `n_bodies=7`（本体 + 3 足 × 2 壳）。与盖裙同源，未修。
* **V05 高足杯 / V04 杯的 `n_bodies=2`**：闭合壳相互嵌入，不影响水密与体积，属拓扑瑕疵。
* **现有 QA 闸门无法发现"参数与几何不一致"**：24/24 通过。建议新增一条**参数一致性闸门**
  （`z_rim` vs `z_rim_target_mm`、本体最大半径 vs 声明的 `R_mm`、各部件间距 ≥ 0），
  但这属于 `synlab/**` 代码改动，本轮写入范围不允许。本轮只在
  `tests/a12/mothers/test_mother_geometry_audit.py` 里固化了"当前闸门确实通过"这一事实。
* **采样/计划漂移未实测**（见 4.3(6)）：只验证了 24 个原型参数点，不等于整条 LHS 不失配。
* **A1 会改变 V01/V02/V13 系 release 的几何**，而 A2 不会——但**不能**据此认为可以先只修 A2：
  只修 A2 而保留 A1，几何会落在一个"半修"状态（颈部回来了但壁面仍是常量半径），
  产生第三套互不兼容的数据，比现状更糟。**P1/P2 必须同批落地。**

---

## 6. 证据文件与复算方式

全部脚本在 `data/a12/reports/mother_geometry_audit/`，**只读**（只 import 并测量，不写 `synlab/**`）：

| 步骤 | 文件 | 作用 |
| --- | --- | --- |
| s01 | `s01_find_v10_params.py` → `s01_v10_params.json` | 从 store 里捞出批产真实参数 |
| s02 | `s02_chain_probe.py` → `s02_chain.json` | 控制点链 + 直接调用 `wall_points` 的对照 |
| s03 | `s03_audit_vessel.py <VID>` → `parts/<VID>.json` | **每个器型单独进程**：构建 + 实测 + `audit_mother` |
| s04 | `s04_frozen_repro.py` → `s04_frozen_repro.json` | 冻结谱系重放（V10/V09/V16），与队友数字逐项对齐 |
| s05 | `s05_trace_helpers.py` → `s05_trace.json` | 追踪 24 个构建器的**真实** `wall_points`/`monotone` 调用与返回 |
| s06 | `s06_summary.py` | 控制台汇总 |
| s07 | `s07_inspect.py <VID>` | 单器型全量打印 |
| s08 | `s08_analyse.py` → `mother_geometry_audit.json`、`s08_symptom_table.md` | 汇总交付物 + 症状表 |
| s09 | `s09_frozen_inventory.py` → `s09_frozen_inventory.json` | 冻结资产清点 |
| s10 | `s10_release_coverage.py` → `s10_release_coverage.json` | release/基线覆盖 |
| s11 | `s11_fix_simulation.py` → `s11_fix_simulation.json` | **修法模拟**（进程内替换，不改仓库） |
| s12 | `s12_chain_exact.py` → `s12_chain_exact.json` | 冻结参数的精确数值链（修前/修后） |

复算命令（在仓库根）：

```powershell
# 单器型（低负载，逐器型单独进程）
.\.venv\Scripts\python.exe data\a12\reports\mother_geometry_audit\s03_audit_vessel.py V10
# 汇总（读 parts/ 与 s05_trace.json）
.\.venv\Scripts\python.exe data\a12\reports\mother_geometry_audit\s08_analyse.py
# 修法模拟
.\.venv\Scripts\python.exe data\a12\reports\mother_geometry_audit\s11_fix_simulation.py
# 只读审计测试（5 个 xfail(strict=True) 是"缺陷仍开放"的预期）
.\.venv\Scripts\python.exe -m pytest tests\a12\mothers\test_mother_geometry_audit.py -q
```

**确定性说明**：母体用固定种子
`make_rng(seed64(0xA12, <VID>, "mother_geometry_audit"), <VID>, "audit")` 构建；
同一参数 + 同一种子两次构建的 `geometry_hash` 完全相同（测试里有断言）。
冻结谱系重放用的是独立种子，因此 warp 的实现可以略有不同——V10 盖的体积因此与队友记录相差
11.6 mm³（0.003%），而 z 范围、面数、壶身体积**逐位一致**。这里如实标注，不把巧合当等价。
