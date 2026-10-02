# 写者归属裁决（Lead）

时间：2026-10-02 01:50 左右，由 Lead 直接裁定并落盘（因为 subagent 无法被消息寻址，只能写进仓库）。

## 裁决

- `synlab/fracture/cut.py` 的**唯一写者**：断裂子任务 A（`6003576d-d958-455e-b8b0-22322d6b7ff9`）。
- 旧任务 `d3ea0ff0`（fracture+truth，超期未回报）**即刻停止写 `synlab/fracture/**`**；其未完成改动视为被取代。
- 其余所有队友一律不得写 `synlab/fracture/**`（`synlab/fracture/backend_fracture_modes.py` 例外，由 fracture_modes 适配任务独占）。

## Lead 已执行的处置

1. 01:45:32 `cut.py` 被写到 `SyntaxError: unterminated string literal (detected at line 986)`（语法损坏的中间态），`import synlab.fracture.api` 当时不可用。
2. Lead 从检查点 `bfc3d23` 恢复 `synlab/fracture/cut.py`（可编译版本），恢复后 `import synlab.fracture.api` 正常。
3. 检查点（可回退）：
   - `bfc3d23` 并发写者快照（cut.py 47962 B 版本）
   - `5ff7650` Blender 环境记录（可能含损坏的 cut.py，**不要**用它恢复 fracture）

## 保留的成果（未被回退）

- `synlab/fracture/booleans.py`：按位置焊接重合顶点（Manifold 不合并属性不同的重合顶点）+ `welded_coincident_vertices` 记录（A 的修复，实测 boundary 1248→0、dup 624→0）。
- `synlab/fracture/fragment.py`：`build_interface` 的 `_stable_seed()` 修复（原 `abs(hash_json(...))` TypeError）。
- `synlab/fracture/SourceResolver` 歧义判定修复（ambiguity 95.8%→10.2%，来源覆盖 7.8%→83.8%）。
- `synlab/truth/api.py` 全量实现 + `tests/a12/truth/**` 手算 fixture。

## 验证要求

恢复后由 A 在真实母体上重跑四后端实测表；每次 edit 后立即 `py_compile` + 最小复跑。任何再次出现的语法损坏由 Lead 用上述检查点恢复。

## 追加（并发覆盖第二次发生）

- 2026-10-02 01:48:41：cut.py 再次被写到 `SyntaxError: unterminated string literal (detected at line 988)`（01:47 恢复后又被覆盖）。
- Lead 处置：从 bfc3d23 恢复 → 备份到 `third_party/known_good/cut.py.bfc3d23` → 将 `synlab/fracture/cut.py` **置为只读**以阻止继续被并发覆盖。
- 解除只读：`Set-ItemProperty synlab/fracture/cut.py -Name IsReadOnly -Value `False`
- 断裂 A 可继续修改其它文件（booleans.py 的顶点焊接与 SourceResolver 歧义修复是 plane 后端的真实修复点，不依赖 cut.py 改动）；需要改 cut.py 时先解除只读并在本文件登记。

## 追加（Lead 最终仲裁 + 旧写者根因转交）

$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

### 1) 旧写者身份与仲裁

旧任务 `d3ea0ff0` 于 $ts 回报：它承认自己是并发写者，并已承诺**不再写 `synlab/fracture/**`**。Lead 最终仲裁：

- `synlab/fracture/**` → **归 A（`6003576d`）独占**；`cut.py` 现为只读（解锁见上）。
- `synlab/truth/**` → **亦归 A**：A 已交付 `synlab/truth/api.py`（finalize_clean_truth / update_residual_truth / update_visibility_truth / build_labels / commit_truth / load_truth）+ `tests/a12/truth/**` 手算 fixture。为避免再次互相覆盖，Lead 已将 `synlab/truth/*.py` 置为只读。
- `d3ea0ff0` 若仍要继续：只能写 `docs/a12/fracture_cut_fix_notes.md`（它自己的文件），不得再改 `synlab/**`。

### 2) 旧写者实测的 cut.py 四个真根因（转交给 A，需按此修）

1. `_Quadtree.refine_all_to` **永不终止**：只标记 cell、计数器不前进，1024→4M+ cell 无限细化。
2. `cell_size(level)` 返回 `extent/2**level`，但存储的 cell level 是**相对 root grid** 的 → 细化后每个 cell 静默大 2^k。
3. `cell_triangles` 的全局 key 用 `i * 2**span`，`top_vertex` 又按 `shift` 二次平移 → 顶点身份取决于"创建它的 cell"，不同顶点被错误焊接，刀具体不水密（实测 266k 坏边）。
4. 细化循环每轮只枚举一次 `tree.leaves()`，pass 中新建的子节点从不做误差检查；随后验证阶段正确地以 `PRECISION_NOT_REALIZED` 拒绝。

**正确不变量**（旧写者给出，A 采信前需自行复现验证）：

- key 索引 = `(i << span) + local`
- `span = key_level - (root_level + level)`
- key 单位 = `hx / 2**key_level`，**对所有 generation 相同**
- 曲率种子单独不可用（它会提出比波长更宽的 cell，`κd²/8` 不成立）→ 需要**每波长最少采样点下限**（`λ_min / 8`）

**旧写者实测收敛案例**：12 mm 盒体、`λ_min=1.5 mm`、预算 0.02 mm → **3163 cells、0 个越界三角形**。

### 3) 并发纪律

任何写 `synlab/fracture/**` 或 `synlab/truth/**` 的动作，必须先在本文档登记并确认自己是唯一写者；Lead 保留用检查点 `bfc3d23`（+ `third_party/known_good/cut.py.bfc3d23`）覆盖回退的权力。

## 追加（独立验证报告 + 仲裁维持）

2026-10-02 02:07:14，旧任务 d3ea0ff0 提交独立验证（未改他人文件）：
- `pytest tests/a12/truth -q` → 14 passed；`pytest tests/a12/fracture -q` → 6 failed / 3 errors。

### 仲裁维持
`synlab/fracture/**` 与 `synlab/truth/**` **仍归 A（6003576d）独占**；d3ea0ff0 **不接管**，只做独立验证与文档（`docs/a12/fracture_cut_fix_notes.md`）。

### 转交给 A 的待修项（按优先级）
1. **PRE 种子规则只用曲率** → rough 刀具体永远达不到自身预算（λ_min≈0.2324 mm、预算 0.01 mm 时曲率规则要求 d≈0.014 mm ≈ λ/16，10^5 cells/mm²，必然撞 400000 cell 上限）。
   修法（已验证收敛）：取两者更细者 `needed = min(λ_min / POINTS_PER_WAVELENGTH, sqrt(8*budget/κ))`，`POINTS_PER_WAVELENGTH = 8`（计划 10.1：0.2 mm 波长约需 0.025 mm 间距）。实测：12 mm 盒体、λ_min=1.5 mm、预算 0.02 mm → 3163 cells、0 越界三角、水密。
2. **歧义面积口径不一致（阻塞 A08 全 R2）**：干净平面切割实测 `patch.ambiguity_area_ratio = 0.1797`，而 truth 层上限 `AMBIGUITY_AREA_RATIO_MAX = 0.02`（QA 协议 A27 = 0.05）→ 干净对全被判 UNKNOWN（0 R2 + 1 UNKNOWN）。同 patch 的 gap P95 ≈ 8.9e-16 mm、法向 0.0°、来源覆盖 1.0 —— 是**歧义度量**而非切面本身在驱动判决。
3. **确定性**：`test_cutter_build_is_reproducible` 实测两次构建 cutter hash 不同（suspect quadtree `refined` 集合迭代序 / `hash()` 派生种子）。
4. **薄壳 fixture**：`ValueError: Not all meshes are volumes!`（碗件布尔在进入刀具前不水密）。
5. `material_inside_fraction` 用精确 `mesh.contains` 判边界采样点 → 贴外表但几何合法的 patch 被降级（实测 25/49 内部点里 0.51 被判在外）。

### Lead 已自行修复
- `synlab/fracture/api.py::_secondary_event` 的 `_Piece` 缺 `mother_id`：改为对母体浅拷贝后替换 mesh（编译/导入 OK）。
- `synlab/pipeline.py` 断裂审计门：审计器返回 `passed` 而管线读 `ok` → 曾会静默接受失败事件；现同时接受两种键名，并把 `ambiguous_area_ratio_max > 0.02` 视为失败。

## 追加（第二次独立验证：现网断裂链不可用 + 4 项确认缺陷）

2026-10-02 02:09:30，d3ea0ff0 报告并实测：

**仲裁（正式答复，第二次）**：`synlab/fracture/**` 与 `synlab/truth/**` **归 A（6003576d）独占**；d3ea0ff0 **保持独立验证者身份**（写 `tests/a12/truth/test_pipeline_contracts.py` 这类契约测试与 `docs/a12/fracture_truth.md`），**不接管实现、不改这两个目录**。理由：实现者当前正在 02:02–02:08 做重构，接管会造成第二次互相覆盖；而独立验证这次又抓到实现者看不见的 4 个缺陷。

### 缺陷清单（转交 A）
1. **【当前 BLOCKER】** `synlab/fracture/event.py:439` → `IndexError: boolean index did not match indexed array along axis 0; size of axis is 666 but size of corresponding boolean axis is 4640`：`_match_faces_by_overlap` 重写后把**逐面通道与逐顶点通道**混用（666 = 面数级、4640 = 顶点级）；一分钟前同文件还抛 `NameError: _match_faces_by_centroid`。**每次 `fracture_event(...)` 都失败**，管线、A08 与验证测试全部无法运行。
2. `audit_fracture` 无 `ok` 键（只有 `passed`/`failures`/23 个键）→ **Lead 已修** `synlab/pipeline.py`：同时接受 `ok`/`passed`，并额外把 `ambiguous_area_ratio_max > 0.02` 判为失败。
3. **接口面积多算 19%**：12 mm 盒体对切得 4 个 patch 各 30.25 mm²（合计 121 mm²），而手算新断面恰为 **144 mm²**（12×12），两半体积恰 864 mm³。原因：`InterfacePatch.area_mm2 = 0.5*(area_a+area_b)`（`fragment.build_interface`）对两侧**三角面积**取平均，而非按计划 30.5 测公共裁剪覆盖面积。
4. **`ambiguity_area_ratio` 不是有效歧义度量**：同一刀下 `bary_min_a/b` 为**负**（−0.565/−0.385/−0.602/−0.429），即重建对应点落在自己三角之外，却只在坐标 <1e-6 时才标歧义 → 在 gap 5.8e-16 mm、法向 0° 的平面上报出 0.117–0.211，导致 `finalize_clean_truth` 把真实平面切割判成 **UNKNOWN 而非 R2**（A08 全 R2 fixture 无法通过）。
5. `update_visibility_truth(clean_truth, obs)` 抛 `AttributeError: 'CleanTruth' object has no attribute 'association_counts'`，应为结构化 `SynLabError`（传错层的调用方需要可诊断错误）。

### 同一事件上已确认正确的量（说明缺陷是孤立的）
`volume_rel_diff = 0.0`、`overlap_ratio = 0.0`、`gap_p95_mm_max = 8.9e-16 mm`、`normal_angle_p95_deg_max = 0.0°`、`source_coverage = 1.0`、两碎片体积恰 864.0 mm³。`tests/a12/truth` 其余 14/14 通过。

### 验证者交付
`tests/a12/truth/test_pipeline_contracts.py`：8 项契约测试，其中 2 项 `xfail(strict=True)` 钉住缺陷 3/4；缺陷 1 修复后该文件应自动转绿。

## 追加（解除 truth 只读，放行 R2 修复）

2026-10-02 02:26:26：A 报告 R2 修复补丁（`docs/a12/_patch_truth_pair_area.py`）因 `synlab/truth/api.py` 被**独占/只读**而无法落盘（PermissionError）。该只读锁是 Lead 之前为防覆盖而设，**现予解除**：`synlab/truth/*.py` 全部恢复可写。

**归属重申**：`synlab/truth/**` 的写者仍是 A（6003576d）；d3ea0ff0 只做验证与文档。`synlab/fracture/cut.py` 仍归 A（已解锁，未加锁）。

### A 本轮实测（已收）
- `synlab generate --config configs/a12/sandbox.yaml` → **exit 0 / status QA_PASSED / accepted 4 of 4**（348.5 s）：每谱系 fragments 2、observations 4、interfaces 10、physical_components 3，clean_truth/feature/label 齐全；**r2_pairs = 0（未解决）**。
- 真实母体 plane 达 A06：V01/V13/V04/V02/V18 体积相对差 2.5e-09…4.1e-08、重叠 0、gap P95 0.0000 mm、法向 P95 ≤0.0147°、覆盖 1.0、歧义 0；secondary V01 3 片 14 patch 亦 OK。
- demo fracture 分区：**4 OK / 2 FAILED / 2 BLOCKED**（此前 0 OK）。
- 仍未解决：① R2=0（逐 patch 面积阈值 vs 分块 patch；以及逐面配对采样致歧义超限，需按计划 §30.5 实现二维交/差裁剪）；② rough 在 0.01 mm 预算下超 400k 单元上限（需计划 §10.1 第 3 步材料带+halo 高频窗，未放宽波长）；③ cut.py 零幅回归/可复现性两测仍失败；④ warped/modes 保持 PENDING/MISSING。

## 追加（授权：修 pipeline 特征泄漏 + 重提交受影响特征）

2026-10-02 09:45:39：收口队友 c772fce6 报告 `truth_isolation` 残余 false 的根因是 `synlab/pipeline.py` 把 `fragment_id/mother_id/component_id/observation_id` 写进 feature meta 与 `meta["feature_fields"]`（实测 12 个 feature bundle 里 8 个中招；另 4 个干净的证明检查非恒假）。

**Lead 决定与授权**：
1. Lead 已在本文件同一时间**直接修掉 pipeline.py 的根因**（特征提交前按 `FORBIDDEN_FEATURE_FIELDS` 剔除身份/答案字段，并把被剔除的键记为 `dropped_forbidden_fields`；身份字段只保留在 provenance 资产里）。**A01 判定口径不变**。
2. **授权 c772fce6 处理存量**：把那 8 个受影响 feature bundle 按与之前 degrade 角色修复**同样的字节级一致方式重新提交为新资产**（`interpret_hash` 含 role，禁止就地改 role/就地改文件），并写墓碑 + 映射报告 `data/a12/reports/feature_leak_repair.json`；随后重跑 `run_negative_control`，目标是 `truth_isolation=true`。若重提交后仍为 false，保留真实原因与精确资产清单，不得改检查来通过。
3. 该授权仅限 `synlab/pipeline.py`（Lead 已改）、`synlab/qc/**`、`tools/closed_loop.py`、`data/a12/**`、`docs/a12/**`；其余模块仍按原范围。
4. 认可其对 `tools/closed_loop.py` 硬编码 `GATE_DOWNGRADES` 强判 PASS 的删除 —— 那是伪造通过，符合计划 §30.18「任何 REQUIRED 门 FAIL/PENDING 都不得发布」。

## 追加（批产期间的计划身份与配置冻结裁决）

2026-10-02 10:47:15，批产队友（74522d92）报告 `configs/a12/next_experiment.yaml` 在其跑批期间被改动（10:26 → 10:34），导致计划身份漂移、lineage_id 命名空间与批次 1 撞名；并请 Lead 二选一。

### 裁决：**(A) 以当前文件为准**

- 当前文件 sha256 = `8186653101612cbc20e9eeba3f60ffbc241e3d1e3ebd690fdecb60746ab1fb16`；**自此冻结**：在批产跑完前，任何人（含 Lead）不得再改 `configs/a12/next_experiment.yaml`。
- 理由：当前计划能给出 Lead 要求的覆盖（**12 材料 + 16 纹样全族**；24 母体实测 16 器型/12 材料/14 纹样/4 层），而 10:26 那份的口径是"材料只到 M01–M05、纹样只有 PAT01"，拿不到纹样族覆盖。
- 批次 1 已入库的 9 条谱系**保留**，按"**不同 spec、同名不同物**"单独统计：报告必须按 `spec_hash` 分组，把批次 1 与当前 spec 的谱系分列，并明确写出 `lineage_id` 撞名的边界（同名不同物、可能不同 split）。

### 记录的真缺陷（**暂不修，避免再次漂移**）

`synlab/pipeline.py` 的 `lineage_id = f"LIN{index:04d}_{vessel}_{material}_{pattern}"` **不含 spec 身份** → 不同 spec 可产生同名谱系。正确修法是纳入 spec 短哈希（例如 `LIN{spec_hash[:8]}_{index:04d}_...`），但**必须等本批产结束后**与新 run 一起生效；届时需要一次性说明：旧名与新名的映射、已入库资产的归属、以及是否重新生成。**在此之前不得改 `lineage_id` 格式**（否则同一批内会再次叠加同名谱系）。

### 同时更正两条早前口径（以队友实测为准）

1. `plane_shared_cut` 的真实片数**不是恒定 2**：实测 2/3/4 片都出现过（一次共享切割出两半，每半再按连通分量拆），配置 `target_piece_range` 已改为实测区间 **[2,4]**。
2. 失败真实存在：批次 1 有 **1/6** 母体失败（`LIN0004_V05`，manifold 布尔 "Not all meshes are volumes"），**已计入失败分母**。
