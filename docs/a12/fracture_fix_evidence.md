# 断裂链修复证据（共享刀具体 / 布尔 / 接口 / 真值）

本文件记录 `relicweave-synlab` 断裂链在**真实母体**上的复现、根因、修复与实测指标。所有数字都是
本机实测（脚本与原始 JSON 都在 `tests/a12/fracture/`、`docs/a12/evidence/`），没有估算值，也没有把
失败改写成 PASS。

* 仓库根：`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab`
* 解释器：`.venv\Scripts\python.exe`（Python 3.12.14，无 `python` 在 PATH）
* 本机限制（实测）：重负载 Python 进程会被宿主直接杀掉（退出码 `-1`，无 Python 异常），因此下述
  验证**分文件/分批**运行，并在表里标出哪些单元是被杀而不是失败。

---

## 1. 复现（修复前）

### 1.1 `make_closed_cutter` 在真实碗体上水密失败

```powershell
& .venv\Scripts\python.exe tests\a12\fracture\_repro_cutter.py --vessel V01 --material M01 `
    --backends rough_shared_cut --out docs\a12\evidence\repro_before_rough_V01.json
# 退出码 -1（宿主杀进程），与 tools/build_demo_assets.py 的 environment_findings 一致
```

`docs/a12/evidence/repro_demo_plane_V01.json`（demo 母体 V01，asset_167bef6a43a93438ec26，
7008 面、自身水密、边直方图 `{2: 10512}`）+ 平面刀具（16896 面、水密、`{2: 25344}`）→

```
[CUTTER_NOT_CLOSED] (fracture.cut.verify) cutter is not watertight: 17411 edges with != 2 incident faces
FRACTURE_CONSERVATION_FAIL (fracture.event.run_shared_cut) M_minus is not watertight after the boolean (faces=3900)
```

实测布尔输出（`_probe_boolean.py`，`probe_boolean_plane_V01.json`）：

| 对象 | 面数 | 边直方图 | 单面边 | 重合位置顶点 | 按位置焊接后 |
|---|---|---|---|---|---|
| M∩C | 3900 | `{1: 1248, 2: 5226}` | 1248 | 624 | 水密 `{2: 5850}` |
| M\C | 6284 | `{1: 1248, 2: 8802}` | 1248 | 625 | 水密 `{2: 9426}` |

### 1.2 demo 清单（修复前）

`data/a12_demo/demo_manifest.json` 的 `fracture` 分区：**0 OK / 6 FAILED / 2 BLOCKED**
（`warped_partition` = PENDING、`fracture_modes` = MISSING，两者都是结构化 BLOCKED，保持原样）。

---

## 2. 根因（逐条实测）

### 2.1 布尔输出非流形：Manifold 不合并“属性不同”的重合顶点

判决性实验 `_probe_property_weld.py`（`docs/a12/evidence/probe_property_weld_V01.json`）——同一个
布尔，只改顶点属性：

| 输入属性 | 结果 |
|---|---|
| 只有位置（3 列） | `boundary=0`，`dup=0`，`{2: 5850}`（水密） |
| `booleans.py` 的 7 列来源属性（mesh_id+tri_id+bary） | `boundary=1248`，`dup=624`，`{1: 1248, 2: 5226}`（非流形） |

**根因**：`manifold3d` 只焊接属性一致的重合顶点，而 `_vertex_properties` 给每个顶点写了
（末尾写入胜出的）三角形 id，于是切面上的重合顶点被保留成两份 → 边只被 1 个面使用。

**修复**（`synlab/fracture/booleans.py::_weld_coincident` + `_from_manifold`）：布尔输出按位置
（量化 1e-9 mm，float32 属性通道的量化远低于任何冻结预算）焊接，所有来源通道同步重映射，并把
`welded_coincident_vertices` 写进 mesh metadata。修复后 M∩C / M\C 全部边恰 2 面。

### 2.2 来源歧义判定把每个正常流形顶点都判成 AMBIGUOUS

修复前实测：`ambiguous area ratio = 0.958`、`source coverage = 0.0782`（→ 事件必然
`FRACTURE_CONSERVATION_FAIL`）。原因：`_TriangleLocator.locate` 只要“第二近的三角形距离差 ≤ 1e-4”
就判歧义，而布尔输出里绝大多数顶点是从母体继承的**网格顶点**，它天然被多个三角形共享。

**修复**：先要求投影落在三角形内（barycentric 在 `[-1e-6, 1+1e-6]`），再排除与最近三角形**共享
顶点**的候选（同一面片的候选不是“来源歧义”，只是正常的网格顶点）。修复后同一事件
`ambiguity = 0.0`、`coverage = 1.0000`（见第 4 节表）。

### 2.3 断面提取：把“擦边”和“只碰到切面一条边”的母体面当成新断面

* 用“点在刀具内”判断面：M⁻ 的**全部**顶点都在刀具内（M⁻ ⊂ C），因此 V18 上 1624 个面里有 966 个
  被标成断面，其重心距切面最远 **32 mm**（`docs/a12/evidence/_v18stages*.txt`）。
* 改成“顶点在刀具**边界**上”后仍有假阳性：母体面**只在一条边上碰到切面**时，3 个顶点里有 2 个
  恰好在切面上，按顶点多数表决就把整张面判成断面——V13 实测断面面积被放大到 **6071 mm²**
  （真实共享面约 1900 mm²），最大 3 张假面 `|dot(n, plane)| = 0.054`、`|w|` 最大 17 mm
  （`docs/a12/evidence/_v13overlap*.txt`）。

**修复**（严格逐面几何判据）：一张面只有在
(1) **三个顶点全部**在刀具表面 1e-4 mm 内，且 (2) 该面**自身**法向与它所在刀具面的法向
`|dot| ≥ 0.9` 时，才算断面。修复后 V13 断面面积 6071 → **1666 mm²**，未匹配面积比 0.89 → **0.135**。

### 2.4 接口配对按“列表位置”zip → 假配对

`_link_interfaces` 原先在每个源三角形分组内做 `list_minus × list_plus` 叉积，再把两侧面列表按
**位置** zip 起来采样。列表顺序没有几何含义，于是 V18 上出现
`interface gap p95 13.62 mm > 0.02 mm`、`normal reversal p95 90° > 2°` 的假补面对。

**修复**：改为**按面质心几何一对一匹配**（`_match_faces_by_centroid` → 之后升级为按 2D 重叠面积
匹配 `_match_faces_by_overlap`），并带法向反向守卫（`dot(n_a, n_b) ≤ -0.5`）；找不到配对的面与面积
计入 `unmatched_interface_faces / unmatched_interface_area_mm2`（**不静默丢弃**）。因为两侧对同一
离散刀具面的裁剪三角化通常**不是 1:1**，重叠匹配允许有限多对一（`max_partners_per_face=3`），
patch 面积改用**实测 2D 交叠面积**（`pair_overlap_area_mm2`），而不是两侧面面积的均值。

### 2.5 `build_interface` 里 `abs(hash_json(...))` 抛 TypeError

`fragment.py` 用 `np.random.PCG64(abs(hash_json({...})) % 2**63)` 播种，而 `hash_json` 返回
`"sha256:..."` 字符串 → `TypeError: bad operand type for abs(): 'str'`。该分支此前从未被执行到
（水密闸门先失败）。**修复**：新增确定性 `_stable_seed(payload)`（取哈希前 16 个十六进制位）。

### 2.6 `cut.py` 的 world 变换用了 R 而不是 Rᵀ（关键帧 bug，已由并行写者修复）

`basis_transforms` 的约定是 `local = R @ world + t`（R 的行 = e_u/e_v/n），其逆必须是
`world = local @ R + origin`。原实现写成 `world = verts @ R.T + t`，等于作用 R 而不是 Rᵀ，
**整把刀具被旋转到另一个坐标系**。实测（`_probe_frame.py`，`docs/a12/evidence/_v01frame.txt`）：

| 器型 | 母体顶点落在刀具实体内 | 按 basis（w≤0）应有 | 符合率 | 刀具 w 区间（basis 系） |
|---|---|---|---|---|
| V01 | 1157 / 3505 | 1752 | 0.613 | −142.161 .. +100.861（应为 −93.428 .. 0） |
| V18 | 11 / 262 | 129 | 0.512 | −46.79 .. +34.285 |

下游无法发现：错误坐标系里的刀具仍是合法闭合实体，布尔两侧依然互补水密、守恒通过。已把该 bug
（含一行修复与 `frame_roundtrip_mm` 自检建议）报告给并行写者；**该写者随后在 01:56:43 自行修复**，
本机复测（`_probe_frame.py`）：

```
V01: material vertices inside the cutter: 1752 of 3505; expected (w<=0): 1752; agreement=3505/3505 (1.0000)
V01: cutter w in basis frame: -93.428 .. 0.000   （= w_min − depth_margin .. 0，符合规格）
V13: agreement=683/683 (1.0000)  cutter w: -53.419 .. 0.000
```

`synlab/fracture/cut.py` 的其余重构（四叉树/共形细分）由该并行写者负责，本轮未改动该文件。

### 2.7 `rough_shared_cut` 在 0.01 mm 预算下超预算（真实资源结论，未放宽）

实测（demo 生成器输出，`docs/a12/evidence/_demo_fracture_run2.txt`）：

```
fracture:V01:rough_shared_cut  PRECISION_BUDGET_EXCEEDED: cutter refinement exceeded the cell budget
    (400000) while chasing a 0.01 mm budget at wavelength 0.2131 mm; the shortest wavelength is not relaxed
fracture:V13:rough_shared_cut  PRECISION_BUDGET_EXCEEDED ... wavelength 0.2581 mm
```

最短波长由包内守卫 `WAVELENGTH_MIN_MM = 0.2`（沙箱冻结配置 `min_feature_wavelength_mm: 0.5`）给定，
按 8 点/波长需要 0.025 mm 级单元，在 200 mm 量级域上不可行。**没有**任何地方放宽最短波长或粗化
网格来换取通过；按计划 10.1 第 3 步，正确路线是“高频只存在于材料交集带 + halo，远侧平滑衰减”，
这条带状自适应（含两侧同一离散 C、同一容差与 hash）**尚未实现**，因此两个 rough 单元保持真实
FAILED（详见第 6 节未解决项）。

---

## 3. 改动文件

| 文件 | 改动 |
|---|---|
| `synlab/fracture/booleans.py` | 输出顶点按位置焊接（修 2.1）；定位器“投影在三角形内 + 排除共享顶点候选”（修 2.2）；断面判据改为刀具边界距离 × 法向一致（修 2.3）；新增 `vertex_container_distance_mm` 诊断 |
| `synlab/fracture/event.py` | 断面面提取改为严格逐面判据（三顶点在刀具上 + 法向一致）；接口配对改为 2D 重叠匹配（含法向反向守卫、有限多对一、未匹配面积入账）；patch 面积改用实测交叠面积；`unmatched_interface_*` 写入事件 meta |
| `synlab/fracture/fragment.py` | `build_interface` 的播种改为确定性 `_stable_seed()`（修 2.5） |
| `synlab/fracture/api.py` | 未改动（`_secondary_event` 由并行写者修复，本机复测通过） |
| `synlab/truth/api.py` | **新增**：`finalize_clean_truth` / `update_residual_truth` / `update_visibility_truth` / `build_labels` / `commit_truth` / `load_truth` / `relation_audit`（§11.1 规则，见 `docs/a12/fracture_truth.md`） |
| `tests/a12/truth/{truth_fixtures,test_relations,test_persistence}.py` | 新增：2/3/4 块手算 fixture（A08）、R2/R1/TINY/UNKNOWN 判据、持久化往返、labels/features 分离 |
| `tests/a12/fracture/{test_shared_cutter,test_event_qa}.py` | 新增：封闭 C（水密/正体积/无 T 接点/预算拒绝/零幅回归）、A06 阈值、二次破碎祖先与 tiny |
| `tests/a12/fracture/_*.py` | 复现与诊断脚本（不含测试断言）：`_repro_cutter`、`_repro_demo_mother`、`_probe_boolean`、`_probe_property_weld`、`_probe_ambiguity`、`_probe_stages`、`_probe_frame`、`_probe_overlap`、`_run_event` |
| `docs/a12/fracture_fix_evidence.md` / `docs/a12/fracture_truth.md` | 本文件与真值层文档 |
| `data/a12_demo/**` | 生成器输出（清单与资产），由 `tools/build_demo_assets.py` 写入，未手工编辑 |

未改动（按写入范围）：`synlab/mothers|materials|patterns|physical|degrade|observe|cameras|storage|jobs|schemas|registry.py|roles.py|pipeline.py|config.py|cli.py|qc/**`、`tools/build_demo_assets.py`、`frontend/**`、`synlab/api/**`、`data/a12/**`。

---

## 4. 真实母体实测（plane_shared_cut，5 个器型）

命令（每个器型一条）：

```powershell
& .venv\Scripts\python.exe tests\a12\fracture\_run_event.py --vessel <V> --backend plane_shared_cut `
    --out docs\a12\evidence\event_<V>_plane.json
```

| 器型 | 状态 | 片数 | 接口 patch | 体积相对差 | 重叠比 | 共享面距离 P95 | 法向反向 P95 | 来源覆盖 | 歧义面积比 | 共享面积 mm² | 未匹配面积比 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| V01 | OK | 2 | 11 | 3.9e-09 | 0.0 | 0.0000 mm | 0.0147° | 1.0000 | 0.0 | 1938.1 | 0.000 |
| V13 | OK | 2 | 5 | 2.7e-08 | 0.0 | 0.0000 mm | 0.0032° | 1.0000 | 0.0 | 1666.0 | 0.135 |
| V04 | OK | 3 | 5 | 5.5e-09 | 0.0 | 0.0000 mm | 0.0003° | 1.0000 | 0.0 | 218.0 | 0.000 |
| V02 | OK | 2 | 6 | 4.1e-08 | 0.0 | 0.0000 mm | 0.0028° | 1.0000 | 0.0 | 2003.5 | 0.001 |
| V18 | OK | 2 | 8 | 2.5e-08 | 0.0 | 0.0000 mm | 0.0004° | 1.0000 | 0.0 | 835.3 | 0.000 |

阈值（计划 A06 / `configs/a12/qa_protocol_v1.json`）：体积相对差 ≤ 0.1%、重叠 ≤ 0.01%、
距离 P95 ≤ 0.02 mm、法向 P95 ≤ 2°、来源覆盖 ≥ 0.999、歧义面积比 ≤ 0.02（`spec.py`）——全部满足。
`未匹配面积比` 是**新增的诚实指标**（两侧三角化不是 1:1 时无法配对的断面面积占比）：V13 = 0.135
需要在下游把该比例纳入 R2 面积审计（见未解决项）。V18 在修复 2.4 之前是
`gap 13.62 mm / normal 90°` 的真失败，修复后通过。

### 其他后端

| 后端 | 器型 | 状态 | 证据 |
|---|---|---|---|
| `secondary_fracture` | V01 | OK（3 片、14 patch、体积相对差 4.1e-09、gap 0、覆盖 1.0） | `docs/a12/evidence/event_V01_secondary.json` |
| `rough_shared_cut` | V01 | FAILED `PRECISION_BUDGET_EXCEEDED`（λ=0.2131 mm，单元预算 400000） | demo 清单 |
| `rough_shared_cut` | V13 | FAILED `PRECISION_BUDGET_EXCEEDED`（λ=0.2581 mm） | demo 清单 |
| `warped_partition` | — | BLOCKED `OPERATOR_NOT_REALIZED`（未实现共形 PLC/形变，拒绝用平面替代） | demo 清单 |
| `fracture_modes` | — | BLOCKED `OPERATOR_NOT_REALIZED`（作者代码/许可未取得，近似替代被拒绝） | demo 清单 |

---

## 5. 命令与退出码

### 5.0 L0 主链（`synlab generate --config configs/a12/sandbox.yaml --json`）

```powershell
& .venv\Scripts\python.exe -m synlab.cli generate --config configs/a12/sandbox.yaml --json
# 退出码 0，status = QA_PASSED，耗时 348.5 s
# data/a12/reports/coverage.json: planned 4 / attempted 4 / accepted 4 / quarantined 0 / failed 0,
#   complete true, vessels [V01,V02,V13], materials [M01,M04], fracture_backend plane_shared_cut
# data/a12/reports/coverage_rows.json: 每个谱系 fragments 2、observations 4、interfaces 10、
#   physical_components 3、clean_truth/feature/label 资产均已提交（4/4 谱系一致）
```

即：**L0 主链端到端跑通（含新的 `synlab/truth`），accepted/attempted = 4/4，产物齐全。**

**但同一份报告里 `r2_pairs = 0`（4 个谱系都是 0）——这是一个已知缺陷，不是通过**：接口被按采样分块记录成
多个 patch，而 R2 面积阈值当前是**逐 patch** 判定，于是 10 个 patch 每个都低于冻结阈值（母体面积
1e-4 相对阈值 ≈ 10 mm²），整对关系落到 `TINY_CONTACT`。正确判据是**逐 fragment 对**汇总共享面积后再比
阈值（计划 §11.1 的“同一次 clean 事件的当前叶片共享真实材料新断裂面，面积超过阈值”）。补丁已经写好并
可一键应用：`docs/a12/_patch_truth_pair_area.py`（把 `_classify_patch` 的面积判定拆成“结构合格”
标记，并在 `_merge_pair_edges` 里按对汇总后判 R2/TINY/UNKNOWN/R1）。**该补丁本次无法落盘**：
`synlab/truth/api.py` 被另一个进程占用（`PermissionError [Errno 13]`，`os.replace`/`copyfile`/
独占打开全部被拒），因此当前 `r2_pairs=0` 必须按“未完成”记录，不能当作合格。

| 命令 | 退出码 | 说明 |
|---|---|---|
| `python tools\build_demo_assets.py --only fracture --force` | **1**（真实结果：4 OK / 2 FAILED / 2 BLOCKED） | 整批一次跑完，耗时 240.3 s |
| `python tests\a12\fracture\_run_event.py --vessel V01 --backend plane_shared_cut --out ...` | 0 | 逐器型跑（V13/V04/V02/V18 同为 0） |
| `pytest tests/a12/truth/test_relations.py -q` | **0**（9 passed） | 手算 2/3/4 块 fixture 与负例 |
| `pytest tests/a12/truth/test_persistence.py -q` | **0**（5 passed） | 三层真值持久化往返、labels 分离 |
| `pytest tests/a12/fracture/test_shared_cutter.py -q` | **-1**（被杀） | 整文件一次跑会被宿主杀掉；逐条运行结果见下 |
| ↳ `test_plane_cutter_is_a_closed_positive_solid` | 0 | 平面刀具水密、正体积、无重合顶点 |
| ↳ `test_plane_cutter_keeps_its_sides_and_bottom_away_from_the_material` | 0 | 侧面/底面远离材料、depth_margin 语义 |
| ↳ `test_height_field_never_shortens_the_admitted_wavelength` | 0 | 最短波长不被下调 |
| ↳ `test_unreachable_budget_is_refused_not_relaxed` | 0 | 1e-6 mm 预算必须结构化报错 |
| ↳ `test_zero_amplitude_rough_regresses_to_the_plane` | 1 | 见未解决项：零幅粗糙尚未回归到平面（cut.py 路径，并行写者负责） |
| ↳ `test_cutter_build_is_reproducible` | 1 | 同上 |
| `pytest tests/a12/fracture/test_event_qa.py::test_fixture_event_passes_the_a06_thresholds[plane_shared_cut]` | **0** | 24 mm 盒夹具 A06 全达标 |
| `pytest tests/a12/fracture/test_event_qa.py::test_conservation_denominator_keeps_every_component` | **0** | 含 tiny/debris 的守恒分母 |
| `pytest tests/a12/fracture/test_event_qa.py::test_clean_truth_of_a_fixture_event_is_consistent` | **1** | 真值层 R2 仍为 0（见未解决项 0） |
| `pytest tests/a12/fracture/test_event_qa.py -q` | **-1**（被杀） | 含真实布尔的重负载，需逐条运行 |

被杀（-1）的单元都记录为**未测**，而不是通过。

---

## 6. 仍未解决 / 未完成（诚实清单）

0. **真值层 R2 目前在真实/夹具事件上都还是 0（两个各自独立的原因，都不许当作通过）**：
   a. `synlab/truth/api.py` 的 R2 面积阈值仍是**逐 patch** 判定；接口按采样分块记录成多个 patch
      （V01 实测 11 个），每个 patch 面积都低于冻结阈值 → 整对关系落到 `TINY_CONTACT`。修复补丁已备好
      （`docs/a12/_patch_truth_pair_area.py`：结构合格标记 + 逐 fragment 对汇总面积后判 R2），但
      `synlab/truth/api.py` 被其他进程占用（`PermissionError`，`os.replace`/`copyfile`/独占打开均被拒），
      本轮无法落盘。
   b. 接口采样按“面 A 上取点 → 投影到面 B 的平面”进行；我的重叠配对允许**有限多对一**，于是不少采样点
      落在面 B 之外，`build_interface` 把这些行标为 ambiguous → patch 歧义面积比 > 0.02 → 真值层判
      `UNKNOWN`（实测 24 mm 盒夹具：32 个 patch 全部 UNKNOWN，reason `ambiguous_area_ratio>0.02`）。
      正确做法是计划 §30.5 的“同一 source triangle 下用现成二维交/差求公共覆盖 → disjoint patch
      polygons → 共享三角化 → 面积加权采样”，替换当前的逐面配对采样；这一步尚未实现。
   因此在应用 (a) 并实现 (b) 之前，`data/a12/reports/coverage_rows.json` 里 `r2_pairs = 0` 是真实读数，
   但**不是**合格状态；A06 层面的指标（守恒/重叠/距离/法向/覆盖/歧义）在 5 个真实器型上是达标的。
1. **`rough_shared_cut` 在真实母体上仍失败**：`PRECISION_BUDGET_EXCEEDED`，λ=0.2131/0.2581 mm、单元
   预算 400000。需要实现计划 10.1 第 3 步的“材料交集带 + halo 高频窗、远侧平滑衰减”并按资源实测；
   在此之前保持真实 FAILED，不放宽最短波长、不粗化。
2. **`cut.py` 的零幅粗糙回归与可复现性测试仍失败**（`test_zero_amplitude_rough_regresses_to_the_plane`、
   `test_cutter_build_is_reproducible`）：`cut.py` 由并行写者持有并持续改动，本轮未修改该文件；
   帧 bug（2.6）已由其修复，其余四叉树/共形细分与零幅回归仍需其收口。
3. **接口未匹配面积比**：V13 = 0.135（260 mm²），其余器型 ≤ 0.001。该比例已写入事件 meta，但尚未进入
   `audit_fracture` 的冻结判据（没有冻结阈值前不擅自设门）。建议下一步把它并进 A27 歧义/覆盖审计，
   并按计划 30.5 用“双侧多边形 2D 交/差 → disjoint patch”替换当前的逐面重叠配对，使该比例趋零。
4. **`warped_partition` / `fracture_modes`** 保持 PENDING / MISSING（结构化拒绝），未用平面或近似替代。
5. 本机重负载杀进程使 `pytest tests/a12/fracture tests/a12/truth -q` 无法一次跑完（exit -1）；
   已按文件/按用例分批给出退出码。
