# 文档结构审阅与具体整改

本页只审阅并修复交接层面的导航与事实边界。旧 handover、continuation、失败件和方案历史不得删除或覆盖；应以新增日期版索引/增补记录把当前状态与旧记录分开。

## 已发现的问题

1. **历史和当前状态容易混读。** `docs/continuation/20261015/STATUS.md` 是一个历史时间切片，`docs/continuation/20261016/STATUS.md` 才是当前较晚记录；两者都保留数个相似 bowl、native cohesive、A12 export 名称。旧 A12 `docs/handover/20261007/HANDOVER.md` 标题仍写 V1.47，且封存时未提交备份的句子是当时事实。只看搜索结果、旧的 PASS 表或 README 导航容易引用错日期。
2. **PASS 候选范围容易膨胀。** run05 的 `GEOMETRY_DIAGNOSTIC_ONLY` 是网格几何/祖先关系通过，母体 source fidelity、foot fillet accuracy、材料、solver、断裂、碎片和训练资格仍未建立。`PASS_STRUCTURAL_CAD_ONLY`、`ROOT_INDEPENDENT_V6_RUN05_GEOMETRY_READBACK_PASS`、`PASSED_NARROW_ELASTIC_COMPLIANCE` 都是窄范围标签；旧 bowl v6 的 2 个闭合 components/6 个 RGB-D views 也不是 physical pass。A12 的蓝白/材质/生成器 55 checks 与 PG 暂停交付时 6 files/55 checks 是两组独立软件测试；都不是纹样成品或实际 run05 mother acceptance。
3. **absolute path 与本机路径假设多。** 旧 10/07 handover 和新 PG preflight/README 有用户目录、WSL mount 或本机 runtime 绝对路径；跨仓证据也依赖 workspace root。最终发布结构把 handover 放在 A12 `docs/handover/20261016/`，历史 continuation 副本保存在 A12 `docs/continuation/`，workspace-support 来源分放于 `workspace_support/docs/continuation/` 与 `workspace_support/experiments/`；A12 仓内 continuation 用相对链接，三仓源码链接依赖同级三仓 workspace layout 和 `DELIVERY_RECEIPT` refs。Akantu runner 仍硬编码 workspace location，单独克隆无法直接复现。
4. **第三方资源“存在/已下载”被误认作“已精修/接受”。** Apsida v3 有几何修补，但 7 个 pinched vertex links 仍导致限定为 visual reference only。MET 50899 图像是已烧成照片的色度 proxy；蓝白 panel 是 vase-derived partial crop 在 bowl candidate 上的合成展示。扫描/图片 hash、衍生件和 receipt 都不是完整的来源资格、清晰轮廓/纹样重建、物理材料或可发布 finished asset。
5. **安装可复现性不完整。** 现有测试/运行依赖 bundled `third_party` venv、Windows + WSL 和外部 Akantu wheel；部分 receipt 会区分 wheel v5.0.7-post1 与本地 source tag v5.0.7，但其他交接入口硬编码本机路径。当前没有一个面向新开发机的、全仓锁定 OS/Python/依赖/wheel/source/license hashes 的安装脚本/manifest 可保证一键复现。
6. **整体方案落后于实际状态。** `RelicWeave_V1.48_ContractAligned.docx` 本身标注 2026-10-09，228 页，SHA-256 为 `23a42e5f4cca40ef733edc9365c15bd0d5fdff647f8821fddec9c649e52b1455`；Word 原档在暂停时打开并锁定，Python 只读提取与归档副本一致。它无法准确导航 10/15–16 才出现的“所有日用/考古器型真实证据”要求、v6 witness-backed 86k T4 mesh、panel texture source-resolution、负耗散 readback、native getter/mass-assembly发现、未启动的 v6 preflight/campaign 和 generic mother binding。总方案仍是总体目标，不是当前工程状态表。2026-10-16 日期化更新已单独保存为 `RelicWeave_V1.48_Engineering_Update_20261016.docx`（SHA-256 `b134f7a781b62bbf8946a269343d8eeedbc87c2697c83dcb55e0ab83cf97fd62`），10/09 原档保留不变。
7. **生成物/快照和完整交付状态混在一起。** `source_snapshot/`、冻结 inputs、partial photo crop、native observations、read-only binding、candidate CAD 和当前 status PASS 被类似“已完成”语言引用时，会让新开发者高估成熟度。Artifact receipt 的 `status`、`qualification`、`limits` 必须一起阅读。
8. **大 raw data 与项目代码的 Git 范围需要分开盘点。** 约 6.8 GB raw data 由本地 manifest 保留；不能因为 handover 要求完整就将其整体当作 GitHub 源码。`_temp_matplotlib` 是外部 runtime cache，应排除。应按数据用途、许可、大小、重建能力和 Git LFS/外部存储策略逐项决定，并在 `DELIVERY_RECEIPT` 记录保留位置、hash 和发布范围。

## 交接文档采用的事实边界与组织方式

- 最终 handover 入口集中在 A12 `docs/handover/20261016/`，workspace continuation 副本保存在 A12 `docs/continuation/`，workspace-support 来源分别归档在 A12 `workspace_support/docs/continuation/` 与 `workspace_support/experiments/`；把“入口、详细技术接手、证据索引、文档整改、机器状态”拆为职责清晰的文件。START_HERE 声明 as-of date、goal OPEN、0 个完整物理包、未启动实验边界和阅读顺序。
- 证据表同时记录 `status`、当前文件入口、可证明范围和不能证明范围。报告窄 PASS 时附限制，失败件保留，不以退出码、文件存在、截图或命名晋级。
- A12 内部 continuation 与 handover 历史使用可点击相对链接；三仓代码 evidence 保留 workspace-root-relative source paths，并将最终 GitHub refs 指向独立 `DELIVERY_RECEIPT`。安装及独立运行前提显式写出 shared root 与同级三仓布局。
- 明确 scan/photo/study 源精修状态，区分 `GEOMETRY_DIAGNOSTIC_ONLY`、已执行的 `READ_ONLY_BINDING_VALIDATED` structural binding、zero-step preflight、完整 native evolution 和 physical qualification。generic mother run05 收据存在且 validator 完成；实际母体仍未 root-accept。
- 为新开发者提供三仓责任、关键 API 函数、恢复顺序及不得从旧 snapshot 直接重跑的条件。

## 方案和仓内文档的维护要求

1. **保留 V1.48 原档，维护 2026-10-16 日期化更新版。** 更新版应清楚标记旧合同基线日期、当前工程快照日期及状态主记录链接。不要把历史完成比例、PASS、预算或失败事实静默改写。对日期版维护时核验页数、文件哈希及与原档未覆盖的关系。
2. **各仓只保留一个当前状态入口。** README 顶部链接 latest dated status；在旧 dated status 首段加“历史快照，当前请看 X”的提示但不改写当时数值。A12 release handover 内做三仓目录/日期/状态矩阵。
3. **统一证据词汇。** 建议 schema 列 `artifact_status`、`scope_pass`、`qualification`、`physical_pass`、`pretrain_eligible`、`source_fidelity`、`measured_vs_assumed`、`known_missing_evidence`、`as_of`。候选 PASS 不得写入整体 readiness 汇总，除非逐项 scope 条件都匹配。
4. **收紧外部资源生命周期。** 每个外部输入都显式经过 `SOURCE_RECORDED → DERIVED → REFINED → REVIEWED → ACCEPTED_FOR_NAMED_USE`；visual-only、research-only 和 rejected 派生必须继续可见。Apsida 当前停在 visual-only；fired-photo crop 仅是 appearance proxy。要迁移到物理输入前，要求来源许可/hash、拓扑/尺寸/视图/表面质量复核和受限用途签收。
5. **恢复环境可重现性。** 增加 repo-relative environment manifest：OS/WSL 发行版、Python、NumPy/SciPy、CadQuery/OCP、Akantu wheel 与 source tag、wheel/source/license SHA、runtime build/install 检查和每仓 focused test command。runner 由 workspace-root 环境变量推导 mount path；变更后更新 pins/receipt，不覆盖被冻结的一次性证据。
6. **将未启动实验单独放在“待审/未运行”列表。** v6 preflight ready != run done；`shape_only_preflight` completed != h/h2/h4 campaign done；zero-step control != fracture; no data should be labeled accepted training. 结果文件、source snapshot、preview PNG 和 `prepared` status 均不能表示执行成功。
7. **把长实验历史改为索引而非重复抄录。** 主 handover 提供短摘要/primary record链接；完整数学推导、原始失败、逐个测试列表和命令保存在 dated source report。每一条自动维护日期与主记录 hash，避免五份文档重写同一组数字后漂移。

## 发布记录要求

本轮完成工程状态、进度口径、导航、安装说明和最终 231 页布局检查。历史方案中的全部外部论文、软件版本推荐、引文真实性及每项科学主张未逐项重新检索验证；保留历史内容不表示它们已获本轮复核。后续研究选型应重新核对官方出处及版本，不能把文档布局通过当作科学结论通过。

- `DELIVERY_RECEIPT` 独立记录三仓实际 GitHub repository、branch/ref、commit SHA、发布状态、README 导航入口和跨仓链接目标；不要把暂停快照分支信息当作交付 ref。
- A12 README 和 continuation 页面只需链接到统一 handover 入口；完整状态数字仍以 `EVIDENCE_INDEX.md` 和 machine receipts 为准。
- v1.48 更新保留 10/09 原档；当前方案指向 10/16 日期版，并将状态/数字链接到对应主记录。
- 外部资源 license、large binary 和数据输出的保留/发布边界逐项记录，尤其是约 6.8 GB raw data 与 `_temp_matplotlib` runtime cache。
