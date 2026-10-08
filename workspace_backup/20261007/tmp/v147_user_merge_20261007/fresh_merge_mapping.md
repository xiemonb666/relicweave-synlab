## STATUS 1 srcblock=1594 matches=[1516]
directidx=447 directtag=p
CURRENT CONTEXT
 C[1513] usermatches=1 direct=444 A12.19 实施输出与研究判断
 C[1514] usermatches=1 direct=445 工程输出现在分三套可独立版本化的资产：①VesselForge Asset Package（母体几何、纹样/材质、厚度/区域场、Physics-Ready验证与generation manifest）；②PG-Frag Result Package（碎片、fracture surfaces、裂纹谱系、材料/事件/solver lineage与physics 
 C[1515] usermatches=1 direct=446 研究输出采用同一批母体的配对质量曲线、数量曲线、跨纹样／后端留出、真实样本需求曲线和成本曲线。理想可见输入低分先排查GT与优化；某退化轴造成显著损失，再用真实补采或重建复核；增加数据无收益时检查多样性、负例和训练预算；只有独立真实确认通过，才把合成收益写入实际能力。
 C[1516] usermatches=0 direct=447 A12.19 当前状态（2026-10-07）：本节所列 Release 能力仍是目标接口与验收清单，不代表已完成发布。当前 31 个退化轴、155 个档位/检查组合属于软件 QA；其中 9 个轴有测量记录、36 个非零级别，均来自 1 个母体且未校准。16 个纹样族 ID 尚无经历史样式验证的族，12 个材料 ID 尚无经物理校准的材料。端到端检索收益、真
 C[1517] usermatches=1 direct=448 预留ID
 C[1518] usermatches=1 direct=448 未来创新方向
 C[1519] usermatches=1 direct=448 要解决的问题
NEAREST PREV: 1515 研究输出采用同一批母体的配对质量曲线、数量曲线、跨纹样／后端留出、真实样本需求曲线和成本曲线。理想可见输入低分先排查GT与优化；某退化轴造成显著损失，再用真实补采或重建复核；增加数据无收益时检查多样性、负例和训练预算；只有独立真实确认通过，才把合成收益写入实际能力。
NEAREST NEXT: 1541 A12.20 双子项目的独立性、非锁定与升级规则
 USER PREV indexes=[2061]
 USER NEXT indexes=[2086]
## STATUS 2 srcblock=1623 matches=[1543]
directidx=451 directtag=p
CURRENT CONTEXT
 C[1540] usermatches=1 direct=448 必须给出最小否定实验
 C[1541] usermatches=1 direct=449 A12.20 双子项目的独立性、非锁定与升级规则
 C[1542] usermatches=1 direct=450 VesselForge和PG-Frag必须各自拥有独立仓库、版本号、CI、单元测试、Benchmark、CLI/Python API与插件注册表；RelicWeave只是当前上层调用方之一。公共API使用能力接口而不是算法名，例如simulate(..., backend=...)，资产/结果Schema不得暴露某个库的私有对象。第三方只要满足Asset C
 C[1543] usermatches=0 direct=451 A12.20 当前实施与资格边界（2026-10-07）：独立仓库、公共合同与可替换后端是架构边界；局部源代码接受或诊断 toy 不等于完整实现或项目资格。PG-Frag 的固定界面与开口控制仍未形成断口分离；moving-front 在合同字段错误处停止。VesselForge 尚无历史器型、生产几何、唇口或实体全局壁厚资格。A12 仍承担观测、权限、关系
 C[1544] usermatches=2 direct=452 5 数据采集与标注实施
 C[1545] usermatches=1 direct=453 我们负责把真实样品变成身份可信、断口可见、关系可核、能直接进入模型的观测数据。现在使用手机加现有转盘手动采集，先证明观察和标签可用；未来升级到开发板相机DIY台时，保留同一数据合同，做同片配对比较。采集数量和画面效果不能代替真实检索有效性。
 C[1546] usermatches=2 direct=454 B1 职责与立即启动清单
NEAREST PREV: 1542 VesselForge和PG-Frag必须各自拥有独立仓库、版本号、CI、单元测试、Benchmark、CLI/Python API与插件注册表；RelicWeave只是当前上层调用方之一。公共API使用能力接口而不是算法名，例如simulate(..., backend=...)，资产/结果Schema不得暴露某个库的私有对象。第三方只要满足Asset Contract即可直接接入PG-Frag；VesselForge生成的资产也可直接输出给CAD/CAE、渲染、数字孪生或其他数据平台。Stable后端用于默认生产，Candidate完成基本验证，Experimental仅用于前沿探索；新后
NEAREST NEXT: 1544 5 数据采集与标注实施
 USER PREV indexes=[2087]
 USER NEXT indexes=[23, 2094]
## STATUS 3 srcblock=2947 matches=[2797]
directidx=817 directtag=p
CURRENT CONTEXT
 C[2794] usermatches=1 direct=814 V1.44逐章修订24项问题，增加沿光轴U、统一指标／权限／标签／风险及资源合同，合成退化扩为31轴。附录H给验收索引；原文件与历史封存成绩保留，未新增硬件或模型实测成绩。
 C[2795] usermatches=1 direct=815 V1.45专项完善A12与附录G，增加周期随机纹样、可审计共享断裂、分层退化算子、训练张量与损失、配对诊断和程序接口。V1.44已修订的24项统一合同继续适用；新增算法与流程按G31.1验收，不改历史实验结果。
 C[2796] usermatches=1 direct=816 V1.46将VesselForge与PG-Frag正式作为两个独立基础设施子项目接入A12：器物/纹样/材质/物理就绪资产归VesselForge，损伤/裂纹/碎裂/断面/碎片动力学归PG-Frag，A12保留观测退化、关系构造、预训练和诊断。附录G同步改为编排层规范，并新增附录I/J完整子项目方案；该架构调整不新增任何模型成绩，也不改写历史实验判决。
 C[2797] usermatches=0 direct=817 V1.47（2026-10-07）收口记录：本次更新实施状态、证据边界与后续资格门，并在不改历史文字、数值或导航的前提下修复缺失的东亚字体映射、A12.17 第 39 表深色表头字色及活动版本页眉/日期页脚；未新增模型成绩或完整物理合格包。moving-front 单次运行因审计字段错配在 wrench/KKT/G 前停止，未重试；objectivity 与
 C[2798] usermatches=2 direct=818 12 本版主要来源与复用边界
 C[2799] usermatches=1 direct=819 [REF-CVPR] CVPR 2027 Dates and Deadlines，2026年9月30日核对：https://cvpr.thecvf.com/Conferences/2027/Dates 。提交前再核作者与匿名政策。
 C[2800] usermatches=1 direct=820 [REF-CAMERA] Luckfox官方SC3336 B规格、兼容表与RV1103相机教程：https://wiki.luckfox.com/SC3336-3MP-Camera/ 和 https://wiki.luckfox.com/Luckfox-Pico-Plus-Mini/CSI-Camera/ 。规格支持选型，不支持本项目清晰度与收益结论。
NEAREST PREV: 2796 V1.46将VesselForge与PG-Frag正式作为两个独立基础设施子项目接入A12：器物/纹样/材质/物理就绪资产归VesselForge，损伤/裂纹/碎裂/断面/碎片动力学归PG-Frag，A12保留观测退化、关系构造、预训练和诊断。附录G同步改为编排层规范，并新增附录I/J完整子项目方案；该架构调整不新增任何模型成绩，也不改写历史实验判决。
NEAREST NEXT: 2798 12 本版主要来源与复用边界
 USER PREV indexes=[3409]
 USER NEXT indexes=[70, 3411]
## STATUS 4 srcblock=4207 matches=[4009]
directidx=1414 directtag=p
CURRENT CONTEXT
 C[4006] usermatches=1 direct=1411 G0 V1.46架构覆盖规则：A12不再拥有器物/断裂底层内核
 C[4007] usermatches=1 direct=1412 权威调用链为 VesselForge Asset Contract → PG-Frag Job/Result Contract → A12 SyntheticLab。G7/G8中的器型、纹样和材质细节是A12对VesselForge输出的Profile与验收要求；G9/G10/G11中的共享切割、分区、物理插件是A12对PG-Frag Backend的测试P
 C[4008] usermatches=1 direct=1413 禁止在relicweave-synlab中复制VesselForge的CAD/纹样/网格核心或PG-Frag的PD/FEM/Phase-Field/接触核心。确需新增底层算法时，先进入对应子项目的Backend Registry并建立ADR；A12只增加Adapter、实验Profile、数据/权限转换、观测退化或研究诊断。
 C[4009] usermatches=0 direct=1414 G0 当前状态（2026-10-07）：本规则已明确底层内核归属，但当前只是局部实现与来源证据归位，不表示端到端 Asset→Job/Result→Release 链路已完整验收。PG-Frag bridge/opening 是诊断 toy；moving-front 因审计字段错配停止。VesselForge native C4 仅完成 driver/run
 C[4010] usermatches=1 direct=1415 G1 实验室要实现的功能与完成标准
 C[4011] usermatches=1 direct=1416 实验室由A12编排核心和多个可替换Adapter组成。VesselForge负责生成只读的完整母体资产，PG-Frag负责生成只读的clean碎裂/断面/物理结果；A12持有跨项目谱系、关系真值、观测与训练权限，并只在标准结果之上做沉积磨损、成像/重建退化和实验构造。每次发布必须能追溯到A12配置、VesselForge/PG-Frag core与backe
 C[4012] usermatches=3 direct=1417 模块
NEAREST PREV: 4008 禁止在relicweave-synlab中复制VesselForge的CAD/纹样/网格核心或PG-Frag的PD/FEM/Phase-Field/接触核心。确需新增底层算法时，先进入对应子项目的Backend Registry并建立ADR；A12只增加Adapter、实验Profile、数据/权限转换、观测退化或研究诊断。
NEAREST NEXT: 4010 G1 实验室要实现的功能与完成标准
 USER PREV indexes=[4621]
 USER NEXT indexes=[4622]
## STATUS 5 srcblock=6093 matches=[5827]
directidx=2190 directtag=p
CURRENT CONTEXT
 C[5824] usermatches=1 direct=2187 G31.1 V1.45新增算法的完成证据
 C[5825] usermatches=1 direct=2188 V1.46新增完成证据：必须同时保存VesselForge asset manifest与validator报告、PG-Frag job/result manifest与solver lineage、A12 release manifest与权限审计；三者任一缺失都不能声称端到端可复现。
 C[5826] usermatches=1 direct=2189 专项签收需提交：16纹样族的recipe和连续性／尺度报告；四必做碎裂后端的共享界面、来源、二次破碎与精度测试；31轴逐档实际测量、零强度回归和组合约束；features与labels隔离检查；多正例、无匹配对应和缺模态的训练执行卡；固定query／gallery的配对诊断；1000片资源profile以及训练中断恢复记录。只完成文档或伪代码不计程序完成。
 C[5827] usermatches=0 direct=2190 G31.1 V1.47 收口核对（2026-10-07）：本节列出的专项签收项目仍是待完成的资格门。当前 31 轴与 155 项 QA 记录没有替代逐档物理校准；16 个纹样族 ID 没有历史样式验证；原方案所列四个必做碎裂后端、完整三方发布谱系、真实检索对照和规模资源实测仍未整体签收。局部来源审阅、几何证明和诊断运行仅按各自范围记录，不晋级为完整程序或物理
 C[5828] usermatches=1 direct=2191 A负责几何场、断裂GT、关系采样与训练；B负责尺度分布、纹样／断口统计、真实校准和人工复核；C负责camera／light profile、渲染与U近远实拍对齐；D负责schema、调度、资产存储、API和界面。共同复核谱系隔离、错误分母及release。实施工时写G27任务卡，以实测更新8.4日历，不同时给四人追加未核算工时。
 C[5829] usermatches=1 direct=2192 G32 算法与软件的官方资料
 C[5830] usermatches=1 direct=2193 以下作为具体接口、算法与使用边界的核验入口，核验日期2026年10月1日。上文的模块组合、覆盖规模、退化范围、容差、存储预算和排期是本项目工程设计，均须实施后实测确认。算法来源与本项目实现分别登记，源论文的效果不能自动转作本项目效果。
NEAREST PREV: 5826 专项签收需提交：16纹样族的recipe和连续性／尺度报告；四必做碎裂后端的共享界面、来源、二次破碎与精度测试；31轴逐档实际测量、零强度回归和组合约束；features与labels隔离检查；多正例、无匹配对应和缺模态的训练执行卡；固定query／gallery的配对诊断；1000片资源profile以及训练中断恢复记录。只完成文档或伪代码不计程序完成。
NEAREST NEXT: 5828 A负责几何场、断裂GT、关系采样与训练；B负责尺度分布、纹样／断口统计、真实校准和人工复核；C负责camera／light profile、渲染与U近远实拍对齐；D负责schema、调度、资产存储、API和界面。共同复核谱系隔离、错误分母及release。实施工时写G27任务卡，以实测更新8.4日历，不同时给四人追加未核算工时。
 USER PREV indexes=[6438]
 USER NEXT indexes=[6439]
## STATUS 6 srcblock=6297 matches=[6023]
directidx=2240 directtag=p
CURRENT CONTEXT
 C[6020] usermatches=1 direct=2237 附录I VesselForge：通用三维器物与纹样生成平台（独立子项目方案）
 C[6021] usermatches=1 direct=2238 VesselForge是A12上游资产基础设施：从参数、规则、参考或生成式先验得到完整、可用、可追溯的三维器物资产，包括器型、部件、语义纹样、浮雕/刻纹、材质、真实尺度、厚度/区域场与物理可用几何。它不负责物理断裂，也不负责碎片匹配。其核心价值是统一CAD、程序化几何、纹样、UV/SDF/PBR、网格和资产协议，并保持多Backend、可替换、可独立发布。
 C[6022] usermatches=2 direct=2239 来源基线：VesselForge × PG-Frag 技术路线总纲 v1.1（2026-10-03）。以下内容已归并到RelicWeave主文档，但项目边界仍保持独立；A12只通过版本化合同调用。
 C[6023] usermatches=0 direct=2240 VesselForge 当前状态（2026-10-07）：已有 bowl/beaker/jar 三个解析参数族、两个默认 CAD 实例，以及局部二维几何候选与理想曲线距离证据；仍有 0 个经历史参考验证的器型族、0 个经资格确认的生产实体和 0 个校准材料/真实纹样外观。最新 native C4 来源审阅为 SOURCE_ACCEPTED，仅接受源代码合同，
 C[6024] usermatches=1 direct=2241 I1 两个项目的共同定位与设计原则
 C[6025] usermatches=2 direct=2242 两个子项目应从第一天起就按“可独立发布、可独立维护、可被第三方调用”的基础设施设计，而不是作为某个主项目内部的脚本集合。当前它们可以服务于上层项目，但 API、数据模型、任务定义、测试集和版本管理必须保持独立。
 C[6026] usermatches=1 direct=2243 I1.1 项目边界
NEAREST PREV: 6022 来源基线：VesselForge × PG-Frag 技术路线总纲 v1.1（2026-10-03）。以下内容已归并到RelicWeave主文档，但项目边界仍保持独立；A12只通过版本化合同调用。
NEAREST NEXT: 6024 I1 两个项目的共同定位与设计原则
 USER PREV indexes=[6633, 7046]
 USER NEXT indexes=[6634]
## STATUS 7 srcblock=6749 matches=[6437]
directidx=2386 directtag=p
CURRENT CONTEXT
 C[6434] usermatches=1 direct=2383 附录J PG-Frag：通用三维物理断裂与碎片生成引擎（独立子项目方案）
 C[6435] usermatches=1 direct=2384 PG-Frag是A12上游物理碎裂基础设施：接收任意满足Asset Contract的三维实体与材料/事件配置，模拟损伤、裂纹、碎裂、断面、碎片分离、接触与后续动力学，并输出统一Fragments + Fracture Surfaces + Physics Metadata。它不负责“生成什么器物”，不假设输入一定是陶器，也不依赖RelicWeave的任务标
 C[6436] usermatches=2 direct=2385 来源基线：VesselForge × PG-Frag 技术路线总纲 v1.1（2026-10-03）。以下内容已归并到RelicWeave主文档，但项目边界仍保持独立；A12只通过版本化合同调用。
 C[6437] usermatches=0 direct=2386 PG-Frag 当前状态（2026-10-07）：固定裂面 virgin elastic bridge 与开口历史控制均为诊断 toy，未证明裂纹增长或碎片分离。12 状态轨迹中 step_index=0..7 均非全点损伤；step_index=6 的 D 范围为 0–1，step_index=7 为 2/3–1；仅 step_index=8..11（第 
 C[6438] usermatches=1 direct=2387 J1 两个项目的共同定位与设计原则
 C[6439] usermatches=2 direct=2388 两个子项目应从第一天起就按“可独立发布、可独立维护、可被第三方调用”的基础设施设计，而不是作为某个主项目内部的脚本集合。当前它们可以服务于上层项目，但 API、数据模型、任务定义、测试集和版本管理必须保持独立。
 C[6440] usermatches=1 direct=2389 J1.1 项目边界
NEAREST PREV: 6436 来源基线：VesselForge × PG-Frag 技术路线总纲 v1.1（2026-10-03）。以下内容已归并到RelicWeave主文档，但项目边界仍保持独立；A12只通过版本化合同调用。
NEAREST NEXT: 6438 J1 两个项目的共同定位与设计原则
 USER PREV indexes=[6633, 7046]
 USER NEXT indexes=[7047]