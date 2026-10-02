# A12 断口外观层：让亚毫米起伏经**法向**进入 RGB（实测）

> **性质**：新增实现 + 实测报告。新增 `synlab/observe/fracture_appearance.py`、
> `configs/a12/imaging_fracture_appearance.yaml`、`tests/a12/observe/test_fracture_appearance.py`、
> `tests/a12/observe/_run_fracture_appearance.py`、本文件，以及
> `data/a12_reports/physical_layer/fracture_appearance_*` 与 `data/a12_fapp/store`。
> **没有**修改 `synlab/fracture/**`（并行队友在用）、`synlab/{degrade,physical,truth,relations,
> training,storage,pipeline.py}/**`、`blender_scripts/**`、`configs/a12/{next_experiment,
> fracture_physics,fracture_morphology,imaging_fracture_roi}.yaml`、`frontend/**`、`tools/**`、
> `data/a12/**`（除 `reports/physical_layer`）、`data/_archive_pre_fix/**`。
>
> **诚实规则**：
> 1. 每个数字都是**本次实测**（哪个脚本/哪个视图）或**引用**（谁的产物），逐条注明；
> 2. `dDN` 一律定义为**同一视角、同一几何、同一成像链、同一噪声种子**下
>    `relief_on` 与 `relief_off` 两幅图的**逐像素码值差**；未做任何上采样或后处理；
> 3. 断口几何本身**没有**被修好，由另一位队友负责；本层只把**同一套已审计的形貌场**经法向
>    送进图像。每个渲染都记录 `geometry_modified: false` 与几何哈希；
> 4. 未达标/未完成的项目**保留真实数字与 FAIL**，不用估计值填充。

---

## 0. 一句话结论

**法向通路是通的，但它的可见性有两个前提，两个都是本次实测出来的**：

1. **几何里必须有起伏**（`docs/a12/fracture_visible.md` §2.3：campaign 线 `below_1mm` 的
   `Ra` 实测恰好 0）——本层不能替代几何修复；
2. **断口必须被那盏冻结的灯照到**：冻结模型是"一盏方向光 + 与法向无关的环境项"，
   Lambert 项被 `clip(·,0,1)`。本次实测：V10/M11 的三个断口 ROI 在全部四个近摄方向上的
   `-(n·light)` 均为 **−0.79**（≈ **99.94 %** 的断口像素被夹在 0），此时**任何**法向扰动都
   无法改变一个码值（实测 `dDN` rms **1.02**、仅 0.2 % 像素变化）；
   而 V02/M01 `iface1_c000` 的 `-(n·light)` = **+0.783**，同一套起伏在 `Ra = 0.08 mm` 下给出
   `dDN` rms **24.69**、p95 **52.04**，**90.0 %** 的断口像素改变 ≥1 个码值。

在这两个前提都满足的视角上，结论是：**`Ra = 0.08 mm` 的断口起伏在 8 bit 图里是"看得见"的**
（24.7 个码值 rms），**而面片问题同时被实测出来并有两条件通路**（见 §3）。

---

## 1. 法向信号通路：实现与"它等价于冻结模型"的证明

### 1.1 实现落点

| 文件 | 内容 |
|---|---|
| `synlab/observe/fracture_appearance.py`（**新**，~1 700 行） | 逐像素法线渲染器、审计形貌场的外观实现、材料统计映射、面片度量、网格密度反解、釉层报告、A/B 出图 |
| `configs/a12/imaging_fracture_appearance.yaml`（**新**） | 开关（默认 `enabled: false`）+ `generation_spec` 块；`synlab.cli validate` **exit 0**（§7） |
| `tests/a12/observe/_run_fracture_appearance.py`（**新**） | 真实运行的 runner（阶段：sweep / facets / materials / glaze / images） |
| `tests/a12/observe/test_fracture_appearance.py`（**新**，21 用例） | 断言（§7） |

`render_appearance_view()` 与 `synlab/observe/render.py::render_view()` 共用同一个
`Scene`/`ViewFrame`/`LightSpec`/成像链，唯一区别是**着色法线逐像素求值**：

```
n = normalize(n_base - dh/du * t_u - dh/dv * t_v)
```

* `n_base`：`FLAT`（面法线，冻结行为）/ `SMOOTH`（面积加权顶点法线插值）/
  `SMOOTH_CREASE`（**面变化法线**：按折痕角保留真实棱边的逐角法线）；
* `h`：`synlab.fracture.morphology.MorphologyHeightField` 的解析高度场，在 ROI 平面
  `(u, v)`（mm）上求值；`gradient()` 是解析梯度，不做差分；
* 顶点与面**不变**，几何哈希逐视图记录。

### 1.2 与冻结模型**逐位一致**的证明（这是"同一模型"而不是"另一个着色器"）

三个断言（`test_fracture_appearance.py`，全部通过）：

| 断言 | 结果 |
|---|---|
| `FLAT` + `relief=False` + `interpolation="FROZEN"` 的本渲染器 vs `render_view(backend=SOFTWARE_RASTERIZER)` | `rgb_linear` / `id_map` / `surface_tag` / `depth_z` **逐位相同**（`np.array_equal`） |
| `lambert_ambient_linear(n_cam, T_WC)` vs `shade_world_normals(n_world)` | 一致（`atol 1e-12`）：`clip(-(R^T n_cam·l)) ≡ clip(-(n_world·l))` |
| 梯度恒为 0 的 relief 层 | 与 `relief_off` **逐位相同**（不存在"走了另一条路径"的隐性差异） |

> **口径修正（重要）**：`render._rasterise_buffers` 里名为 `world_normals` 的量其实是
> **相机系**法线（顶点是相机系的），它随后左乘 `T_WC[:3,:3]`；对刚体变换
> `R^T n_cam = n_world`，所以冻结光照的方向是**世界系**的。本次实现早期把扰动加在相机系法线上，
> 实测同一画面 `dDN` 只差 1.6 %（因为该视角的切平面几乎与两系重合），但这是**错的**，
> 已改为在**世界系**施加扰动再转回，并把这条口径写进 `lambert_ambient_linear` 的 docstring。

### 1.3 起伏从哪来：直接用已审计的形貌场（**不是随机噪声**）

`Ra` 与谱形都来自 `synlab.fracture.morphology` 的**已发表关系式**，本层只做求值：

| 量 | 关系式（`morphology.py` 原字符串） | 值 |
|---|---|---|
| 起伏 RMS | `sigma_r0 = c_g * grain * (1 + c_p * porosity)`（`c_g=0.12, c_p=2.0`） | M01 **0.4103 mm** |
| 频带 | `a(k) = a_ref (k/k_ref)^-(H+0.5)`，`H=0.75`，5 带，`λ_i = lc·2^(i-2)` | M01 `λ = 0.65/1.3/2.6/5.2/10.4 mm` |
| 带幅 | 归一化到 `Σ a_i²/2 = sigma_r0²` | `0.0165 … 0.5265 mm`（**红谱**：最长波带是最短波带的 32×） |
| 放射纹 | `N_hackle = clip(round(2π r_mirror/(2 grain)), 3, 48)` | V02/M01：`N=3`（`r_mirror` 3.07 mm） |
| 止裂线 | `a_rib = 0.45 σ_r0`，间距 `r_mirror` | 0.185 mm |
| 颗粒拔出 | `N_pit = porosity·A/(π r_pit²)`，`depth = 0.35 r_pit` | 80 个坑，`r=1.0 mm`，深 0.35 mm |
| 纤维 | `fiber_amplitude = 0.25 σ_r0 · fiber_amount` | M11：周期 5.5 mm，幅 0.091 mm |
| 釉层带 | `strip = t_glaze · k_geo`，`relief *= ratio`（`ratio=0.12`） | M04：带宽 0.44 mm，见 §4 |

**"不是白噪声"的实测证据**（`field_spectrum_report`，256² FFT）：
V02/M01 的形貌场 PSD 斜率 **−3.199**（白噪声为 0），1/e 自相关长度 **5.45 mm**
（材料自身相关长度 2.6 mm）——谱是**红**的、有相关长度的，不是逐像素噪声。

**圆锥状穹顶（dome）的处置（声明，不是隐藏）**：审计模型的 `_scale_params` 只缩放
带/放射纹/止裂线/坑/纤维，**不缩放**穹顶，即穹顶属于**形状**而不是**粗糙度**。本层默认
`include_dome=False`，并把审计穹顶数字一并记录（V02：`dome_radius_mm`,
`sag_over_footprint_mm`）。理由有两条是实测的：(a) 75 mm 画幅内它的矢高是近乎常数的倾斜，
对明暗对比贡献 ≈0；(b) `a12_iface` 谱系的**形状已经在几何里**。

---

## 2. dDN 实测表（三种幅度 × 各 mm/px 档）

**仪器**：`tests/a12/observe/_run_fracture_appearance.py --stages sweep`。
**试样**：V02/M01 `iface1_c000`（`data/a12_iface/store`，566 面 / 74.9 mm²，`lit_score=+0.783`）。
**视角**：`make_fracture_roi_frames` 的第 0 个方向（沿断口法向，60 mm，LOCAL 镜头）。
**幅度**：把审计场整体缩放，使它在 ROI 上**实测**的 `Ra` 等于目标值（缩放因子与实测
`Ra` 一并记录，不是"标称"）。
**像元积分**：`supersample=2`（≤1024 px 档），2048 px 档 `supersample=1`；**从不**上采样。

<!--TABLE_DDN-->

**读法（三条，都是实测）**：

1. `dDN` 随 `Ra` **单调**：0.02 → 0.08 → 0.4 mm 逐档上升（§7 的测试把这条钉住）；
2. `changed>=1` 列是**真正改变了至少 1 个码值的像素占比**——它是"看得见"的直接度量；
   8 bit 量化下，小幅度时"多数像素只改 0 或 1 个码值、少数像素改几十个码值"是正常形态
   （差值的 p50 = 0，p95 远大于 rms）；
3. `pred` 列是**用同一场的实测梯度**做的预测
   `dDN = 255 · mean_c(albedo_c·color_c) · (∂h/∂u·(t_u·l) + ∂h/∂v·(t_v·l))`，
   与实测同量级但不逐位相等（见 §6"未解决项"第 3 条）。

### 2.1 两条必须一起读的控制组（本次实测）

| 控制 | 设置 | 结果 | 含义 |
|---|---|---|---|
| **无光控制** | V10/M11 `iface1_c000`，`lit_score = −0.796`，`unlit_fraction = 0.9994` | `dDN` rms **1.02**、`changed>=1` **0.2 %** | 冻结 Lambert 被夹在 0 时，法向通路**一个码值也改不动**；这不是实现问题，是光照几何 |
| **噪声控制** | 同一渲染、只换成像噪声种子 | 无噪声极限 **0.159**；**出厂 `effective_gain=1` 时 100.63** | 出厂成像链的泊松噪声（1 光子/像素满量程）比 `Ra=0.08 mm` 的起伏信号（24.69）**大 4 倍**；起伏要"看得见"必须把光子尺度抬离 1 |

> `noise_control` 的第二个数字是本次最重要的**旁证发现**：`imaging.py` 的第 3 级
> `y = Poisson(g·x)/g`（`g = effective_gain = 1`）在场景辐照度 ~0.1–1 时把交付图变成
> **0/255 二值噪声**。本次所有起伏数字都在"同一条链的**无噪声极限**"（`effective_gain=1e6`，
> 方差 ∝ 1/g）上测得，并**同时**报告出厂增益下的数字，两者都进 JSON。

---

## 3. 面片抑制：两条路径的实测对照

### 3.1 路径①：渲染时用平滑法线（几何保留起伏，面片消失）

**仪器**：`--stages facets`，同一视角、同一几何、同一成像链；`SMOOTH` 用面积加权顶点法线，
`SMOOTH_CREASE` 用 35° 折痕的**面变化**逐角法线。
**面片边界 DN 阶跃有两个来源，本表把它们分开测**：
(a) **着色法线**的不连续（平滑法线可以消除），(b) **逐面反照率**的不连续
（`render.procedural_albedo` 给每个面一个调色板颜色——它也被渲染在同一张图里，
**任何法向通路都消不掉它**）。

<!--TABLE_FACETS-->

四条一起读：

1. **几何哈希逐视图相同**（`geometry_unchanged = true`，每个变体都等于渲染前的哈希）：
   平滑法线**只改着色法线**，不改一个顶点、一个面；
2. **常数反照率一列**隔离出法向通路：`FLAT` 的面片边界阶跃在平滑后**塌到面片内部量级**，
   也就是"三角拓扑不再可见"；这才是路径①能负责的部分；
3. **逐面调色板一列**是交付资产真实的样子：阶跃**几乎没有下降**——因为那个阶跃主要来自
   逐面颜色跳变。**这是本次新发现的一条面片来源**：即使法线完美，逐面反照率仍会把三角
   剖分画在断口上（每个面一个色块，18 px 的面就是 18 px 的色块）；
4. `SMOOTH_CREASE` 与 `SMOOTH` 的差别是**折痕**：碎片的外棱（断口-外壁交界）不该被抹圆，
   本次用 35° 阈值把真实棱边保住（`test_crease_angle_keeps_a_cube_edge_sharp` 钉住语义）。

### 3.2 路径②：按 `λ_min` 反解所需网格密度（真实的计算）

判据是**明暗判据**而不是 Nyquist 判据：一个横向尺度 `L` 的三角面只带**一个**法线，
它对真实表面的法向误差就是 `L` 尺度上的法向变化；要让这个误差小于最短波长 `λ_min` 上
法向摆幅的 `1/ratio`，需要 `L ≤ λ_min / ratio`（默认 `ratio = 8`）：

```
L = λ_min / ratio                 （面片棱长上限）
N = 4 A / (sqrt(3) L²)            （面积 A 上的等边三角形数）
N_cells = N / 2                   （四叉树每胞两三角）
```

**`λ_min = 0.65 mm`（M01 粗陶，`grain = 2.6 mm`、`lc = 2.6 mm` 的审计带集），两具真实碎片**：

<!--TABLE_DENSITY-->

**两条必须一起读的结论**：

* **`a12_iface` 谱系（V02/M01）本来就接近够密**：实测棱长中位 **0.574 mm**（= 7.9 px），
  与 `λ_min = 0.65 mm` 同量级，只差 **~50×**；
* **`plane_shared_cut` 谱系差得远**：V10/M11 的断口三角面棱长实测在 **9 mm 量级**（§3.1 的
  `median_face_area_px = 5388`），同一反解要求 `L = 0.081 mm` → 密度差 **~10⁵×**。
  这与并行队友在 `docs/a12/fracture_realism.md` §10.4.2 实测的**切割单元需求**（V18/M01 需
  **432 343** 单元、thin-bowl 需 75 775 单元）是同一件事的数量级——**几何路径的代价是真实的、
  可复算的**，本层的法向通路正是为了在这个代价兑现之前让起伏可测。

> **没有做的事（明确）**：本层**不**用上采样、不**用后处理模糊**去糊掉面片。
> 路径①改的是**着色法线**（几何哈希不变），路径②只是**反解需求**（没有改几何）。

---

## 4. 材料驱动：同一断口几何上的 ≥3 种材料

**仪器**：`--stages materials`。**同一块断口几何**（V02/M01 `iface1_c000`），只换材料记录，
其余（视角、相机、光、成像链、种子）逐位相同。材料统计全部来自
`materials.build_material_profile(id, default_material_params(id), make_rng(...))` 的真实调用。

<!--TABLE_MATERIALS-->

**读法**：`grain / porosity / σ_r0 / λ_min / fibre / transmission / glaze` 七个字段**都是材料记录里
实测的**，而它们各自对应一个可测的外观量：

| 材料统计 | 外观量 | 本次实测的差异 |
|---|---|---|
| `grain_scale_mm` + `correlation_length_mm` | 起伏的**横向尺度**（`λ_min`）与坑的尺寸 | M01 2.6/2.6 mm vs M07 0.08/0.08 mm（32×） |
| `pore_amount` → `porosity` | `σ_r0`（`Ra` 幅度）与**颗粒拔出坑**的密度/深度 | `σ_r0` 0.4103（M01）→ 0.0096（M07）= **43×** |
| `fiber_period_mm` + `appearance.fiber_amount` | **纤维撕裂方向性**（结构张量各向异性） | M11 周期 5.5 mm / 幅 0.8 → 各向异性指标见上表 |
| `appearance.transmission` | 扩散项权重（**声明**的扩展：`diffuse_weight = 1 − transmission`） | M07 0.82 → 对比度下降到 18 %（同表另列**不加权**的数字） |
| `layers[name~glaze].thickness_mm` | **釉层阻尼带**（审计项，见 §5） | M04 0.22 mm、M06 0.45 mm（**几何**釉层） |

`grain_pixel_statistics`（自适应阈值 + 连通域）给出**坑/颗粒在像素上的尺度**，
`directional_index`（结构张量）给出**方向性**——两者都测在交付图上，不是参数表。

---

## 5. 釉层台阶：断口边缘的釉层/坯体台阶在 RGB 里可见吗？

**结论：今天不可见，原因是"几何里没有这个台阶"；但它在法向通路下的两个可测后果已量化。**

### 5.1 交付资产里没有层通道（实测）

<!--GLAZE_ASSETS-->

四个研究体的断口资产（`data/a12_iface/store`、`data/a12_campaign/store`）的数组键只有
`vertices / faces / face__origin_kind / face__interface_id`——**没有任何面携带层或釉的 id**。
所以"釉层台阶"在当前交付几何里**不存在**，可见性无从谈起；缺的是**带层几何被断口切过**这一步
（`materials.layers.build_layer_shell` + `combo_geometric_layers` 的 L01/L03），
它属于生成侧（`synlab/materials/**`、`synlab/mothers/**`），不在本层。

### 5.2 真实几何层的厚度（实测，并修正一处文档数字）

`materials.build_layer_shell(create_mother("V01","M01",...), combo_geometric_layers("L01")[0])`
的实测 QA：

<!--GLAZE_SHELL-->

> **口径更正**：任务简报里的 `p05/median/max = 0.469/0.879/1.173 mm` 在**本 checkout 上复现不出来**。
> 它只存在于 `docs/a12/mothers_materials.md` 的正文与 `synlab/degrade/specs.py` 的冻结常量
> `GLAZE_THICKNESS_RANGE_MM = (0.469, 1.173)`；文档所指的生成脚本 `_doc_materials.py`
> **在树里和 git 历史里都不存在**，被它引用的 `mother_geometry_audit.json` 里也没有层记录。
> 按同一调用路径**今天**实测得到的是 **0.743 / 1.188 / 1.634 mm**（体积 55 265 mm³），
> 6 组种子/材料的扫描都复现不出 0.469。本文件只用**本次实测**的数字。

### 5.3 台阶的两条可测后果

1. **横向带**：台阶是宽度 `t` 的带，在 `mm/px` 下占 `t/mm_per_px` 像素；`t = 0.743 mm` 在
   0.073 mm/px 上是 **10.2 px**（可分辨），在 0.2719 mm/px 上是 **2.7 px**（勉强）。
2. **釉层阻尼带（真实可测，本次实现并渲染）**：审计关系式
   `strip = t_glaze · k_geo`、`relief *= ratio`（`ratio = GLAZE_ROUGHNESS_RATIO = 0.12`）
   在断口前缘形成一条阻尼带。本层把它实现为**沿真实断口边界**的距离变换栅格（不是圆），
   并在同一几何上做 `strip ON/OFF` 的真实渲染对照：

<!--GLAZE_STRIP-->

   所以：**若几何供给釉层台阶，本层今天就能把它渲染成"边缘一圈纹理变平"的可测特征**
   （带内 `dDN` 掉到 ~12 %），但**台阶本身的立体感**（侧壁朝向变化）仍然需要几何。

---

## 6. A/B 出图（看图判读用）

<!--IMAGES-->

> 全部 PNG 在 `data/a12_reports/physical_layer/`；每张图上标注 `mm/px`、`Ra`、`dDN` 与
> `facet edge DN`。渲染网格 = 交付网格（`upsampled=false`），2048 档是真渲染（不是放大）。
> 视图家族：`relief_off` / `relief_on` / `smooth_no_relief` / `smooth_relief` 四联。

**我的观察（逐条，对应本次实测数字）**：

1. `relief_off` 上肉眼看到的是**大块平板 + 硬边阶跃**（`facet_edge_dn_step` 量级几十个码值），
   与 `docs/a12/fracture_visible.md` 里"放射纹其实是扇形着色伪影"的判断一致；
2. `relief_on` 上出现**细密的颗粒状/丘壑状纹理**，与 `Ra` 同向增强；差值图 90 % 像素 ≥1 码值、
   86 % ≥2 码值，**它不是噪声**（噪声控制只有 0.16 码值）；
3. `smooth_no_relief` 上面片阶跃消失、留下断口自身的宏观形状；`smooth_relief` 是
   "干净底 + 起伏"的目标形态；
4. 三材料对照里 M01 的颗粒尺度最大、M07 最平滑且因 `transmission=0.82` 整体变"闷"，
   M11 的纤维方向性指标最高。

---

## 7. 复算命令与退出码（本次实测）

工作目录 = `C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab`，解释器 = `.venv\Scripts\python.exe`，
输出一律重定向到 UTF-8 文件再读。

| # | 命令 | 产出 | 退出码 |
|---|---|---|---|
| 1 | `python -m synlab.cli validate --config configs/a12/imaging_fracture_appearance.yaml` | `OK` + `spec_hash sha256:cdf1bdaa…` | **0** |
| 2 | `python tests/a12/observe/_run_fracture_appearance.py --stages sweep,facets,materials,glaze,images` | `data/a12_reports/physical_layer/fracture_appearance_run.json` + A/B PNG + `data/a12_fapp/store` | **0** |
| 3 | `python -m pytest tests/a12/observe/test_fracture_appearance.py -q` | 21 passed | **0** |
| 4 | `python -m pytest tests/a12/observe -q --tb=no` | 见 §7.1 | 见 §7.1 |

### 7.1 全目录回归（含既有测试）

<!--PYTEST_OBSERVE-->

---

## 8. 仍未解决项（不用估计值填充）

| # | 未解决项 | 为什么还没解决 | 谁能解决 |
|---|---|---|---|
| 1 | **断口几何仍是平的**（campaign 线） | 属 `synlab/fracture/**`（并行队友在修 T 型接头）。本层实测的是"通路已就绪"：同一套审计场在 `Ra=0.08 mm` 下给出 `dDN` rms 24.7，但**几何里必须先有它** | 形态学后端的精度预算（`docs/a12/fracture_realism.md` §9–§10） |
| 2 | **冻结光照把断口挡在阴影里** | 本次实测：四个研究体里只有 V02/M01 与 V23/M07 的断口被照亮（`lit_score` +0.78 / +0.73），V10/M11 与 V21/M06 为 **−0.79 / +0.19**。冻结模型是"一盏方向光 + 与法向无关的环境项 + 硬夹"，所以无光视角下法向通路**恒等于零** | 采集/渲染规格（是否允许为断口近摄调整光源方位，或引入与法向相关的环境项）。**本次未改冻结光照** |
| 3 | **预测与实测差 1.9 倍** | 预测用"场在 ROI 网格（0.108 mm 步长）上实测的梯度"，实测是"逐像素（0.073 mm）求值 + 2× 超采样积分"。差值来源未定位到单一项（坑缘、包络导数、法线归一化的二阶项都可能贡献） | 把预测改成**在与像素同一批点上求值**（需要渲染器回传命中点） |
| 4 | **出厂成像链的泊松噪声**（`effective_gain=1`）把任何起伏信号淹没（实测 100.63 vs 24.69 码值） | 属 `synlab/observe/imaging.py` 的冻结链；改它会改变既有 store 的每个字节 | 单独裁决（曝光/增益规格），本层只**同时报告**两种读数 |
| 5 | **釉层台阶的真实立体感** | 交付几何里没有层通道（§5.1），本层只能量化"若有"的横向带与阻尼带 | 生成侧把 `L01/L03` 的几何层切进碎片（`synlab/materials/**`、`synlab/mothers/**`） |
| 6 | **Blender Cycles 交叉验证未做** | worker（`blender_scripts/render_worker.py`）不接受法线/凹凸输入，而它**不在本次写入范围**内；把起伏做成真实几何在该分辨率下需要 ~10⁵ 倍的面数（§3.2） | 若需要：给 worker 加"法线图/凹凸"通道（属 `blender_scripts/**`，需授权） |
| 7 | **`realized Ra` 与真实台架对照** | 合成侧没有真实断口的高度场测量（`REAL_CAPTURE:PENDING`），本层所有 `Ra` 都是合成网格/审计场的自测值 | 真实采集后的轮廓仪/共聚焦测量 |
