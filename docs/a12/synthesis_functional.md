# 合成链功能普查与修复（24 器型，configs/a12/next_experiment.yaml）

目标：**让合成链对全部 24 器型都能跑通**（判据只有一条：功能正确性）。
配置 `configs/a12/next_experiment.yaml` 全程冻结（sha256
`818665310161…`，见 §8），不改判据、不跳审计、不吞异常。

- 普查驱动：`data/a12/reports/synthesis_functional_survey.py`（逐谱系、每步写盘、记录
  `error.code/stage/message` **与 traceback**）
- 汇总脚本：`data/a12/reports/synthesis_functional_merge.py`（合并分片到
  `data/a12/reports/synthesis_functional_survey.json`）、
  `data/a12/reports/synthesis_functional_census.py`（器型 × 结果表）
- 原始普查数据：`data/a12/reports/synthesis_functional_survey.json`
- 结果表：`data/a12/reports/synthesis_functional_table.md`

---

## 0. 结论

| 项 | 数值 |
| --- | --- |
| 普查器型 | 24（每器型 ≥1 条谱系；另加被点名的 `LIN0003_V23_M11_PAT06`） |
| 成功 | 见 §2（最终普查表） |
| 失败 | 见 §2 |
| 修掉的失败类 | 2 类：`FRACTURE_CONSERVATION_FAIL`（复合件布尔）、空布尔分片被误判为丢属性 |
| 未修通项 | 见 §7 |

修掉的两处都在 `synlab/fracture/**`，且都是**最小处**：

1. `synlab/fracture/event.py::_cut_both_sides` + `synlab/fracture/booleans.py::
   mesh_shells/concat_tagged` —— 多壳体母体必须**逐壳体**做 CSG；
2. `synlab/fracture/booleans.py::_from_manifold/_empty_tagged/concat_tagged` ——
   某一壳体整体落在刀具体一侧时布尔结果**真的为空**，这是合法结果，不是"属性通道丢失"。

两者都不放宽任何判据：刀具体字节不变、两侧仍由同一次离散切割产生、`audit_fracture_result`
照旧执行（体积/重叠/间隙/法向/来源覆盖/歧义全部照旧）。

---

## 1. 方法与复现命令

```powershell
# 逐谱系普查（每个进程只跑一条：本机长进程会被宿主杀掉）
pwsh -NoProfile -File data/a12_smoke/_tmp/run_census_loop.ps1 `
     -Root data/a12_smoke/_tmp/censusA -Out data/a12_smoke/_tmp/survey_finalA.json `
     -Indices "51,30,5,9,15,44,10,8,6,13,19" -Label census-A

# 指定谱系（复跑单个失败项）
.venv\Scripts\python.exe -X utf8 data\a12\reports\synthesis_functional_survey.py `
     --root data/a12_smoke/_tmp/censusA --out data/a12_smoke/_tmp/survey_finalA.json --indices 0

# 合并 + 出表
.venv\Scripts\python.exe -X utf8 data\a12\reports\synthesis_functional_merge.py `
     --out data/a12/reports/synthesis_functional_survey.json `
     data/a12_smoke/_tmp/survey_finalA.json data/a12_smoke/_tmp/survey_finalB.json
.venv\Scripts\python.exe -X utf8 data\a12\reports\synthesis_functional_census.py `
     --after data/a12/reports/synthesis_functional_survey.json
```

**为什么一个进程只跑一条谱系**：本机（2 物理核）长驻的 Python 进程会被宿主直接杀掉
（`exit -1/1`，无 traceback）。实测：三谱系同进程跑到第 3 条（正是被点名的那条）时进程被杀；
把每条谱系放进独立进程后，余项稳定完成。普查驱动每跑完一条就重写 JSON，所以即使被杀也只丢
在跑的那一条。

**为什么普查跑在"冻结副本"上**：本机同一工作区当时有**其它工作流在并发改动 `synlab/**`**，
实测两次误报都是别人改到一半的代码造成的（`synlab/observe/routes.py` 的 `IndentationError`、
`synlab/pipeline.py` 的 `NameError: name 'context' is not defined`，见下），而不是器型本身的问题。
为了让普查可复现、不被并发编辑污染，本次普查把当时的 `synlab/**`（174 个文件）复制到
`data/a12_smoke/_tmp/frozen_tree/`，用该副本的 `synlab` 包跑（`sys.path` 指向副本，
工作目录仍是仓库根，所以 `configs/**`、`third_party/**` 等输入不变），并把哈希清单写进
`data/a12/reports/synthesis_functional_code_state.json`：

- `synlab/fracture/booleans.py` = `sha256:033b2e6f999a3e90…`（本次修复 2 处都在这里）
- `synlab/fracture/event.py` = `sha256:da9e36c7e645f472…`
- `configs/a12/next_experiment.yaml` = `sha256:8186653101612cbc…`（冻结，未改）
- 其余 171 个文件见清单的 `frozen_tree.files`；清单里的 `frozen_matches_live`
  逐文件说明该副本与当时工作区是否一致。

被并发编辑污染的两条实测记录（**不是器型缺陷**，已在冻结副本上重跑）：

| 谱系 | 表面错误 | 真实原因 |
| --- | --- | --- |
| `LIN0051_V01_M10_PAT08` | `UNEXPECTED` / `IndentationError: expected an indented block after 'if' statement on line 275 (routes.py, line 277)` / 0.933 s | 另一工作流正在改 `synlab/observe/routes.py` |
| `LIN0021_V13_M04_PAT16` | 同上 / 0.2 s | 同上 |
| `LIN0020_V14_M08_PAT09` | `UNEXPECTED` / `NameError: name 'context' is not defined`（`pipeline.py:1716`）/ 48.7 s | 另一工作流正在改 `synlab/pipeline.py` 的 context 落章 |

---

## 2. 器型 × 结果（最终普查表）

<!-- CENSUS_TABLE -->

---

## 3. 失败类 A：`FRACTURE_CONSERVATION_FAIL`（V10、V24）

### 3.1 报告与复现

被点名的谱系：`LIN0000_V10_M11_PAT15`（V10 是复合件：body + 盖 + 盖裙）。

| | 值 |
| --- | --- |
| 错误码 | `ErrorCode.FRACTURE_CONSERVATION_FAIL` |
| 阶段 | `fracture.event.run_shared_cut` |
| message | `M_minus is not watertight after the boolean (faces=7466)` |
| 复现 | `python data/a12/reports/synthesis_functional_survey.py --root data/a12_smoke --indices 0`（2.7 s，frag=0 obs=0） |

### 3.2 根因（实测，不是猜的）

`synlab/mothers/vessels/group_composite.py::build_lidded_pot` 用
`build_vessel(parts, union=False, …)` 组装 —— 这是**设计**：注释写明盖裙与壶口是
"a real volumetric lap, not a point contact"，即三个闭合壳体**互相穿透**。实测（
`data/a12_smoke/_tmp/probe_boolean_deep.py 0`）：

```
mother 壳体: [6912, 768, 256] faces, 体积 [2209997.323, 5637980.707, 2117292.690] mm^3
壳体两两相交体积: [114708.813, 227806.509, 529292.115] mm^3   ← 三个壳体互相穿透
```

把"互相穿透的多壳体网格"当成**一个** CSG 操作数是无效输入：在壳体互相重叠处绕数没有定义。
Manifold 因此返回"几何上闭合、拓扑上不闭合"的结果：

| 对象 | faces | watertight | boundary edges | 4-面边 | 连通分量 |
| --- | --- | --- | --- | --- | --- |
| 整件布尔 M_minus | 7466 | **False** | 0 | **69** | 11（其中 10 个是 1-2 面的碎片） |
| 整件布尔 M_plus | 7738 | **False** | 0 | **124** | 71 |
| 整件布尔 M_minus（焊接前原始输出） | 7466 | False | **1882** | 0 | 7 |

进一步定位：原始输出有 987 个重合位置（属性分裂副本），`_weld_coincident` 合并后
边界边降到 0，却**产生** 69 条被 4 个面共用的边 —— 也就是说原始曲面本身不是合法的闭合
流形面，焊接只是把"开边"换成了"非流形边"。所以问题**不在焊接**，也不在刀具体坐标系
（刀具体 `watertight=True`、`realized_error=0`、母体顶点到平面无恰好为 0 者），而在
"多壳体互相穿透的网格被当作单一实体"这一输入前提。

### 3.3 修法（最小处）

CSG 的操作数必须是**一个合法实体**。既然管线本身就把"每个连通分量"当作独立碎片
（`fracture.fragment.split_components`），母体体积也按壳体求和，那么"逐壳体切割"才是与
管线其余部分一致的定义：

- `synlab/fracture/booleans.py`
  - `mesh_shells(mesh)`：把一个网格拆成若干闭合壳体，并返回每个壳体面在**母体中的原始
    三角形编号**（来源追踪不能用壳体局部编号）；
  - `concat_tagged(results, label=…)`：把逐壳体布尔结果拼回一个结果，逐片偏移顶点索引，
    `point/mesh_id/source_tri/bary` 四个通道原样保留。
- `synlab/fracture/event.py::run_shared_cut` 改调 `_cut_both_sides(source_mother,
  source_cutter)`：单壳体母体走**与原来完全相同**的代码路径；多壳体母体逐壳体做
  `M∩C` / `M\C` 再拼接。

没有放宽任何判据：`M_minus`/`M_plus` 仍必须 `is_watertight`，否则照样抛
`FRACTURE_CONSERVATION_FAIL`；`audit_fracture_result` 一字未改。

### 3.4 before / after（同一谱系，同一刀具体）

| | before | after |
| --- | --- | --- |
| M_minus | 7466 面，**不水密**，69 条非流形边，11 个分量 | 7430 面，**水密**，0 条非流形边，3 个分量 |
| M_plus | 7738 面，**不水密**，124 条非流形边，71 个分量 | 7612 面，**水密**，0 条非流形边，3 个分量 |
| 体积（两侧） | 5449360.623244 / 4515909.021605 mm³ | 5449360.623305 / 4515909.021646 mm³（差 6e-5 mm³，几何等同） |
| 事件 | `FRACTURE_CONSERVATION_FAIL`（2.7 s，frag=0） | 通过：frag=6，6 片全水密，interface=35，`overlap_ratio`=0.0，`volume_rel_diff`=1.079e-07，`source_coverage`=1.0，`gap_p95`=4.095e-06 mm |
| 端到端 | 事件即拒绝，obs=0 | `censusA`: `LIN0000_V10_M11_PAT15 OK frag=6 obs=72 r2=2 195.9 s` |

单壳体母体不受影响（这是"最小处"的关键证据）：

- 代码级：`_cut_both_sides` 对单壳体直接返回原来的整件布尔调用；
- 实测：V01（`LIN0051_V01_M10_PAT08`）逐壳体结果与整件结果**逐浮点相同**
  （vertices=True, faces=True）；
- 回归测试 `tests/a12/fracture/test_multishell_shared_cut.py::
  test_single_shell_mother_keeps_the_whole_body_path_bit_for_bit` 把这一点钉住。

### 3.5 这次修复实际触及哪些器型（逐一实测）

只有多壳体母体会走新路径。24 个器型的母体壳体数实测
（`data/a12_smoke/_tmp/probe_shells.py`，结果 `data/a12_smoke/_tmp/shell_census.json`）：

| 器型 | 壳体数 | 壳体面数 | 壳体是否互相穿透 |
| --- | --- | --- | --- |
| V05 | 2 | [3360, 96] | 是（内含：63.246 mm³ = 小壳体全部体积） |
| V10 | 3 | [6912, 768, 256] | 是（三对全部相交） |
| V15 | 2 | [3936, 956] | 否 |
| V16 | 11 | [14944, 48, 96, 96, 48, 48, 96, 48, 96, 48, 96] | 否 |
| V17 | 2 | [4048, 496] | 否 |
| V24 | 4 | [1936, 16, 12, 12] | 是（含内含：213.05 与 31390.67 mm³） |
| 其余 18 个 | 1 | — | — |

同一把刀具体下，**修复前的整件布尔**对每个多壳体器型是否会被守恒门拒绝
（`data/a12_smoke/_tmp/probe_prefix_gate.py`，结果 `data/a12_smoke/_tmp/prefix_gate.json`）：

| 器型 | 修复前整件布尔 M_minus | M_plus | 修复前结论 |
| --- | --- | --- | --- |
| V05 | 水密 | 水密 | 通过 |
| **V10** | 7466 面 / 69 非流形边 | 7738 面 / 124 非流形边 | **`FRACTURE_CONSERVATION_FAIL`** |
| V15 | 水密 | 水密 | 通过 |
| V16 | 水密 | 水密 | 通过 |
| V17 | 水密 | 水密 | 通过 |
| **V24** | 2554 面 / **242 非流形边 / 255 个分量** | 2574 面 / **262 非流形边 / 280 个分量** | **`FRACTURE_CONSERVATION_FAIL`** |

即：本次修复把 **V10、V24** 两个器型从"事件阶段即被拒绝"变成可跑通；对 V05/V15/V16/V17
是行为等价（仍逐壳体做，但结果与整件一致，见 §3.4 的等价性证据与回归测试）。18 个单壳体
器型走原路径。

---

## 4. 失败类 B：空布尔分片被误判为"属性通道丢失"（V24）

修完 §3 后 `LIN0058_V24_M06_PAT11` 立刻暴露出第二个、同源的缺陷：

| | 值 |
| --- | --- |
| 错误码 | `ErrorCode.SCHEMA_INVALID` |
| 阶段 | `fracture.booleans.source` |
| message | `M_minus: manifold dropped the source properties (got (0, 3))` |
| 耗时 | 2.2 s |

原因：V24 有 4 个壳体，其中 16 面和 12 面的内壳体**整体落在刀具体一侧**，逐壳体做交集时
结果**真的是空的**；`Manifold.to_mesh()` 对空结果返回 0 个顶点，而 `_from_manifold` 把
"0 行属性"当成"Manifold 丢了来源属性"直接抛错。

修法（`synlab/fracture/booleans.py`）：

- 新增 `_empty_tagged()`：空结果的合法表示（0 顶点/0 面 + 四个空通道）；
- `_from_manifold`：`faces.shape[0] == 0` 时返回空结果，而不是断言失败；真正丢属性的情况
  （有面但没有属性列）仍然照旧抛 `SCHEMA_INVALID`；
- `concat_tagged`：丢弃空分片；若一侧**整体**为空，返回空结果交由
  `run_shared_cut` 的 `minus.n_faces == 0 or plus.n_faces == 0` 判据处理
  （即"刀具体没有切到母体"仍然如实报 `FRACTURE_CONSERVATION_FAIL`，没有被吞掉）。

before / after：

| | before（整件布尔，修复 §3 之前） | 修复 §3 之后、§4 之前 | after（§4 之后） |
| --- | --- | --- | --- |
| M_minus | 2554 面 / 242 非流形边 / 255 分量 | `SCHEMA_INVALID`（空分片） | 见 §2 普查行（V24） |
| M_plus | 2574 面 / 262 非流形边 / 280 分量 | 正常 | 见 §2 普查行（V24） |

回归测试：`tests/a12/fracture/test_multishell_shared_cut.py`（含"整件布尔确实不闭合"的
负对照、空分片、通道对齐、单壳体逐浮点等价、真实 V10 谱系）。

---

## 5. 失败类 C：`UNEXPECTED`（`LIN0003_V23_M11_PAT06`，208.3 s，obs=0）

**这条我没有拿到可归因的根因，如实记录，不给推测当结论。**

已有证据：

1. 报告值：`FAILED UNEXPECTED`，frag=2，obs=0，208.3 s（`--root data/a12_smoke --batch 3
   --only 1,2,3 --resume` 的第 3 条）。
2. 存储证据（`data/a12_smoke/metadata.sqlite`）：该谱系已提交的资产止于 `clean_truth`
   （mother / fragment_mesh / material_profile / pattern_recipe / pattern_channels /
   clean_truth 都在，**没有任何 obs_result / feature_bundle / label_bundle**）。这说明失败点
   在 observe → visibility → labels 这一段，而不是母体/碎裂/实物阶段。
3. 单独复跑（当前代码、独立空库 `data/a12_smoke/_tmp/v23store`）：**通过** ——
   `frag=2 obs=24 r2=1 516.8 s`（`data/a12_smoke/_tmp/survey_v23_before.json`）。
4. 忠实复现报告的运行形态（同一进程连跑 `LIN0001 → LIN0002 → LIN0003`，
   驱动 `data/a12/reports/synthesis_functional_survey.py --indices 1,2,3`）：
   `LIN0001` OK 119.1 s、`LIN0002` OK 143.4 s，跑到 `LIN0003` 时**进程被宿主杀死**
   （exit 1，没有 ledger 行、没有 traceback，`data/a12_smoke/_tmp/survey_repro3.json` 只有
   前两条）。

结论：在当前代码树上，`UNEXPECTED` **无法复现为代码缺陷**；它在单独运行下成功，在多谱系
长进程里与"进程被宿主杀死"同时出现。报告里的 `208.3 s` 与"资产止于 clean_truth"这两点，
与该段正好是整条链 90% 墙钟所在的观察渲染段一致 —— 但我没有 traceback，因此**不把它归因
给任何模块，也没有为它改代码**（先编一个原因再"修好"会违反诚实规则）。若要真正定位，需要
宿主允许长进程存活并保留 traceback（本机当前不允许）。

---

## 6. 回归测试

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest tests/a12/fracture tests/a12/mothers tests/a12/observe -q
```

<!-- PYTEST_RESULT -->

### 6.1 三个套件的退出码（分目录、重定向到文件）

| 套件 | 命令 | 退出码 | 日志 |
| --- | --- | --- | --- |
| `tests/a12/fracture` | `.venv\Scripts\python.exe -X utf8 -m pytest tests/a12/fracture -q` | **1**（4 项失败，见 §6.2） | `data/a12_smoke/_tmp/pytest_tests_a12_fracture.log` |
| `tests/a12/mothers` | 同上换目录 | **0** | `data/a12_smoke/_tmp/pytest_tests_a12_mothers.log` |
| `tests/a12/observe` | 同上换目录 | **0** | `data/a12_smoke/_tmp/pytest_tests_a12_observe.log` |
| `tests/a12/fracture/test_multishell_shared_cut.py`（新增） | 单文件 | **0**（6 passed） | `data/a12_smoke/_tmp/pytest_multishell.log` |

### 6.2 `tests/a12/fracture` 的 4 项失败**不是本次修复造成的**（实测排除）

失败的 4 项全部在**粗糙切割面（rough cutter）**路径上，与本修复无关：

```
FAILED tests/a12/fracture/test_shared_cutter.py::test_rough_cutter_is_closed_and_within_budget
FAILED tests/a12/fracture/test_shared_cutter.py::test_cutter_build_is_reproducible
FAILED tests/a12/fracture/test_shared_cutter.py::test_default_cutter_reports_its_measured_error
FAILED tests/a12/fracture/test_event_qa.py::test_fixture_event_passes_the_a06_thresholds[rough_shared_cut]
    CUTTER_NOT_CLOSED (fracture.cut.verify) cutter is not watertight: 4486 edges with != 2 incident faces
    PRECISION_NOT_REALIZED (fracture.cut.verify) realized interpolation error 0.010090 mm > 0.01 mm budget
```

排除方法（可复现）：把整棵树复制到 `data/a12_smoke/_tmp/prefix_tree/`，**只把本修复的两处改回原样**
（`event.py` 恢复整件布尔调用、`booleans.py` 去掉空结果早退），再跑同样的 4 项：

```
cd data/a12_smoke/_tmp/prefix_tree
..\..\..\..\.venv\Scripts\python.exe -X utf8 -m pytest tests/a12/fracture/test_shared_cutter.py tests/a12/fracture/test_event_qa.py -q
→ 同样 4 项失败，exit=1
```

即：失败在"有/无本修复"两种树上**完全一致**，根因在 `synlab/fracture/cut.py`
的粗糙切割面自检（该文件当时正被另一工作流改写：697 行 diff），不属于本次改动范围。

### 6.3 新增测试的负对照（证明测试真的抓得住这个缺陷）

在**未修复**的 `prefix_tree` 上跑新增测试：synthetic 双壳体用例直接复现了报告里的同一类错误 ——

```
E  SynLabError: [ErrorCode.FRACTURE_CONSERVATION_FAIL] (fracture.event.run_shared_cut)
   M_minus is not watertight after the boolean (faces=4034)
```

在**已修复**的树上同一用例通过（两侧水密、0 非流形边、体积守恒、审计通过）。真实 V10 谱系
用例在 `prefix_tree` 上的失败原因是该副本缺少 `docs/a12/reuse_manifest.json`（复制遗漏，
非代码原因）；真实 V10 的 before/after 由 §3.4 的独立探针与 `prefix_gate.json` 给出。

新增测试（`tests/a12/fracture/test_multishell_shared_cut.py`，6 项）：

| 测试 | 覆盖的失败模式 |
| --- | --- |
| `test_mesh_shells_returns_each_part_with_its_parent_face_ids` | 逐壳体切割的来源追踪不能用壳体局部编号 |
| `test_concatenated_result_keeps_every_channel_aligned` | 拼接后 `point/mesh_id/source_tri/bary` 仍与顶点对齐 |
| `test_whole_body_boolean_of_interpenetrating_shells_is_not_a_closed_surface` | 负对照：整件布尔确实返回不闭合结果（0 边界边 + 非流形边） |
| `test_shared_cut_of_an_interpenetrating_assembly_is_closed_and_audited` | 逐壳体切割两侧水密、体积守恒、审计通过 |
| `test_single_shell_mother_keeps_the_whole_body_path_bit_for_bit` | 18 个单壳体器型结果不许动一个浮点 |
| `test_real_v10_lid_skirt_lineage_is_cut_into_closed_fragments` | 真实 V10 谱系（冻结计划参数）6 片全水密、审计通过 |

---

## 7. 仍未修通项与原因

1. **`LIN0003_V23_M11_PAT06` 的 `UNEXPECTED`**：无法复现（§5）。单独跑通过，同进程连跑三条
   时进程被宿主杀死且无 traceback。没有可归因的代码缺陷，因此没有改动。
2. **V13 `PRECISION_NOT_REALIZED`（`physical.sdf`）—— 全局 SDF 网格分辨率能力上限**。
   实测（`data/a12_smoke/_tmp/probe_physical.py 21`，结果 `probe_physical.json`）：

   | 量 | 实测值 |
   | --- | --- |
   | 谱系 / 目标片 | `LIN0021_V13_M04_PAT16` / `..._E01-m`（1 554 776.8 mm³） |
   | 配方 | `P03_depth_light`：`depth_mm = 0.05`，`corr_length_mm = 6.0` |
   | 目标片网格 | 1702 面，**watertight=True，winding=True，是合法体积** |
   | 网格间距 | **2.3835 mm**，`basis = min_wall_thickness/6 + node_budget_relaxation`，**`budget_ok = false`** |
   | `depth/间距` | **0.021**（声明效果是 2% 个格子） |
   | 零水平集（marching cubes on `d0`） | **watertight=False**，3 条边界边、5 条非流形边、6 个连通分量 |
   | 结果 | `intersect_with_source` 的 only-remove-material 守卫被 trimesh 的体积检查拒绝：`ValueError: Not all meshes are volumes!` → `PRECISION_NOT_REALIZED`（stage `physical.sdf`） |

   根因不是器型几何本身，也不是刀具体/布尔；是**该片在 600k 节点预算下被迫松弛到 2.38 mm 间距，
   这个间距连未扰动的零水平集都不是闭合流形**。V01/V02 用同一配方能过，是因为它们的片更小、
   间距更细（间距由 `min_wall_thickness/6` 与节点预算共同决定）。

   已有的正解在仓库里、但**只在退化路线**上接线：`synlab/degrade/narrowband.py` 与
   `synlab/degrade/physical_narrowband.py` 实现了窄带局部构造，`synlab/degrade/axes.py::
   NARROWBAND=True`（P02/P03/P04）走那条路；而**生成链**（`synlab/pipeline.py` 第 6 步 →
   `synlab/physical/api.py::apply_damage` → `synlab/physical/operators.py::run_damage` →
   `GEOMETRY_DISPATCH["P03"] = erode_interface`）仍走全局网格。把窄带后端接进生成链需要
   `DamageOutcome` ↔ `PhysicalResult` 的结果类型适配，属于 `synlab/physical/**` +
   `synlab/degrade/**`（当时正被另一工作流改动）的跨模块改动；按"最小处修改 + 不改别人正在改的
   模块"的约束，本次**没有**动它，如实记录为未修通项，并给出可直接落地的修法方向。
   仓库自己也把这一类记为已知限制：`synlab/degrade/narrowband.py` 写明随包审计
   `146 PASS / 9 FAIL / 0 NA`，失败项正是 P02/P03/P04 的亚格子效果。
3. **V14 `UNEXPECTED`（`cv2.error: Unknown C++ exception from OpenCV code`）**：
   `synlab/observe/routes.py::_resize_to`（第 843 行 `cv2.resize`），调用点 `routes.py:765`
   （`cluster = _resize_to(render.uncertain_mask, render_size)`）。本地实测 `cv2.resize`
   对**空**输入会抛带 OpenCV 版本信息的 `cv::Exception`（此路径已被 `_require_raster` 拦截：
   空 raster 会得到结构化的 `SCHEMA_INVALID`）；而 "Unknown C++ exception" 是 OpenCV 捕获到
   非 `cv::Exception`（典型为分配失败）时的措辞，因此这条更像**渲染/缩放期的资源或后端异常**，
   不是器型几何缺陷。V14 是单壳体（§3.5），本次修复对它**逐浮点等价**，与它无关；该文件当时
   也被另一工作流改动。普查的多次重跑会给出它是否可复现（见 §2 表里的尝试次数/最终状态）。
4. **宿主杀长进程**：这不是仓库缺陷，但它决定了本批数据的产出方式：一条谱系一个进程。任何
   想在一个进程里连跑几十个母体的批产命令（`synlab.cli generate` 全量、`--batch` 大于 1）
   在本机都会被截断，`tools/batch_generate.py` 的存在理由与实测一致。
5. 其余见 §2 表：若最终普查仍有个别器型失败，其错误码/阶段/真实 message/耗时都在表里，
   且每条都是真实分母。

---

## 8. 环境与代码状态

<!-- CODE_STATE -->

本次修复涉及的文件（哈希取自 `data/a12/reports/synthesis_functional_code_state.json`）：

| 文件 | sha256（前 20 位） | 说明 |
| --- | --- | --- |
| `synlab/fracture/booleans.py` | `033b2e6f999a3e9061ea` | 新增 `mesh_shells` / `concat_tagged` / `_empty_tagged`，`_from_manifold` 空结果早退 |
| `synlab/fracture/event.py` | `da9e36c7e645f472482a` | 新增 `_cut_both_sides`，`run_shared_cut` 改调它 |
| `tests/a12/fracture/test_multishell_shared_cut.py` | `f4f1ccec66cca2c9f3ad` | 新增回归测试（6 项） |
| `configs/a12/next_experiment.yaml` | `8186653101612cbc20e9` | **未改动**（与冻结前缀一致） |

- 配置 `configs/a12/next_experiment.yaml`：**未改动**（sha256 见上）。
- 本次改动仅：`synlab/fracture/booleans.py`、`synlab/fracture/event.py`、
  `tests/a12/fracture/test_multishell_shared_cut.py`、`docs/a12/synthesis_functional.md`、
  `data/a12/reports/*`（普查/汇总/出表脚本与证据）、`data/a12_smoke/**`（临时库与探针）。
- **注意**：本机同一工作区当时有其它工作流在并发改动 `synlab/**`（
  `synlab/pipeline.py`、`synlab/observe/*`、`synlab/degrade/*` 等在我作业期间被改动），
  所以本文所有 before/after 都以 §8 的哈希清单为准；跨工作流的"before"若与你的运行不同，
  先比哈希。
