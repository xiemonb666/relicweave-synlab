# A12 最小闭环（closed loop）：冻结、导出、loader 与泄漏修复

- 本文所有数字来自实际命令产物：`data/a12_exports/closed_loop/closed_loop_report.json`（步骤账本）、
  `closed_loop/gates_evaluated.json`、`training_package/export_manifest.json`、
  `data/a12/reports/*.json`、`data/a12_exports/closed_loop/store/releases/<release_id>/manifest.json`。
- 两个 store 必须区分，本文不混用：

| store | 角色 | 本轮相关 run | 关键事实 |
|---|---|---|---|
| `data/a12` | 长期证据 store（验收 / 算子审计 / 泄漏负控 / 覆盖） | `run_2fad0ac4d3b67098`（accepted **4/4**，354.9 s）、`run_404bbe3c80f2c04e`、`run_23664ddb26eada4b` | 247 个资产；本轮在此做泄漏修复与 A01 复核 |
| `data/a12_exports/closed_loop/store` | 闭环 store（生成 → 审计 → pool → 冻结 → 导出 → loader） | `run_852ab2a1e4c3b70f`（accepted 3/3，224.9 s） | 175 个资产；本轮在此冻结最小 release 并导出训练包 |

- `data/a12` 的生成闭环证据（本轮未重跑，仅复核）：`coverage_rows.json` 4 条谱系
  `r2_pairs = 1`，`interfaces = 10/13/11/9`，split = train/dev/train/train。

## 1. 命令与退出码

按步骤分跑（每一步立即落盘，避免长时间进程被杀丢失证据）：

| # | 命令 | 退出码 | 状态 | 说明 |
|---|---|---|---|---|
| 1 | `& .venv\Scripts\python.exe tools\closed_loop.py --step audit` | **0** | DEGRADED | 真实缺口：3 个 `visible_labels` 资产 QA_FAIL（run 审计因此 `ok=false`）；契约项 A02 已修好并记录 `ran=true / status=PASS` |
| 2 | `& .venv\Scripts\python.exe tools\closed_loop.py --step release_freeze` | **0** | OK | 冻结 `rel_852ab2a1e4c3_1790905541`，165 个 QA_PASS 资产，`scope_pending=[]` |
| 3 | `& .venv\Scripts\python.exe tools\closed_loop.py --step export_training_package` | **0** | OK | 13 个文件 / 3 785 587 B（另出 `release_index` 平铺导出，165 资产） |
| 4 | `& .venv\Scripts\python.exe tools\closed_loop.py --step loader_probe` | **0** | OK | `ok=true`，`status=PASS`，写 `data/a12/reports/loader_probe.json` |
| 5 | `& .venv\Scripts\python.exe tools\closed_loop.py --step report` | **0** | OK | 写 `closed_loop_report.json` 汇总 |
| 6 | `& .venv\Scripts\python.exe tools\closed_loop.py --step all --resume` | **0（带 caveat）** | generate/audit/build_pool/release_freeze/export/loader/report 全部有记录 | `audit` 保持 DEGRADED；脚本以 exit 0 + 明确 caveat 输出，不把降级当失败也不掩盖 |

辅助命令：

| 命令 | 退出码 | 产物 |
|---|---|---|
| `& .venv\Scripts\python.exe data\a12\reports\repair_degrade_role.py --store data/a12` | 0 | 干跑：`degrade_role_repair.json`（20 个候选，0 个被引用阻塞） |
| `& .venv\Scripts\python.exe data\a12\reports\repair_degrade_role.py --store data/a12 --apply` | 0 | 20/20 重提交 + 移除错挂行，`faithful=True` |
| `& .venv\Scripts\python.exe tools\evidence_min.py --step leakage --data-root data/a12 --run-id run_2fad0ac4d3b67098` | 0 | 规范负控报告（`ok=false`，见第 6 节） |
| `& .venv\Scripts\python.exe data\a12\reports\augment_leakage_report.py --store data/a12` | 0 | 在同一报告内追加 run 范围 / 全店 / 干净 run / 角色普查 / 残余原因 |
| `& .venv\Scripts\python.exe -m synlab.cli acceptance --profile SANDBOX_CORE --json` | **1** | 36 项：FAIL 5 / PASS 12 / PENDING 6 / NOT_RUN 6 / NA 7（见第 7 节） |
| `& .venv\Scripts\python.exe tools\gen_status_matrix.py --data-root data/a12` | 0 | `docs/a12/status_matrix.csv`（153 行）、`algorithm_registry.md`、`registry.json` |

## 2. 每步产物与计数

- **generate**（账本中为既有记录，`--resume` 复用）：`run_852ab2a1e4c3b70f`，attempted 3 /
  accepted **3** / failed 0，224.9 s；`coverage.json`：`per_split.train=2, dev=1`，
  `fracture_backend=plane_shared_cut`。
- **audit**（本轮实跑，exit 0 / DEGRADED）：`audit_run_852ab2a1e4c3b70f.json`
  `ok=false`，`counts.assets=168`（run 标记资产），`closure.files_checked=171`（闭包本身
  `ok=false`，因为 run 里含 QA_FAIL 资产），`store_health {assets:175, files_checked:176, ok:true}`，
  `lineage_splits` 3 条谱系（train/dev/train）。**三条真实问题**：
  1. `assets with QA_FAIL referenced by run`：3 个 `visible_labels` 资产（交付前景 mask 为空 →
     “没有任何视图可见对应采样”），被排除在冻结范围之外并逐个记录在 release manifest 的
     `excluded_assets`；
  2. 同上引起的 `reference closure failed`（`closure.ok=false` 是 run 级的；**冻结范围**自己的
     闭包是 `ok=true`，见第 4 节）；
  3. `forbidden fields inside feature bundles`：本 store 的特征资产带 `fragment_id`/`mother_id`
     且把它们声明进 `feature_fields`（第 6.4 节的 pipeline 缺陷，闭环 store 内同样可见）。
  `fixture_contract` 把仓库级 `docs/a12/reuse_manifest.json`（hash `sha256:8cb2b729…`）连同
  来源与哈希 staged 进 store 报告目录；A02 契约项修正后记录 `ran=true / status=PASS`。
- **build_pool**（复用）：`QA_PASSED_WITH_FALLBACK`，candidates 6 / queries 3 /
  **r2_edges 3** / unknown 0，3 个母体；`pool_report.json` 落盘。
- **release_freeze**（本轮实跑）：见第 4 节。
- **export_training_package**（本轮实跑）：见第 3 节。
- **loader_probe**（本轮实跑）：见第 5 节。
- **report**：账本 `ok=true`，`degraded_steps={audit}`、`failed_steps={}`；`summary` 里记录
  release/package/loader 三块计数（与本节和第 3、4、5 节同源）。

## 3. 训练包清单（13 文件 / 3 785 587 B）

`data/a12_exports/closed_loop/training_package/export_manifest.json`
（`manifest_hash = sha256:88db4bdfc9747bc122b42132234e3a7a25a587f667835dd0dfed8a034dd1af26`）：

| 视图 | 文件 | 字节 | 内容 |
|---|---|---|---|
| `deploy` | 8 | 3 766 777 | `deploy_index.json`(1 364)、`geometry/index.json`(1 015)、`geometry/shard_0000.npz`(192 983)、`obs/index.json`(1 636)、`obs/shard_0000.tar`(2 375 680)、`queries.parquet`(3 699)、`tokens/index.json`(998)、`tokens/shard_0000.npz`(1 189 402) |
| `research` | 5 | 18 810 | `relations.parquet`(3 714)、`labels/clean.parquet`(5 925)、`labels/physical.parquet`(5 930)、`labels/visible.parquet`(2 709)、`labels/query_map.json`(532) |

计数（`counts`）：`geometry_points = 6049`、`geometry_bytes = 145176`、`geometry_fragments = 3`、
`obs_views = 12`、`obs_bytes = 2359296`、`observations = 3`、`tokens = 576`、`token_fragments = 3`、
`zarr_arrays = 3`、`queries = 6`、`relations = 3`（全为 R2）、`r2_relations = 3`、
`superseded_relations = 18`、`label_layers = 3`（clean 27 行 / physical 27 行 / visible 12 行）、
`fragments_with_observation = 3`、`fragments_without_observation = 3`。

真值分离（`views`/`separation`）：deployment 视图 `contains_truth=false`，
`deploy_truth_files=[]`（导出时按文件名实测：deploy 下没有 label/truth/relation 文件），
research 视图 `contains_truth=true` 且与 deploy 物理分目录。
token cache 记录 `encoder_id=identity_rgb_blockmean` 与 4 个哈希（crop/encoder/input/policy），
即 token 是可复算的缓存，不是新增监督。

另出平铺导出 `release_index/`（`export_release(fmt="parquet")`，165 资产，
`export_hash = sha256:65eae778ed93583d247bf8084acdffa689a79bc0e18fccefc2ff3ff28a52f6a1`）。

## 4. release 状态：**已冻结**（SANDBOX_CORE）

| 项 | 值 |
|---|---|
| `release_id` | `rel_852ab2a1e4c3_1790905541` |
| `profile` / `scope` | `SANDBOX_CORE` / `SYNTHETIC` |
| `manifest_hash` | `sha256:c86c14af36e243fef2b2ba5e5a909d73555ddcfcb79aa9899cd3d2f9a3b01ddd` |
| 冻结资产 | 165（全部 QA_PASS；`closure.ok=true`，165 资产 / 165 文件逐个哈希校验） |
| 必需门 | `fixture_contract, coordinate_contract, source_map, readonly_commit, fracture_operator_runs, observation_operator_runs` |
| `scope_completed` | 上述 6 门**全部 PASS** |
| `scope_pending` | `[]`（**无未过必需门**） |
| `gate_overrides` | `[]`；`refused_gate_overrides` `[]`（没有任何门被声明改判） |
| 门来源 | 全部由 `synlab.qc.gates.evaluate_gates(store, run_id, evidence_dirs=["data/a12"])` 从 store 证据判定；`gates_evaluated.json` 记录了每个门实际读取的报告路径与哈希 |

资产角色分布（165）：`fragment_mesh 42`、`mother_mesh 21`、`feature_bundle 21`、`label_bundle 21`、
`provenance 21`、`clean_truth 9`、`physical_truth 9`、`visible_labels 6`、`material_profile 3`、
`obs_result 3`、`physical_component 3`、`pattern_recipe 3`、`pattern_channels 3`。

**未过门清单（本 profile 不要求、因此未阻塞冻结，但如实列出）**：37 个门中 12 个 PASS、25 个
PENDING。PENDING 分为三类：

1. **本机不具备的外部能力**（`real_capture_dataset`、`phone_rgb_mvs`、`scale_source`、
   `mask_source`、`capture_profile`、`proxy_calibration`、`mvs_subset_real_run`、`l2_qualification`、
   `resource_profile` 之外的规模门 `accepted_nested_10k/50k/100k`）——没有实拍数据、没有
   patch-match 稠密后端、没有 L2/L3 规模 run；
2. **规模/覆盖门**（`coverage_24_vessels`、`coverage_12_materials`、`coverage_4_layers`、
   `coverage_16_patterns`、`coverage_4_backends`、`coverage_31_axes`）——闭环只跑 3 个母体；
3. **研究/许可门**（`frozen_protocol`、`training_runs`、`risk_calibration`、
   `confirmation_complete`、`legal_inputs`、`relations_complete`、`references_loadable`、
   `leakage_audit`）——`leakage_audit` 读 `acceptance_summary.items.A32`，而 SANDBOX_CORE 下
   A32 本身为 NA，因此保持 PENDING；`legal_inputs` 要求 `audit.ok` 为真，而本 run 的审计
   `ok=false`（3 个 QA_FAIL 资产 + 特征角色里的 `fragment_id`/`mother_id`，见第 2、6.4 节）；
   `relations_complete` 需要 pool 资产带 QA_PASS 的 `relation_pool`（本环的 pool 资产是
   QA_PENDING，只有 roster 被显式判 PASS）。

`leakage_audit` 属 PILOT/CORE_COVERAGE，不进 SANDBOX_CORE 必需集；第 6 节的泄漏负控结果说明
它在升档前仍然是 blocking 的。

### 4.1 本轮修掉的两个“门读出错误”（不是放宽门）

1. **`synlab/qc/gates.py` 读错层级**：验收报告把 36 项嵌在 `items` 下（`acceptance_summary.json`），
   而 gate 用 `acceptance.get("A02")` 取顶层键，永远取不到 → `coordinate_contract` 恒为 PENDING。
   新增 `acceptance_item()` 兼容 `items.<ID>` 与顶层两种形状；改后该门读到真实条目
   （A02 `status=PASS`，`max_mm_error=1.42e-14`、`max_px_error=0.0`，证据
   `docs/a12/env_report.json`）。判定口径（读哪个报告、什么算 PASS）未改。
2. **`tools/closed_loop.py` 里硬编码的 `GATE_DOWNGRADES` 把 6 个必需门强判 PASS**（含把当时
   证据为 PENDING 的 `coordinate_contract` 改写成 PASS，理由是一段散文）。这属于伪造门结论：
   该表已清空，并且在代码层面加了拒绝逻辑——任何声明都不得把门抬成 PASS，只能降到
   `PENDING`/`NA` 并记录理由与被查阅证据；`ReleaseManager.freeze` 拒绝时，步骤改为落盘
   `release_freeze_blocked.json`（包含门明细、`scope_pending`、真实错误码 `STOP_QA`），
   并说明 SANDBOX_CORE 已是 `PROFILE_GATES` 的最低档，**不存在可降级的 profile**，
   因此“未过门”只能表现为“未冻结 + 原因”，不能表现为换档放行。
   （本轮 6 个必需门在修正读取后本来就由证据全 PASS，所以没有触发该分支。）
3. 附带修好 `_run_contract_item`：它把 `run_acceptance(report_path=…)` 的 **markdown** 落点当成
   JSON 解析，每轮都抛 `JSONDecodeError`，并在 store 报告目录留下一个名为
   `acceptance_summary.staged.json`、内容却是 markdown 的残留文件。现在直接回读并校验
   `acceptance_summary.json`，audit 步骤记录 `ran=true / status=PASS`。残留文件保留未删（它就是
   那段 bug 的证据）。

## 5. loader 结果（`data/a12/reports/loader_probe.json`）

- `ok=true`、`status=PASS`、`files_ok=true`，检查 13 个包文件。
- `counts`: queries 6 / relations 3 / relation_kinds `{R2: 3}`；
  `relation_pool`: `pool_id=exported`，`r2_closure.ok=true`（3 条 R2 边，6 个 fragment 有 mate）。
- 真实分母：`fragments=6`，`fragments_with_observation=3`，`fragments_without_observation=3`，
  `points_valid=6049`，`scale_valid_fragments=3`，`tokens_total=576`，`tokens_valid=576`。
- 特征形状：`points [6,4158,3]`、`local_tokens [6,192,256]`、`global_rgb [6,4,3,192,256]`、
  `token_budget=192`、`token_retention=[1,0,1,0,1,0]`、`scale_valid_fraction=0.5`。
- batch：`n_queries=3`、`n_candidates=1`、`positives=3`、`negatives=0`；
  `negative_audit.ok=true`、`problems=[]`、`r1_fallback_used=0`。
  **负例为 0 不是缺陷而是受控分母**：exposure 直方图 `none=3`、其余桶（`known_R2`、`gray_zone`、
  `same_fragment`、`label_invalid`、`unknown`、`TINY`）全 0，因为每个 query 的 R2 伙伴必须被
  排除、而本环 pool 只有 R2 关系（`r2_edges_exposed=3`），所以“合法负例”确实不存在；
  该事实由 `negative_audit` 与 `exposure` 两块同时给出，不当作 PASS 之外的结论。
- 六个 fragment 中 3 个没有观测（`fragments_without_observation=3`）：它们以 `absent` 载荷进入
  batch（`feature_shapes` 里 `points`/`local_tokens` 每第二个 fragment 的保留率为 0），
  这正是“缺测”分支的真实样本，而不是被丢弃。

## 6. 泄漏修复（A01 / leakage_negative_control）

### 6.1 缺陷

`synlab.degrade.api._apply_impl` 把每个轴档位的观测估计结果提交成 `feature_bundle` 角色，
meta 里带 `axis_id` / `level` / `variant` —— 这三个键正是
`synlab.roles.FORBIDDEN_FEATURE_FIELDS` 明令禁止出现在特征资产里的“答案字段”
（特征不得携带因子标签，否则模型可以直接把因子读出来）。

### 6.2 修法（代码）

- `synlab/roles.py`：新增专用角色 `ROLE_DEGRADE_MEASUREMENT = "degrade_measurement"`
  （schema 用既有的 `SCHEMA_MEASUREMENT = "synlab.measurement.v1"`）。
- `synlab/degrade/api.py`：`COMMIT_ROLES["X"] = (ROLE_DEGRADE_MEASUREMENT, SCHEMA_MEASUREMENT)`。
  **A01 判定口径未改**（`FORBIDDEN_FEATURE_FIELDS` 与 A01 的检查逻辑一字未动）。

### 6.3 存量修复（数据）

已提交的 20 个错挂行不会因为代码修复而消失。修复方式：
`data/a12/reports/repair_degrade_role.py` 用模块自身的逆函数 `load_source` 把资产读回，
再用 `commit_source` 以正确角色重提交，**逐数组校验字节一致**（keys/shape/dtype/hash 全等，
`faithful=True` × 20），然后才删除错挂行与其目录，并写墓碑（role/schema/unit/frame/qa/meta/
文件哈希）与 old→new 映射到 `data/a12/reports/degrade_role_repair.json`。
不做就地改 `role`：`asset_id = interpret_hash(role, …)`，改 role 会直接破坏 store 的身份契约。
删除前逐个资产检查引用（其它资产 ancestry、release manifest、pool/roster）：20/20 无阻塞引用，
仅 events 追加日志提到它们（不阻塞）。

实测（`data/a12` 角色普查）：

| 角色 | 修前 | 修后 |
|---|---|---|
| `feature_bundle` | **32** | **12** |
| 其中带 `axis_id`/`level`/`variant` | **20** | **0** |
| `degrade_measurement` | 0 | **20** |
| 资产总数 | 247 | 247（重提交 20 + 删除 20） |

`health_check`：`ok=true`、247 资产、250 文件、0 问题。

### 6.4 负控结果（`data/a12/reports/leakage_negative_control.json`）

| 范围 | `features` | `truth_isolation` | `ok` | 说明 |
|---|---|---|---|---|
| run 范围 `run_2fad0ac4d3b67098`（规范 `evidence_min --step leakage`） | 4 | **false** | false | 4 个特征资产带 `fragment_id`/`mother_id` |
| 全店（无 run 过滤） | 12 | **false** | false | 12 个里 8 个带 `fragment_id`/`mother_id` |
| 干净 run `run_23664ddb26eada4b` | 4 | **true** | **true** | 证明该检查不是恒假 |
| 修前（历史报告，`run_id=probe_recovery`） | 20 | false | false | 20 个带 `axis_id`/`level`/`variant` |

结论必须如实写：**退化角色泄漏已修好并清理干净（`axis_id`/`level`/`variant` 在特征角色中 0 个），
但 `truth_isolation` 整体仍为 `false`，原因换成了另一个模块的缺陷**：

- 残余 8 个 QA_PASS 特征资产（`run_2fad0ac4d3b67098` 4 个、`run_404bbe3c80f2c04e` 4 个）meta 带
  `fragment_id`、`mother_id`，并把它们写进了 `meta["feature_fields"]`；
- 提交方是 `synlab/pipeline.py::_commit_features`（`meta["fragment_id"] = …`）与
  `synlab/pipeline.py::_observation_feature_block`（把 `fragment_id`/`mother_id`/`component_id`/
  `observation_id` 合并进特征 meta）；
- `synlab/pipeline.py` **不在本任务的写入范围**，且这 8 个是真实 run 的 QA_PASS 资产
  （被 run 覆盖、闭包和 pool 引用），不能删、不能就地改 meta（meta 参与 `payload_hash` 与
  `asset_id`）。因此保留原样并如实报告，正确修法是让这两个函数把身份字段留在 provenance
  侧、不要写进 feature meta 与 `feature_fields`，然后重跑受影响 run 的生成。

对应的 A01 实测（同一判定口径，前后对比）：`forbidden_fields_in_committed_features`
**76 → 16** 条（20 个退化资产 × 3 键 → 8 个 pipeline 特征 × 2 键），`leakage_detector=true`、
`unknown_field_rejected=true` 不变；A01 状态仍为 **FAIL**（原因如上，未放宽口径让其变绿）。

## 7. 验收（前后计数）

`& .venv\Scripts\python.exe -m synlab.cli acceptance --profile SANDBOX_CORE --json`

| 快照 | 退出码 | FAIL | PASS | PENDING | NOT_RUN | NA |
|---|---|---|---|---|---|---|
| 前（`acceptance_summary.before.json`，`generated_at=1790905375.21`） | 1 | 5 | 12 | 6 | 6 | 7 |
| 后（`acceptance_summary.json`，`generated_at=1790905610.66`） | 1 | 5 | 12 | 6 | 6 | 7 |

**状态迁移：0 项**（A01/A05/A06/A09/A24 仍 FAIL，其余不变）。本轮改动只改变了 A01 的
*实测明细*（76 → 16 条 forbidden 字段）与两个门的可读性，不改变任何一项的状态判定——
这一点按诚实规则原样记录，不用“看起来完成”的方式修辞。

失败项与本轮无关的原因（保持 FAIL，未修，不在写入范围或属真实缺陷）：
A05（PAT07/PAT08 的 `cut_continuity` 继承检查失败）、A06（四后端缺口）、A09（物理损伤审计）、
A24（`source_dependency_audit.json`：`gt_pose_invariance=false`）。

## 8. 仍未解决项 / 缺口

1. **A01 与 `truth_isolation`**：见 6.4，修法在 `synlab/pipeline.py`（越权）。
2. **`audit` 步骤 DEGRADED**：3 个 `visible_labels` 资产 QA_FAIL（交付前景 mask 为空），
   已排除出冻结范围并逐个记录；这是真实缺口，不是流程噪声。
3. **`relations_complete` / pool 资产 QA 状态**：闭环的 `relation_pool` 资产仍是 QA_PENDING
   （只有 `query_roster` 被显式判 PASS），所以该门在升档（PILOT+）时仍会 PENDING。
   本环 pool 只有 3 条 R2、0 个合法负例 → 不能作为监督数据集发布。
4. **规模/覆盖/实拍类门**（25 个 PENDING）：本机没有实拍数据与稠密 MVS 后端，也没有
   L2/L3 与 24×20 规模的 run；这是数据/算力缺口，不是代码结论。
5. **证据哈希的时点性**：release manifest 用 `gate_evidence` 记录“冻结那一刻读到的文件 + 哈希”。
   冻结后我又补跑了 audit 修复与 loader_probe，因此 12 个证据文件中 4 个的当前哈希与 manifest
   记录不同：`acceptance_summary`（loop store，A02 仍 PASS）、`audit_run_852ab2a1e4c3b70f`、
   `loader_probe`（仍 `ok=true`）、`recovery_probe`（验收 harness 的 A17 重跑产物）。
   冻结后重新核验：manifest 自校验通过、引用闭包 `ok=true`（165/165）、6 个必需门仍全 PASS。
   这些哈希是时点快照而非“文件不可变”的声明。
6. **导出包里的一个常量**：`separation.features_carry_answer_fields` 在
   `synlab/storage/export.py` 是硬编码 `False`（第 696 行），不是测量值；包内真正的边界证据是
   deployment 视图 `deploy_truth_files=[]`（按文件名实测）+ 物理分目录。该字段的清白不能作为
   A01/泄漏结论使用（A01 的实测是 FAIL）。`export.py` 不在写入范围。
7. **规范 `leakage` 步骤仍是 run 范围**：`tools/evidence_min.py --step leakage` 的
   `_feature_assets` 在 run 过滤命中时只用该 run 的特征，未命中时回退全店。全部范围已写进同一
   报告（`store_wide` / `clean_run_scoped` / `residual`），口径未改。

## 9. 复现命令

```powershell
$py = ".venv\Scripts\python.exe"
# 泄漏修复（数据）
& $py data\a12\reports\repair_degrade_role.py --store data/a12
& $py data\a12\reports\repair_degrade_role.py --store data/a12 --apply
& $py tools\evidence_min.py --step leakage --data-root data/a12 --run-id run_2fad0ac4d3b67098
& $py data\a12\reports\augment_leakage_report.py --store data/a12
# 闭环（分步，各步立即落盘）
& $py tools\closed_loop.py --step audit
& $py tools\closed_loop.py --step release_freeze
& $py tools\closed_loop.py --step export_training_package
& $py tools\closed_loop.py --step loader_probe
& $py tools\closed_loop.py --step report
& $py tools\closed_loop.py --step all --resume
# 验收与状态矩阵
& $py -m synlab.cli acceptance --profile SANDBOX_CORE --json
& $py tools\gen_status_matrix.py --data-root data/a12
```
