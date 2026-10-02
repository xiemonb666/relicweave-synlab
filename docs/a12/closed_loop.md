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
| 3 | `& .venv\Scripts\python.exe tools\closed_loop.py --step export_training_package` | **0** | OK | 修复前 13 个文件 / 3 785 587 B；**§12.1 修复后 53 个文件 / 3 928 494 B**（另出 `release_index` 平铺导出，165 资产） |
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
- **export_training_package**（本轮实跑）：修复前见第 3 节，修复后见 §12。
- **loader_probe**（本轮实跑）：见第 5 节。
- **report**：账本 `ok=true`，`degraded_steps={audit}`、`failed_steps={}`；`summary` 里记录
  release/package/loader 三块计数（与本节和第 3、4、5 节同源）。

## 3. 训练包清单（**修复前快照**：13 文件 / 3 785 587 B）

> 本节是 **zarr 路径缺陷修复之前**的快照：当时写在 `deploy/geometry/zarr` 的 40 个 zarr 文件
> 不在 `files[]` 里。两个导出缺陷的修法与修复后实测清单（53 文件 / 3 928 494 B、双向差集为空、
> 53/53 hash 通过）见 **§12**；本节数字保留作对照。

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

- `ok=true`、`status=PASS`、`files_ok=true`，检查 **53** 个包文件（zarr 路径修复前为 13，
  见 §12.1；修复后 `files_checked=53`，重新跑该步骤退出码 0、batch 计数不变：
  `queries=6 / n_queries=3 / positives=3 / negatives=0`）。
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
- **本轮修掉的一个完整性漏洞**（`synlab/qc/loader_probe.py`）：`probe_training_package` 的
  `ok` 只取 `negative_audit.ok`，完全忽略 `package.verify_files` 的结果，于是一个
  **manifest 哈希对不上的包也会报 `ok=true`**（集成测试
  `test_loader_refuses_a_tampered_package` 就是这样失败的）。现在 `ok = files_ok ∧
  negative_audit.ok`，完整性失败时落 `error.code=ASSET_HASH_MISMATCH` +
  `blocking_attempt=package.verify_files`。真实包复跑结果不变（`files_ok=true`、
  `files_checked=13`（当时 `files[]` 只有 13 项，§12.1 修复后为 53）、`ok=true/PASS`）。

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

> **上述 8 个残余资产已在 §11 收口**：`forbidden_fields_in_committed_features` 16 → **0**、
> `truth_isolation` false → **true**、`A01` FAIL → **PASS**（口径与检查实现未改）。
> 代码侧仍存在的残余（`synlab/pipeline.py:893`）见 §11.5 第 1 条。

同一缺陷在闭环 store 内也被闭环自己的审计抓到（`audit_run_852ab2a1e4c3b70f.json` 第三条
problem）：`asset_84a2eb0b437d1361ded9 / asset_cdd4f2a28f0d9075f697 / asset_60790a61ffd50cf21d32 …`
`['fragment_id','mother_id']`，并且 `declared=['fragment_id','mother_id']`（即确实写进了
`feature_fields`）。这同时是 `legal_inputs` 门 PENDING 的直接原因之一。两个 store 相互独立地
指向同一个 `synlab/pipeline.py` 缺陷。

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

1. **A01 与 `truth_isolation`**：见 6.4；其中的 8 个存量资产已由 §11 修复（A01 现为 PASS、
   `truth_isolation=true`）。**代码侧**残余仍在 `synlab/pipeline.py:893`（新生成会复现），
   属越权项，见 §11.5 第 1 条。
2. **`audit` 步骤 DEGRADED**：3 个 `visible_labels` 资产 QA_FAIL（交付前景 mask 为空），
   已排除出冻结范围并逐个记录；这是真实缺口，不是流程噪声。
   → **描述更正（§13.4 实测）**：mask **不是**空的（132–204 px/视图、并集 498 px），真实根因是
   景深（弥散圆）判据的单位错误把 mask 削到物体的 0.26–9.4 %，可见性判据交集为空；
   同一缺陷在本轮 L0 单母体上同样复现（mask 5–204 px，1448 个样本 0 可见）。
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
   → **已修（§12.2）**：该字段与两个 `contains_truth` 现在都由真实内容扫描产生，扫描分母与命中
   列表写进 manifest；修复过程中扫描实测到 3 个命中并据此修掉了 deployment 视图里 3 个越界键。
7. **规范 `leakage` 步骤仍是 run 范围**：`tools/evidence_min.py --step leakage` 的
   `_feature_assets` 在 run 过滤命中时只用该 run 的特征，未命中时回退全店。全部范围已写进同一
   报告（`store_wide` / `clean_run_scoped` / `residual`），口径未改。
8. **导出包的 zarr 副本没进 manifest**（`synlab/storage/export.py`，越权未改）：
   第 439 行把 zarr 写到 `deploy/geometry/zarr`，第 441 行却扫描 `deploy/zarr` 去登记文件，
   因此该副本**不在 `files[]` 里**（本包 `views.deploy.files=8`、`bytes_total` 不含 zarr），
   集成测试 `test_export_produces_every_declared_artifact` 期望的正是 `deploy/zarr`
   ——测试与实现的路径不一致，属真实缺陷。后果：`package.verify_files()` 覆盖不到 zarr 副本
   （本包 `files_checked=13`）。本轮的 loader 修复只能保证“manifest 覆盖到的文件”被校验。
   → **已修（§12.1）**：`export.py` 本轮已在写入范围内；写盘与登记同源后 40 个 zarr 文件全部
   登记（`files[]` 13 → 53，`deploy` 8 → 48），独立核对的双向差集为空、53/53 hash 通过。
9. **`TrainingPackage.verify_files` 的覆盖面**：它按 `files[]` 逐个哈希校验（这点是对的），
   但 `files[]` 本身受第 8 条影响而缺项；修 zarr 路径登记是补全该门的前提。
   → **已修（§12.1）**：zarr 副本的写盘与登记改用同一个 `_zarr_root()`，`files_checked` 13 → 53。

## 9. 测试

| 命令 | 退出码 | 结果 |
|---|---|---|
| `& $py -m pytest tests/a12/operators -q` | 0 | 148 项全部通过（退化算子 API/身份/效果/注册表） |
| `& $py -m pytest tests/a12/api/test_roles_and_isolation.py -q` | 0 | 21 项全部通过 |
| `& $py -m pytest tests/a12/integration/test_closed_loop.py -q` | **1** | 修复前 20 通过 / 2 失败；loader 完整性修复后 **21 通过 / 1 失败**，仅剩第 8 条的 `test_export_produces_every_declared_artifact` |
| `& $py -m pytest tests/a12/integration -q -p no:cacheprovider`（修复前基线，留档 `data/a12/reports/pytest_before_export_fix.txt`） | **1** | 3 项失败：导出目标项 `test_export_produces_every_declared_artifact` + 2 个与本任务无关的 L0 项（`test_l0_commits_every_stage_asset`、`test_features_and_labels_are_separate_and_clean`） |
| `& $py -m pytest tests/a12/integration -q -p no:cacheprovider`（导出修复后，留档 `data/a12/reports/pytest_after_export_fix.txt`） | **1** | 导出项全部转绿（含新增的 4 项：双向文件集合、separation 实测、注入命中、常量化回归守卫）；仅剩 **1 项与本任务无关**：`test_l0_loop.py::test_l0_commits_every_stage_asset`（见 §12.5） |

注：`tests/a12/operators` 与 `tests/a12/api` 同时收集会因两个同名 `conftest.py`
（`from conftest import ALL_AXES`）冲突而报 ImportError，这是既有测试布局问题，按目录分开跑即可，
与本轮改动无关（两个目录各自的退出码均为 0）。

## 10. 复现命令

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
# 训练包导出的独立核对（自己读键 + 自己算 sha256，不复用导出器代码）
& $py tools\closed_loop.py --step export_training_package
& $py data\a12\reports\verify_export_package.py --package data\a12_exports\closed_loop\training_package --out data\a12\reports\export_package_verification.json
# 测试（按目录分开跑，避免同名 conftest 冲突）
& $py -m pytest tests/a12/operators -q
& $py -m pytest tests/a12/api/test_roles_and_isolation.py -q
& $py -m pytest tests/a12/integration -q -p no:cacheprovider
```

## 11. feature 泄漏存量修复（A01：8 个历史资产收口）

§6.4 记录的“最后 8 个残余特征资产”已在本节收口。**口径、`FORBIDDEN_FEATURE_FIELDS`、
`qc/leakage.py`、`qc/audit.py`、各 release 门均一行未改**；改的只有 `data/a12` 的存量行。

### 11.1 策略（为什么不能就地改）

`asset_id = interpret_hash(role, schema, unit, frame, payload_hash)`，meta 参与 `payload_hash`，
所以就地改 meta / 改 role 都会破坏 store 的身份契约。采用的策略（与
`data/a12/reports/repair_degrade_role.py` 同风格），逐资产按序执行：

1. 用 `store.load_arrays` 读回**原特征数组**并逐个算 `array_hash`（作为“同一份特征数组”的度量）；
2. 用**剔除身份字段后的 meta** 把同一批数组重提交为新资产（同 `role=feature_bundle`、
   同 `schema=a12.obs.v1`、同 unit/frame、`QA_PASS`、同 ancestry/lineage/split）；
   剔除 `fragment_id`/`mother_id`（表内禁用）+ `component_id`/`observation_id`（同一身份链），
   重算 `meta["feature_fields"]`，记录 `dropped_forbidden_fields` 与 `leak_repair.source_asset_id`；
3. **逐数组校验字节一致**（keys/shape/dtype/hash 全等，`differences=[]`）——不通过就保留旧行并如实报告；
4. 校验通过才退役旧行：删除 SQLite 行 + `assets/<id>` 目录（删除前解析绝对路径并核对资产 id），
   写完整墓碑（role/schema/unit/frame/qa/meta/文件哈希/逐数组哈希）到
   `data/a12/reports/feature_leak_repair.json`；
5. **改指派生边**：旧 id 出现在同 run provenance 资产的 `ancestry`（`[feature, label]`）里，
   共 8 条，逐条改指到孪生资产（记录前后值与原因）。`ancestry` 不参与
   `interpret_hash`/`blob_hash`，改指不改变任何资产 id 与文件哈希；若引用方处于已冻结
   manifest 内则**拒绝改写**（本次 0 条命中）。

工具：`tools/repair_feature_leak.py`（`--plan` 复现 / `--apply` 修复 / `--verify` 复核 /
`--freeze` 冻结尝试）。

### 11.2 命令与退出码

| 命令 | 退出码 | 结果 |
|---|---|---|
| `& $py tools\repair_feature_leak.py --store data/a12 --plan` | 0 | 8 资产 / 16 条 forbidden（`fragment_id`+`mother_id` 各 8） |
| `& $py tools\repair_feature_leak.py --store data/a12 --apply` | 0 | `repaired=8`、`refused=0`、8/8 `faithful=true`、派生边 8/8 改指 |
| `& $py tools\repair_feature_leak.py --store data/a12 --verify` | 0 | 全店 forbidden 0；`truth_isolation=true` |
| `& $py tools\repair_feature_leak.py --store data/a12 --freeze --apply` | 0 | 两次冻结尝试均被门拒（见 11.4），`frozen=false` |
| `& $py tools\evidence_min.py --step leakage --data-root data/a12 --run-id run_2fad0ac4d3b67098` | 0 | `ok=true` / `status=PASS`（原 `ok=false`） |
| `& $py data\a12\reports\augment_leakage_report.py --store data/a12` | 0 | 追加 `runs_scoped`（两个受影响 run + 干净 run）与 `feature_leak_repair` |
| `& $py -m synlab.cli acceptance --profile SANDBOX_CORE --json` | **1** | FAIL 5→**4**、PASS 12→**13**、**A01 FAIL→PASS**；退出码 1 来自 A05/A06/A09/A24（与本轮无关） |
| `& $py tools\gen_status_matrix.py --data-root data/a12` | 0 | `docs/a12/status_matrix.csv` A01 行 = `PASS` |

### 11.3 复核数值

| 指标 | 修前 | 修后 |
|---|---|---|
| `feature_bundle` 资产数 | 12 | 12（12 − 8 + 8） |
| 带 forbidden 键的特征资产 | **8** | **0** |
| `feature_bundle.meta` 的 forbidden 条目 | **16** | **0** |
| A01 `forbidden_fields_in_committed_features` | **16**（基线 76） | **0** |
| `truth_isolation`（run_2fad0ac4 / run_404bbe3 / 全店 / 干净 run） | false / false / false / true | **true / true / true / true** |
| 派生边（provenance ancestry）失效引用 | 8 | **0**（全部改指） |
| `health_check` | ok=true（247 资产 / 250 文件 / 0 问题） | ok=true（247 资产 / 250 文件 / 0 问题） |
| 逐数组 faithful | — | **8/8 true**（各 17 个数组，keys/shape/dtype/hash 全等） |

映射（旧 → 新，逐数组 hash 证据见 `feature_leak_repair.json`）：

| 旧 id | 新 id |
|---|---|
| `asset_2ddeda824c6b7dec8a95` | `asset_fded2bb0ae17aa1f409f` |
| `asset_846bd1b7cf1e44d139d0` | `asset_b9a422864590b8115042` |
| `asset_0bcbf10e87b9b54fbbc2` | `asset_8c29450b0260f5726bd3` |
| `asset_e612e193c8fa59f47aa5` | `asset_cadb60574457189e9b22` |
| `asset_2e59947b6438587153b5` | `asset_219282d10ed84ad8cc9a` |
| `asset_b31e078177be3f23c81b` | `asset_fb073cc932fc7661d49a` |
| `asset_5bb19a7894def812c16e` | `asset_1214795958e2a814c8b6` |
| `asset_b438e92147420409adae` | `asset_433cc1381e62aa47d28a` |

### 11.4 release：**没有重新冻结成功**（被必需门拦下；未放宽、未抬门）

- **`data/a12` 原本没有已冻结 release**（`releases` 表 0 行、`data/a12/releases/` 空），所以
  **不存在“旧 release 闭包指向旧 asset_id”**：全仓字节级扫描显示这 8 个旧 id 从未出现在任何
  manifest 里（只出现在 `_scratch` 笔记、旧 store 备份与本次墓碑/报告）。
- 仍按“新 id + 新 manifest”**真实尝试**冻结（`ReleaseManager.freeze`，从不覆盖同名 release），
  两次都被拒，明细落盘 `data/a12/reports/release_freeze_after_feature_leak_repair.json`：
  - 全范围（run 的 24 个 QA_PASS 资产）：`verify_closure` 失败 —— 引用链
    `feature_bundle → obs_result → physical_component(asset_6351703c8814ff83c390, QA_PENDING)`
    的 `ancestry` 是 `LIN0000_V01_M01_PAT01:LIN0000_V01_M01_PAT01_E01:v1`（**fragment id，不是 asset id**）；
    这两个缺陷**与本轮修复无关**：未改动的干净 run `run_23664ddb26eada4b` 的闭包同样失败，
    且在修前备份库上可复现。
  - 缩减范围（自身闭包可验证的 16 个资产，排除 8 个 provenance/feature）：闭包可过，但
    `STOP_QA`：必需门 `fracture_operator_runs`、`observation_operator_runs` 为 PENDING
    （这两个门按 `meta["run_id"]` 统计 QA_PASS 资产，而本 store 的 truth/observation 资产
    没有 run 标注；闭环 store 是靠 `tools/closed_loop.py::_tag_run_assets` 补标注解决的，
    本 store 未做该步）。
  - 结果：**两个 run 均 `frozen=false`，本轮没有产出任何 release manifest**（不制造“看起来成功”的发行版）。
- **旧 release 只读未动**：`data/a12_exports/closed_loop/store/releases/` 下 5 个 manifest
  修复前后逐文件哈希相同（`external_releases_untouched=true`）。

### 11.5 仍未解决项

1. **代码侧残余**：`synlab/pipeline.py:893`
   （`meta["fragment_id"] = encoded.get("fragment_id") if encoded else None`）在剔除逻辑之后重新写入
   forbidden 键，因此**新生成仍会复现该泄漏**。硬证据：
   `& $py -m pytest tests/a12/integration/test_l0_loop.py -q` → 退出码 1，
   `test_features_and_labels_are_separate_and_clean` 失败：
   `AssertionError: features carry forbidden fields: ['fragment_id']`
   （输出留档 `data/a12_exports/_scratch/l0_gap_probe.txt`）；闭环 store 的 21 个特征资产
   也全带 `fragment_id`/`mother_id`。本任务写入范围不含 `synlab/**`，故**只报告未改**；
   最小修法是删掉第 893 行（`relations/gallery.py::attach_features` 与 `storage/export.py`
   有 provenance/obs 回退路径），但它牵动 pool 装配与训练包导出两条并行开发中的路径。
2. **闭环 store 的 5 个已冻结 release 仍含带 `fragment_id`/`mother_id` 的特征资产**
   （每份 12–21 个），按“旧 release 只读”未动；要修需在该 store 重新生成并冻结**新版本**。
3. **陈旧派生台账**：`data/a12/reports/coverage_rows.json`（4 个旧 id）、`coverage.parquet`
   （2 个旧 id）由 `synlab/pipeline.py::_write_coverage` 在下次生成时重写，本次未手改；
   `coverage.json` 不含 asset id，不受影响。
4. **A01 之外的门没有变化**：`legal_inputs`、`fracture_operator_runs`、`observation_operator_runs`
   的 PENDING 由 run 标注与闭环 store 的缺陷决定，与这 8 个资产无关。
5. **pool 特征装配未受影响（已实测）**：修前 `attach_features` 的映射阶段把 4 个 fragment 指向
   4 个退役资产（`meta["fragment_id"]`），修后指向 4 个孪生资产（provenance `ancestry` 回退）；
   payload 阶段两边同为 0 —— `_feature_payload` 需要 payload 内有 `points` 键，而特征数组用的是
   `point_cloud__xyz`（`global_rgb`/`view_tokens` 等），**未修过的干净 run 资产同样为空**
   （`data/a12_exports/_scratch/probe_attach_stages.txt`）。即 `attached=0` 是既有缺陷，
   不是本轮修复造成；去掉 `pipeline.py:893` 后映射仍由 provenance 回退承担（同一实测）。

## 12. 训练包导出：两个缺陷的修法与实测（本轮）

§11 收口的是 feature 泄漏的**存量数据**；本节收口 `synlab/storage/export.py` 里**训练包导出**的
两个缺陷。共同原则：**manifest 里的结论必须是测量值**——扫描与哈希都在真实文件上做，达不到就把
真实差异留在文档与报告里，不放宽任何断言、不跳过任何测试。

### 12.1 缺陷 1：zarr 副本“写了但没登记”（写盘路径 ≠ 登记路径）

**症状（修复前实测）**：`_write_zarr(deploy_root / "geometry", "zarr", …)` 把副本写到
`deploy/geometry/zarr`，而登记扫描的是 `(deploy_root / "zarr").rglob("*")`——两处各自写死的
字面量路径不一致，于是：

- `files[]` 只有 13 项（deploy 8 / research 5），盘上却有 53 个受管文件（另有
  `export_manifest.json`）；**deploy 视图 48 个文件里的 40 个 zarr 文件（3 fragment × 13 +
  顶层 `zarr.json`）完全没有进 manifest**；
- `TrainingPackage.verify_files()` 只能校验 manifest 覆盖到的 13 个文件；
- 集成测试 `test_export_produces_every_declared_artifact` 断言的 `deploy/zarr` 根本不存在。

**修法（精准改动，未重写文件）**：

1. 新增常量 `ZARR_DIR_NAME = "zarr"` 与函数
   `def _zarr_root(view_root): return Path(view_root) / ZARR_DIR_NAME`；
2. 写盘与登记**只经过这一个函数**：`_write_zarr(_zarr_root(deploy_root), geometry_by_fragment)`
   与 `for path in sorted(_zarr_root(deploy_root).rglob("*"))`；`_write_zarr` 去掉自带的 `name`
   参数，于是全模块不再有第二处 zarr 路径字面量；
3. `counts` 增加 `zarr_files`，登记时逐个 `_record()`（bytes 与 sha256 一并入 manifest）。

**修复后实测**（`data/a12_exports/closed_loop/training_package/`）：

| 项 | 修复前 | 修复后 |
|---|---|---|
| `files[]` 总数 | 13 | **53** |
| `deploy` / `research` 文件数 | 8 / 5 | **48 / 5** |
| `bytes_total` | 3 785 587 | **3 928 494**（deploy 3 909 684 + research 18 810） |
| `counts.zarr_files` | （字段不存在） | **40**（`zarr_arrays=3`） |
| 盘面 vs `files[]` 差集（deploy / research） | 40 / 0 | **0 / 0** |
| `verify_files().files_checked` | 13 | **53** |
| manifest 自校验 | 通过 | 通过（`manifest_hash=sha256:19891c7f0a14c4fa04d952b1216fe271ca199af30be028229547fdccf38314ad`） |

### 12.2 缺陷 2：`separation` 是常量，不是测量

**症状**：`views.deploy.contains_truth=False`、`views.research.contains_truth=True`、
`separation.features_carry_answer_fields=False` 都是代码里的字面量（旧第 696 行）。

**修法**：

1. `scan_view_fields(view_root)`：真实读取视图里每个容器并**从内容取键**——JSON 递归取每一层
   对象键、parquet 取列名、npz 取数组名（剥掉 `<opaque>__` 前缀）、tar 取成员名、zarr 副本取它
   自己声明的数组名；每容器键数即分母（`keys_scanned`），读不了的容器进 `not_read`（按原因分组）；
2. `features_carry_answer_fields = bool(hits)`，其中
   `hits = deploy 视图键 ∩ roles.FORBIDDEN_FEATURE_FIELDS`；`hits`、`hits_by_field`、逐容器分母、
   `forbidden_fields` 全部写进 manifest 的 `separation.answer_field_scan`；
3. `truth_bearing_files(view_root, scan)` 按**内容**判定真值：监督列名
   （`kind`/`loss_mask`/`eligible_as_negative`/`label_layer`/…）、非空 `truth_channels`、
   或 `{opaque: 真实 id}` 反查表；`views.<view>.contains_truth` 与 `separation.truth_content_scan`
   都由它产生。

**真实扫描第一次跑就抓到 3 个命中**（修复前，分母 76 键 / 55 唯一键）：

| 文件 | 命中键 | 处理（不是豁免，是修正越界/重复） |
|---|---|---|
| `deploy/obs/index.json` | `split`、`lineage_id` | 删除：两键都在 `FORBIDDEN_FEATURE_FIELDS` 内，且模块文档字符串与 `deploy_index.json` 都声明 deployment 视图“不含 lineage/split”；split/lineage 在 research 侧逐行保留（`relations.parquet` 的 `split`/`lineage_cluster`、`labels/<layer>.parquet`） |
| `deploy/queries.parquet` | `fragment_id` | 删除该列：它与 `query_id`（`q::<fragment_id>`）和 `fragment` 列完全重复；loader 从 `query_id` 取行身份（`qc.loader_probe._query_fragment`），删列后重跑 loader 计数不变（`queries=6 / n_queries=3 / positives=3`） |

**没有允许名单、没有白名单豁免、扫描口径一字未放宽**：两个删除都是删掉“重复/越界”的信息，
research 侧仍完整保留。

**修复后实测**：deploy **79 键（9 个容器，全局唯一键 52）、命中 0**；未读取 40 个 zarr 内部文件
（22 个 `zarr.json` 存储格式元数据 + 18 个二进制 chunk），原因逐条写进 manifest 的 `not_read`；
research 59 键，`truth_bearing_files` = 5 个文件。

> 口径说明：zarr v3 的 `zarr.json` 里有 zstd 编解码器的 `level` 键，与 `FORBIDDEN_FEATURE_FIELDS`
> 里退化轴的 `level` 同名。它是存储格式的压缩参数、不是数据字段，因此按文件名
> （`zarr.json`/`.zarray`/`.zattrs`/`.zgroup`/`.zmetadata`）排除并**如实记录**；zarr 副本真正承载
> 的字段名由它声明的数组名（`points/normals/point_valid/normal_valid/scale_valid/frame_id`）计入分母。

deploy 逐容器分母（修复后）：`deploy_index.json 13`、`geometry/index.json 11`、
`geometry/shard_0000.npz 6`、`obs/index.json 14`、`obs/shard_0000.tar 3`、`queries.parquet 9`、
`tokens/index.json 12`、`tokens/shard_0000.npz 5`、`zarr/*（声明的数组名）6`。

### 12.3 命令与退出码

| # | 命令 | 退出码 | 结果 |
|---|---|---|---|
| 1 | `& $py tools\closed_loop.py --step export_training_package`（留档 `data/a12/reports/closed_loop_export_after_fix.txt`） | **0** | `export_training_package OK 1.8s 3928494 bytes in 53 files` |
| 2 | `& $py data\a12\reports\verify_export_package.py --package data\a12_exports\closed_loop\training_package --out data\a12\reports\export_package_verification.json` | **0** | 7 项独立核对全部 `ok=true`（见 12.4） |
| 3 | `& $py tools\closed_loop.py --step loader_probe` | **0** | `ok=true/PASS`、`files_ok=true`、`files_checked=53`、`queries=6`、batch `n_queries=3 / positives=3 / negatives=0`、`negative_audit.ok=true` |
| 4 | `& $py tools\closed_loop.py --step report` | **0** | 账本刷新 `data/a12_exports/closed_loop/closed_loop_report.json` |
| 5 | `& $py -m pytest tests/a12/integration -q -p no:cacheprovider`（留档 `data/a12/reports/pytest_after_export_fix.txt`） | **1** | 导出相关全部转绿；仅剩 1 项与本任务无关的 L0 失败（见 12.5） |
| 6 | 同上，修复前基线（留档 `data/a12/reports/pytest_before_export_fix.txt`） | **1** | 3 项失败：目标项 `test_export_produces_every_declared_artifact` + 2 个 L0 项 |

### 12.4 独立核对（脚本不复用导出器代码）

`data/a12/reports/verify_export_package.py` 自带读取器（自己的 JSON/parquet/npz/tar 键提取 +
`hashlib.sha256`），**不 import `export.py` 的扫描函数**，所以结论不循环。

| 核对项 | 修复前 | 修复后 |
|---|---|---|
| `deploy` 盘面 vs `files[]`（双向差集） | ❌ 48 vs 8，缺 40 | ✅ 48 vs 48，`[] / []` |
| `research` 盘面 vs `files[]` | ✅ 5 vs 5 | ✅ 5 vs 5，`[] / []` |
| 逐文件 sha256 | ✅ 13/13 | ✅ **53/53**（`mismatches=[]`、`missing=[]`） |
| deploy forbidden 字段 | ❌ 3 命中 / 76 键 | ✅ **0 命中 / 79 键**（唯一键 52） |
| `deploy.contains_truth`（按内容） | ✅ false | ✅ false（内容命中文件 `[]`） |
| `research.contains_truth`（按内容） | ✅ true | ✅ true（5 文件：`relations.parquet`、`labels/{clean,physical,visible}.parquet`、`labels/query_map.json`） |
| `features_carry_answer_fields` 与真实扫描一致 | ❌ manifest=false / 实测 3 命中 | ✅ 一致（false / 0） |
| 脚本退出码 | 1 | **0** |

证据文件：`export_package_verification.json`（修复后）、`export_package_verification_before.json`
（修复前）、`verify_after.txt`、`verify_before.txt`。

### 12.5 集成测试

| 快照 | 退出码 | 失败项 |
|---|---|---|
| 修复前基线（30 项：`test_closed_loop.py` 22 + `test_l0_loop.py` 8） | 1 | `test_closed_loop.py::test_export_produces_every_declared_artifact`（本任务目标）+ `test_l0_loop.py::test_l0_commits_every_stage_asset` + `test_l0_loop.py::test_features_and_labels_are_separate_and_clean` |
| 修复后（34 项 = 30 + 新增 4 项） | 1 | 仅 `test_l0_loop.py::test_l0_commits_every_stage_asset` |
| 收尾复跑（同上，留档 `data/a12/reports/pytest_final_export_fix.txt`） | 1 | 同上，仅 1 项；导出相关 30 项（含新增 4 项）全部通过 |

新增 4 项断言（只加不减、不放宽）：

1. `test_export_manifest_and_disk_agree_in_both_directions`：`files[]` 与实际盘面**双向差集为空**，
   且每个声明文件的 sha256 与 manifest 记录一致（旧测试只查单向“声明的一定存在”，看不见 zarr 缺项）；
2. `test_separation_block_is_measured_on_the_written_package`：分母 ≥ 40、`hits == []`、
   `forbidden_fields == sorted(FORBIDDEN_FEATURE_FIELDS)`，并用测试自己实现的键读取器独立复核
   “deploy 视图不含任何 forbidden 键”；
3. `test_the_answer_field_scan_notices_an_injected_answer_field`：往副本注入 `split`/`lineage_id`
   后扫描必须报出这两个命中（证明扫描不是恒空）；
4. `test_separation_flags_are_not_hardcoded_constants`：源码层面禁止三个标志位再出现字面量
   （`"contains_truth": True/False`、`"features_carry_answer_fields": False` 均已不存在）。

**仍未解决（与本任务无关，原样保留失败，不跳过、不放宽）**：
`test_l0_loop.py::test_l0_commits_every_stage_asset` 失败于
`AssertionError: physical_result: expected >= 1, got 0`。实测（`data/a12/reports/l0_role_census.json`，
现网代码、单母体、accepted 1/1）：L0 链实际提交的角色是
`mother_mesh 1 / material_profile 1 / pattern_recipe 1 / pattern_channels 1 / fragment_mesh 2 /
clean_truth 1 / physical_component 1 / physical_truth 1 / obs_result 1 / visible_labels 1 /
feature_bundle 1 / label_bundle 1 / provenance 1`——**没有 `physical_result` 这个角色**：
`ROLE_PHYSICAL_RESULT` 在整个 `synlab/**` 里没有生产者（`pipeline.py` 只 import 未使用；物理层由
`physical.commit_physical` → `physical_component`、`truth.commit_truth(role="physical_truth")` 提交）。
同一实测还显示该 store 是 `QA_PASS 11 / QA_PENDING 3`，而该测试随后断言“所有资产 QA_PASS”，
所以即使改角色字面量也不会绿。这是 L0 链/配置与测试期望的口径差（归物理层与 QA 提升策略的
归属方），不属于训练包导出范围，故**只报告未改**。
另：`test_features_and_labels_are_separate_and_clean` 在修复后已转绿，同一实测也显示 L0 新生成的
特征资产 `forbidden_meta=[]`（即 §11.5 第 1 条“新生成仍会复现该泄漏”在 `pipeline.py` 侧改动后
已不成立；以本节的实测为准）。

> **本节第 598–609 行的“仍未解决”已在本轮收口，见 §13**：`physical_result` 生产者已补（plan 4.1），
> 该测试的 QA 断言已按 plan 25.1 改成“release 闭包 + 失败分母”，L0 store 现在
> `QA_PASS 10 / QA_PENDING 3 / QA_FAIL 2`，测试转绿（§13.1）。当时记录的“3 个 QA_PENDING 是
> visible_labels / 前景 mask 为空”是两次实测的归属混淆，真实构成见 §13.3 与 §13.4。

## 13. L0 集成测试收口：PhysicalPack 结果资产（plan 4.1）与 QA 口径（plan 25.1）

目标：收掉 `tests/a12/integration` 的最后一项失败
（`test_l0_loop.py::test_l0_commits_every_stage_asset`，`AssertionError: physical_result: expected >= 1, got 0`）。
结论分四块：**补缺件**（13.2）、**按计划改正 QA 口径**（13.3）、**查清 3 个 `visible_labels` 的真实根因**
（13.4，与 §8 第 2 条旧描述不同，属实测更正）、**本轮改动的文件与仍未解决项**（13.5/13.6）。
所有数字来自落盘产物：`data/a12/reports/pytest_before_physical_result.txt`、
`pytest_after_physical_result.txt`、`l0_role_census.json`、`l0_role_census_run.txt`、
`physical_result_smoke.json`、`visible_labels_mask_probe_l0_current.json`、
`visible_labels_coc_units_l0_current.json`、`visible_labels_*_closed_loop.json`、
`plan_param_mapping_probe.json`。

### 13.1 命令与退出码

| # | 命令 | 退出码 | 结果 |
|---|---|---|---|
| 1 | `& $py -m pytest tests/a12/integration -q -p no:cacheprovider`（基线，留档 `data/a12/reports/pytest_before_physical_result.txt`） | **1** | 34 项 1 失败：`test_l0_loop.py::test_l0_commits_every_stage_asset`（`physical_result: expected >= 1, got 0`） |
| 2 | `& $py -m pytest tests/a12/integration -q -p no:cacheprovider`（本轮改动后，留档 `data/a12/reports/pytest_after_physical_result.txt`） | **0** | **35 项全部通过**（收集数 `--collect-only -q`：`test_closed_loop.py 26` + `test_l0_loop.py 9`，留档 `data/a12/reports/pytest_collected_after.txt`；进度行 35 个点、无 F/E）。相对基线：失败 1 → **0** |
| 3 | `& $py data\a12\reports\l0_role_census.py --config configs/a12/sandbox.yaml --out data/a12/reports/l0_role_census.json` | **0** | 单母体 `accepted 1/1`（`run_563ae39481ee5ff5`，`LIN0000_V02_M01_PAT02`）；角色普查新增 `physical_result 1`；QA `QA_PASS 10 / QA_PENDING 3 / QA_FAIL 2` |
| 4 | `& $py data\a12\reports\smoke_physical_result.py --out data\a12\reports\physical_result_smoke.json` | **0** | 8/8 结构检查通过（真实 audit + 真实数组 + ancestry + 判定=审计状态） |
| 5 | `& $py data\a12\reports\probe_visible_masks.py --store <L0 store>` / `probe_coc_units.py` | **0** | 见 13.4 的实测表 |

### 13.2 PhysicalPack 缺件：`physical_result` 生产者（plan §4.1）

plan §4.1 要求 PhysicalPack 同时给出 `fragment、damage recipe、mesh、survivor map、lost volume、
revision/hash`（并保留 clean 引用）；此前只有 `physical_component`（代表体 mesh）与
`physical_truth`（残差真值），**`ROLE_PHYSICAL_RESULT` 在 `synlab/**` 里没有任何生产者**
（`pipeline.py` 只 import 未使用）——这就是该测试失败的直接原因。

修法（最小、向后兼容、不动既有签名）：

- `synlab/physical/api.py`：抽出共享的组件 payload/meta 写入（`_component_payload` /
  `_component_meta`，`commit_physical` 行为不变），新增
  `commit_physical_result(store, result, *, audit, clean_asset_id, clean_asset_hash,
  component_asset_id, revision, lineage_id, split, run_id)`。没有 audit（真实测量）就抛
  `DAMAGE_EFFECT_MISSING`；资产的 `qa_status` **只**取自 `audit_physical(...)["status"]`
  （`PASS`→`QA_PASS`，其余含 `NA`→`QA_FAIL`，fail-closed）。
- `synlab/pipeline.py`：物理阶段在 `commit_physical` 之后提交该结果资产，并把
  `physical_result_asset / physical_result_qa / physical_audit_status` 写进 coverage 行。
  入口签名、既有调用与资产角色语义均未改（新增角色，不改既有角色）。

实测字段（`data/a12/reports/l0_role_census.json`，单母体、真实测量，非常量）：

| 字段 | 实测值 |
|---|---|
| asset / role / schema / unit / frame | `asset_373e79ee5e6bafaabe78` / `physical_result` / `synlab.physical.v1` / `mm` / `F_mm` |
| `qa_status`（= 审计状态） | `QA_FAIL`（`audit.status=FAIL`） |
| `recipe_id` / `axis_id` / `variant` / `level` / `revision` | `P03_depth_light` / `P03` / `smooth_recession_field` / `1` / `1` |
| `lost_volume_mm3` / `lost_volume_ratio` | `276.58071298516006` / `0.0039723611424414135` |
| `components` | `count 3`（`core 1` + `debris 2`，`supportable 1`，`contamination 0`），`component_ids` 3 个 |
| `representative_map` | `{LIN0000_V02_M01_PAT02_E01-m: LIN0000_V02_M01_PAT02_E01-m#c0}` |
| `measurement`（来自 `audit_physical`） | `source_volume_mm3 69626.27592696004`、`damaged_volume_mm3 69349.69521397488`、`added_volume_mm3 0.0`、`measured_lost_volume_mm3 276.58071298516006`、`max_outside_mm 0.0014018026413396`、`min_thickness_mm 1.7242470979690552`、`roi_external_drift_mm 0.2866218388080597`、`component_count 3`、`declared_level 1` |
| `source_asset_id` / `source_hash` / `source_geometry_hash` | `asset_525518289d681e164db0`（clean_truth）/ `sha256:6cc3e518…`（该资产 blob hash）/ `sha256:3af7fc1f…` |
| `ancestry` / payload 数组 | `[clean_asset, physical_component_asset]` / `component_volume_mm3`、`component_is_representative`、`component_supportable`、`component_is_contamination`、`measurement_values` |
| `audit_failure_codes` | `DAMAGED_NOT_SUBSET_OF_CLEAN`、`NON_POSITIVE_VOLUME`、`NOT_WATERTIGHT`（A09 已知缺陷，§7 已列 A09 FAIL） |

**这是刻意的**：结果资产的 QA 判定就是物理审计的判定，所以 L0/SANDBOX 与 closed-loop 配置下它是
`QA_FAIL`（3 条谱系里 2 条审计 FAIL），并因此**被排除出 release 范围**、逐条记进
`excluded_assets`（`tools/closed_loop.py::EXCLUDED_ROLE_REASONS` 新增该角色的原因说明）。
不为了让它变绿而填常量或改判。

### 13.3 QA 断言口径（plan §25.1）：改的是什么、依据是什么

- **依据**：plan §22「release 只引用 COMMITTED 且 QA_PASS 资产；验证完整引用闭包」与
  §25.1「未过 QA 的资产必须进失败分母」。原文断言“**store 里所有资产都 QA_PASS**”不是这条门，
  而且与流水线设计矛盾：`pattern_recipe` / `pattern_channels` / `physical_component` 三个角色
  的判定属于 release 准备步骤（`tools/closed_loop.py::_promote_pending_assets` 用真实
  payload 契约判），`physical_result` 的判定属于 `audit_physical`。
- **改后断言**（只加不减，未放宽、未 skip）：
  (a) release 范围（全部 `QA_PASS` 资产）及其**完整 ancestry 引用闭包**全部 `QA_PASS`；
  (b) 每个 `QA_PENDING`/`QA_FAIL` 资产可枚举且**可归因**——`role:status` 计数与 id 进断言消息，
      且 `qa` 块必须给出 `failure_codes`/`failures`/契约 `problems`；
  (c) 数量守恒 `QA_PASS + QA_PENDING + QA_FAIL == 总数`，且不存在第四种状态。
  三个延迟判定角色的判定不由测试发明：测试调用 shipped 的 `_promote_pending_assets`
  （mesh/recipe/channel 契约）与 `_resolve_ancestry`（语义 `clean_ref` 的引用修复），
  两者的 promoted/failed/repairs 计数写进断言消息。
- **前后差异**：L0 store 由“断言全店 PASS（实测 11/3/0，必失败）”变成
  “闭包 PASS + 分母枚举（实测 10/3/2，通过）”。注意 3 个 `QA_PENDING` 是
  `pattern_recipe` / `pattern_channels` / `physical_component`（**不是** `visible_labels`；
  `visible_labels` 在本次 L0 run 里是 `QA_FAIL`，见 13.4），并经真实契约提升为 `QA_PASS` 后进入闭包。
- 新增测试 `test_physical_result_pack_is_committed_with_real_measurements` 独立校验 13.2 的字段与
  守恒关系（`lost = source − damaged`、`ratio = lost/source`、`count = core + debris`、
  payload 数值 = `measurement` 数值、判定 = 审计状态），不参与“让测试变绿”的口径。

### 13.4 3 个 `visible_labels` QA_FAIL：根因是掩膜被“景深判据”抹掉，不是前台 mask 为空

**先更正事实**：§8 第 2 条写的“交付前景 mask 为空”经实测**不成立**——mask 非空但被削得极小，
QA_FAIL 的直接原因是 `truth/api.py::update_visibility_truth` 的可见性判据交集为空。

实测（A）本轮 L0 单母体（现网代码，`run_563ae39481ee5ff5`，`obs asset_dafa19d53f663c2295b9`，
CAM_MID_V3，4 视图 256×192，`data/a12/reports/visible_labels_mask_probe_l0_current.json` +
`visible_labels_coc_units_l0_current.json`）：

| 量 | 视图 v00 / v01 / v02 / v03 |
|---|---|
| 交付前台 mask 像素 | **204 / 50 / 5 / 27**（占画幅 0.42 % / 0.10 % / **0.010 %** / 0.055 %；并集 243 px） |
| 渲染到的物体像素 | 2833 / 2376 / 1907 / 1895 |
| `uncertain_mask` 占物体比 | **82.7 % / 85.9 % / 88.2 % / 89.7 %** |
| mask 占物体比 | 7.2 % / 2.1 % / **0.26 %** / 1.4 % |
| 对应点投影 `projected` | 1448 / 1448 / 1448 / 1448（1448 个样本**全部**落在画面内） |
| `depth_ok` / `id_ok` / `not_uncertain` / `deployment_ok` | 262/694/450/**0**、2/383/468/**0**、53/857/341/**0**、116/1123/277/**50** |
| `visible` | **0 / 0 / 0 / 0** |
| 渲染器 CoC p50 / p95（像素） | 17.15/39.24、21.71/36.33、31.03/37.45、29.36/42.87 |
| 声明光学下的 CoC p50 / p95（同网格） | 0.231/0.529、0.293/0.490、0.419/0.505、0.396/0.578 |

（B）持久化闭环 store（`data/a12_exports/closed_loop/store`，`run_852ab2a1e4c3b70f`，3 个
`visible_labels` QA_FAIL）是同一机制：mask 132–204 px/视图（0.27–0.42 % 画幅，并集 498 px，
占物体 6.4–9.4 %），1583 个样本全部投影，`depth_ok` 146–207、`not_uncertain` 388–634、
`deployment_ok` 20–70，交集 **0**。

**根因（代码位置）**：`synlab/observe/render.py`

1. `circle_of_confusion_px(z_mm, focus_distance_mm, f_number, f_px)` 把**像素单位的焦距**
   `f_px` 代进**毫米制**的弥散圆公式（`f²/(N·z)·|z−zf|/zf`），少除了传感器采样密度
   `D = 交付长边像素 / 传感器宽度_mm`；`render_view` 第 460 行还以硬编码 `f_number=1.0` 调用它。
   实测比值：`coc_render / coc_declared = 74.105 = D × f_number = 33.684 × 2.2`（4 个视图完全一致，
   `renderer_over_declared_ratio_p50 == expected_ratio_D_times_fnumber`）；`f_px / D = 5.200 mm`
   恰好等于 `cameras/profiles.py` 为 `CAM_MID_V3` 声明的焦距（独立交叉验证）。
2. `deployment_mask_from_render` 把 mask 定义为 `(id_map≥0) ∧ ¬uncertain_mask`（再腐蚀 1 px），
   于是“CoC 判据把 83–90 % 物体判为不确定”直接变成“mask 只剩 0.26–7.2 % 物体”。
3. `update_visibility_truth` 的判据 `depth_ok ∧ id_ok ∧ ¬uncertain ∧ deployment_mask` 本来是
   计划要求的遮挡/不确定带语义（`VISIBILITY_RULE`），**没有实现缺陷**；投影也正确
   （1448/1448 全部落在画面内）。所以问题在 `synlab/observe`（掩膜/可见性），不在 `synlab/truth`。

**判据本身是否合理**：按 `CAM_MID_V3` 声明的光学（f=5.2 mm、f/2.2、220 mm 工作距、7.6 mm 传感器、
256 px 交付），同一批物体像素的声明 CoC **100 % 低于该 profile 自己声明的 2.0 px mark-out**
（`declared_coc_below_markout_ratio = 1.0`），交付分辨率下的景深区间为 `[109.3 mm, ∞)`
（`cameras/profiles.thin_lens_dof`），而物体深度跨度 88–94 mm 落在其中。也就是说：
**这 3 个 `visible_labels` 的失败不是物理必然，而是单位错误把 mask 缩小了约一个数量级**。
（另一处口径不一致：`pipeline._resolve_observe_spec` 的阈值补偿读的是
`configs/a12/camera_profiles.json` 的 f/8，而实际视图来自 `CAM_MID_V3` 的 f/2.2，于是阈值是
6.0 px 而不是 1.65 px——两种读法都比声明口径严得多。）

**处置：不改 + 给出精确修法（不是"放宽断言"）**。理由与最小修法：

- 最小修法（未实施）：在 `render_view` 里按交付网格评估 CoC，即除以
  `D = f_px / ViewFrame.meta["focal_length_mm"]`（`cameras/viewframes.py:223` 已把
  `focal_length_mm` 放进 frame meta；V1 registry 的 profile 缺该键时必须回退并记录，不能静默）。
  保留 `_resolve_observe_spec` 的阈值补偿时语义正好是声明的 mark-out：
  `coc_render / D = 0.51 px ≤ 2.0 px`（实测 v00：17.15/33.68）。
- 未实施的原因（如实记录，不含“做不到”）：(i) 它改变**所有后续渲染**的交付 mask 语义，
  而队友正在用 `configs/a12/next_experiment.yaml` 批量产数——中途改会让同一批数据混两种 mask 语义；
  (ii) 持久化闭环 store 里的 3 个 QA_FAIL 资产**不可就地修**（资产不可变），修代码只能让*重新生成*
  的数据不再复现，无法把已有 3 个变绿；(iii) “权威分辨率口径”是相机合同决策（`cameras/profiles.py`
  的 DoF 用传感器像元、`observe/render.py` 用交付网格），需要相机/观测负责人一起定，
  超出本次“最小修复”范围。**不采用放宽 `update_visibility_truth` 判据或删断言的方式掩盖。**
- 附带实测到的第二个缺口（只报告，未改，越权）：4 个视图 `interface_pixels = 0`，即物理组件
  网格上没有任何 `rim`(interface) 面片 → `observe/routes.py::_roi_mask_full` 得到的 ROI 为空。
  来源是 `physical/api.py::apply_damage` 在几何变化时把**所有**面写成
  `ORIGIN_AMBIGUOUS`（且仅在 `geometry_changed` 时写），以及 `observe/routes.py::resolve_target`
  在网格没有 face 属性时退化为全 0 标签；这两个文件按本任务写入范围（`physical/api.py` 仅限新增/
  扩展提交 helper、`observe/routes.py`/`api.py` 禁止改）均未改动。

### 13.5 本轮改动的文件

| 文件 | 改动 |
|---|---|
| `synlab/physical/api.py` | 新增 `commit_physical_result` + 共享 `_component_payload`/`_component_meta`；`commit_physical` 行为不变 |
| `synlab/pipeline.py` | 物理阶段提交 `physical_result`；coverage 行新增三个字段；**并修掉队友并行改动引入的器型↔参数错配**（见 13.6） |
| `tests/a12/integration/test_l0_loop.py` | `test_l0_commits_every_stage_asset` 按 plan 25.1 重写（闭包 PASS + 失败分母 + 守恒）；新增 `test_physical_result_pack_is_committed_with_real_measurements` |
| `tools/closed_loop.py` | `EXCLUDED_ROLE_REASONS`：更正 `visible_labels` 的原因描述（mask 非空、实测数字、指向 §13.4）；新增 `physical_result` 条目 |
| `data/a12/reports/**` | 新增探针与留档：`l0_role_census.py`（增强）、`smoke_physical_result.py`、`probe_visible_masks.py`、`probe_visible_render_spec.py`、`probe_uncertain_decomposition.py`、`probe_coc_units.py`、`probe_plan_param_mapping.py`、`l0_role_census.json`、`physical_result_smoke.json`、`visible_labels_*`、`pytest_*` |

### 13.6 仍未解决项

1. **`visible_labels` 的 mask 侵蚀**（13.4）：代码侧根因已定位、修法与验证算术已给，未实施；
   在修好并重新生成之前，L0/闭环数据里仍会有 `visible_labels` QA_FAIL（现在被测试如实枚举）。
2. **`physical_result` 在 L0/SANDBOX 与 closed-loop 配置下是 `QA_FAIL`**（A09：`NOT_WATERTIGHT`
   / `NON_POSITIVE_VOLUME` / `DAMAGED_NOT_SUBSET_OF_CLEAN`），因此 PhysicalPack 结果资产**进不了
   release**（被排除并记录）。这是真实缺口，修 A09 之前不应抬门。
3. **三个延迟判定角色仍是 `QA_PENDING`**（`pattern_recipe`/`pattern_channels`/`physical_component`）：
   判定属于 release 准备步骤，流水线未改；测试现在按 §25.1 枚举它们并用真实契约提升后再断言闭包。
4. **并行改动引入并已修的一致性缺陷**：`plan_generation` 改成“组合枚举 + `rng.permutation`”后，
   `_sample_parameter_sets` 仍按 `vessels[index % len(vessels)]` 发参数 → 3/4 谱系拿到别的器型参数
   （witness：`LIN0000_V02` 收到 V01 的 `depth_ratio`/`rim_flare`，`MOTHER_INVALID`，单母体
   accepted **0/1**；证据 `data/a12/reports/plan_param_mapping_probe.json`）。本轮把 permutation
   只抽一次、并把“被选中的 vessel 序列”交给采样器（签名不变）：修复后 sandbox 4/4、
   `next_experiment` 4/4 匹配、`mismatched=[]`。**若队友继续改同一函数，请保留这一处**，
   否则批量产数会大面积 quarantine。该修复也改变了 L0 第一条谱系（`LIN0000_V01_M01_PAT01` →
   `LIN0000_V02_M01_PAT02`），故 §12.5 与 §8 引用的旧 census 数字以本轮为准。
5. **持久化 store 的存量 QA_FAIL**：`data/a12_exports/closed_loop/store` 的 3 个 `visible_labels`
   资产不可变，保持 `QA_FAIL`（未就地改、未删）。

## 14. 两个阻塞 release/覆盖统计的缺陷：run_id 未落到全部资产、`release_freeze` 硬编码结论

本轮修两处**阻塞真实 release 与真实覆盖统计**的缺陷，判定与数字全部来自 store 与
`qc.gates.evaluate_gates`，**没有引入任何 override / 降级 / 强判 PASS**：

- 缺陷 1：`meta.run_id` 在 6 个角色上**完全缺失**——`clean_truth` / `obs_result` / `physical_truth` /
  `visible_labels` / `pattern_channels`（题目点名的 5 个）以及同一 `commit_pattern` 路径上的
  `pattern_recipe`。于是按 run 过滤的门（`fracture_operator_runs` / `observation_operator_runs`）
  恒为 `PENDING`（§14.1）；另有 2 个角色本轮仍未覆盖（§14.4 第 1 条）。
- 缺陷 2：`tools/closed_loop.py --step release_freeze` 把 sandbox 批次的结论**硬编码成 manifest
  文本**（`r2_relations_in_scope: 0`、"3 mothers / 3 materials / 3 patterns"、"contains NO relation
  with an R2 label"），而当前批次每个接受谱系都有真实 R2 → 写出的冻结 manifest 与自己的内容矛盾
  （§14.2）。

产物：`data/a12/reports/runid_coverage_probe.py`（探针）、`runid_coverage_compare.py`（对比）、
`runid_fix_before.json` / `runid_fix_after.json` / `runid_fix_comparison.json` /
`runid_fix_manifests.json`、`runid_fix_*.txt`、`closed_loop_freeze_after_runid_fix.txt`、
`closed_loop_fresh_*_after_runid_fix.txt`、`pytest_integration_after_runid_fix*`。

### 14.1 缺陷 1：6 个角色的 `meta.run_id` 完全缺失（实测）

判定口径：`qc.gates.evaluate_gates` 第一句就是
`assets = [a for a in store.list_assets(...) if (a.meta or {}).get("run_id") == run_id]`，
`qc.audit.audit_run` 与冻结范围同样只认 `meta["run_id"]`。

**实测（同一个 config、同一个 master_seed、单母体，仅代码版本不同）**：探针把
`configs/a12/closed_loop.yaml` 以 `max_mothers=1` 生成到两个私有 store，然后**只读**统计
每个角色的 `meta.run_id`：

| 角色 | 修复前 `run_id`/总数 | 修复后 `run_id`/总数 | 备注 |
|---|---|---|---|
| `clean_truth` | **0 / 1** | **1 / 1** | `fracture_operator_runs` 的判定对象 |
| `obs_result` | **0 / 1** | **1 / 1** | `observation_operator_runs` 的判定对象 |
| `physical_truth` | **0 / 1** | **1 / 1** | |
| `visible_labels` | **0 / 1** | **1 / 1** | |
| `pattern_channels` | **0 / 1** | **1 / 1** | |
| `pattern_recipe` | 0 / 1 | 1 / 1 | 同一个 `commit_pattern` 调用路径 |
| `mother_mesh` | 1 / 1 | 1 / 1 | |
| `fragment_mesh` | 2 / 2 | 2 / 2 | |
| `feature_bundle` / `label_bundle` / `provenance` | 1 / 1 | 1 / 1 | |
| `physical_result` | 1 / 1 | 1 / 1 | 队友已补（§13.2） |
| `material_profile` | 0 / 1 | 0 / 1 | **仍未覆盖**（§14.4 第 1 条） |
| `physical_component` | 0 / 1 | 0 / 1 | **仍未覆盖**（§14.4 第 1 条） |

run / 代码版本（探针在生成前后各算一次哈希，两次相同，故数字可归因到确切版本）：

| 阶段 | run_id | accepted | `synlab/pipeline.py` | `truth/api.py` | `observe/api.py` | `patterns/commit.py` | `qc/gates.py` |
|---|---|---|---|---|---|---|---|
| 修复前 | `run_6a878b1a93ffb34f` | 1/1 | `cff1342147d570af` | `06513d487c449592` | `d6009c04c17924c4` | `1f1cd32b2f5b8066` | `bac93774f326d3a7` |
| 修复后 | `run_d766886cb5b2f45b` | 1/1 | `bf6485351685c183` | `da5d224cc63fc18c` | `ed2122bc4c0b021d` | `c1b7ca7df5dc87f8` | `bac93774f326d3a7`（未改） |

**门状态前后**（同一探针内 `qc.gates.evaluate_gates(store, run_id)`，无 tagging/无提升/无 override）：

| 必需门（SANDBOX_CORE） | 修复前 | 修复后 |
|---|---|---|
| `fixture_contract` | PASS | PASS |
| `source_map` | PASS | PASS |
| `fracture_operator_runs` | **PENDING** | **PASS** |
| `observation_operator_runs` | **PENDING** | **PASS** |
| `coordinate_contract` | PENDING | PENDING |
| `readonly_commit` | PENDING | PENDING |

后两个门与 run_id 无关，它们读的是**闭环 `audit` 步**才产出的证据
（`coordinate_contract` ← `reports/acceptance_summary.json` 的 A02 项；`readonly_commit` ←
`reports/audit_<run_id>.json` 的 `store_health.ok`）。在跑过 `audit` 的 store 里这两门转 PASS，
见 §14.2 的 fresh store（6/6）。

**修法（最小、向后兼容、不动既有签名）**：

| 文件 | 改动 |
|---|---|
| `synlab/truth/api.py` | `commit_truth(..., run_id: str \| None = None)`：给了才写 `meta["run_id"]`（未给则元数据逐字节不变 → 既有调用者资产 id 不变） |
| `synlab/observe/api.py` | `commit_observation(..., run_id=None)`：同上 |
| `synlab/patterns/commit.py` | `commit_pattern(..., run_id=None)`：**只**写进 recipe 资产与 channels 资产的 `meta`，**不碰** recipe 文档（它被哈希进 `recipe_hash`） |
| `synlab/pipeline.py` | 5 处调用补 `run_id=run_id`：clean truth / physical truth / visible labels / `commit_observation` / `commit_pattern` |
| `synlab/qc/gates.py` | **未改**：门本来就按 `meta["run_id"]` 过滤，缺的是写入方，不是判定方（改动为零亦为证据） |

**命令与退出码**

| # | 命令 | 退出码 |
|---|---|---|
| 1 | `& .venv\Scripts\python.exe data\a12\reports\runid_coverage_probe.py before` | **0**（单母体 accepted 1/1，99.6 s） |
| 2 | （改代码） | — |
| 3 | `& .venv\Scripts\python.exe data\a12\reports\runid_coverage_probe.py after` | **0**（单母体 accepted 1/1，125.5 s） |
| 4 | `& .venv\Scripts\python.exe data\a12\reports\runid_coverage_compare.py` | **0**（写 `runid_fix_comparison.json`，留档 `runid_fix_comparison.txt`） |

> 归属说明：这两次生成是用同一个探针在仓库根目录以临时文件名跑出来的（内容与
> `data/a12/reports/runid_coverage_probe.py` 相同，仅把仓库根解析改为按 `pyproject.toml` 上溯），
> 跑完后归档到 `data/a12/reports/`。compare 脚本已在新位置实跑复核（退出码 0，输出与本表一致）。

### 14.2 缺陷 2：`release_freeze` 的硬编码结论（已删，全部改为实测）

**删掉的硬编码**（`tools/closed_loop.py`）：

1. `coverage.r2_relations_in_scope: 0`（字面量）→ 现在从冻结范围内的关系资产数出来。
2. `extra.scope_declaration` 整段模板文字（"3 mothers / 3 materials / 3 patterns / 6 fragments"、
   "It contains NO relation with an R2 label"）→ 现在由实测覆盖与实测关系计数拼装；
   **只有** `r2 == 0` 时才允许出现"no relation with an R2 label"这句话，否则写成
   "contains N relation(s) with an R2 label"。
3. `extra.relation_status` 的 `{r2_edges: 0, unknown_edges: 3, reason: "ambiguity_area_ratio …"}`
   → 现在逐角色、逐 kind 实数（`R2/R1/TINY_CONTACT/UNKNOWN`）+ 关系行 `reason` 直方图 +
   `clean_truth` 与 `label_bundle` 的 R2 交叉核对。
4. `extra.visibility_status` 的 `{passed: 2, failed: 1, reason: "…camera-z span…"}`
   → 现在按冻结范围内 `visible_labels` 的**自身判定**计数，失败项逐条带 `qa.failures`。
5. `EXCLUDED_ROLE_REASONS` 里引用 `run_852ab2a1e4c3b70f` 实测像素数的散文
   → 换成 `EXCLUDED_ROLE_CONTRACTS`（只写**合同**，不含任何 run 的数字）；
   每个被排除资产的理由从它自己的 `qa` 块读出（`excluded_assets[].reasons`），
   并按 `{role: {qa_status: [reasons]}}` 汇总进 `excluded_role_reasons`。
6. `coverage` 的 `vessels`/`materials`/`fragment_assets_in_scope` 仍在，但全部改为按
   `meta.run_id` 的实测集合；新增 `mothers/mother_ids/lineages/splits/patterns/layer_combos/
   observations/run_id_attribution/ledger/sources`。

`GATE_DOWNGRADES` 保持**空字典**（PASS 只能由证据给出），冻结仍在
`ReleaseManager.freeze` 处对任何非 PASS 必需门**拒绝**，未过门写进 `scope_pending` 与
`release_freeze_blocked.json`（§14.2.3 有反例）。

#### 14.2.1 命令与退出码

| # | 命令 | 退出码 | 结果 |
|---|---|---|---|
| 1 | `& .venv\Scripts\python.exe tools\closed_loop.py --step release_freeze`（默认 store/ledger 原样） | **0** | `release_freeze OK 2.3s` → `rel_852ab2a1e4c3_1790909619`，`assets=165`，`scope_pending=[]` |
| 2 | `… tools\closed_loop.py --step generate --mothers 1 --store data/a12_exports/cl_fresh/store --out data/a12_exports/cl_fresh --report data/a12_exports/cl_fresh/ledger.json --evidence data/a12` | **0** | 单母体 accepted 1/1（105.5 s） |
| 3 | `… --step audit`（同上 store/out） | **0**（`DEGRADED`） | `DEGRADED` = 该 run 内有 `QA_FAIL` 资产：实测 `qa_failed = ['asset_992a91766722166cb536(physical_result)']`（`qa.failures = ["NOT_WATERTIGHT"]`）；延迟判定的 3 个角色由真实契约提升为 `QA_PASS`（`pattern_recipe`/`pattern_channels`/`physical_component`） |
| 4 | `… --step release_freeze`（同上） | **0** | `release_freeze OK 1.0s` → `rel_9a5c5a39a8ad_1790909613`，`assets=14`，`scope_pending=[]` |

`--step release_freeze` 的默认调用读的是持久化 store 与 74 MB ledger，**按题目原样执行**；
fresh store 的三个步骤给出一个没有历史污染的对照。

#### 14.2.2 manifest 关键字段（实测，全部可由 store 复算）

**fresh store**（`data/a12_exports/cl_fresh/store/releases/rel_9a5c5a39a8ad_1790909613`，
单母体、无历史污染）：

| 字段 | 实测值 |
|---|---|
| `release_id` / `profile` / `assets` | `rel_9a5c5a39a8ad_1790909613` / `SANDBOX_CORE` / 14 |
| `scope_completed` / `scope_pending` | 6/6 必需门 / **`[]`** |
| `extra.gate_overrides` / `refused_gate_overrides` | **`[]`** / `[]` |
| `coverage.run_id` / `lineages` | `run_9a5c5a39a8ada0fc` / `["LIN0000_V02_M01_PAT02"]` |
| `coverage.mothers` / `vessels` / `materials` / `patterns` / `layer_combos` | `1` / `["V02"]` / `["M01"]` / `["PAT02"]` / `["L01"]` |
| `coverage.fragment_assets_in_scope` / `observations` / `splits` | `2` / `1` / `{"train": 14}` |
| `coverage.r2_relations_in_scope` / `relations_in_scope` | **`1`** / `1` |
| `coverage.roles` | 13 个角色共 **14 个 `QA_PASS` 资产**：`clean_truth 1, feature_bundle 1, fragment_mesh 2, label_bundle 1, material_profile 1, mother_mesh 1, obs_result 1, pattern_channels 1, pattern_recipe 1, physical_component 1, physical_truth 1, provenance 1, visible_labels 1`（store 内另有 1 个被排除的 `physical_result`，共 15 资产） |
| `coverage.run_id_attribution` | `stamped_at_commit 12` / `stamped_by_run_attribution_repair 2`（= `material_profile` + `physical_component`，§14.4 第 1 条） |
| `coverage.ledger` | `run_id_matches true`，`rows_attributed_to_this_run 1`（按行内 asset id 归属） |
| `relation_status.kinds`（逐角色） | `label_bundle {R2: 1}`、`clean_truth {R2: 1}`、`physical_truth {R2: 1}`、`visible_labels {}` |
| `relation_status.cross_check` | `clean_truth_r2 1` == `label_bundle_r2 1` → `agree true` |
| `visibility_status` | `passed 1 / failed 0 / pending 0`（按资产自身判定） |
| `excluded_role_reasons` | `{"physical_result": {"QA_FAIL": ["NOT_WATERTIGHT"]}}`（真实失败码，不是散文） |
| `scope_declaration` | "…1 mother(s) / 1 material(s) / 1 pattern(s) / 1 layer combo(s) / 2 fragment asset(s) / 1 observation(s) over 1 accepted lineage(s)… Measured relation content … **1 R2** / 0 R1 / 0 TINY_CONTACT / 0 UNKNOWN over 1 frozen relation edge(s) … **This release contains 1 relation(s) with an R2 label**…" |
| `manifest_hash` / `closure` | `sha256:…`（可 `ReleaseManager.load` 复算）/ `{ok: true, files_checked: 15}` |

**同一持久化 store、同一 run 的旧/新 manifest 对照**（证明缺陷 2 的"自相矛盾"确实存在、且已消除）：

| 字段 | 旧 `rel_852ab2a1e4c3_1790905541`（硬编码） | 新 `rel_852ab2a1e4c3_1790909619`（实测） |
|---|---|---|
| `coverage.r2_relations_in_scope` | `0` | **`6`** |
| `extra.relation_status` | `{r2_edges: 0, unknown_edges: 3, reason: "…ambiguity_area_ratio (0.13-0.28) …"}` | `kinds {R2: 6, UNKNOWN: 15}`，逐角色 `{label_bundle {R2:6,UNKNOWN:15}, clean_truth {R2:6,UNKNOWN:3}, physical_truth {R2:6,UNKNOWN:3}}`，`cross_check.agree = true`（`relations_in_scope = 21`） |
| `extra.scope_declaration` | "…3 mothers / 3 materials / 3 patterns / 6 fragments…" + "**contains NO relation with an R2 label**" | 实测数字 + "**contains 6 relation(s) with an R2 label**" |
| `extra.visibility_status` | `{passed: 2, failed: 1, reason: "…camera-z span (~64 mm)…"}` | `passed 6 / failed 0 / pending 0` + 逐条 `failures`（本 store 的 `QA_FAIL` 是 3 个旧 `visible_labels`，见下） |
| `extra.gate_overrides` | `[]`（更早的 3 个 manifest 里还有 1 条 `coordinate_contract` PENDING→PASS 的旧 override） | **`[]`** |
| `extra.excluded_role_reasons` | 引用 `run_852ab2a1e4c3b70f` 像素数的散文 | `{"visible_labels": {"QA_FAIL": ["no correspondence sample is visible in any view"]}}`（来自资产 `qa.failures`） |

**旧 manifest 的"矛盾"是可复算的**：同一 store 的 `label_bundle.meta.relations_json` 里
`kind == "R2"` 的边为 6 条（`relations_in_scope` 21 条），而旧文本写的是 0 与 "NO relation with an
R2 label"——冻结时的数字必须与内容一致，这正是本轮要消除的失真证据。

**存量污染（实测，如实在 manifest 里暴露）**：新 manifest 的
`coverage.run_id_attribution = {stamped_at_commit: 18, stamped_by_run_attribution_repair: 147}`。
该 store 的 7 次生成（02:18–02:53，同一 plan、代码指纹不同 → 不同 run_id）都留下了资产，而**旧版**
`_tag_run_assets` 按 `lineage_id` 归属（同一 plan 的 lineage id 会重复），把别的 run 的
`mother_mesh`/`fragment_mesh`/`clean_truth` 等也盖上了 `run_852…` 的戳：实测
`mother_mesh 21` 个里只有 3 个是流水线在提交时自己写的（`run_id_source` 为空），18 个是旧的
lineage 归属写的；`clean_truth 9` 个全部由旧归属写入。本轮的冻结**不隐藏**这一点：
`run_id_attribution` 直接给出"提交时写入 vs 归属修复写入"的计数并附说明，
`coverage.roles` 因此在该 store 里是 42 fragments / 21 mothers / 3 lineages（真实反映 store 的声明）。
**这些戳不可回滚（资产元数据在提交后只可由 store 层改写，而本轮的归属修复已不再按 lineage 猜）**，
所以下一批必须写进**新 store**；fresh store 的 14 资产对照即是干净口径。

**本轮的归属修复**（`tools/closed_loop.py::_tag_run_assets`）改为**按 run 自己写的 coverage 行里的
asset id 精确归属**（`mother_asset/material_asset/pattern_asset/clean_truth/physical_asset/
physical_result_asset/obs_asset/visible_asset/feature_asset/label_asset/provenance_asset`），
且**只在** `reports/coverage.json` 的 `run_id` 与本次 run 一致时才生效（否则一个都不标并写出原因）。
它现在只覆盖"提交路径本身不带 run 的两个角色"（`material_profile`、`physical_component`），
fresh store 里恰好是那 2 个。

#### 14.2.3 没有放宽门：缺证据时仍然 PENDING / 拒绝冻结

- 未跑 `audit` 的 store（§14.1 的两个探针 store）里 `coordinate_contract` 与
  `readonly_commit` 保持 **PENDING**，`evaluate_gates` 不会因为"结果想要 PASS"而给 PASS。
- `GATE_DOWNGRADES` 为空字典；`ReleaseManager.freeze` 对非 PASS 必需门抛
  `STOP_QA`，`step_release_freeze` 捕获后写 `release_freeze_blocked.json`
  （含 `required_gates`/`gates`/`scope_pending`/`coverage`/`relation_status`/`visibility_status`），
  并返回 `status=FAILED, frozen=false`。
- 全部 10 个 release 的 `gate_overrides` 实测（`data/a12/reports/release_manifests_after_runid_fix.txt`）：
  更早版本冻结的 4 个（`rel_8049cf187288…` / `rel_fda083aa68a8…` / `rel_b06f9f7e9508…` /
  `rel_852ab2a1e4c3_1790880811`）各带 **1** 条 `coordinate_contract` override（旧逻辑残留）；
  **本轮改动后冻结的 5 个**（`rel_852ab2a1e4c3_1790909555/1790909572/1790909619`、
  `rel_9a5c5a39a8ad_1790909543/1790909613`）`gate_overrides` **全部为 `[]`**，
  `refused_gate_overrides` 亦为空。
- 本轮**没有**为了让任何东西变绿而改 `qc/gates.py`、改 profile 门表、或抬/降门的判据。

### 14.3 集成测试（本轮改动后）

| # | 命令 | 退出码 | 结果 |
|---|---|---|---|
| 1 | `& .venv\Scripts\python.exe -m pytest tests/a12/integration -q -p no:cacheprovider` | **0** | 进度 `...................................`（35 点，无 `F`/`E`） |
| 2 | `& .venv\Scripts\python.exe -m pytest tests/a12/integration -q -p no:cacheprovider --junitxml=data/a12_exports/pytest_integration_after_runid_fix.xml` | **0** | **`tests 35 / failures 0 / errors 0 / skipped 0`，用时 164.5 s**（junit XML 由 pytest 自己写出，逐用例可查：`test_closed_loop 26` + `test_l0_loop 9`） |
| 3 | `… --collect-only -q -p no:cacheprovider` | **0** | 收集数 **35** = `test_closed_loop.py 26` + `test_l0_loop.py 9` |
| 4 | `& .venv\Scripts\python.exe -m pytest tests/a12/truth tests/a12/patterns tests/a12/observe tests/a12/materials -q -p no:cacheprovider --junitxml=data/a12_exports/pytest_units_touched_modules.xml`（回归：本轮改签名的 4 个模块） | **0** | **`tests 324 / failures 0 / errors 0 / skipped 2`，用时 164.7 s**（留档 `pytest_units_touched_modules.xml` / `.txt`） |

**失败项：无**。`test_l0_loop.py::test_l0_commits_every_stage_asset`（§13 的最后一处失败，
`physical_result: expected >= 1, got 0`）本轮**转绿**——`physical_result` 生产者已在 §13.2 补齐，
本轮未再改该测试。留档：`pytest_integration_after_runid_fix.xml`（权威计数）、
`pytest_integration_after_runid_fix.txt` / `_run2.txt`（退出码 0）、
`pytest_integration_collected_after_runid_fix.txt`（35）。

> 控制台留档的注意点：本机 PowerShell 读子进程 stdout 用 GBK，遇到 Python 的 UTF-8 输出会抛
> `PytestUnhandledThreadExceptionWarning: 'gbk' codec can't decode byte 0xa3`，`-q` 的末尾
> "35 passed" 摘要行因此可能丢失（日志里可见）。故以 **junit XML + 退出码 + 收集数**三件一致为判据。

### 14.4 仍未解决项（真实原因与分母，本轮未改）

1. **`material_profile` / `physical_component` 仍不带 `meta.run_id`**：这两个角色的提交入口
   （`synlab/materials/api.py::commit_material`、`synlab/physical/api.py::commit_physical`）
   不在本轮写入范围。影响：它们只能靠闭环 `_tag_run_assets` 的精确归属进入 run 范围，
   直接跑 `run_generation`（不经闭环）时它们不被计入 run。**建议**：给这两个提交 helper 同样加
   一个可选 `run_id=None`（与 §14.1 的改法完全同构）。
2. **`relations_complete`（PILOT 必需门）仍会拦下 PILOT 冻结**：该门读 `ROLE_POOL`（`relation_pool`）
   的 `QA_PASS` 且带 `run_id` 的资产，而 pool/roster 由 `synlab/relations/api.py::commit_pool/
   commit_roster` 提交、不带 run（写入范围外）。实测：`data/a12` 主库里 `relation_pool 5`、
   `query_roster 2` 全部 `run_id=None`；`data/a12_exports/closed_loop/store` 里同样为 `None`。
   因此 SANDBOX_CORE（6 门）可以冻结，**PILOT（12 门）不行**——这是本轮之后下一批实验的
   第一阻塞点，需要 relations 侧补 `run_id` 或由 Lead 决定把 pool 的 run 归属写在别处。
3. **`coverage_*` 门需要"按 run/按批次聚合"的覆盖表，现在读不到**：
   `gates.py` 读 `reports/coverage.json`，而该文件是 **store 全局**（每次生成覆盖前一次），
   且它的键是 `fracture_backend`（单数、字符串）与**不存在**的 `axes`
   （实测 fresh store 的 `coverage.json` 键：`accepted/attempted/complete/failed/fracture_backend/
   layer_combos/materials/patterns/per_split/planned/quarantined/run_id/schema/seconds/spec_hash/
   vessels`）。所以即使覆盖到位：`coverage_24_vessels/12_materials/16_patterns/4_layers` 只能反映
   **最后一次生成**；`coverage_4_backends` 永远读不到（键名多一个 s）；`coverage_31_axes` 永远
   读不到（键不存在）。**且批次是分 run 生成的**（`tools/batch_generate.py` 每批一个 `run_id`），
   单 run 聚合不可能达到 24 器型/12 材料。→ 需要一份按批次多 run 聚合的覆盖产物（并补
   `fracture_backends`/`axes` 两个键），这是独立工作项；本轮**没有**改 `gates.py` 的判据、
   也没有伪造这两个键。
4. **持久化 store 的 run_id 存量污染不可回滚**（§14.2.2）：`data/a12_exports/closed_loop/store`
   的 165 资产里有 147 个是旧归属写入的戳，下一批实验请使用新 store。`data/a12` 主库同理
   （本轮开始时该库只有 `feature_bundle/fragment_mesh/label_bundle/mother_mesh/provenance` 带
   `run_id`，而 `clean_truth 13` / `obs_result 8` / `physical_truth 12` / `visible_labels 12` /
   `pattern_channels 16` / `pattern_recipe 16` / `physical_component 24` / `material_profile 10`
   全部为 `None`）——它的存量必须靠**重新生成**由本轮修复写入，不能事后补戳假装是当时的归属。
5. `visible_labels` 的 mask 侵蚀（§13.4）与 `physical_result` 的 A09 `QA_FAIL`（§13.6 第 1/2 条）
   保持原样：它们让相应资产被排除出 release，本轮未放宽、未删断言。


