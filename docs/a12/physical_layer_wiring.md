# A12 物理层接线（physical layer wiring）：接线点、开关、实测与仍未解决项

本文记录"物理层"（真实母体上的断裂后端：平面 / rough / 形态学）的**接线点**、**开关**、
以及本轮（2026-10-02）实测到的**三情形**。所有数字来自真实运行；**未放宽任何审计/预算/门限**，
未达标的项保留 FAIL 与真实数字并注明证据文件。

---

## 1. 接线点（真实代码位置）

| 层 | 入口 | 位置 | 作用 |
| --- | --- | --- | --- |
| 配置 | `configs/a12/fracture_morphology.yaml` | `generation_spec:` | 形态学实验的声明式配置（含 `backend`、精度、开关说明） |
| 配置 | `configs/a12/fracture_precision.yaml` | 新 | **本轮新增**：显式提高 `max_cells` 的声明 + 实测单元需求 + 耗时曲线 + 坡度约束状态 |
| API | `synlab/fracture/api.py::make_closed_cutter` | L208 | 唯一刀体入口；`BACKEND_MORPHOLOGY` → `_make_morphology_cutter`，其余 → `cut_mod.build_closed_cutter` |
| API | `synlab/fracture/api.py::fracture_event` | L273 | 事件入口；`plane/rough` → `event_mod.run_shared_cut`，`morphology` → `_morphology_event` |
| 高度场 | `synlab/fracture/cut.py::make_height_field` | L405 | 平面/rough 的冻结 Fourier 系数集（`target_rms_mm = 0` ⇒ 解析平面） |
| 高度场 | `synlab/fracture/morphology.py::build_morphology_field` | L1094 | 形态学场（穹 + 径向 hackle + rib + 坑 + 纤维） |
| 刀体 | `synlab/fracture/cut.py::build_closed_cutter` | L1204 | 细化定点 → 装配（顶/底/侧）→ 插值验证 → 水密/绕向/体积验证 |
| 三角化 | `synlab/fracture/cut.py::_Quadtree.cell_triangles` | L970 | 逐胞边界环 + 胞心扇形；`edge_extra` 默认 0 ⇒ 平面路径逐位不变 |
| T 型接头 | `synlab/fracture/cut.py::edge_extra_all` | L1154 | **本轮新增**：装配器级额外细分点（挂点消解） |
| 事件 | `synlab/fracture/event.py::run_shared_cut` | — | 共享刀体切两侧 → 碎片 + 审计（gap/法向/守恒/覆盖/歧义） |

**开关**：`SYNLAB_FRACTURE_MORPHOLOGY`（`synlab/fracture/api.py`）。
默认**关闭**：`fracture_event(backend="morphology_shared_cut")` 抛 `OPERATOR_NOT_REALIZED`，
**不静默降级**；置 `1` 后进入 builder（本轮实测仍被 `fracture.cut.verify` 拒绝）。

---

## 2. 三情形实测（本轮，2026-10-02）

证据：`data/a12_reports/tjunction/*.json`、`data/a12_reports/cutfix/plane_regression.json`。

### 2.1 情形 A：平面（`plane_shared_cut`）——控制组，逐位不变

| 项 | 实测 |
| --- | --- |
| 母体 | thin-bowl / box20 |
| `mesh_hash`（box20 平面） | `sha256:07d5a59a…`（与 §10 基线**相同**） |
| 同母体同 seed 逐位回归（冻结源码对照） | `mesh_hash` / 顶点 / 面 / 报告 / 碎片体积 / 审计 **全同** |
| `edge_use_histogram` | `{"2": 25344}` |
| 坏边 / 水密 / 绕向 / 体积 | **0** / True / True / 25 077.0838 mm³ |
| `realized_error_mm` | **0.0** |
| 新增自审 | `hanging_corner_points = 0`、`edges_missing_a_hanging_point = 0`、`edge_extra_histogram = {"0": 16384}` |
| 耗时 | 0.63 s（4 096 单元） |

**结论**：平面是**唯一能建成**的后端，且本轮改动对它**逐位无影响**。

### 2.2 情形 B：rough（`rough_shared_cut`）——仍未水密（FAIL）

thin-bowl，`target_rms_mm = 0.02`、预算 **0.011 mm**（测试用；0.01 mm 时同一配置停在插值验证，
见 2.4）、`max_cells = 90000`：

| 项 | 实测 |
| --- | --- |
| 状态 | `CUTTER_NOT_CLOSED`（`fracture.cut.verify`） |
| 坏边 | **1 623**（全部 `side` 型：顶-底混合竖直边） |
| `edge_use_histogram` | `{2: 415889, 4: 933, 6: 629, 8: 61}` |
| 轮廓顶点度直方图 | `{2: 3967, 4: 933, 6: 629, 8: 61}` ← **新根因**（§3.1） |
| 同向重复有向边 | **0**（本轮消解） |
| 悬挂角点 / 缺挂点的边 | **0 / 0**（本轮消解） |
| 面数 / 顶面顶点 | 279 924 / 68 684 |
| `realized_error_mm` / gap P95 | **无法给出**：刀体在验证阶段被拒，没有交付面 |

**与上一轮（§10.5）对比**：坏边 4 369（记录）→ 2 621（同夹具复现）→ 2 616（遍历方向 + 中点复用）
→ **1 623**（再加额外细分点），−63 %；同向重复有向边 86 → **0**。

### 2.3 情形 C：形态学（`morphology_shared_cut`）——仍不可测

| 项 | 实测 |
| --- | --- |
| 开关默认 | 关闭；`OPERATOR_NOT_REALIZED`（不静默降级） |
| 打开后 | 进入 builder，被 `fracture.cut.verify` 拒绝 |
| gap P95 / 法向 P95 / 守恒 / 覆盖 / 歧义 / 共轭点距离 P95 / `Ra` / `Rz` / 相关长度 / 脊线密度 | **无法测**——刀体未通过验证，交付面不存在。**不给替代数字** |
| 与平面基线对照 | 只能引用**模型层**数字（`analytic_field_request`）：`Ra` 0.392/0.377 mm、法向 P95 33.8°/31.8°，平面基线 `Ra` **1.103e-07 mm**、法向 1.7e-04° |

### 2.4 预算：精确需求（实测）与耗时

| 夹具 | 后端 | `target_rms_mm` | 预算 mm | 结果 | 单元数 | 耗时 s |
| --- | --- | --- | --- | --- | --- | --- |
| thin-bowl | plane | 0 | 0.01 | **OK** | 4 096 | 0.63 |
| thin-bowl | rough | 0.02 | 0.01 | `PRECISION_NOT_REALIZED` | 163 393 | 34.7 |
| thin-bowl | rough | 0.02 | 0.011 | `CUTTER_NOT_CLOSED` | 63 883 | 38.9 |
| thin-bowl | rough | 0.05 | 0.01 | `PRECISION_BUDGET_EXCEEDED` | 需 **164 002** > 90 000 | 65.1 |
| thin-bowl | rough | 0.05 | 0.01 | `PRECISION_BUDGET_EXCEEDED` | 需 **75 775** > 60 000（§10.4.2 同 seed 路径） | — |
| box20 | rough | 0.05 | 0.01 | `PRECISION_BUDGET_EXCEEDED` | 需 **284 263** > 90 000 | 207.0 |
| box20 | rough | 0.05 | 0.01 | `PRECISION_BUDGET_EXCEEDED` | 需 **411 394** > 320 000 | 141.8 |
| V18/M01 | rough | 0.05 | 0.01 | `PRECISION_BUDGET_EXCEEDED`（§6 已记） | 需 **432 343** > 400 000 | — |

**耗时曲线与显式预算声明**见 `configs/a12/fracture_precision.yaml`。
**没有**任何一处放宽 `error_budget_mm`（冻结在 `synlab/schemas/spec.py`）。

---

## 3. 仍未解决项（按优先级）

### 3.1 【阻断级】轮廓顶点度 > 2（新根因，已定位未修）

`edge_use_histogram` 里 4/6/8 次边与 `silhouette_degree_histogram {2: 3967, 4: 933, 6: 629, 8: 61}`
一一对应：共形边界上每个轮廓顶点的度必须是 2，度为 4/6/8 意味着**两条以上的轮廓环穿过同一顶点**，
每条"用一次"的边都生成一堵侧壁，侧壁的竖直边因此被用 4/6/8 次。
下一次应从**轮廓环连通性**入手（对 `top_edge_use` 里 `uses == 1` 的边建图，检查顶点度分布），
而不是继续调 `edge_extra` 的下潜深度。

### 3.2 【阻断级】rough 交付数字仍不可给

`realized_error_mm` 与共享面 P95 仍然**无法测**（刀体未通过验证）。**保留 FAIL，不给替代数字。**

### 3.3 【阻断级】形态学审计仍不可测

同上；形态学的 gap/法向/守恒/覆盖/歧义/共轭/`Ra`/`Rz`/相关长度/脊线密度全部**无法测**。

### 3.4 【资源】0.01 mm 预算下的真实单元需求（见 2.4）

thin-bowl 需 ≥ 75 775（另一 seed 路径 164 002）、box20 需 ≥ 411 394、V18/M01 需 432 343。
提高 `max_cells` 只让细化跑完，**不修复拓扑缺陷**。

### 3.5 【物理】坡度合理性约束未应用

`configs/a12/fracture_precision.yaml` 第 4 节：`status: OPEN_NOT_APPLIED`。
它是物理决策（改变请求起伏 → 改变 `realized_rms_mm` 与全部形态学表），不在精度修复里顺手做。
已确立的算术：0.01 mm 插值需求 ~ `sigma / lambda^2`。

### 3.6 【精度】`estimate_cell_demand` 低估（§9.3，未处理）

### 3.7 【配置】`FractureConfig.backend` 仍是封闭 `Literal`

`configs/a12/fracture_morphology.yaml` 的 `generation_spec.backend` 仍不能写
`morphology_shared_cut`；`synlab/schemas/spec.py` 本次**未改**（改 `Literal` 只会放宽配置校验，
不解决任何实测问题）。

---

## 4. 渲染（本轮未产出）

用户要求的"同一碎片 plane vs 形态学并排 + 断口高亮 + 正面/特写、长边 ≥1024 PNG"
**没有产出**：形态学刀体建不出来（2.3），没有可渲染的形态学碎片；对平面碎片单独出图不能回答
"像/不像真实断裂"这个问题（平面断裂面按定义不带起伏特征，§7 已实测「任何扫描档都看不到」）。
证据目录 `data/a12_reports/physical_layer/` 保持为空，**不用平面图冒充形态学图**。

Blender CUDA 可用（`synlab.observe.blender`）；渲染脚本模板在
`tests/a12/fracture/_render_physical_layer.py`，形态学刀体一旦建成即可复用。

---

## 5. 复现命令

```powershell
$r = "C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
# 平面 / 零振幅 rough / rough 夹具的拓扑实测（一行一夹具）
& "$r\.venv\Scripts\python.exe" -B "$r\tests\a12\fracture\_probe_cutter_measure.py" `
    --cases plane,zero,bowl-lo --budget 0.011 --max-cells 90000 --label final
# 平面逐位回归（临时装回冻结源码后逐位比较）
& "$r\.venv\Scripts\python.exe" -B "$r\tests\a12\fracture\_plane_regression.py"
# 分文件退出码
& "$r\.venv\Scripts\python.exe" -B -m pytest "$r\tests\a12\fracture\test_cut_triangulation.py" -q
```

---

## 6. 测试退出码（本轮，分文件，2026-10-02）

逐文件日志与退出码：`data/a12_reports/tjunction/pytest/*.log`、`pytest_exit_codes.csv`。

| 文件 | 退出码 | 说明 |
| --- | --- | --- |
| `test_cut_triangulation.py` | **0** | 4 passed + 6 xfailed（本轮新增断言，详见 `fracture_realism.md` §11.6） |
| `test_shared_cutter.py` | **1** | 3 个 `FAILED`，全部 `CUTTER_NOT_CLOSED`（rough 夹具）；与 §10.6 的失败名相同 |
| `test_event_qa.py` | **1** | `test_fixture_event_passes_the_a06_thresholds[rough_shared_cut]`；同 §10.6 |
| `test_morphology_event.py` | **1** | `ERROR at setup`（刀体建不出来）；同 §10.6 |
| `test_physical_layer_wiring.py` | **1** | 1 个 `FAILED` + 10 个 `ERROR`；**同源**（形态学/rough 刀体建不出来） |
| `test_multishell_shared_cut.py` | **1** | `configs/a12/next_experiment.yaml` 相对路径解析失败（**工作目录相对**，与本次改动无关；文件确实存在） |
| `test_morphology_model.py` / `test_interface_clip.py` / `test_impact_count.py` / `test_target_selection_and_lid_skirt.py` / `test_fracture_realism.py` | **0** | 无变化 |
| `pytest tests/a12/fracture -q`（整体） | **非 0** | 仍非全绿；**失败原因与改动前同类**（刀体不水密），无新引入的失败类别 |

**与 §10.6 基线的差异**：新增 `test_cut_triangulation.py`（0），其余文件的失败**名字与原因相同**
（`CUTTER_NOT_CLOSED` 及其派生 ERROR），坏边数字更小。`test_multishell_shared_cut.py` 与
`test_physical_layer_wiring.py` 需要**从仓库根或带 `rootdir` 的方式**运行才能解析
`configs/a12/next_experiment.yaml`（本轮按文件直接跑，故前者 1、后者 1）。
