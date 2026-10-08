# synlab 合同版本审计

审计日期：2026-10-09。只读检查 V1.47 主合同与原稿、A12 data contract、SynLab 配置/CLI/API、导出/验证器和相关测试。排除 workspace_backup、docs/backup、third_party、runtime、vendor。没有执行 CLI、pytest 或数值生成。

V1.47 主合同 SHA-256：883C831648D0697F456228F4D862DEDA8A36FF9740ECD6AADB3A3EBFDFDFFC7D。原始 V1.47 SHA-256：41F1254E40A2ECABDCFA1C6583AF2FCE0AE1B0AB980D5F9179BBAF687B7BE64B。DOCX 定位使用 word/document.xml 的 body 子节点/表格行，不推测页码。

## 结论

当前 SynLab 代码实际实现和受理的生成配置版本是 **synlab.v3**，因此 v3 不只是设计：有严格配置模型、配置编译、CLI validate、API 校验、现行配置样例及测试。更大的 G30 编排仍是方案范围；README 将主仓集成列为 MAIN_REPO_INTEGRATION_PENDING。

**synlab.v2 的读取、字段兼容或迁移没有当前实现证据。** 在指定排除范围外，SynLab 源码、配置、测试中没有精确的 synlab.v2 实现。V1.47 对 v2 的只读解析与“保留旧版本迁移器”属于未实现的设计承诺，不是当前受理能力。

合同文档存在已确认的内部版本冲突：主合同 body[921] 写“现行数据合同rw-schema-1.1，合成合同synlab.v2”；body[2110] 又规定新算子/训练配方使用 v3、v2 按旧定义只读。G30.1 body[2146–2147] 称旧 v2 只读，并给出 schema_version: synlab.v2；G30.5 body[2242–2243] 则称新字段用 v3 并给出 schema_version: synlab.v3。body[2355] 表格 row[5] 仍把 rw-schema-1.1／synlab.v2 列为旧版只读迁移。原稿对应定位也有相同文本：body[903]、[2090]、[2126–2127]、[2222–2223]、[2334] row[5]。

## 版本层次与字段

| 层 | 当前版本/字段 | 依据 |
|---|---|---|
| 生成配置 | synlab.v3，内层字段名是 schema | C:/Users/xiemo/Desktop/ShardForge/relicweave-synlab/synlab/schemas/spec.py:15,221–246 将 schema_id 限定为 Literal synlab.v3、别名设为 schema，并禁止额外字段。字段包括 data_scope、release_profile、experiment_purpose、master_seed、units、integration、implementation、dataset、sampling、pattern、fracture、physical、observation、resources、storage、quality 等。 |
| CLI/API | API 外层 schema_version 只允许 synlab.v3、synlab.train.v1、synlab.diagnose.v1；内层 spec 仍按自己的模型验证 | C:/Users/xiemo/Desktop/ShardForge/relicweave-synlab/synlab/api/deps.py:59–70；api/specs.py:25–46；api/routers/jobs.py:133–140。CLI validate 通过 GenerationSpec 校验直接配置或 generation_spec 嵌套段：synlab/cli.py:92–116。 |
| 其他配置方言 | synlab.train.v1、synlab.diagnose.v1、synlab.pool.v1 | synlab/qc/acceptance.py:551–595；synlab/roles.py:19。它们是独立配置合同。 |
| Store/资产 | store 为 synlab.store.v1；asset 自带独立 schema | synlab/storage/store.py:28,150–157；现存 release manifest 可见 a12.obs.v1、synlab.mother.v1、synlab.truth.clean.v1：data/a12_exports/closed_loop/store/releases/rel_852ab2a1e4c3_1790880811/manifest.json:92,535,4439。data_contract.md:63–65 也说明 asset 的 role/schema/unit/frame 等独立。 |
| 训练包 | manifest v1、package v1、deploy 边界 v2 | synlab/storage/export.py:64–65,1483–1485；synlab/storage/deploy_boundary.py:21,77–109,158–188。deploy v2 是数据容器版本，不是 synlab.v2 生成配置。 |

现行配置使用 schema: synlab.v3，例如 configs/a12/pilot.yaml:1–9、configs/a12/fracture_physics.yaml:202–218。测试辅助代码分别展示内层 schema: synlab.v3 与外层 job schema_version: synlab.v3：tests/a12/api/api_test_support.py:45–84。API 测试覆盖合法 v3 spec 和额外字段拒绝：tests/a12/api/test_capabilities_and_specs.py:55–83。没有找到显式的 synlab.v2 接受/拒绝/迁移回归测试。

V1.47 的 v2 样例 body[2147–2151] 使用 schema_version、release_id、master_seed、单数 unit、顶层 mother。当前 GenerationSpec 使用 schema、units、dataset 等类型化字段；没有 release_id、单数 unit 或顶层 mother，且额外字段会被拒绝。源码未提供 v2→v3 字段映射。更明显的是，G30.5 的 v3 样例 body[2243] 也使用 schema_version；将它放在内层 GenerationSpec 会因额外字段而失败。schema_version 的合法位置是 API 外层 job envelope，内层 spec 使用 schema。

rw-schema-1.1 也缺少当前映射依据：主合同 body[921] 称其为现行数据合同，但 README:7–10 标记主仓集成待定；docs/a12/contract_diff.json:3–10,72–76（记录日期 2026-10-01）称外部 schema 缺失，并将字段映射、导入导出 adapter 和 versioned migrator 列为待补。当前 SynLab 源码未发现 rw-schema-1.1 adapter。

## 分类与推荐统一口径

- **已确认文档错误：** V1.47 主合同与原稿都把 synlab.v2 同时称为现行合同和旧版只读迁移版本；G30.1/G30.5 内层示例的 schema_version 字段与运行时 GenerationSpec 不匹配。
- **历史兼容：** 训练包 v1 仅保留显式 research 读取，deploy 读取要求独立 deploy v2。synlab/storage/export.py:3008–3012,3039–3056 与 tests/a12/storage/test_deploy_boundary_v2.py:161–188、429–434 有代码和测试依据。这不等于 synlab.v2 配置兼容。
- **未来设计/未实现：** synlab.v2 冻结读取、v2→v3 字段迁移、旧 hash 保留及迁移报告、rw-schema-1.1 到 A12 pack 的映射/导入导出，均无实现与测试依据。G30.1 body[2146] 明确称其为“拟实现配置合同”。

推荐统一为：**当前 SynLab 生成配置是内层 schema: synlab.v3；API 外层 job 才用 schema_version；training/diagnose/pool、asset、package 和 deploy 分别采用独立 schema。** 在 v2 模型、字段映射、只读解码或迁移器及测试齐备前，把 synlab.v2 标记为不受理/设计中；rw-schema-1.1 继续标记为集成待定。

验收缺口是：修订 V1.47 当前/旧版措辞与 schema 键；若承诺 v2，则补冻结字段定义、v2 fixture、映射与迁移报告/hash 规则、CLI/API 正反向测试；若承诺 rw-schema-1.1，则先提供外部 schema 和逐字段映射并验证单位/有效性转换；增加测试区分 API 外层 schema_version 与内层 schema。

docs/a12/data_contract.md:3–5 将语义定义指向代码，本身没有声明覆盖全部 pack/导出物的 synlab.v2 或 synlab.v3 总版本。