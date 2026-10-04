# RelicWeave 对齐审计（2026-10-04）

## 结论

V1.44 的不变目标是：从真实可获得的碎片观察出发，在混合图库中找回真实历史邻片，给出有序、可追溯且待人工核验的候选；证据不足时说明拒识、补采或停止原因。A12、VesselForge 与 PG-Frag 应分别供应可控数据/退化、器物几何、以及经过验证的物理碎裂证据，不能取代 A3/A4 的检索、证据判读、拒识、重新采集和 STOP 主干。

总计划位置：项目主目标与真实数据边界见 DOCX 段落 P00003–P00006；输入/输出及关系口径见 P00178–P00180；交付表 T4:R3–R5（候选链、可靠输出、补采）。A3 的字段和标签隔离见 P00321、T8、P00398；召回池与关系精排见 P00362–P00372；PairOutput、开放库拒识与校准边界见 P00395–P00396；研究管线和算法可替换边界见 P00686–P00688；A12 独立支线定位见 P01101–P01104、P01191–P01192。

## 目标链、候选层级与真值边界

- **输入**：每片可变观察集合，包含原图、片 mask、断口 ROI、质量、灯光和可用标定；合格 3D 是可选增强。`fragment_id`只作索引/跨服务关联。`object_id`、`bag_id`、关系标签、GT 装配位姿、答案距离和测试 mate 状态不能进入模型输入（P00321、T8、P00398）。
- **Stage A 高召回初检**：整片描述与断口局部描述分别检索全库、合并去重，验证集冻结 M；M=50 是首轮开发轴，必须报告 M=20/50/100 的 any@M 与实际库大小，排除查询自身，GT 不参与初检（P00362–P00364）。
- **Stage B 精排**：在召回池上比较局部互补与兼容证据；多名 R2 可以同时为真。R2 是同一碎裂事件叶片间直接历史邻接；R1/R0/UNKNOWN 分开处理，邻接不传递。磨损后 current fit 或 evidence visibility 变化，不能删除历史 R2（P00179、P00366–P00372）。
- **输出/拒识**：候选须带 `candidate_id`、未校准排序分数类型、支持与冲突区域、可观测性、模型版本和 evidence revision。开放库结果表示“当前输入和图库下没有可靠候选”，不能推断世界中不存在邻片；列表是待核验候选，阈值只在独立数据上校准。观察不足走补采/人工检查，不得当作负证据（P00383–P00396，T4:R4–R5）。主指标需把拒识计回有效命中/覆盖分母，并另报接受率与无邻片风险（P00246–P00247）。
- **truth 泄漏边界**：合成结果显式标为 SYNTHETIC，真实确认集独立；clean truth/答案仅用于训练目标或离线评分。前向输入只接白名单的观测、估计和合法上下文；A12 把 features、labels、provenance 分开，递归拒绝 seed、谱系/答案/R2 等字段（`data_contract.md:12–18,44–52`；`features.py:166–214`）。Deploy v2 还将 labels/relations/测量质量/UUID-source 映射隔离到 research 访问；缺少观测返回 `INPUT_UNAVAILABLE`，结构校验不代表科学有效（`deploy_boundary_v2.md:3–30`）。

真实断裂与退化的最低交付直接支撑候选召回和拒识：每个受控事件至少要有可追溯的 parent/fragment 集、历史 R2 邻接图、正面积成对断面与 lineage，并保留 R1/R0 困难候选；质量阶梯要对同一底层样本只改变预注册退化轴、保留历史 R2，再分别测 any@M、Hit/Cov 和有效拒识/补采。这样可以判断真邻片是否被退化挤出召回池，以及“看不清”是否被正确解释为证据不足。合成断口可用于机制筛选和控制实验；在材料校准、数值收敛、事件表面/谱系未过门前，不可拿来证明真实陶瓷物理断裂（P01101–P01104、P01191–P01192；`CONTINUATION_20261004.md:34–43`）。

## 三个仓库实际接点与缺口

| 支线 | 已有公开契约 | 对“给定碎片→候选”的实际缺口 |
|---|---|---|
| A12 / relicweave-synlab | 独立合成、真值、损伤、观察、关系池、训练与诊断工程；`a12.obs.v1` 特征适配器与固定图库 `evaluate(checkpoint, pool, ...)`。评估器会给特征池排序并分开报告候选池覆盖和 Top-K，但这是离线 evaluator（排序位置 `training/api.py:209–210,346–383`），不是已接入主仓的真实查询服务。 | README 和 `contract_diff.json` 明示 `MAIN_REPO_INTEGRATION_PENDING`：工作区没有 A3/A4 schema 或 `rw-schema-1.1`，外部字段映射、索引身份和 job 接口仍 PENDING（README:7–9；contract diff:5–11,68–76）。A12 不能自行定义兼容后称接入，也不能拿其评估入口替代 A3/A4 的证据卡、校准拒识和采集/STOP 输出。旧 5 GB 包仍未迁移。 |
| VesselForge | `create_asset_package`/`validate_asset` 输出带 hash/provenance 的 `forge.asset.v1`、STEP 和表面网格；当前 README 明确是一个 open turned vessel + swept handle 的原型。力学参数 `UNVALIDATED_PROTOTYPE`，纹样是无浮雕 painted-band 光学规则；QA 仅 geometry-only（README:1–17；`asset.py:89–102,212,258,286`）。 | 当前是整器几何资产，不是已观测碎片/候选关系输入；还没有已核验的 A12 ObsPack/A3 适配，也没有多个器型的真实泛化证据。其价值应是增加可控母体形状与可追溯的后续切分输入，当前杯器样例不可据此宣称真实器型召回收益。 |
| PG-Frag | 能验证 VesselForge 的 `forge.asset.v1` 契约；job schema 接受盒状 bar fixture 或 asset surface，并约束 `UNVALIDATED_PROTOTYPE` 材料和 `local_smoke` 资源上限（`jobs.py:53–69,72–120,148–160`）。 | surface-to-volume 离散未实现，surface asset 的 run 返回 `UNSUPPORTED`（`backend.py:477–521`）。当前 bar 输出端点 bond 状态，不输出 crack surface、正面积配对面、动态碎片、接触/姿态、事件时间线或 A12 历史 R2（README:1–20；`backend.py:45,95–99,617–626`）。它目前既不生成 A12 候选样本，也不能作为物理邻接 truth 源。 |

因此实际贯通仍缺一条可审阅的路径：真实照片/ROI/质量 → 经主仓 A3 schema 白名单映射到 A12 观测特征 → 冻结 gallery/index → 高召回 M 池 → A4 成对精排和证据 → 独立校准的接受/拒识 → 重新采集建议或 STOP。当前只有独立 `a12.obs.v1` 与 pool evaluator；VesselForge 到 A12 的观察/碎片桥缺失，PG-Frag 的 surface solver 前置能力缺失，主仓 A3/A4 adapter 与部署输出缺失。

当前状态按总计划和本轮交接口径：A12 未跑 RTX5090 批量合成或预训练；PG PD baseline 冻结，Akantu extrinsic toy 的耗散为负且未达到 GcA，full-debond/damage/native-energy 语义 UNKNOWN；另一路 201 点 intrinsic Mode-I 只属本构试验，不能据此升格自由裂纹或 R2。没有真实材料校准、独立网格偏差/完整收敛、受验 R2 裂面或预训练准入；不得以几何 QA、测试 PASS 或固定界面插入声称物理真实度（`CONTINUATION_20261004.md:3,12,28–43`；`engineering_policy.md:5–15,35–39`）。

## 核心不变与可替换方法

不变的是候选检索任务、A3 输入权限/谱系与关系语义、Stage A 召回分母、支持/反证/观察不足分离、拒识和成本约束补采/STOP、端到端真实评测及 fail-closed 真值隔离。可替换的是如何实现这些目标：DINOv2、256 活跃 token、M=50 首轮、CTM/循环网络、局部匹配算子，以及 SDF/CSG、PD/Akantu 等生成或物理路线都应视为基线/候选。总计划本身允许非 CTM substrate；A6 方法只有经冻结同输入、同预算、独立对照后才成立（P00350–P00356、P00687–P00690；`engineering_policy.md:63–75,127–140`）。不得因为文档列了某算法就把它当必须采用，也不得为它放宽 QA/泄漏门限。

## 优先复审建议（只建议，不在本审计执行）

1. **先打通候选垂直切片。** 锁定 A3/A4 实际 schema 后定义 A12 adapter 和最小服务输出，至少含 M 池召回、R2 候选覆盖、证据/观察不足、校准状态、evidence revision，以及补采/STOP 原因。先以真实低质与异常 query 对照静态 A3/A4 基线，再扩 synthetic/pretraining；否则 A12、VF、PG 的进度无法映射到候选召回。
2. **把断裂方案拆成可证伪的小门。** 当前 Akantu 自由演化负耗散、目标 GcA 不符且不同 dt 差异大；保持其失败证据，受控本构 patch 先核 opening/traction/damage/history/能量语义，再做独立网格、方向、dt 和材料校准，最后要求事件生成的配对正面积裂面及 lineage。PD、Akantu 或其他算法只有通过这些门才进入物理 truth；201 点 intrinsic Mode-I 仍是本构局部结果。
3. **复核退化几何与 wall 证据仪器。** 已报告的 bool 磨损后盲删面会破坏 watertight，应该先分清纯外观退化和材料移除，再为材料移除选能保拓扑/可审计的表示；用实际 wall reference 检查，不从函数名推断全局厚度。局部 `paired_thickness` 文档写的是源面内偏移后同射线比较（`degrade_axes.md:194`、`narrowband.py:368–410`），但根侧近期证据指出外表面起始的 first-hit 不构成 wall 证明；需确认真实调用的起点、法向与穿越次数，并与封闭 CAD 截面/已知壁厚对照。把不满足资格的量保留为探针值，不能充当物理 QA 或拒识模型的真值。

资源与精度也是复审边界，不宜直线放大：V1.44 的目标设备配置明确未实测吞吐（P04842）；10万/50万规模须通过 G27 的存储、I/O、失败审计和收益闸门（P05106），不应以可生成代替准入。工程政策登记的 T 型接头 432k 单元后 0.01056 mm 仍略超 0.01 mm 门槛（`engineering_policy.md:101–103`），这是表示/算法复审触发信号，不是“继续细调必能通过”或“门槛已证明不可能”的结论。

## 提取与来源清单

DOCX 正文 `word/document.xml` 全量按 XML 顺序提取：5,526 个段落、128 个表格；表格行/单元格边界和全局段落序号保留在 `extract.txt`。原文大小 546,163 bytes，SHA-256：`4507EAD923D60CC8DC20C2A31E532394F4D8AB406A5703BF09EEB606AB6F6374`。审计末复核哈希不变。提取文件 607,704 bytes，SHA-256：`63643EBE51F3B671A307CF68C7826A2A46910B08449526A447F99E8ED4F90560`。

以下为本次读取的 source 路径、bytes、SHA-256（完整哈希）；未列出的文件未用于结论：

| Source | bytes | SHA-256 |
|---|---:|---|
| `RelicWeave_V1.44_Optimized_Complete_Plan.docx` | 546163 | `4507EAD923D60CC8DC20C2A31E532394F4D8AB406A5703BF09EEB606AB6F6374` |
| `relicweave-synlab/docs/a12/CONTINUATION_20261004.md` | 10681 | `395FB0EAEAFF00E538D733E041DE70BEE0ECD4004603D0AAA34B4F28146FB17E` |
| `relicweave-synlab/docs/a12/deploy_boundary_v2.md` | 2278 | `450F03E992A0801D1282579032B7AA705AED114E10A9712156381C7DAE399D16` |
| `relicweave-synlab/docs/a12/engineering_policy.md` | 20981 | `707EF32C4C6765F2061E69E0D2AC24CB9907BFF2F4CFA2DD0B23B7FB50708A8E` |
| `relicweave-synlab/README.md` | 4052 | `9FE91F1C2F664F665E2074449333B32BC8DCEC49AF84969E48962D9F95A315F7` |
| `relicweave-synlab/docs/a12/interfaces.md` | 6436 | `8193FE460289705296DD12402F968D26BDF62418B292D6043734F4BA26CF4B1B` |
| `relicweave-synlab/docs/a12/data_contract.md` | 4758 | `DB67589068D48BCC9500EADA8A4CBA5F6E99FAC2E053F67FEE0DEC68D782AC1F` |
| `relicweave-synlab/docs/a12/contract_diff.json` | 3806 | `7170FBC6CD2CBC884F31D8C709980CD269A9265021A40951806C3460883944AB` |
| `relicweave-synlab/synlab/observe/features.py` | 21017 | `ABF9AF42871B923DD65FB92046C91962237A96376C7CA8A18D562D52E7CFF922` |
| `relicweave-synlab/synlab/training/api.py` | 29422 | `DF71C374844FB4E285045CD2C89D318F34D4F1121929FA0A3132274797652FA9` |
| `relicweave-synlab/docs/a12/degrade_axes.md` | 44367 | `C4373AF95520F18A522AA607CF4CA74AC579F8C1F86365267870CCF6C9F6D62B` |
| `relicweave-synlab/synlab/degrade/narrowband.py` | 22646 | `31E5E44F198F357991768C2AC1EC08DF4115A5E5E5C9BADCF903F82B1F9C5A8A` |
| `relicweave-synlab/synlab/degrade/wear.py` | 85075 | `A6068898297EE8095735E5FC1F58AA2F000875C01986CF63B76458C5C649EDE7` |
| `vesselforge/README.md` | 3005 | `1976F82FF3A9A5B398431D9A7ECF55A5137E522AC74A5CE9D6A2C0CCDBE52F86` |
| `vesselforge/src/vesselforge/__init__.py` | 233 | `6D318F53572B600631C71FA9F9EFDDD98EF21264ADB6BEC20F44C7DDCEC1B61A` |
| `vesselforge/src/vesselforge/asset.py` | 20367 | `F9C11A60BEED1D165431B8EA590C52DB382B780479AD262FEE1CC5A7BE3274D0` |
| `vesselforge/src/vesselforge/schema.py` | 14126 | `B58AE7B3BC5E09B699A36FE57FADA12DD969759CF9991BF2749660D6CFBBDFE9` |
| `pgfrag/README.md` | 2830 | `92B6F77D0306D71F8C28BEA6E5587814976DBACDA1C3C07E4829EB5713CEE1D2` |
| `pgfrag/src/pgfrag/__init__.py` | 122 | `D45C208386D910E5815546599533BD56C54E1154C3A8B7155092CB47322E43A1` |
| `pgfrag/src/pgfrag/jobs.py` | 10520 | `C9D1E70EA063A47DEA5136C59A65583A9FECD3CD1D44B1F94EAA2AAF8E32CAAD` |
| `pgfrag/src/pgfrag/assets.py` | 13625 | `9E56B9F1F2EF289B061CF9A1F4241D473990F895D330E40CFC7B100CAEAAD889` |
| `pgfrag/src/pgfrag/backend.py` | 42840 | `8B3577201E0E8E94E747B3C5C3529C2D117D8CECCB729F0D2D2510DD3FD834DC` |
| `pgfrag/src/pgfrag/cli.py` | 2569 | `40129B7761BBBDA378BE0184987CC9DB7DE027D00A2A1B8C234BC2D3DD8FB14E` |
| `pgfrag/schemas/pgfrag.job.schema.json` | 3643 | `7A4DBEA65D328D881C9CC6458FB8F4A518B83C929DBC4F89093E54313C62C2A9` |
| `pgfrag/schemas/pgfrag.result.schema.json` | 1208 | `A2BF99C0D0E09FCD496F7E125DDBB4EFDDA96E76FA96F89904F2D1FF67F8EF95` |
