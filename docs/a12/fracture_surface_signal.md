# 断面信号链修复（fracture surface signal）

> **对象**：断面（fracture / interface surface）在 4 跳链路上的信号——
> **损伤构件面归属 → 渲染 tag → 2D 像素 → 真值标签层**。
> **性质**：只写真机实测值。每个数字都给出复算命令与落盘产物；容差、命中率、像素占比全部与
> **真实断口面积（及投影面积）**对照，不做"看起来有信号"的调整。
>
> 仓库根 `C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab`；解释器 `.venv\Scripts\python.exe`
> （Python 3.12.14 / numpy 2.5.3 / trimesh 5.x）。
> 新库：`data/a12_iface/store`（本次新建）；`data/a12` **只读**（除 `data/a12/reports/**` 未写入）。
> 原始产物：`data/a12/reports/fracture_surface_signal/**`。

---

## 0. 一句话结论

| 指标 | 修复前（实测） | 修复后（实测，新库 2 条谱系） |
|---|---|---|
| `physical_component` 面归属 | **3 446 247 面 = 100 % `origin_kind=2`（歧义）**，断面 **0** | 222 061 面 → `0`:215 082 / **`1`(断面):6 417** / `2`:562 |
| 观测帧断面像素（`surface_tag=2`） | **0 / 312 213 504**（`data/a12` 37 件 `obs_result`，本次独立复算） | **1 962 像素 / 393 216**（2 帧，逐视图 **全部非零**） |
| `physical_truth` 的 `iface_*` | **0 个数组**（43 件，普查 §6.3） | **6 个数组 + 14 个 `iface*` 元数据键** |
| `visible_labels` 的 `iface_*` | **0 个数组**（41 件，普查 §6.3） | **5 个数组 + 6 个元数据键**（含逐视图断面像素） |
| 缺来源渲染目标 | 静默输出全 0 tag 图 | 结构化 `OBS_TARGET_PROVENANCE_MISSING` |

断面在 2D 里从"精确 0"变成**可测量、可定位**：断面像素占"成像到的物体"的 1.83 %，
与**前向投影**的断口面积占比（LIN0000 4.18 % / LIN0001 2.26 %）之比为 **0.91 / 0.76**（§5）。

---

## 1. 缺陷链（逐跳）

### L1 —— `physical/api.py` 把每个面都写成"来源不明"

修复前 `synlab/physical/api.py:522-531` 的两个分支**逐字节相同**，且都不读 clean 源面的任何通道：

```python
if component.meta.get("is_contamination"):
    origin = np.full(len(component.mesh.faces), 2, dtype=np.uint8)
else:
    origin = np.full(len(component.mesh.faces), 2, dtype=np.uint8)   # 同一份代码
with_face_attrs(component.mesh, origin_kind=origin)
```

本次**独立复算**（`run_iface_lineage.py --mode before`，产物 `before_after.json`）：

```
physical_component: 55 件（39 件扁平 face__origin_kind + 16 件 payload.mesh.face__origin_kind）
face__origin_kind 直方图 = {"2": 3446247}      → 断面面数 = 0
```

### L2 —— `resolve_target` 丢面属性，再用全 0 兜底

`synlab/observe/routes.py::resolve_target` 对 `PhysicalResult` 分支用
`trimesh.Trimesh(vertices=…, faces=…, process=False)` **重建**网格对象；新建 `Trimesh` 的
`metadata` 为空，于是 `chosen.mesh.metadata["face_attr_arrays"]` 里的 `origin_kind` /
`interface_id` **在进入渲染前就丢了**。随后 `else: surface_tag = np.zeros(n)` 整块归 0。

独立复算（37 件 `obs_result`，逐件只读 `surface_tag` 通道）：

```
{"pixels": 312213504, "histogram": {"-1": 221347167, "0": 90866337},
 "rim_pixels": 0, "observations": 37}
```

### L3 —— 断面真值只在 clean 层

`physical_truth` / `visible_labels` 的 payload 只写 `corr_*` / `visible_corr_*`，
clean 层的 `iface_*` 全部丢失（普查 §6.3：43 件 / 41 件，0 个 `iface_*`）。

### L4 —— **本次新发现**：`corr_interface_id` 永远不可能是 0

`synlab/truth/api.py::_correspondence_from_rows` 原为
`int(r.get("interface_id", -1) or -1)`：`0 or -1` 求值为 **−1**，
**第一个断面（`interface_id = 0`）的配对样本被静默改写成"无断面"**。实测
（`tests/a12/truth/_probe_iface_table.py`）：

```
bundle interface_id  修复前 [-1 -1 -1 …] (144 样本)   修复后 [0 0 0 …]
iface_corr_start/stop 修复前 [0, 0)  (空区间)          修复后 [0, 144)
```

这条缺陷决定"成对断口的 `corr_*` 引用"能否落地（§2.4 的 `iface_corr_start/stop`），故一并修复
（1 行；语义只向正确方向变：0 不再被当作"无"）。

---

## 2. 修法

### 2.1 三类面归属：只按**可证明的证据**分类

新增 `synlab/physical/api.py::classify_face_origin`
（`ORIGIN_PROVENANCE_VERSION = "origin_provenance_v1"`），逐面只用两个可测量证据：

| 类 | 判据（可复算） | 证据 / 容差 |
|---|---|---|
| **`0` 母体表面** | 面心到 clean 源面的**精确最近点**距离 `d <= tol_mm`，面法向与最近 clean 面法向 `|cos| >= 0.5`，且该 clean 面 `origin_kind == 0` | 继承 clean 面的 `interface_id` |
| **`1` 断面** | (a) 同一映射命中，但 clean 面 `origin_kind == 1`（继承型）；或<br>(b) 映射未命中（SDF 新生面）**且**落在算子**自己声明的 ROI 带**内（到声明 ROI 几何距离 `<= halo_mm`） | (b) 的 `interface_id` 取最近 ROI 源面的 id；源面无 id 时保持 −1，**不编造** |
| **`2` 歧义** | 映射未命中且不在声明 ROI 带内；以及一切映射无法接受的面（含通道长度不符） | 逐条计入 `ambiguous_reasons` |

**容差来源（不是调参调出来的）**

```
tol_mm = clip(0.05 + 0.5 * spacing_mm + realized_max_recession_mm, [0.05, 1.0])
         再 cap 到 0.5 * min_wall_mm（薄壁不被映射到对面）
```

* `0.5 * spacing`：损伤面是在**冻结 SDF 格**上重新提取的等值面，同一张真实表面可偏半个格子
  （`synlab/degrade/axes.py` P03 实测探针 spacing = 0.5246 mm）；
* `realized_max_recession_mm`：算子**实测**的最大凹陷（P03 L1 = 0.05 mm）；
* `0.5 * min_wall_mm`：薄壁下限保护。

三个输入与最终 `tol_mm`／`roi_band_mm`／`cos_min`／`roi{roi_kind, roi_source, n_faces}` 全部写进
资产元数据（`tol_basis` + `rule`），读者可复核。**声明 ROI** 即算子自己的 ROI：
`physical.fields.roi_faces(clean, fragment, recipe.roi)`（`{"kind": "interface"}` →
clean 的 `interface_id >= 0` / `origin_kind == 1` 面）；带宽度取算子自报的 `halo_mm`
（`_smooth_recession` 中 ROI 权重归零的距离），缺失时回退 3.0 mm 并记录。

**污染体单独处理**（`CONTAMINATION_UNMAPPED`）：污染体是沉积材料，在 clean 源面上没有对应表面
——把污垢壳映射到它覆盖的器壁等于"把脏东西标成母体表面"。因此污染体**不做任何映射**，整件记 `2`
并单列一类与理由；测试用**完全共位**的壳验证它不会被继承成母体表面。

### 2.2 持久化：资产里真的带 `face__origin_kind` / `face__interface_id`

* `attach_face_provenance()` 在 `apply_damage()` 的几何改变分支对每个组件
  `with_face_attrs(origin_kind=…, interface_id=…)`；
* `commit_physical()` 的 payload 是 `mesh_arrays(component.mesh)` → arrays.npz 里出现
  **`face__origin_kind`** 与 **`face__interface_id`**（键名实测见 §4.1）；
* 证据块写进 `physical_component.meta.face_provenance`（本组件）与
  `physical_result.meta.face_provenance`（整份报告：`totals`/`totals_fraction`/逐组件）+ `face_channel_arrays`；
* **identity level 0 不动源对象**：只写 `face_provenance = {"attached": false, "reason": …}`，
  源自己的通道仍然权威——不伪造标签。

### 2.3 渲染兜底：不许静默全 0

`resolve_target` 改为**证据阶梯**，并把"谁回答了"记进 `Target.meta["surface_tag_source"]`：

1. `MOTHER_FACE_SURFACE_TAG` —— 母体 `face_surface_tag`，原样透传；
2. `MESH_FACE_SURFACE_TAG` —— 网格自带 `surface_tag` 通道（`mvs_subset` 直接渲染 `mother.mesh`
   的路径此前同样是全 0，现在可读）；
3. `FACE_ORIGIN_KIND` —— `origin_kind` → `ORIGIN_TO_TAG = {0:0, 1:2, 2:6}`；
4. `FACE_INTERFACE_ID_ROI` —— 只有 `interface_id` 时，`>= 0` 即断面面（**与
   `physical.fields.roi_faces` 选择 ROI 的规则同一条**）；
5. `UNLABELED` —— 一条证据都没有：**默认抛结构化错误** `INPUT_UNAVAILABLE:
   OBS_TARGET_PROVENANCE_MISSING`（含面数/输入类型/找过的通道名）。确需渲染无来源网格的调用方
   必须显式 `allow_unlabeled=True`，此时 `Target.meta["surface_tag_absence"]` 记录结构化缺证块
   （"空 tag 图是缺证据，不是测量"）。

同时把**实测像素账本**写进观测元数据 `meta["surface_tag_pixels"]`（逐视图直方图、`rim_pixels`、
`rim_fraction`、目标面直方图、`tag_source`），"断面在图像里有多少像素"不必解包 mask 即可回答。

### 2.4 标签层：`iface_*` 带进 physical / visible

`measure_interface_faces(components)` 从损伤构件的 `origin_kind`/`interface_id` **面通道**实测逐断面
面数与面积；**通道缺失时记 `available: False` 并计数**（`iface_faces_without_channel`），
绝不把"没有通道"读成"没有断面"。

`physical_truth` 新增数组（行序 = `iface_id`）：

| 字段 | 语义 |
|---|---|
| `iface_id` | clean 事件声明的断面 id |
| `iface_area_mm2` | clean 层声明该断面的面积 |
| `iface_new_faces` | **损伤后**该构件上 `origin_kind == 1 且 interface_id == 该 id` 的面数 |
| `iface_new_area_mm2` | 上述面的面积 |
| `iface_corr_start` / `iface_corr_stop` | `corr_*` 中 `corr_interface_id == 该 id` 的半开区间（配对断口引用） |

元数据：`iface_ids`、`iface_pairs`、`iface_declared_area_mm2`、`iface_new_faces_by_id`、
`iface_new_area_mm2_by_id`、`iface_new_faces_total`、`iface_new_area_total_mm2`、
`iface_origin_kind_faces/area`、`iface_faces_with/without_channel`、`iface_field_semantics`。

`visible_labels` 新增数组：`iface_id`、`iface_corr_samples`、`iface_visible_samples`、
`iface_projected_samples`、`iface_visible_projections`；元数据 `iface_rim_pixels`、
`iface_rim_pixels_per_view`、`iface_rim_visible`、`iface_visible_samples_by_id`、
`iface_field_semantics`，并把这组计数同时写进 `qa`。**断面像素为 0 时字段仍然存在并写 0**
（`test_visible_truth_reports_zero_rim_pixels_when_there_are_none`）。

---

## 3. 容差标定：4 条已提交构件上的回溯分类实测

脚本 `tests/a12/physical/_probe_classify_origin.py`（**只读** `data/a12`，把新分类器套在已提交的
`physical_component` 上）；产物 `probe_classify_origin_4.json` + `classify_summary.txt`。
规则容差（spacing 0.5246、recession 0.05）→ **`tol_mm = 0.3623`**，ROI 带 3.362 mm：

| 谱系 | clean 面 | clean ROI 面积占比 | 损伤面 | `0` | `1` | `2` | 映射命中率 | `1` 类**面积**占比 | ÷ clean ROI 面积占比 |
|---|---|---|---|---|---|---|---|---|---|
| LIN0000_V01_M01_PAT01 | 6 382 | 3.731 % | 110 306 | 95 621 (86.69 %) | 3 456 (3.13 %) | 11 229 (10.18 %) | 88.80 % | **3.782 %** | **1.01** |
| LIN0001_V02_M01_PAT01 | 4 188 | 11.427 % | 108 217 | 100 502 (92.87 %) | 7 548 (6.98 %) | 167 (0.15 %) | 99.74 % | **10.720 %** | **0.94** |
| LIN0002_V13_M01_PAT01 | 1 570 | 28.039 % | 53 346 | 37 737 (70.74 %) | 15 252 (28.59 %) | 357 (0.67 %) | 97.88 % | **27.581 %** | **0.98** |
| LIN0003_V01_M04_PAT01 | 4 896 | 4.700 % | 125 838 | 121 725 (96.73 %) | 3 808 (3.03 %) | 305 (0.24 %) | 99.47 % | **4.182 %** | **0.89** |

`1` 类**面积**占比与 clean 层声明的断口面积占比之比在 **0.89–1.01**：
被标成断面的面确实就是断口本身，而不是容差放水放出来的。

**容差敏感性（LIN0000，同一件，只改 `tol_mm`）**

| `tol_mm` | 0.05 | 0.10 | 0.25 | **0.3623（规则值）** | 0.50 | 1.00 |
|---|---|---|---|---|---|---|
| `0` 面 | 81 905 | 86 534 | 93 045 | **95 621** | 97 541 | 102 368 |
| `1` 面 | 4 115 | 3 869 | 3 583 | **3 456** | 3 368 | 3 144 |
| `2` 面 | 24 286 | 19 903 | 13 678 | **11 229** | 9 397 | 4 794 |
| `1` 类面积占比 | 4.68 % | 4.36 % | 3.97 % | **3.78 %** | 3.62 % | 3.27 % |

容差放大 **20 倍**，断面面数只在 **3 144–4 115**（±14 %）、断面面积占比 3.27 %–4.68 %
（真值 3.731 %）之间。→ 不是容差挑出来的，是真实断口几何。

---

## 4. 端到端实测（新库 `data/a12_iface/store`，2 条谱系）

```powershell
& .venv\Scripts\python.exe tests\a12\observe\run_iface_lineage.py --mode run --only 0,1   # 冻结 pipeline 生成
& .venv\Scripts\python.exe tests\a12\observe\run_iface_lineage.py --mode observe-only     # 观测+可见标签（见下注）
& .venv\Scripts\python.exe tests\a12\observe\run_iface_lineage.py --mode measure
& .venv\Scripts\python.exe tests\a12\observe\run_iface_lineage.py --mode before           # 修复前对照
```

配置 = 冻结的 `configs/a12/sandbox.yaml`（`plane_shared_cut` + `P03_depth_light` L1 + `proxy_scan`
4 视图 / 256×192 交付），链路 = 冻结的 `synlab.pipeline.build_one_mother`（mother → pattern/material
→ fracture → clean truth → physical → observe → truth/labels），**只换存储根**。

> **`observe-only` 存在的原因**：本机被多个写者/会话共用，内存压力下 OpenCV 会在
> `_correlated_field`（G01 深度误差场）抛 `cv2.error: Unknown C++ exception`
> （`routes.py:1233`，实测复现见 §8）。因此观测/标签两跳由同一个冻结 API
> （`observe` / `commit_observation` / `update_visibility_truth` / `commit_truth`）在**已提交的**
> `physical_component` 上执行（= pipeline 第 7–8 步），资产同样落在新库里；`--mode run` 的
> `physical` 跳与它产出的 `physical_component` / `physical_truth` 完全一致（同一份数组与元数据）。

### 4.1 跳 1：损伤构件 `origin_kind` 直方图（从 arrays 读回）

arrays 键实测：`vertices, faces, face__origin_kind, face__interface_id`
（`face__interface_id` 为本轮新增通道）。

| 谱系 | 面数 | `0` | `1` 断面 | `2` 歧义 | 断面面占比 | 断面面积 mm² | 断面**面积**占比 | 映射命中率 | `tol_mm` | ROI 带 mm |
|---|---|---|---|---|---|---|---|---|---|---|
| LIN0000_V02_M01_PAT02 | 115 435 | 110 980 | **4 206** | 249 | 3.64 % | 385.79 | 6.32 % | 99.69 % | 0.3557 | 2.785 |
| LIN0001_V02_M01_PAT01 | 106 626 | 104 102 | **2 211** | 313 | 2.07 % | 2 648.96 | 2.83 % | 99.62 % | 1.0000 | 7.974 |
| **合计** | **222 061** | **215 082** | **6 417** | **562** | **2.89 %** | **3 034.75** | **3.04 %** | — | — | — |

逐 `interface_id` 面数（`face__interface_id` 直方图，实测）：
LIN0000 `{−1: 113 475, 0: 617, 1: 610, 2: 255, 3: 179, 4: 130, 5: 75, 6: 61, 7: 33}`；
LIN0001 `{−1: 105 819, 0: 428, 1: 184, 2: 97, 3: 61, 4: 25, 5: 12}`。

`physical_result` 元数据同样带证据块，实测（LIN0000 `asset_0ddb2ad1cfe9b43476ef`）：
`face_provenance.totals = {"0":110980,"1":4206,"2":249}`、`tol_mm = 0.3557`、
`roi_band_mm = 2.785`、`face_channel_arrays = ["face__origin_kind","face__interface_id"]`。

### 4.2 跳 2：观测帧 `surface_tag` 直方图（断面 tag 必须 > 0）

| 观测资产 | 谱系 / 目标 | `tag_source` | 像素 | 物体像素 | **`2`(rim) 像素** | rim/物体 | tag 直方图 |
|---|---|---|---|---|---|---|---|
| `asset_9703b08c8911fe7d3038` | LIN0000 / `…E01-p` | `FACE_ORIGIN_KIND` | 196 608 | 5 562 | **212** | 3.81 % | `{−1:191046, 0:5350, 2:212}` |
| `asset_54a6d4859f2f97861be1` | LIN0001 / `…E01-m` | `FACE_ORIGIN_KIND` | 196 608 | 101 643 | **1 750** | 1.72 % | `{−1:94965, 0:99893, 2:1750}` |
| **合计** | 2 帧 | | **393 216** | **107 205** | **1 962** | **1.83 %** | |

**逐视图像素数**（4 视图，全部非零）：

| 观测 | v000 | v001 | v002 | v003 | 逐视图 rim/物体 |
|---|---|---|---|---|---|
| LIN0000 `…-p` | **48** | **58** | **50** | **56** | 3.59 % / 4.02 % / 3.47 % / 4.18 % |
| LIN0001 `…-m` | **249** | **347** | **481** | **673** | 1.12 % / 1.35 % / 1.78 % / 2.54 % |

### 4.3 跳 3：标签层 `iface_*` 字段存在性与计数

| 层 | `iface_*` 数组 | `iface*` 元数据键 | 关键实测值 |
|---|---|---|---|
| `clean_truth` | 12（`iface_id/area_mm2/gap_p95_mm/normal_p95_deg/ambiguity_ratio/offset/points_a·b/normals_a·b/common_clip_area_mm2/pair_common_clip_area_mm2`） | 0 | `interface_count` = 9（LIN0000）/ 7（LIN0001） |
| `physical_truth` | **6**（`iface_id, iface_area_mm2, iface_new_faces, iface_new_area_mm2, iface_corr_start, iface_corr_stop`） | **14** | LIN0000：`iface_new_faces_total = 1 960`、`iface_new_area_total_mm2 = 243.29`、逐 id 面数 `[617,610,255,179,130,75,61,33,0]`；LIN0001：`807` / `1 385.19 mm²` / `[428,184,97,61,25,12,0]`；`iface_origin_kind_faces` = 构件直方图 |
| `visible_labels` | **5**（`iface_id, iface_corr_samples, iface_visible_samples, iface_projected_samples, iface_visible_projections`） | **6** | LIN0000：`iface_rim_pixels = 212`、逐视图 `{48,58,50,56}`、`iface_visible_samples = 185 / 878`；LIN0001：`1 750`、`{249,347,481,673}`、可见样本 `3 / 612` |

> 两处**口径差异**（都不掩盖）：
> ① `iface_new_faces_total`(1 960) < 构件 `1` 类面数(4 206)：差额是 `interface_id == -1`
>    的断面面（clean 层未把它们配进 patch，`fracture/event.py::_write_interface_ids`），
>    它们不进逐 id 统计，但仍计入 `iface_origin_kind_faces["1"]`。
> ② LIN0001 的 `iface_visible_samples` 只有 3：corr 样本是 clean 事件的一小组重心采样点，
>    "这些点是否可见"与"断面在图上占多少像素"是两个不同的量——后者由
>    `iface_rim_pixels = 1 750` 给出。

### 4.4 修复前 / 修复后对照表

| 跳 | 修复前（`data/a12`，本次独立复算） | 修复后（`data/a12_iface/store`） |
|---|---|---|
| 构件 `origin_kind` | 55 件 / **3 446 247 面 100 % = `2`**，断面 0 | 222 061 面 → `0`:215 082 / `1`:**6 417** / `2`:562 |
| 构件 arrays 键 | 39 件扁平 + 16 件嵌套，只有 `face__origin_kind` | `face__origin_kind` **且** `face__interface_id` |
| 观测 tag 直方图 | `{−1:221347167, 0:90866337}`，**无 `2`、无 `6`** | `{−1:…, 0:…, 2:…}`，逐视图 `2` > 0 |
| 断面像素 | **0 / 312 213 504** | **1 962 / 393 216** |
| `physical_truth` | 0 个 `iface_*` | 6 数组 + 14 键 |
| `visible_labels` | 0 个 `iface_*` | 5 数组 + 6 键 |
| `corr_interface_id` | 全 −1（含 `interface_id = 0` 的样本） | 0 保留 0 |
| 缺来源渲染目标 | 静默全 0 | 结构化拒绝（或显式 `allow_unlabeled=True` + 缺证块） |

---

## 5. 断面像素占比 vs 真实断口面积占比

三个口径都要摆出来（`_probe_projected_share.py`，产物 `probe_projected_share.json`）：

| 谱系 | ① 3D 断口面积占比 | ② **前向投影**断口占比（逐视图均值，`∑ area·max(0,n·u)`） | ③ rim 像素 / 物体像素 | ③ ÷ ②（逐视图比值的均值） | ③ ÷ ① |
|---|---|---|---|---|---|
| LIN0000_V02_M01_PAT02 | 6.32 % | 4.176 %（4.185 / 4.197 / 4.143 / 4.177） | 3.81 % | **0.913** | 0.60 |
| LIN0001_V02_M01_PAT01 | 2.83 % | 2.194 %（2.032 / 2.135 / 2.256 / 2.352） | 1.72 % | **0.762** | 0.61 |
| 合计（像素计数） | 3.04 % | — | **1.83 %**（1 962 / 107 205） | — | 0.60 |

**结论（三条，全部实测）**：

1. 直接用 ①（3D 面积占比）比会得到 0.60 的比值——**这不是标签丢失**，而是**斜视效应**：
   断口平面在这些视角下与相机成斜角，其**投影**面积只有 3D 面积的 66 %（LIN0000）/ 80 %
   （LIN0001）。②才是"相机真正看到的断面份额"。
2. 对 ② 而言，rim 像素占比为 **0.91 / 0.76**（逐视图比值的均值）：LIN0000 基本 1:1；LIN0001 偏低，
   且逐视图从 1.12 %（最斜）升到 2.54 %（最正对），与"斜视时断口被相邻母体壁遮挡/压缩"一致
   （②用的投影模型不含遮挡，因此它高估了可见占比）。
3. 与**全帧**比则更小：1 962 / 393 216 = **0.50 %**，因为交付视图里**物体只占 27.3 %**
   （107 205 / 393 216），其余是背景（`tag = −1`，渲染器不给背景写 tag）。

**量级判断**：断面占物体像素 1.8 %、占全帧 0.5 %；在 256×192 交付网格上约
**40–670 像素/视图**（4 视图 × 2 帧全部非零）。这是一个**稀疏但可定位**的信号——
可以说"断面能被模型看见"，但**不能说断面已被充分观测**；要提高可见度应当增加视角/贴近拍摄，
而不是改标签语义（本次按冻结配置 4 视图运行，没有为了让数字好看改配置）。

一个旁证：更早一次**完整 pipeline**运行（2 条谱系、每条 2 个端点共 6 帧）测得断面像素
**7 008 / 228 965 物体像素 = 3.06 %**，与 3D 面积占比 3.04 % 几乎相等（1.01 倍）——
该次运行的 store 已被重新生成覆盖，数字仅作为量级旁证记录在此，不作为主表。

---

## 6. 测试与退出码

逐文件执行（`tests/a12/observe/_run_in_scope_tests.py`，产物 `pytest_files.json` + 每个文件一份
`pytest_*.txt`），**13/13 文件退出码 0**：

| 文件 | 退出码 | 通过 / 跳过 / xfail（收集数） |
|---|---|---|
| `tests/a12/physical/test_face_provenance.py` | **0** | 8 / 0 / 0（8） |
| `tests/a12/truth/test_interface_layer.py` | **0** | 7 / 0 / 0（7） |
| `tests/a12/truth/test_persistence.py` | **0** | 5 / 0 / 0（5） |
| `tests/a12/truth/test_relations.py` | **0** | 9 / 0 / 0（9） |
| `tests/a12/truth/test_pipeline_contracts.py` | **0** | 9 / 0 / 1（10） |
| `tests/a12/observe/test_fracture_surface_signal.py` | **0** | 9 / 0 / 0（9） |
| `tests/a12/observe/test_coc_units.py` | **0** | 6 / 0 / 0（6） |
| `tests/a12/observe/test_pixel_contract.py` | **0** | 7 / 1 / 0（8） |
| `tests/a12/observe/test_mvs_subset.py` | **0** | 7 / 0 / 0（7） |
| `tests/a12/observe/test_renderer_dispatch.py` | **0** | 24 / 0 / 0（24） |
| `tests/a12/observe/test_carve_holes_bounds.py` | **0** | 174 / 0 / 0（174） |
| `tests/a12/observe/test_realism_config_and_bridge.py` | **0** | 20 / 0 / 0（20） |
| `tests/a12/observe/test_blender_backend.py` | **0** | 15 / 0 / 0（15） |

整目录：`pytest tests/a12/physical -q` → **0**（8 passed）；
`pytest tests/a12/truth -q` → **0**（31 passed, 1 xfailed，日志 `pytest_truth_all.txt`）。

新增断言要点：

* **physical**：容差规则（含薄壁 cap）；源面复制件 100 % 回投；**ROI 带内新生面 = 断面**、
  带外新生面 = 歧义（同一个面，只改 band）；跨面 sliver 不被映射；通道长度不符时**一个面都不认领**；
  污染体共位壳**不被映射**；level 0 不动源对象；提交 payload 里存在 `face__origin_kind` /
  `face__interface_id` 且断面面数 > 0。
* **observe**：`PhysicalResult` 的 provenance 进入渲染目标；只有 `interface_id` 时按 ROI 推导；
  母体 tag 透传；网格自带 `surface_tag` 可读；**无来源目标被结构化拒绝**（默认）与显式
  `allow_unlabeled=True` 下的缺证块；**真实渲染帧 rim 像素 > 0**；`route_proxy_scan` 的
  `meta.surface_tag_pixels` 逐视图可核。
* **truth**：`physical_truth` 的 6 个 `iface_*` 数组 + 键、面积 > 0、`corr_*` 切片非空；
  通道缺失记 `unmeasured` 而不是 0；`visible_labels` 的 `iface_rim_pixels > 0` 与逐断面可见样本；
  **rim = 0 时字段存在并写 0**；两次落盘往返。

### 6.1 运行环境噪声（实测记录，非测试失败）

* `pytest tests/a12/truth -q` 在 **31 passed / 1 xfailed、退出码 0** 之后，stderr 出现
  `Windows fatal exception: code 0x8007000e`（`platform._wmi_query`，解释器退出阶段，
  本机同时运行 40+ 个 python 进程）；
* 同一批运行里 `trimesh` 通过 `subprocess` 调 `git` 抓指纹时抛
  `UnicodeDecodeError: 'gbk' codec can't decode byte 0x94`（父进程按本地码页解码子进程 UTF-8 输出），
  发生在旁路线程，不影响产物。

---

## 7. 仍未解决 / 已知缺口（诚实清单）

1. **`2` 类里仍有真实缺口**：回溯实测 LIN0000 有 10.18 % 的面 / **17.07 % 的面积**落在 `2`
   （SDF 新生粗格面片：既不与 clean 面共位、也不在声明 ROI 带内；实测它们到 clean 母体表面的中位
   距离 0.0585 mm，很可能是同一面母体壁的粗格重采样，但**没有源三角映射可证明**，所以没有被判成
   母体表面）。把它标成 `0` 等于凭猜测发明来源，故保留。其余三条谱系只有 0.15 %–0.67 % 的面。
2. **非平面/起伏断面**仍不可产出（`warped_partition` / `fracture_modes` = `OPERATOR_NOT_REALIZED`），
   本链路只在**平面共享切**上被验证。
3. **断面仍不是独立 3D 资产**（21 个库中无断面 mesh role）；`iface_*` 只作为面属性子集与逐断面表格存在。
4. **`iface_new_*` 只统计 `interface_id >= 0` 的断面面**（见 §4.3 注①）；根因在
   `fracture/event.py::_write_interface_ids`（队友写入范围，本次未改）。
5. **断面像素稀疏**（占物体 1.8 %、占全帧 0.5 %，40–670 px/视图）；提高可见度需增加视角/贴近拍摄。
6. **未接入训练/交付包**：`deploy/obs/index.json` 的 `forbidden_channels` 仍禁止 `surface_tag`
   （既定契约，本次不动）；本节只保证**研究侧**（`obs_result` / 标签层）的断面信号真实存在。
7. **新库只有 2 条谱系**（冻结 sandbox 配置）；更大批次的 tag 直方图可直接用
   `run_iface_lineage.py --mode measure` 复用。
8. **`physical_result` 不含 mesh arrays**（记录型资产），故只有元数据里的
   `face_provenance` / `face_channel_arrays`；`face__origin_kind` 在 `physical_component` 上。
9. **本机资源竞争会让冻结 pipeline 的观测跳偶发失败**（见 §8），端到端因此拆成
   `--mode run`（physical 跳）+ `--mode observe-only`（观测/标签跳，走同一冻结 API）。

---

## 8. 改动面与并发说明

**只改**：`synlab/physical/api.py`、`synlab/physical/fields.py`（新增 `face_channel` 公开别名）、
`synlab/observe/routes.py`、`synlab/truth/api.py`、`tests/a12/{physical,observe,truth}/**`、
`docs/a12/fracture_surface_signal.md`、`data/a12/reports/fracture_surface_signal/**`、
新库 `data/a12_iface/store`。**未改** `synlab/fracture/**`、`synlab/degrade/**`、`synlab/mothers/**`、
`synlab/patterns/**`、`synlab/pipeline.py`、`synlab/storage/export.py`、`synlab/training/**`、
`configs/**`、`frontend/**`、`tools/**`、`data/a12/**`（除 `reports/`）、`data/a12_demo/**`。

并发事实（读数字时必须知道）：

* 本次工作期间**有其它写者实时改动本仓库**（`synlab/pipeline.py`、`synlab/degrade/**`、
  `synlab/fracture/**`、`synlab/observe/**`、`configs/a12/**`、`tests/a12/observe/**`）。
* 第一次端到端运行时 `synlab/pipeline.py` 正处于半写完状态：`_commit_provenance` 引用未导入的
  `SCHEMA_PROVENANCE`（`NameError`，`pipeline.py:2483`），每条谱系在**观测成功之后**中断。
  该文件**不在本次写入范围**，我没有改它；运行器里留有一个**只在名字缺失时**补绑定的钩子
  （`missing_pipeline_names()`），最终运行实测 `pipeline_names_restored = {}`（写者已自行修好）。
* 该写者随后**主动适配**了 `resolve_target` 的新契约（`_provenanced_box` 夹具，
  `tests/a12/observe/test_realism_config_and_bridge.py:78-93`）——即"缺来源目标必须显式声明"
  已被下游接受，而不是我单方面收紧。
* 本机同时有 40+ 个 python 进程（峰值单个 >2.8 GB），冻结 pipeline 的观测跳在内存压力下会抛
  `cv2.error: Unknown C++ exception`（`routes.py:1233` `_correlated_field` 的 `cv2.GaussianBlur`）。
  复现与定位脚本 `tests/a12/observe/_probe_g01_crash.py`（产物 `probe_g01_crash.txt`）实测：
  同一构件、同一 `ObsSpec`（4 视图 / 256×192 / max_render_pixels 49 152）下
  `render_mm_per_px = 1.2560`、`depth_sigma = 0.35 mm`、`correlation = 8.0 mm` →
  `sigma_px = 6.37`，随后 `route_proxy_scan` **成功**并给出 `rim_pixels = 1 750`。
  即：该崩馈与断面链路无关，是资源竞争下的 OpenCV 分配失败；`--mode observe-only` 因此逐条
  短进程执行观测跳。
* `data/a12_iface/store` 里保留了第一次失败运行的资产（已由内容寻址去重，同一 lineage 只保留
  最新那份；§4 的所有数字都取自**带 `face_provenance.attached = true` 的那一件**）。

### 复算清单

```powershell
$py = ".venv\Scripts\python.exe"
# 1) 修复前（独立复算）：37 件 obs_result 的 tag 直方图 + 55 件构件的 origin_kind
& $py tests\a12\observe\run_iface_lineage.py --mode before
# 2) 容差标定：4 条已提交构件上的回溯分类（只读 data/a12）
& $py tests\a12\physical\_probe_classify_origin.py --root data/a12 --lineages 4 `
      --out data\a12\reports\fracture_surface_signal\probe_classify_origin_4.json
# 3) 端到端（新库）
& $py tests\a12\observe\run_iface_lineage.py --mode run --only 0,1
& $py tests\a12\observe\run_iface_lineage.py --mode observe-only
& $py tests\a12\observe\run_iface_lineage.py --mode measure
# 4) 投影占比对照
& $py tests\a12\observe\_probe_projected_share.py --root data/a12_iface/store `
      --out data\a12\reports\fracture_surface_signal\probe_projected_share.json
# 5) 测试（退出码逐文件记录）
& $py tests\a12\observe\_run_in_scope_tests.py
```
