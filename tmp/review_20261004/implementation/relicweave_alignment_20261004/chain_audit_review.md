# 2026-10-04 `forge_chain_audit` 只读审阅

## 结论与审阅边界

现存 `current_chain_audit.json` 给出 `INCOMPLETE`、29 个 gap；它正确保留 `SCIENCE_UNVERIFIED`、`physics_qualified=false`、`pretrain_qualified=false`。当前来源能证明的是：VF manifest、PG job/result、A12 export/degradation index、deploy view policy 这 6 个被显式引用的 JSON 文件，其实际字节 SHA 与 input 中声明的 SHA 一致。当前链没有 event ID/parent ID、行级 fragment 与 crack surface、行级关系、真实 observation/capture、独立 feature/label 资产链接；PG job 的 initial condition 是 `uniform_box_bar_fixture`，不是 VF 表面派生初始条件。故其现有求解器证据可保留为受限诊断，不能据此说 VF→PG→fragment→A12 生产链已经闭合。

此工具是静态 lineage auditor，不返回“给定碎片→候选列表”，也没有 A3/A4 检索、排序证据、拒识、重新采集或 STOP 接口。RelicWeave 的不变目标仍是这些候选行为；此审计器以及让所有缺失输入都成为同一个全局阻断条件，都是可替换的实现方法。当前报告没有 `SCHEMA_MISMATCH`；29 项是缺少引用/行级数据、显式失败状态或未接受 gate，并非 29 个 schema 定义缺失。

未重跑 pytest 或 solver。`execution_receipt.json` 记载目标模块 8 个测试通过（`........ [100%]`，exit 0）；该 receipt 只保留这次通过记录。在本次可见的 audit 目录及针对性搜索结果中没有找到先前 initial-fail 日志，因此不能声称该失败证据已经被 receipt 保存，也没有覆盖或重建它。审计报告中的 `STRUCTURAL_PASS` 只表示其有限静态结构断言全满足：测试特意把科学资格与之分开，但该状态不能成为物理/训练准入或候选质量证据。

## 29 项 gap 与依赖层级

| 计数 | 层级 / gap 字段 | 对当前目标的含义 |
|---:|---|---|
| 7 | **VF→PG 事件来源与对象覆盖**：`references.fragment_set_manifest`、`references.crack_surface_manifest`、`event.event_id`、`event.parent_asset_id`、`native_job.initial_condition`、`fragment_set.fragments`、`crack_surfaces` | 这是从指定资产到真实事件、全碎片集合及其配对断面的基础 join；缺失时不得声称这些候选边来自当前资产的真实断裂。`uniform_box_bar_fixture` 仍可用于独立 solver/序列化诊断，但应标为未链接 fixture。 |
| 8 | **材料与退化测量**：`references.material_calibration_record`、`material.calibration_status`、`references.degradation_recipe_record`、`degradation.recipe_id`、`references.degradation_measurements`、`degradation.actual_quantities`、`degradation.actual_measurements`、`degradation_index.rows` | 校准缺口阻断物理结论；退化缺口阻断损伤/磨损鲁棒性、同一碎片跨退化级的候选不变性声明。它不应阻止明确标注为无校准、无退化覆盖的接口或模型诊断。 |
| 12 | **历史关系、观测、采集及输入/标签分离**：`references.historical_relations_record`、`historical_relations`、`historical_relations.provenance`、`references.observations_manifest`、`observations`、`references.capture_records`、`capture_records`、`references.input_feature_spec`、`features.fields`、`references.isolated_label_spec`、`labels.fields`、`labels.separate_asset` | 缺口阻断真实候选召回/拒识评估及监督准入；可以运行合成契约/接口诊断，但输出必须显式排除真实候选召回结论。A12 的 aggregate R0/R1/R2 与 59 observations 不能充当此事件的行级真值或 capture。 |
| 1 | **物理 gate 证据引用**：`gates.NumericPhysical.evidence_ref` | 当前 NumericPhysical 为 UNKNOWN、无证据引用；阻断数值物理 gate 的接受，不必阻断 solver 诊断。 |
| 1 | **A12 export 引用闭包**：`dataset_export_manifest.reference_closure` | 实际 export 明示 `ok=false`，含 pending/fail/missing asset 问题；阻断将 aggregate package 当作闭合发布包或预训练准入。 |
| **29** | **总计** | 缺少相关 schema 不应抹掉其它已核验的诊断证据；也不应将诊断提升为候选链闭合。 |

当前 A12 export 明确记录 `degrade_sources=0`、`degrade_variants=0`；被引用 `degrade/index.json` 也明确 `rows=[]`、`sources=[]`，所以这次“无已提交退化测量/变体”是实际零值，非推断。export 的 aggregate relation counts（R0 3120、R1 48、R2 56、TINY_CONTACT 6、UNKNOWN 212）只描述合成汇总；它们不能证明与当前 PG event 有关的任一行标签。审计器把 aggregate 与行级链分开是正确方向。

## 关键审查发现

**P1 — 全片 roster 和关系 endpoint 仍由调用方声明，来源引用没有闭合这些行。** `event.fragment_ids` 只在它是 list 且 `fragments` 非空时比较（`forge_chain_audit.py:413-416`）；缺省 roster 不报错，空列表配空 rows 也不与 PG 结果或 fragment manifest 的权威 roster 核对。`fragment_set_manifest` / `crack_surface_manifest` 的 JSON 只被 hash-read，内容未用于确认 `chain.fragments` / `chain.crack_surfaces` 的覆盖。R0/R1 只要求 candidate 是不同非空字符串，不检查它在 fragment roster 内（`504-509`）；R2 才通过成对断面检查端点（`510-519`）。因此可以遗漏小片/孤片而不知，或给出不存在的 R0/R1 candidate；这会改变候选召回分母、负例集合及拒识阈值。应把全片集合与来源 manifest/PG 结果做可核对的完整 join，保存每个小片/孤片和 UNKNOWN；校验每个关系两端都存在，但保留一对多 R2 邻接，不做 R2 传递闭包。

**P1 — 单一严格状态把全链验收与允许的诊断混成一种阻断。** `REQUIRED_REFERENCE_KEYS` 与其缺失检查对任何调用都记录 structural problem（`63-78, 246-249`）；PG job 不是 `forge_asset_surface` 也进入同一阻断（`376-379`）。本次缺 observations/labels/R2 真值，确实不能验收真实候选/训练；但这不应该抹掉已有 uniform-box PG 求解器诊断、hash核验、adapter 契约测试或纯接口集成状态。建议区分 diagnostic-only、候选数据链就绪、物理 gate、预训练准入；缺失来源仍逐项报告，且 diagnostics 明确不计入真实召回/物理验证。不要把 `SCHEMA_MISMATCH`、引用缺失与物理 gate UNKNOWN 合并成同一语义。

**P2 — 面积与“成对”目前只证明弱结构条件。** 每条断面 finite 且 `area_mm2>0`，每个 pair 恰有 A/B（`448-468`），但没有经过验证的可分辨面积/数值容差，也没要求 A/B 属于不同 fragment（R2 存在时，后续端点比较才间接约束）。虚构完整 fixture 用 `1e-9 mm²` 的两侧断面仍通过 `STRUCTURAL_PASS`（测试 `test_forge_chain_audit_20261004.py:81-86, 128-140`）；这可证明不硬编码样本数，却不能证明物理断裂面具有足够分辨率。不要从这个 fixture 推导最小现实面积阈值；需由项目分辨率/几何 QA 与用途共同给定，且配对双方分别留存 source 与 measurement provenance。

**P2 — ref SHA 已重算，manifest 内 payload SHA 不是实际文件校验。** `_read_reference` 对显式 JSON 的实际字节 SHA 与 input 声明比较（`140-195`）；当前 parent/job/result/export/index/policy status 都为 `HASH_VERIFIED_JSON_READ`，result 当前 `input.job_sha256` 也与已核验 job JSON SHA 匹配。另一方面，VF manifest 的 STEP/NPZ entries 只检格式、byte数并比较 canonical STEP 声明（`313-320`），不会打开/哈希这些 payload；fixture 故意用 `a…a`、`b…b` 等虚构文件 SHA、每个 byte count=1，仍可结构通过（测试 `34-43,128-140`）。此外 result 的 job SHA 仅在字段存在时比较（`368-370`）。因此报告的“verified”严格指其列出的 JSON reference 字节，不是包内几何或观测 payload 已验证。可保留只读/不扫描目录的安全边界，同时对 manifest 列明的有限 payload 路径显式逐项校验，或将状态命名为 manifest-declared-only。

**P2 — 模型特征白名单和 deploy channel 白名单被混作同一字段空间。** `fragment_ids`、`meta` 被正确排除于 `FEATURE_BUNDLE_FIELDS`，A12 adapter 也说明 `fragment_id/row_id/sample_id` 只用于索引/日志（`adapter.py:82-86`）；`TorchFeatureBundle.select` 去掉 IDs/meta 后选择 tensor，实际 encoder 用图像、点/法线、local tokens、quality/presence 和 validity/scale masks，不读 ID 或 R2 标签（`adapter.py:545-590; model.py:270-319`）。然而审计器没有核对 hash-verified `input_feature_spec` 内容；它将 `_check_feature_policy` 返回的 deploy channel key 直接并入模型字段许可集（`forge_chain_audit.py:54-61, 206-214, 590-609`）。当前 channel keys 含 `K`、`roi`、`tiles`、`deployment_mask` 等，与 `FeatureBundle` 成员并非同一名字空间；`features.fields=["K"]` 可能被这套静态比较放行，尽管未验证其如何映射到 encoder tensor。另 `labels.separate_asset=true` 与字段清单是 caller 声明，label spec 的引用内容没有与真实 label-bundle bytes/role 绑定。当前泄漏检查是字段名层面的，不是 payload/runtime 层证明。

**P2 — aggregate 缺省会被当作明确零。** 当前 export 的相关键全都在且为 0，因此本次 gap 有数据支持。但 `degrade_counts.get("degrade_sources", 0)` 和 `.get("degrade_variants", 0)`（`705-707`）会把非空 partial mapping 中缺失的键也报告为零；若未来 manifest 缺字段，审计会报“zero committed”，而非“count missing/unknown”。应分别要求键存在且值是有效整数后判零，缺键报告 UNKNOWN/schema-contract gap。测试没有覆盖 partial/missing-key 情形。

**测试范围边界。** 8 个用例验证了 fictional结构通过但 science/pretrain仍 false、缺历史标注为 UNKNOWN、禁止 R2 特征字段、保留孤片/微小片、未知关系不降格为 R0、缺 crack pair、PASS 字符串不构成 gate 证据、路径遍历与引用 hash mismatch。它们没有检验真实 producer row 与链行的完整对照、roster 缺省/部分遗漏、R0/R1 candidate 孤儿、多个非传递 R2 邻居、同一 fragment 两侧误配、deploy channel 与模型张量错位、aggregate count 缺键，以及 payload bytes/hash 语义。未要求本轮新增测试或运行。

## 与候选召回和拒识的最小交付关系

真实断裂边与双侧面几何提供哪些碎片确实是候选 mates 的事件真值；材料与数值可信度决定模型学到的是可部署的碎裂线索还是 solver/网格伪影。若来源片集合缺失，真实 mate 可能从 gallery 与召回分母消失；若 damaged/unknown label 被删或默认映射为 R0，会同时污染正例、负例与拒识校准。退化必须有实际测量和 label invalidation/有效性记录，才能分清“同一物理碎片不同可见状态”（外观/观察不变性）与“同一碎片 mate 关系”；不然模型可能把表面磨损当成非配对证据，或把已毁损的 mate 仍算有效答案。

部署侧模型输入应限于实际会取得的观测模态及其质量/有效性掩码（当前 adapter/model 包括 RGB/multiview、local observation tokens、点/法线、quality/presence 与 masks）。fragment/event/object IDs 只用于索引/日志；R0/R1/R2、mating truth、GT pose/thickness/normals、clean hidden geometry、damage labels、future capture/recapture outcome 是监督/评估或采集控制真值，不能进入模型 forward。即使 `STRUCTURAL_PASS`，本审计不读取 feature/label payload，故不能证明线上无 truth leakage。A3/A4 仍负责给出候选和支撑证据；证据不足时由其拒识、要求重采或 STOP。

## 优先复审建议（仅建议，本轮未执行）

1. **先拆状态语义，不拆目标。** 将 solver/geometry/contract diagnostic 与真实候选链闭合、物理 gate、预训练准入分层出结果；所有缺项照常列出，diagnostic-only 不阻断运行但永不冒充 recall/physics evidence。固定的 `forge_asset_surface` 只能是闭合真实链的一条路径，不应用来拒绝其它有明确定界的诊断方式。
2. **先补权威来源 join 和完整 roster。** 从 PG/fragment/surface producer manifest 建立明确版本化的引用合同；要求全 event fragment roster可验证、所有关系两端在集合中、成对面属于两个不同碎片、每个 R2 edge 有独立双面证据。保留多邻居、非传递 R2 及 UNKNOWN/孤片，不通过删退化面或 aggregate count 代替行级真值。
3. **复审物理/API 证据边界。** 将观测 channel keys 与 `FeatureBundle` tensor field schema 分离，并把 feature/label 真实资产分别链接；明示 SHA 检验覆盖 JSON 还是 payload。对面积分辨能力/退化测量阈值按目标分辨率和用途立证据，不沿用任意 epsilon；aggregate 缺键报 UNKNOWN、明确零才报零。

## 读取来源和 SHA-256

这些 hash 是本轮审阅实际只读读取时计算；源代码与测试的值也与现存 `execution_receipt.json` 内冻结 digest 一致。receipt 本身是已存执行说明，不等于外部签名证明。

| 路径 | 字节数 | SHA-256 |
|---|---:|---|
| `RelicWeave_V1.44_Optimized_Complete_Plan.docx` | 546163 | `4507EAD923D60CC8DC20C2A31E532394F4D8AB406A5703BF09EEB606AB6F6374` |
| `relicweave-synlab/synlab/qa/forge_chain_audit.py` | 48386 | `6A02483758A4D77E0ED15538C9C6D7114251D52AE34CA86C5C6E7CFD0DE79279` |
| `relicweave-synlab/tests/a12/qa/test_forge_chain_audit_20261004.py` | 11756 | `58FE78A9C5A78BBD4A22809A25488399AF0E40F08FC227827CCB86449601CD66` |
| `tmp/review_20261004/implementation/forge_chain_audit_20261004/current_chain_input.json` | 2901 | `6F8C23B64601AB6AAD0BB0EE1F3C271802C9BF1EB8A43DB895FAAA4226EA234E` |
| `tmp/review_20261004/implementation/forge_chain_audit_20261004/current_chain_audit.json` | 11206 | `C1E3C53998552F388346FA514B7C9092562E070F82D6E400025975DDE4288422` |
| `tmp/review_20261004/implementation/forge_chain_audit_20261004/execution_receipt.json` | 4483 | `7C6AC348F78812B4B94D61430D6CA4D7A4F35CCC56576B3CD251D99954AC87E6` |
| `relicweave-synlab/tmp/review_20261003/implementation/vf/artifacts/four_bands_brep_semantics1_final/manifest.json` | 19597 | `3A2640A3E98F777AF3E3CD6C1C9B3CDF488DF423B25255539E9181CD0B515832` |
| `relicweave-synlab/tmp/review_20261003/implementation/pg/jobs/osb_fracture_branch_001/job.json` | 949 | `83AF8EA8CB0FD204AB288841FD87382C9DAE77EC1CFB5DC9D0C925D610D430D1` |
| `relicweave-synlab/tmp/review_20261003/implementation/pg/jobs/osb_fracture_branch_001/output/result.json` | 8258 | `B3FB84F20D409F4A4DCA0B34FFD8B95A07B7C7944B8B6ECD70100B0B5B17DC20` |
| `relicweave-synlab/data/a12_exports/experiment_ready/training_package/export_manifest.json` | 814199 | `07700A460589D325E2029F0522B73261043EB5C2031F4F3EE4C51C663AA585E9` |
| `relicweave-synlab/data/a12_exports/experiment_ready/training_package/degrade/index.json` | 1660 | `9D44852B7FFFED7E7A7605A02316538B490631FFDFF3664334C6D131ECDC1DAC` |
| `relicweave-synlab/synlab/schemas/view_channels.json` | 10078 | `84AAA8F72179B0D059F6AFB88D2655F9761B96401193C52C3B78C699F0E88E7F` |
| `relicweave-synlab/synlab/training/adapter.py` | 31354 | `E2ACDC6D8EA34F784A9724D42C547613036E722DBEF86FDDCA4C1F040E87C8EA` |
| `relicweave-synlab/synlab/training/model.py` | 37154 | `7034BACED19F96BF800DACA5170CD127FCF2F05CF8529BDBE42FFF1A2BE2B2E0` |
| `relicweave-synlab/docs/a12/data_contract.md` | 4758 | `DB67589068D48BCC9500EADA8A4CBA5F6E99FAC2E053F67FEE0DEC68D782AC1F` |
| `relicweave-synlab/docs/a12/engineering_policy.md` | 24688 | `7B696CA6F02B62C00BB37755091B4C31F676BE7B6B97D5D17ACC62A2232DCAA6` |

The earlier full-plan extraction and baseline alignment remain in `relicweave-synlab/tmp/review_20261004/implementation/relicweave_alignment_20261004/{extract.txt,alignment.md}`; this review only adds this file and does not modify that extraction or any source, plan, formal documentation, test, Git state, or solver artifact.
