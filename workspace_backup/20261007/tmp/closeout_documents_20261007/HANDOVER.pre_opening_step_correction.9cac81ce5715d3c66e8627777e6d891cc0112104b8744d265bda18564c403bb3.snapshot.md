# RelicWeave V1.47 A12 VesselForge PG-Frag closeout handover

**更新时间：** 2026-10-07（Asia/Shanghai）  
**面向对象：** 接手本地三仓工程状态的研究与实现负责人  
**状态：** 文档修订稿；本轮 PG / objectivity / native C4 来源审阅均已由根任务验收，外部三仓备份仍为 prepare-only。先完成本手册与 V1.47 的内容和逐页视觉 QA，再由独立协调者写入固定 delivery receipt；该后置回执不触发本手册二次改写。

## 先读结论

RelicWeave 的目标仍是“观察碎片 → 排序候选 → 给出证据 → 接受、拒绝、补采或 STOP”。在线路径只读碎片观察和已准入的公开元数据；干净真值、隐藏母体身份、装配姿态和邻接答案只供离线审计，不能进入候选排序、检索键、缓存或线上日志。

截至本次收口，三个项目都有可复查的工程进展，但尚无完整的物理合格包。PG-Frag 的固定裂面 93-DOF bridge 是 virgin elastic toy；另有 12 状态固定界面开口历史控制，含软化、卸载和再加载；第 8–12 个保存轨迹状态（JSON `step_index=7..11`）所有积分点 D=1，但 bulk 仍承载、未断开成碎片。moving-front 只完成到刚度/刚体诊断后因审计字段错配停止，未产生 wrench、KKT、G 或 primary result。VesselForge 结果限于解析曲线、候选几何、二维条件证明和理想曲线距离证明；A12 计数主要是软件 QA 和一母体、未校准退化读数。不得据此宣称真实裂纹增长、材料校准、历史器型资格、纹样或材质真实性、端到端检索能力或批量交付。

工程估计维持 PG-Frag 25–35%、VesselForge 30–40%、A12 30–40%。这些区间是负责人给出的工程进度判断，不是由测试覆盖率、样本数或物理准确度换算出的百分比。完整物理合格包仍为 0。

本次 V1.47 记录 2026-10-07 的窄范围实施与证据边界。原 V1.46 文件必须保持原字节不变；历史指标、FAIL、STOP、NOT_RUN、NOT_ESTABLISHED 和旧导航继续作为历史记录保留。

## 接手时的操作边界

开始工作前先核对当前结果、独立审阅和来源锁定文件。不要自动启动周期提交循环、旧服务、预览站点、长跑任务或旧 HANDOVER 中的启动命令。旧交接文档在 2026-10-02 写成，里面的私有 SDF 断裂主线、主仓服务地址、自动提交循环和前端预览入口均已过时；其正文保留用于历史追溯，后续按本文件和当前证据件继续。

已批准的 2026-10-07 moving-front 任务只有一次尝试。它因来源字段名不一致退出；该停止属于运行合同/序列化字段错误，不是物理失败，也不是数值通过。保存结果已由独立审阅者进行一次有界 NPZ 读回；那是对既有失败 checkpoint 的读取，不是新查询、求解或重试。用户要求单次失败后停止，故不修复后重跑。将来的重试必须由新的用户授权、新的 run ID、新的冻结输入和新的预算开始。

当前仅可把已保存证据作为状态依据。没有保存的求解量、图像、CAD 实体、材料值或独立审阅，均按 UNKNOWN / NOT_ESTABLISHED 处理。

## 系统分工与验收路线

| 层 | 仓库与职责 | 当前交接条件 |
|---|---|---|
| VesselForge | vesselforge：完整母体几何、部件、连续语义、纹样/材质、厚度与 Physics-Ready Asset Package | 输出必须有可追溯输入、几何与语义映射；真实历史器型、全局壁厚、relief 和材料外观仍须独立验收 |
| PG-Frag | pgfrag：材料/事件求解、裂纹与损伤、断面、碎片动力学和 Result Package | 需有来源绑定求解、独立重建、材料校准、网格/方向收敛及闭合碎片；固定界面 toy 不足以晋级 |
| A12 SyntheticLab | relicweave-synlab：退化、观察、关系/episode、训练、离线诊断和发布 | 不复制几何或断裂底层内核；不得把 GT、隐藏位姿、母体 ID 或邻接标签交给在线排名器 |
| RelicWeave | 当前上层实验与检索任务 | 合格目标为观察碎片到候选排序的证据链；输出必须允许接受、拒绝、补采或 STOP |

GT Oracle 只可离线使用。采样、分裂、标签和审计可以保留特权真值，但任何运行时特征、检索键、缓存、排序服务日志都必须由许可清单阻断 hidden pose、mother ID、完整邻接集合与 solver 内部场。在线含有这些字段的结果一律不得作为产品或研究迁移证据。

## 核心证据台账

### PG-Frag 固定裂面 cohesive bridge

| 字段 | 记录 |
|---|---|
| 负责人 | 本轮归档责任为 root；独立保存审阅由 `luna_bridge_mass_independent_20261006` 完成；原始 producer 创建者姓名未能从当前 receipt/source 恢复，不猜测。视觉核验由 root 完成。 |
| 冻结输入 | entry `pgfrag/experiments/mixed93_actual_cohesive_bridge_20261006/run_actual_cohesive_bridge.py` SHA-256 `36ac1710286b0abf607bda5b1c6ffab893f8191830eae091517e2acd41d62236`；case `.../case.json` SHA-256 `fcc4b46ed101b0f6067a9f3ec10816909c9fa931edd5a8cdde4c7f46cb3f3a71`；operator `.../mixed93_actual_cohesive_bridge.py` SHA-256 `023d730454802ec755df41c9878744aa086cd5b97a8a88e9d5bbd4181b6f1412`。 |
| 结果路径 | pgfrag/tmp/review_20261006/mixed93_actual_cohesive_bridge_20261006/numeric_runs/run01/result.json |
| 结果 SHA-256 | e0819a792789fe8fdada86a75983e7cb8465c5d0aa78140ca93a84c4440159f2 |
| 独立审阅 | pgfrag/tmp/review_20261007/mixed93_actual_cohesive_saved_independent/run02/result.json；SHA-256 `06c3362a3ed405edb78edf201ae2e1520054cf59ba284fe007c2b819b9763e5c`。保存的执行收据：`.../numeric_runs/run01/receipt.json`，其 `argv` 是本历史尝试的唯一命令记录。 |
| 结果状态 | ACCEPTED_DIAGNOSTIC_ONLY：16 个 MLS 查询、16 个界面积分点、3 次 assembly、1 次 KKT；弹性 virgin toy 接口结果。 |
| 原始预算/命令 | receipt 记录 `--wall_limit_seconds=60`、总输出上限 12,582,912 B；child 0.266 s、外层 rc=0。请从 receipt `argv` 原样核对本次消耗过的 Root GO 字符串；该一次性命令不可复用。本手册不再执行它。 |
| 视觉件 | pgfrag/tmp/review_20261007/mixed93_actual_cohesive_saved_visual/run01/bridge_saved_diagnostic.png；SHA-256 41ddd1acdcc06b0951d741906685b6ae9ea247170d8d433f8862f2a911fdfcb5。根任务已查看该图。 |
| 资格边界 | damage 与耗散为零；没有裂纹推进、材料标定、mesh bias、动态碎裂或真实器物耦合结论。NPZ 为保存的数值附件，复核时先核对哈希，不因该台账自动重读大数组。 |
| 下一最小动作 | 无需重跑已接受 toy。转向经授权的独立材料与网格资格工作；本交接不授权任何新求解。 |

### PG-Frag opening-history toy 控制

| 字段 | 记录 |
|---|---|
| 负责人 | 本轮归档责任为 root；保存结果审阅由 `luna_cohesive_law_20261006`，图像复核由 `luna_full3d_consistent_mass_replay_20261006` 完成；原始 producer 创建者未能从 receipt/source 恢复，不猜测。 |
| producer 路径与 SHA | pgfrag/tmp/review_20261007/mixed93_opening_control_20261007/run01/result.json；SHA-256 1e83ecf628db8e30066dba287fa616b2e84fb6eb467e9ebf75c1cc57b2615bbb |
| 冻结输入 | `pgfrag/experiments/mixed93_opening_control_20261007/run_mixed93_opening_control.py` SHA-256 `ba00de0d635d2daecfd113ab28c9518d196655c89406a09472fbcf0af5fcd291`；`.../case.json` SHA-256 `49bec605348679ae6fbc105c4944a08efcdfcd44ee193cbd8c8c1546161fef6c`。 |
| 独立保存审计 | pgfrag/tmp/review_20261007/mixed93_opening_history_independent/run02/result.json；SHA-256 19d3649f5e1d2d880a300151425be0212f7aecbbc76bb40fdf8d41e6f533ea79 |
| 审计范围 | ACCEPTED_DIAGNOSTIC_ONLY；12 个状态、9 道独立门、192 个点状态检查；0 次新 solver/provider 调用，0 次 NPZ 内容读取。全耗散 1e-6 J，面积 1e-4 m²，示例 J=Gc×A；仅为 toy 历史控制。 |
| 原始预算/命令 | capture case 写有 20 s deadline、总文件上限 8,388,608 B；receipt 实测 child 0.734 s、rc=0、总计 1,738,889 B。receipt 只保留 GO token hash 和带占位符的 child-argument contract，不保留完整外层原始 argv；实际历史 argv 标记 UNKNOWN。参考入口见“运行环境与安全复现”，不是重跑授权。 |
| 视觉件 | pgfrag/tmp/review_20261007/mixed93_opening_history_saved_visual/run01/opening_history_saved_diagnostic.png；SHA-256 8bcea264c56920585b75737484a5bd17516006d1d186e1293285521660145ac9。根任务已查看。 |
| 关键限制 | `trajectory.step_index=0..6` 展示损伤演化/软化以及卸载与再加载；在 `step_index=6`，damage 范围为 2/3 至 1、并非所有点全损伤。只有后五个状态 `step_index=7..11`（按第 8–12 个轨迹状态编号）的 `all_points_fully_damaged=true`，积分点 D=1。bulk 仍承载；固定全局基底上的开口控制没有形成 fragment disconnect。曲线/界面图不是粗糙断口或真实碎片证据。 |
| 下一最小动作 | 保留为数值控制件；不得把它升级成裂纹增长或材料卡结果。 |

### PG-Frag moving-front 单次失败

| 字段 | 记录 |
|---|---|
| 负责人 | 执行与单次运行：`luna_full3d_cracked_elastic_operator_20261006`；独立失败 checkpoint 审阅：`luna_cracked_mls_coupling_design_20261005`；root 已接受为失败证据并关闭。独立收口 `ROOT_ACCEPTANCE.md` SHA-256 `22705687ecb002460595f214c2b269adc63d99fa79f8513748577a598f82f693`。 |
| 来源目录 | `pgfrag/tmp/review_20261007/mixed93_moving_front_reanalysis_20261007/`；历史 attempt receipt `capture_once01/capture_receipt.json` SHA-256 `779b503781d711a6b06257cfbc72fd00938af34c315307bb2de948e6908240f3`。 |
| 来源锁定 | `pgfrag/tmp/review_20261007/mixed93_moving_front_reanalysis_20261007/SOURCE_PINS.json` SHA-256 `5cafe06dda8f9704450bdff34a3d4386d03f2cad644effa6c25dfbd5f53f919c`；执行源 `pgfrag/experiments/mixed93_moving_front_reanalysis_20261007/mixed93_moving_front_reanalysis.py` SHA-256 `8c662a69e7b4c60b0ce70fcde2b53fd3547a23e1e00f6e19adfa2f6801b0b9c4`。 |
| 核心 case | `pgfrag/experiments/mixed93_moving_front_reanalysis_20261007/case.json` SHA-256 `f727e7b4e23f26ac7c200caf94e4e5d1e0556ecfa747c96cf617f682c7863a1e`。执行 owner 是 `luna_full3d_cracked_elastic_operator_20261006`；独立失败读回/审阅 owner 是 `luna_cracked_mls_coupling_design_20261005`。 |
| 失败件 | run01/failure.json SHA-256 9da8793fda4925014154931462a111fae0f71a35fbae6db48f9d6ac3447f2935；run01/failure_arrays.npz SHA-256 8f6d3ca994d44ea5003379736ae4cd91f9c4daa98af1366c8c59c81f757c0e2f |
| 外层收口 | CLOSEOUT.md SHA-256 43124925237edeaa988b4308d889186023a0212e47fef6b5d0830398bf914d58；CLOSEOUT.json SHA-256 1045ece87a3ca9cdf631967cb237fd84e7df10f67d07b40189c1b511da028656 |
| 实际进度 | 一次 worker 与 wrapper 均返回 2，无 timeout；外部工具调用 1.269 s，wrapper 后哈希计时 0.968 s；27 项 pins 稳定。输入/输出收口 1,802,359 B，低于 12,582,912 B 限额。 |
| 已完成工作 | 1,344 条新 MLS 查询分 6 批全部 OK；两组 raw 93-DOF K 与谱检查均记录为 6 个零模、87 个正模、0 个显著负模，刚体秩 6。失败检查发生在 candidate_front_rigid_checks_complete 之后，边界 wrench 与 KKT 之前。 |
| 停止原因 | driver 检查 audit.producer_run.rc；实际冻结审计字段是 audit.producer_run.return_code=1 且 result_json_present=false。该模式造成 schema 字段错配，未生成 wrench、KKT、G 或 primary result。 |
| 判定 | 一次运行的来源/序列化合同失败；不是物理 FAIL，也不是物理 PASS。该执行者未打开 NPZ；独立审阅者随后对已保存数组作了一次有界读取：reader rc=0 / 0.154 s，71 个 archive members、63 个 float arrays 均有限，两个 93×93 前沿谱分别为 6 零 / 87 正 / 0 显著负，未产生任何新查询或 KKT/G。独立审阅 `pgfrag/tmp/review_20261007/mixed93_moving_front_independent/SAVED_FAILURE_REVIEW.md` SHA-256 `7ad900056899e5f15a39da097cc6d97da0dfd4a82cacf0f025dfefc71b2f53b9`，JSON SHA-256 `f2fcb37c53acd1e3b114cb8bea47f7f9debb5c602da58ac6e38d41908b3b8faa`。用户已要求单次失败后不重跑。 |
| 原始预算/命令 | capture receipt 保存确切 child argv；外层 64 s wall deadline，worker timeout 59.938 s，总输出上限 12,582,912 B；child/wrapper rc=2、外层工具时长 1.269 s、wrapper 到 post-hash 统计为 0.968 s，无 timeout、1,802,359 B。实际 child 执行时长 UNKNOWN，不能把 0.968 s 写作 child time。命令见 `capture_once01/capture_receipt.json` 的 `command`，作为历史审计记录，不可重放。 |
| 下一最小动作 | 仅在用户重新启动任务后，先让检查器读取实际 return_code 并在 1,344 查询前验证审计 metadata，然后用新 run ID 和新预算重新审批。 |

moving-front 原始执行与收口文本保存在上述目录；完整 execution receipt、stdout、stderr、source pins 和失败数组均保留。不要修改 run01，也不要复用旧授权标记。

### VesselForge 器型与壁厚证据

| 字段 | 记录 |
|---|---|
| 负责人 | 当前台账与证据边界由 root 负责；原始候选 producer 姓名未能从保存 receipt 确认，记录为 UNKNOWN，不按相似 agent 名推测。 |
| 解析器型 | `vesselforge/src/vesselforge/profile_catalog.py` SHA-256 `e9d4bc1458a107208e537449d6526f1c0077d6d3afc6953a6200d86512f9c26f`，定义 bowl、beaker、jar 三个解析参数族；catalog-native pilot 只有 bowl_default 与 jar_default 两个实例，beaker 无实例，无非默认域 sweep。 |
| 当前数量边界 | 三个软件定义族、两个默认 CAD 实例、0 个历史参考验证的器型族、0 个全局壁厚合格生产实体。 |
| R9 外轮廓候选 | 已接受的是几何候选而非完整生产器型：结果位于 `vesselforge/tmp/review_20261006/curvature_constrained_meridian_20261006/curvature_constrained_meridian_result.json`，SHA-256 `839c461cdf0dcae93f362ee7d80d0446cf52b6b1e1f04ed18842e17527673185`；源 `vesselforge/experiments/curvature_constrained_meridian_20261006/curvature_constrained_meridian.py` SHA-256 `96875bb6592a6fd57ceef4dc326c35faeb3f96de16607faa816c7d3fed1e08ce`，设计案例 `.../design_cases.json` SHA-256 `d1bb74bfc90de5937884854fd4e5e62c4dbf01f33e2f1f7be5dbf931ee35c8eb`；10 个 jar side R9、11 个 C4/regular 条件；80 次 SLSQP 未收敛。历史 raw argv 未从存留 receipt 确认（UNKNOWN）；任何源入口调用仅供以后复核参考，本手册未执行。没有因几何候选替代完整 wall/lip/solid 检查。 |
| R9 执行 owner / 预算 | 原创建者未在存留 raw receipt 中记录，标为 UNKNOWN；root 负责当前归档。历史 `run01_capture/receipt.json` 记录 `timeout_seconds=60`、8 MiB capture cap、worker returncode 0 / 6.922 s；其 `worker_command` 调用 `run_constrained_design(root_ready=True, design_cases=None)`。SLSQP 80 次后状态未收敛，returncode 0 不代表几何优化成功。receipt 的调用语义供审计，不是重跑授权。 |
| 局部 2D 候选 | jar meridian local normal-offset 候选路径 `vesselforge/tmp/review_20261006/normal_offset_meridian_20261006/retry01_after_zprime_fix/normal_offset_meridian_result.json`，SHA-256 `96ea35c44d40d12acc4b57a932ebb5194dbccdfd516b1fc2338ec58c51a9956a`；driver `vesselforge/experiments/normal_offset_meridian_20261006/run_normal_offset_meridian_zprime_fixed.py` SHA-256 `ae91c04bac02e9a057e9f1a099350a34a9cb261d21c5bbd70388f931cb17cd54`，case `.../case_false.json` SHA-256 `6ae5611616dbb1fdeeb498efc845a91a79798e0db5894e9577c4312c8a81a319`；历史原始 argv/budget 字段若 receipt 无记录则 UNKNOWN，并引用 receipt 文件供只读审计。该结果只覆盖二维子午线局部 offset，不能代表完整旋转实体的最小壁厚。 |
| 局部 offset 执行 owner / 预算 | 原创建者姓名未由 receipt 保存，标为 UNKNOWN；当前 root 保管结果。`normal_offset_meridian_run_receipt.json` 记录 actual argv 为 pinned VF Python `-B run_normal_offset_meridian_zprime_fixed.py --worker`，user argv 为 source `--root-go`（Root GO token 不在该字段中）；outer limit 15 s，4 MiB 总持久化上限，rc=0 / 0.187 s / 438,983 B。没有 runtime CAD/STEP。 |
| 单射条件证明 | producer `luna_vf_convex_feasibility_20261006`；结果 `vesselforge/tmp/review_20261007/monotone_normal_strip_decision/once_capture_02_after_scope_fix/result.json` SHA-256 `4b7d019d2c119fb7f5db398f1205bc4830d72702f21a565a0859e1a6282335bf`；源 `vesselforge/experiments/monotone_normal_strip_certificate_20261007/monotone_normal_strip_certificate.py` SHA-256 `ae1d34351e113bf08f4de287468b38d5035f4bf1c75f98e3fb84d7b361c851ce`，case `.../case.json` SHA-256 `9e7b9e7945a14b3dd45517c75a672607cf0923cdac5c723ab614fa0162fc127b`。独立审阅 `.../monotone_normal_strip_independent/REVIEW.md` SHA-256 `a82d39f5df33c32a618295530ba347dfb78ea757bdbdbd178f8e9dab91da3861`。它是固定二维子午线映射与固定范围内的条件性单射证书。run02 runner receipt 的 argv 为 bundled Python `-B .../invoke_once_02_after_scope_fix.py`，child timeout 13 s、输出树上限 4 MiB、rc=0 / 0.125 s / 29,025 B。新运行仍需另行授权。 |
| 理想全局距离 | producer `luna_global_wall_theorem_20261007`；结果 `vesselforge/tmp/review_20261007/global_wall_distance_certificate_20261007/run01_capture/result.json` SHA-256 `2ed29f2581c49304581c36dfdf8fdda9d02b193c8078629202bc82bcefe727f0`；源 `vesselforge/experiments/global_wall_distance_certificate_20261007/global_wall_distance_certificate.py` SHA-256 `2466306decc0af17d47c71d8e66b110aa77255f8f9279b94180a86ee7029886d`，case `.../case.json` SHA-256 `985b12a38a9996372a39afb700ecc413ecbb52c106f0594dc94350674b7c27d8`。独立审阅者 `luna_bspline_independent_20261006`，`.../global_wall_distance_independent/RESULT_REVIEW.md` SHA-256 `f87220d1dd6ff9fb70040a77e07278755e134ad22084b32ac08efcc625355301`。固定理想 meridian pair 及其理想旋转集合的最小距离精确为 3 mm；实际 CAD 曲面、唇口、生产实体壁厚仍 UNKNOWN。receipt 保存的 helper argv 为 bundled Python `-B .../invoke_once.py`，child timeout 10 s、整个 supervisor 15 s、raw output cap 1,100,000 B、一次调用、rc=0 / 0.140 s；外层原始 argv 未保留。没有重跑。 |
| 最新 native C4 来源 | 执行 owner `luna_native_cad_visual_20261005`；driver `vesselforge/experiments/c4_jar_native_ingress_20261007/native_c4_ingress.py` SHA-256 `361dac93245b10baa5d331e8d66f808b3bb0af317b8f4ac8d0f13de7acaf7f6e`；runner `.../capture_once.py` SHA-256 `f06787c7dd358149f701abaa14bdbfa58c6251ab73c9bc1c417542f2744b886a`；case `.../native_c4_ingress_case.json` SHA-256 `c440df8ff8d7cd0ec3f6d67d6ce8b566f783974bdf14cd27aafdf6203cba96be`；pins `vesselforge/tmp/review_20261007/c4_jar_native_ingress_20261007/native_source_v1/source_pins.json` SHA-256 `33f727be1fc4f31b84f894ac6f34c98235036fdc46ada255b87b6bf41a98bc04`。独立来源审阅 owner `luna_native_c4_source_critic_20261007`；`FINAL_SOURCE_REVIEW.md` SHA-256 `fd0499f1b70933700df3e78eb79186c3748e5f2403c5cd10bf22e6d52fcba2c2` / JSON `4439f8482f277ba8b7de17343e50ceab37a4294694b4e914d9fe8e7963ae6e9c`；根 SOURCE_ACCEPTANCE SHA-256 `cccf36d55a7a6355c53799f4dcf0fe3f86ec5057d42e5c1e4ac0cdd7b14601e6`。结论 SOURCE_ACCEPTED 只覆盖 driver/runner/静态合同；CADQuery/OCP 7.9.3.1.1 匹配 stub wheel 仅签名核查、未安装；CAD/STEP 调用数 0。没有实际 runtime argv，因为未做 CAD；执行保持未授权。 |
| 下一最小动作 | native 来源接受结束；CAD ingress 不由本文件或 source acceptance 授权。未来只有用户另行明确授权、新 run ID 与新预算后，才可考虑窄范围 CAD ingress；实体级 wall、lip、STEP roundtrip 和历史器型相似度还需独立资格门。 |

这里的 R9、C4、exact-distance 只描述它们各自冻结的数学/几何对象。任何结果都不表示材料标定、真实器物身份、完整 CAD 输入链或物理后端可用。

### PG-Frag mechanics objectivity 来源包

| 字段 | 记录 |
|---|---|
| 负责人 | source owner `luna_continuous_bias_bounds_20261006`；独立 source-only reviewer `luna_objectivity_design_critic_20261007`；根任务已接受窄范围。 |
| 当前适配器 | `pgfrag/experiments/mixed93_mechanics_objectivity_20261007/mechanics_objectivity_adapter.py`；SHA-256 `6ca66a86dcf801464afc1104d69b55b3421aadda6860482bc898170ce5c253ce` |
| case / pins | `pgfrag/experiments/mixed93_mechanics_objectivity_20261007/CASE_DRAFT.json` SHA-256 `a189527e639190192312dd8e9685d493f2b241aaed7680c2979e42a63390574e`；`pgfrag/tmp/review_20261007/mixed93_mechanics_objectivity_20261007/source_pins.json` SHA-256 `367ca3c1dfd694a760941b42bb2b54b5f00a64560978cd11f5f1f6413d874178`。 |
| 变更范围 | 相对快照 `pgfrag/tmp/review_20261007/mixed93_mechanics_objectivity_20261007/mechanics_objectivity_adapter.precloseout.snapshot.py`（321 行，SHA-256 `f9b35bd271e1ac9e86bedb813435f3a0b9b045bc84f4b1e1e56c1f10244c346f`），窄修正只增加 FrameState.mls_origin_world_m 字段及从构造函数传入计算所得 MLS origin。根任务核对 20/20 当前 pins。 |
| 独立窄修复审阅 | NARROW_FIX_ACCEPTANCE.md SHA-256 6011faf8d255863aed384d6c51395c745d09b1f334b4d5aec85e28007350033f；NARROW_FIX_ACCEPTANCE.json SHA-256 2c27b2a4a57bbbdcc7ab1fa2d3a77881e54b4739d474c019b27d5cf1d7269013。 |
| 判定 | SOURCE_ONLY ACCEPTED。窄修复只新增 `FrameState.mls_origin_world_m` 字段与传递已计算 MLS origin 的 constructor argument；20/20 pins match。尚无数值查询、quadrature、cloud、crack bias、KKT 或 solver run。源码约束不是 mesh/orientation-bias 结论。 |
| 命令/预算 | 数值执行未授权且未发生。`CASE_DRAFT.json` 仅列待申请计划：2 个状态合计 2,560 provider queries（每状态 1,280）、每状态 5 批×256、2 次新 raw K/C/f assembly、2 次谱检查、2 次 99×99 KKT；资源上限为 30 s external wall、8,388,608 B result、67,108,864 B dense array。此为计划上限，不是本轮已执行数据。 |
| 下一最小动作 | 源码窄修复已独立接受为 SOURCE_ONLY；没有数值 GO。未来数值验证须由用户另开授权、新 run ID 与独立预算。 |

### VesselForge native C4 ingress 来源包

根任务对 native C4 driver、runner、case 与完整来源差异做过完整阅读并复核 20/20 pins。source-only 最终审阅和 root acceptance 均已收到；这只接受 459 行 driver、runner 与静态合同。当前实现整理 representation-dependent face classifier、axis cast、预算和来源 pins；未运行 CAD/STEP、未导入 OCP 或创建 native instance。匹配 OCP 7.9.3.1.1 的签名 stub wheel SHA-256 为 `5ecba090df1ada12c558ff4a1b49c61d5155edc8cb3411067a785e3b43f4b359`，只下载作静态签名核查、未安装。CAD 拓扑、STEP 往返、native wall、lip 与生产表面均 UNKNOWN。

### A12 合成、退化和资格

| 字段 | 记录 |
|---|---|
| 负责人 | A12 claims alignment `luna_a12_g01_resume_20261005`；来源读者 `luna_a12_pg_source_reader_20261005` 在本次收口中负责核验；本轮由 root 关闭文档边界。 |
| 当前证据入口 | `relicweave-synlab/docs/a12/reviews/20261007/REVIEW.md` SHA-256 `881e71d0441d235b2143a1a06cf7429547892a953c2c74a951ec6161576eeeba`；`claims.json` SHA-256 `7c7d6c6c00e7086c7da1b531103cb95812b87e5befd0ae69730e1f395d482806`。支撑数据分别为 `relicweave-synlab/data/a12/reports/precision_probe_07_degrade_audit.json` SHA-256 `b38d7dd1cddeff2dfcc06173de44ac83eb583cab045c05d6f47aff102a9f39fb`、`precision_probe_09_degrade_error.json` SHA-256 `d964413f473caea5bb75ec7a7ca39c140dcd8ac38892e13ebe3247a40327987e`、`pattern_audit.json` SHA-256 `e52989f1fa25cfb47442094c3c36dccbccc8b59a10ca97c9cbf910d3071e7e71`；后三者均位于 `relicweave-synlab/data/a12/reports/`。 |
| 进度与 readiness | `pgfrag/docs/progress/20261006_physics_core_review_addendum.md`（3,962 B，SHA-256 `379c3f9079cb25aa97797ccd40a76bb2bd5c303b50ee3992b409f4c932ffd8f3`）及其 pins `pgfrag/tmp/review_20261006/20261006_physics_core_review_addendum.pins.json`（62,911 B，SHA-256 `389656a11ce48037ce1be66e86d310a235ae65b2fff5c5b63c685e8fdda80f33`）；跨项目 readiness `tmp/review_20261007/core_readiness_inventory/READINESS.md`（21,701 B，SHA-256 `7f38cc3a9c330d646a07a108321ea528aeaa3755072943f718a9baa5b49bd939`）及 `readiness.json`（72,333 B，SHA-256 `c8459dbac69a4e5cab3c5b3dcea752805a8b605d2176512c5bdba8eee4dfd9f1`）。根任务已签收这些状态文件；它们没有新增源代码或数值运行。 |
| 退化轴 | 当前登记 31 轴 × 5 档，即 155 条 software QA rows；155/155 的 PASS 仅指实现执行/有效性，不是保真精度。有效 goal/measured 对仅覆盖 9/31 轴、36/155 档；28/31 轴声明了 pair-key 定义，但 22/31 轴没有非空实测对，3 轴 P01/P05/P06 连 pair-key 定义也没有。 |
| 测量范围 | 有效配对覆盖一份 independent mother，量值仍全部未校准；剩余偏差和代理量不得改写成物理精度。 |
| 纹样 | 源定义 16 个 pattern IDs，软件/fixture QA 不等于历史纹样有效性，也不保证 true-mother 纹样几何实际应用。历史验证 style families 为 0；当前 pattern audit 的两项 guard rejection 不能计为成功应用。 |
| 材料 | 源定义 12 个 A12 material IDs 和 layer combinations；profile/module QA 不等于实物标定。物理标定 families 为 0。 |
| 全模型门 | A12 whole-model leakage / release admission 尚未闭合。局部 wear/error reports 是子轨道证据，不是整体 admission。完整可资格物理包为 0。 |
| 下一最小动作 | 把真实对象 provenance、保持隔离的 offline GT 审计、准入模型视图和一份有测量不确定度的材料/退化标定计划纳入新任务；每一项均需独立 scope 与 run authorization。 |

### 研究方向核对与材料边界

RelicWeave 当前主线不包含论文新颖性结论。已做的接口、证据合同、版本化和失败可观测性属于工程实现改进；论文贡献仍需针对最近相关工作、强对照和真实任务证据单独论证。

陶瓷校准目录中的论文与官方方法只用作测量设计参照，不是本项目材料卡。不同烧成温度、孔隙、矿物组成、取向和试验方法会改变弹性、强度与断裂量的含义。文献中的 apparent toughness、flexural strength 或从 K 推出的 G，不能替代本项目实物的同批次、同含水状态测量。PG-Frag 的 density、E、ν、tensile strength、Gc、cohesive law、process zone 和 refinement response 仍需来源绑定的实物和不确定度。

## 保留的反例与停路线

| 路线 | 已知问题与处置 |
|---|---|
| Astra ghost-jump / support topology | Astra 是既有旧决策，不是本轮运行。有限裂片两侧 Boolean-visible support sets 可突变并产生非物理 ghost jump；解析反例说明不应称为 CPM2018 的合法复现。Bool-only 路线停止作为主支持构造；优先连续 MLS 与 support-topology-restricted H/front partition-of-unity enrichment。 |
| 6,810 first-break / grip detach | 6,810 是事件数量，不是 Julia 版本号。保存记录中的全部 first-break events 均关联右 grip 并跨越 grip boundary；它们证明的是图关联/边界事件归属，不是内部裂纹或碎片。结果记录：`pgfrag/tmp/review_20261005/free_fracture_pilot_independent_review/run03/RUN03_EXECUTION_RECORD.json`，SHA-256 `65f01810c31798f2dbb7e041505e99617c3451e84e34c6a51b4e05e296ad271e`。 |
| degree-7 curvature constraint | 已有反例阻断直接使用；改为保守 degree-5 C4 约束后也只当工程证书使用，后续 R9/SLSQP 微调和 conservative LP 628 路线已停止。 |
| flat BOX geometry fixture | 它是几何 fixture，不能证明 rough-fracture 物理真实性或材料参数。 |

失败历史、源快照、未通过的报告和撤回结论都保留。只有新冻结输入、独立审阅、显式预算和获准的新 run ID 才能增加状态；不能覆盖先前失败、把失败样本删出分母或将 candidate 改称 stable。

## 运行环境与安全复现

本次文档复核使用 Windows PowerShell，仓库根目录为 C:\Users\xiemo\Desktop\ShardForge。通用文档/元数据任务使用捆绑的工作区运行时：

- Python：C:\Users\xiemo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
- Node.js：C:\Users\xiemo\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe
- 文档渲染专用 LibreOffice：C:\Users\xiemo\Desktop\ShardForge\third_party\doc-render-runtime\LibreOffice-26.8.0\program\soffice.exe

不要让渲染器调用用户桌面安装的 LibreOffice。任何新运行都应使用其 own source_pins 和 case 中固定的项目运行时、依赖版本、许可证清单与预算；本交接不宣称所有仓库的运行环境或第三方许可证已统一审计。没有 source pins 时先补审，不从全局 PATH 或其他项目 venv 猜测依赖版本。本机目前只允许按小型 micro case 计划未来验证；即使后续使用 RTX 5090 32 GB VRAM / 48 GB RAM，本机 bulk 生成也须先通过单独资源基准与新授权。

下列路径用于按证据回查，不代表可重放的运行命令。已运行项的实际参数以其外层 receipt 中的 argv/command 字段为准；任何历史 Root GO 已消耗，不可复用。

| 工作项 | 保存的执行/命令记录 | 原始限额与运行状态 |
|---|---|---|
| PG 固定界面 bridge | `pgfrag/tmp/review_20261006/mixed93_actual_cohesive_bridge_20261006/numeric_runs/run01/receipt.json` 的 `argv`，source entry `run_actual_cohesive_bridge.py`，case `case.json`。 | 60 s wall、12 MiB总输出；rc 0，child 0.266 s。该命令已执行一次，不再重放。 |
| PG opening history | `pgfrag/tmp/review_20261007/mixed93_opening_control_20261007/run01/receipt.json` 和 `pgfrag/tmp/review_20261007/mixed93_opening_control_20261007/capture_CASE.json`（SHA-256 `433b574c9f08624ef07b6c04ddb57f9fbfbe87f2856bc026ecab3dc3262992b2`）；receipt只留token hash与占位符参数模板，完整历史外层 argv 为 UNKNOWN。 | 20 s deadline、8 MiB总文件；rc 0，child 0.734 s。consumer读回另见 independent run02 receipt。 |
| PG moving-front run01 | `pgfrag/tmp/review_20261007/mixed93_moving_front_reanalysis_20261007/capture_once01/capture_receipt.json` 的 `command`，固定 Python `third_party/vesselforge-runtime/venv/Scripts/python.exe -B` 和 driver。 | 64 s whole-call、59.938 s child timeout、12 MiB输出；child wall time UNKNOWN，outer 1.269 s / capture统计 0.968 s，rc 2。禁止重放。 |
| VF R9候选 | `vesselforge/tmp/review_20261006/curvature_constrained_meridian_20261006/run01_capture/receipt.json` 的 `worker_command` / `invocation`。 | 60 s timeout、8 MiB；rc 0 / 6.922 s；80次优化未收敛。 |
| VF local offset | `vesselforge/tmp/review_20261006/normal_offset_meridian_20261006/retry01_after_zprime_fix/normal_offset_meridian_run_receipt.json` 的 `actual_argv` 与 `user_argv`。 | 15 s、4 MiB；rc 0 / 0.187 s / 438,983 B。GO值未保存在 argv 字段。 |
| VF normal strip | `vesselforge/tmp/review_20261007/monotone_normal_strip_decision/once_capture_02_after_scope_fix/receipt.json` 的 `process.argv`。 | 13 s child timeout、4 MiB输出树；rc 0 / 0.125 s / 29,025 B。 |
| VF ideal wall distance | `vesselforge/tmp/review_20261007/global_wall_distance_certificate_20261007/run01_capture/receipt.json` 的 `process.argv`（helper）与 `whole_call_limit_seconds`。 | child 10 s、全流程15 s、raw 1,100,000 B；一次调用、rc 0 / child 0.140 s。原始外层工具 argv 未保留。 |
| PG objectivity / VF native C4 | 无数值或 CAD runtime argv。source-only审阅由其案例文件列出计划预算，不等于运行。 | objectivity计划2,560 queries / 2 KKT / 30 s / 8 MiB；native C4未运行、当前无CAD预算消费。 |
| A12 claims alignment | 只读报告对齐；`relicweave-synlab/docs/a12/reviews/20261007/REVIEW.md` 自述单次JSON检查低于1 s，无solver/Blender/CAD/Git/production CLI。 | 没有新的测量或合成运行，也没有可主张的全模型 admission。 |

复核保存内容可使用以下只读命令；这些命令只哈希或读取小型人工审阅件：

~~~powershell
Set-Location C:\Users\xiemo\Desktop\ShardForge
Get-FileHash -Algorithm SHA256 -LiteralPath 'pgfrag\tmp\review_20261007\mixed93_moving_front_reanalysis_20261007\CLOSEOUT.json','pgfrag\tmp\review_20261007\mixed93_moving_front_reanalysis_20261007\run01\failure.json','pgfrag\tmp\review_20261007\mixed93_moving_front_reanalysis_20261007\run01\failure_arrays.npz'
Get-Content -LiteralPath 'pgfrag\tmp\review_20261007\mixed93_moving_front_reanalysis_20261007\CLOSEOUT.md' -Encoding UTF8
Get-Content -LiteralPath 'pgfrag\tmp\review_20261007\mixed93_moving_front_independent\SAVED_FAILURE_REVIEW.md' -Encoding UTF8
Get-Content -LiteralPath 'pgfrag\tmp\review_20261007\mixed93_mechanics_objectivity_independent\NARROW_FIX_ACCEPTANCE.md' -Encoding UTF8
Get-Content -LiteralPath 'vesselforge\tmp\review_20261007\native_c4_source_independent\FINAL_SOURCE_REVIEW.md' -Encoding UTF8
Get-Content -LiteralPath 'relicweave-synlab\docs\a12\reviews\20261007\REVIEW.md' -Encoding UTF8
~~~

不要再次读取 NPZ 负载来“补齐”未保存的物理结果，也不要启动 solver、CAD、服务、训练或提交循环。先读小型 receipt/status 与独立审阅结论，再检查对应 source pins。旧 HANDOVER 中的 commit loop、API service、Vite preview 命令已过时。

## 版本、历史与备份

V1.46 保留件为根目录 RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx，原始 SHA-256：

15978a3956fa33e8048cc54c1dad6878a7e19d9c71b84415dcaf8732f041a3b4

原件大小 733,634 bytes。原始结构记录为 2,343 个正文段落、176 张表、520 个 bookmark 与 80 个 hyperlink。V1.47 必须由原件复制后局部补丁产生；历史导航、书签、超链接、样式和原生公式继续保留。

2026-10-02 的 relicweave-synlab/docs/a12/HANDOVER.md 保留为历史快照。其顶部新增 superseded 标记与本文相对链接，原始字节另存于 tmp/closeout_documents_20261007/A12_HANDOVER_20261002.original.md（SHA-256 c9a9950886c76ea773c53b72fec15bbce6e4e3388c361b27a295bd591c64393a）；新文件在前缀之后与原始正文逐字节相同。不能再按旧正文操作自动启动服务或周期提交。

SCIENCE 98-file 独立备份曾被接受。当前基线 HEAD 记录为 PG-Frag `cc0e79773ce34bdebe9124d3fe60c078a85a2f5d`、VesselForge `30b7e23aa696eafb3a39f9368de55382c9206069`、A12 `7cfb7fbb63c0d9170871f72cbfd8586a4c416c56`。三仓 canonical remote 与共享备份分支如下：

| Repo | Remote | Branch | 本地基线 commit |
|---|---|---|---|
| PG-Frag | `https://github.com/xiemonb666/pgfrag.git` | `backup/forge-work-20261003` | `cc0e79773ce34bdebe9124d3fe60c078a85a2f5d` |
| VesselForge | `https://github.com/xiemonb666/vesselforge.git` | `backup/forge-work-20261003` | `30b7e23aa696eafb3a39f9368de55382c9206069` |
| A12 SynLab | `https://github.com/xiemonb666/relicweave-synlab.git` | `backup/forge-work-20261003` | `7cfb7fbb63c0d9170871f72cbfd8586a4c416c56` |

若后续任务由用户明确要求恢复隔离工作树，可按仓库选择其中一组 reference-only 命令；用独立目录代替示例目录，绝不覆盖现有 workspace：

~~~powershell
git clone --no-checkout https://github.com/xiemonb666/pgfrag.git C:\restore\pgfrag
git -C C:\restore\pgfrag fetch origin backup/forge-work-20261003
git -C C:\restore\pgfrag worktree add --detach C:\restore\pgfrag-baseline cc0e79773ce34bdebe9124d3fe60c078a85a2f5d

git clone --no-checkout https://github.com/xiemonb666/vesselforge.git C:\restore\vesselforge
git -C C:\restore\vesselforge fetch origin backup/forge-work-20261003
git -C C:\restore\vesselforge worktree add --detach C:\restore\vesselforge-baseline 30b7e23aa696eafb3a39f9368de55382c9206069

git clone --no-checkout https://github.com/xiemonb666/relicweave-synlab.git C:\restore\relicweave-synlab
git -C C:\restore\relicweave-synlab fetch origin backup/forge-work-20261003
git -C C:\restore\relicweave-synlab worktree add --detach C:\restore\relicweave-synlab-baseline 7cfb7fbb63c0d9170871f72cbfd8586a4c416c56
~~~

这些是记录已知 baseline 的恢复样例，不执行、不产生 push。若要从当前备份 branch 恢复，则需先用协调者的 delivery receipt 核对其最终 HEAD，再以 receipt 明确列出的 SHA 建外部工作树。开始工作前必须核对 commit 与 branch；未验收的 source-only 或 failed artifact 不得因备份存在而晋级。

协调者在本手册与两个 DOCX 内容及视觉 QA 完成后才归档它们。本轮冻结文档只引用固定 post-push delivery sidecar：`relicweave-synlab/docs/handover/20261007/BACKUP_DELIVERY_RECEIPT.json` 与同目录 `BACKUP_DELIVERY_RECEIPT.md`。该 sidecar 记录三仓最终 HEAD 和清单，后置于其记录的 commit-set 之外；文档不写该回执自己的 hash，也不在 sidecar 落盘后改写 DOCX。最终 HEAD 和回执仍 PENDING，未声称本次最终备份完成。

另有计划中的文件级恢复树 `workspace_backup/20261007/`；截至当前文档收口，该路径尚未由协调者落盘。落盘后，manifest 的 SHA 是每个原始文件的哈希，不是 Git commit。恢复单个文件时先按 manifest 中原路径与 SHA 对照，写入后用 `Get-FileHash -Algorithm SHA256` 再核验。不要从恢复树递归复制 `.git`、虚拟环境、凭证或服务状态。

历史保全有限：V1.46原始 DOCX 与旧 A12 handover 正文已按记录留存；早期的两个 DRAFT 精确字节包（记录前缀 `e275…` / `eb7a…`）未能恢复，但更早源码/文档快照仍存在。因此本归档不宣称包含所有中间草稿、每一份原始 stdout/stderr 或所有被用量中断前的文本。

## 接手后的实际步骤

先验证V1.46保留件的 SHA-256 和此处标明的保存审阅件，再从本手册对应任务条目判断状态。历史候选仅可按其冻结 source/case/result 和独立审阅结论解释。若要继续任何 solver、CAD、材料、合成或线上检索任务，先由用户重新定义范围、给出新的 GO/run ID/预算与样本许可，再冻结输入、完成独立 source review 和数据隔离检查。当前范围没有授权任何新数值求解、CAD实例、训练、服务、自动循环或批量生成。

尚未解决的资格工作包括真实裂纹增长、动态撞击与多体接触、mesh/取向/前沿方向偏差、粗糙断口与 process-zone 收敛、同批次陶瓷材料校准、生产级母体几何/唇口/壁厚、历史 style/material/relief 验证、真实退化与标注校准、A12 全模型 release admission 以及 online GT/hidden-state 泄漏审计。现有 engineering completion estimates 为计划/资源判断，继续保持 PG-Frag 25–35%、VesselForge 30–40%、A12 30–40%；合格 physical packages = 0。

