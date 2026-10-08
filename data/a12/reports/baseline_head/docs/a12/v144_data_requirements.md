# V1.44 合成数据需求规格（可执行版）

- 来源文档：`RelicWeave_V1.44_Optimized_Complete_Plan.docx`（546,163 字节）
- 抽取范围：**与"数据合成 / 下一批实验数据需求"有关的全部章节与表格**
- 产出用途：供后续批量产数据使用；本文只做"读文档 + 写规格"，**未修改任何代码或既有配置**
- 配套草案：`configs/a12/next_experiment.yaml`（待执行，schema `synlab.v3`）
- 抽取日期：本次会话；文档内所有数字均为**文档原文引用**，非本文推断

## 0. 文档规模、读法与标注约定

### 0.1 文档结构实测（python-docx 1.2.0 读取）

| 项目 | 实测值 |
|---|---|
| 段落数 | 1807 |
| 表格数（body 级 `w:tbl`） | **128**（全部读出，含合并单元格去重） |
| 标题总数 | **357** = Heading 1 × 79 + Heading 2 × 186 + `SYN Section` × 32 + `SYN Subsection` × 60 |
| 其它样式 | `Normal` 1003、`SYN Body` 241、`SYN Code` 130、`SYN Reference` 73、`Title`/`Subtitle`/`Caption` 各 1 |
| 读取失败项 | 无。128 个表格全部读出（表头行 + 全部数据行） |

**读法说明（重要）**：本文档**没有任何表格编号/题注**（全文正则 `表\s?\d+` / `Table\s?\d+` 命中 0 处）。
因此本文用 `T###` 作为**可复现定位符**：按 docx body 顺序给 128 个表格编号 T001–T128，
并同时给出**所属章节标题**（取该表之前最近的标题，含 `SYN Section`/`SYN Subsection` 样式）。
定位符可由脚本复现：按 body 顺序遍历 `w:p`/`w:tbl` 即可。**引用格式：`章节号 + T###`**。

### 0.2 完整标题清单（一级/二级，357 项摘要）

> 全文标题清单已按 docx 顺序检视；下表列出**与数据合成/数据需求相关度**的判定，
> 供说明"覆盖了哪些、忽略了哪些"。完整 357 项清单保存在抽取产物 `outline_full.txt`（见 §0.4）。

| 区块 | 标题范围 | 与数据合成需求的相关性 |
|---|---|---|
| 1–3 章 | 文档体系、阶段命名、当前事实台账、合并主线、内部指标合同、创新收敛 | **高**（指标分母、split 纪律、事实台账） |
| 4 章 / A1–A11 | 模型架构、输入合同、训练、循环机制、参考技术 | 中（输入白名单、质量/可见性合同） |
| **A12 + A12.1–A12.16** | 可控合成碎片实验室（长期维护区） | **最高**（数据合成主线） |
| 5 章 / B1–B13 | 数据采集与标注：B2 真值、B3 必采数据、B4 SOP、B6 字段、B7 划分、B8 验收、B9 3D | **高**（真实数据侧的同类合同、母体数与确认集门限） |
| 6 章 / C1–C15 | DIY 采集台软硬件、C3.2 分辨率、C5.1 灯态、C10.1 分辨率档 | 中（退化轴的真实标定来源） |
| 7 章 / D1–D12 | 前后端、D3 元数据账本、D4 API、D5 状态机 | 中（接口与字段） |
| 8–12 章 | 并行推进、8.4 工时与 GPU 日历、共享台账、交付计划、归位历史 | **高**（资源与工期门限） |
| 附录A/K/X01–X16 | 实验执行卡与历史结论 | 中（历史 FAIL/STOP 边界，不可改写） |
| 附录B/E01–E20、C1–C4 | 结论卡与历史记录 | 低（历史成绩，只读） |
| 附录D、E、F、参考来源 | 重建工程参考、修订映射、参考资料 | 低 |
| **附录G（G1–G32）** | 可控合成碎片实验室**完整实现方法** | **最高**（本文主要来源） |
| **附录H（H1–H7）** | V1.44 统一实施合同与问题验收索引 | **高**（合同命名、确认签收、24 项验收） |

### 0.3 抽取方法

1. 用 python-docx 遍历 `document.element.body` 的 `w:p` / `w:tbl`，**按 body 顺序**输出段落（含样式名）与表格（含合并单元格去重后的完整行列）；
2. 生成 `blocks.json` / `full.txt` / `outline_full.txt` / `table_map2.txt` 四份中间产物；
3. 全文检索关键词（母体、独立谱系数、碎片、观测、划分、种子、退化、释放、hash、parquet/zarr/npz/tar/GLB 等），再逐条回到原文段落核对；
4. 表格全部读出后与段落交叉验证，**表格与段落都覆盖**。

### 0.4 抽取产物（非交付物，仅审计用）

`%TEMP%\v144_extract\out\` 下：`blocks.json`、`full.txt`（3028 行）、`outline_full.txt`（357 行标题）、`table_map2.txt`（128 行表→章节映射）、`census.txt`/`probe2.txt`/`probe3.txt`（现状普查）。

### 0.5 标注约定

- 【文档】= 文档原文要求，附 `章节 + T###`
- 【推断】= 文档未直接写明、由本文推导，**不是文档要求**
- 【工程判断】= 基于本仓库实测资产/构建状态给出的工程结论
- 【实测】= 本次在 `relicweave-synlab` 上跑只读脚本得到的真实数字

---

## 1. 数据规模要求

### 1.1 规模层级与绝对数量（文档逐条引用）

| 层级/阶段 | 母体数 | 独立谱系数 | 接受片数 | 其它计数要求 | 出处 |
|---|---|---|---|---|---|
| SY0 规范冻结 | — | — | — | 冻结 schema、seed/provenance、关系定义、split | A12.13（T038） |
| **SY1 生成器 MVP（pilot）** | **约 100** | 与母体 1:1（见 §1.2） | **约 2000** | clean 与理想可见；人工抽检邻接/纹样连续/几何真值 | A12.13（T038）、A12.3、G4 |
| **1000 片精度与资源基准** | **约 50 冻结**（"先 10 母体探峰值"） | ≥50 | **目标 1000** | 覆盖薄壁空腔/高曲率/0.2mm 频带/四必做后端；记录全部尝试与失败 | G22.6 |
| G27 第 2 周 | **不少于 100** 母体种子 | — | — | 4 器型族封闭薄壳 + 母体表面场 | G27.1（T121） |
| G27 第 3 周 | — | — | **约 2000** 片闭环 | 全部 R2 自动核验 | G27.1（T121） |
| SY3 大规模生成 | — | — | **2 万–10 万以上**碎片 | 关系统计与难度分布 | A12.13（T038） |
| **SY-P1** | **约 5000** | — | **约 10 万** | 平均片数变化须重算母体、资源和工期 | A12.3 |
| **SY-P2** | **约 25000** | — | **约 50 万** | 同上 | A12.3 |
| E-SYN-01 真值与信号 | **固定 100** | — | — | 变输入模态与浅基线 | G21.1（T115） |
| E-SYN-03 数量曲线 | 嵌套子集 | — | **2000 / 1 万 / 5 万 / 10 万 / 50 万** | 同时给独立母体数、碎片数、关系曝光数、训练步数 | G21.1（T115） |
| 扩容闸门 | — | — | 100–2000 片修正确性 → 1 万片查覆盖与 P95 资源 → 十万片要求审计齐全 | 50 万片需独立收益证据与容量计划 | G27.3 |
| 完整 V1.0（L2） | **≥480**（24 器物 × ≥20 母体） | — | 约 1 万 | 24 器物 / 12 材料 / 4 层 / 16 纹样 / 4 必做后端 / 31 轴 / 基础 episode 全实现 | G1（"完整 V1.0 必须 L2"）、G28、G4 |

> **首版预算假设**（文档原文）："首版用 100 个母体、每母体 1 次主要碎裂、每次目标 20 片，
> 预算约 2000 片；片数是接受后的实际结果，不强行切到 20 片破坏形状。"（G4）
> "对相同母体做 5 次碎裂会扩大事件和碎片数，但独立母体数仍是 1，不能把它记为 5 个独立形状。"（G4）

### 1.2 计数口径：必须分列统计的 8 个量

【文档】G3 / G4 / A12.3 明确要求**分列统计、不得互相替代**：

| 序号 | 计数项 | 文档原文要点 |
|---|---|---|
| 1 | 独立母体数 | 重复碎裂/渲染**不增加**独立母体；同模型不同尺度/微扰归同一 `shape_lineage_id` |
| 2 | 谱系数（`shape_lineage`） | 尺度变化、纹样更换、微形变、二次破碎全部继承同一 lineage 并**同 split** |
| 3 | 事件数（`event_id`，碎裂事件） | 同母体多事件共享 lineage，不增加独立母体 |
| 4 | 片数（接受的叶子碎片） | 以**实际接受片数**为准，不强行切到目标片数 |
| 5 | 邻边数（R2 无向边） | 全部 R2 保留 |
| 6 | 观测数（observation） | 每片 × 视图数 × 退化档位；重复观测不当独立样本 |
| 7 | 关系曝光数（relation exposure） | 训练预算按 query / pair / candidate list / parent object **分层**统计 |
| 8 | episode 数 | 主动补采环境；类型数不是样本量 |

【文档】"10 万片本身不是最终规模指标；真正重要的是可以构造多少高质量关系和困难候选。"（A12.8）

### 1.3 训练 / 验证 / 确认划分比例

| 项 | 文档要求 | 出处 |
|---|---|---|
| 推荐比例 | **训练 80% / 开发验证 10% / 确认测试 10%** | G6.3 |
| 可调整性 | "数据不足时可改变比例，但**在发布前冻结**" | G6.3 |
| 冻结时机 | "**先冻结母体谱系划分**，再生成碎片、纹样、破裂事件和观测" | G6.3 |
| 最小隔离单位 | **parent object / shape_lineage_id**；同一父器物所有碎片和所有退化版本只能属于同一 split | A12.7、G6.3 |
| 额外留出（generator split） | 另设**器型族留出、纹样模板留出、碎裂后端留出、相机工况留出** | G6.3 |
| 背景与灯光 | "背景与灯光**不能只跟 split 绑定**，否则域变化与难度混杂" | G6.3 |
| 确认集纪律 | 开发集选参数；确认集**只运行预注册的最终比较**；确认前锁 `protocol_hash` | G6.3、H5 |
| 泄漏检查 | `leakage_audit` 门；训练/验证/确认**谱系交集为 0** | G28 H5 表（T122） |
| 真实数据侧 | 真实训练、真实验证、真实确认**各自独立** | G6.3、B7 |

### 1.4 每个器型 / 材料 / 纹样 / 层组合的最低覆盖

| 维度 | 完整规划（V1.0/L2） | 每类最低覆盖 | 首版范围（文档指定） | 出处 |
|---|---|---|---|---|
| 器物 | **24** 品种 | **每类 ≥20 个母体或独立实例**通过正向测试（⇒ ≥480 母体） | 碗 / 盘 / 罐 / 瓶先打通 | G4（T102）、G28、G7.4（T105） |
| 材料族 | **12** | 12 材料族均需能生成、能切碎、能应用适用退化并通过 GT 审计 | 粗陶 / 白瓷 / 釉面先打通 | G4（T102）、G7.5 |
| 层状组合 | **4**（L01 坯+釉、L02 坯+彩绘、L03 石质+涂层、L04 木基+涂饰） | 4 层组合可生成/可碎裂/可退化 | 支持空间材质场、层厚、交界和剥落 | G4（T102）、G7.5 |
| 纹样族 | **16** | **每类至少 20 个独立母体的样例**；样例可跨材质与形状交叉层，"不能只提交 16 张贴图" | 素面 / 环带 / 条纹 / 点阵 / 刻线 / 组合 | G8.3、G8.1（T107）、G4（T102） |
| 碎裂后端 | **5**（4 必做 + fracture-modes 可选） | **前 4 种必做**：平面基线 / 共享粗糙切割 / 形变 Voronoi / 二次破碎 | 前 4 种为必做；物理插件另验收 | G4（T102）、G10.4 |
| 退化轴 | **31**（实物 8 + 成像 10 + 重建 8 + 输入 5） | "pilot **每组先 2 轴**，完整全部实现" | SY-Q0、SY-Q2 及单证据移除 | G4（T102）、G16（T109） |
| 质量配置 | **6**（SY-Q0_OBS…SY-Q5） | G17 给出严格定义 | SY-Q0 / SY-Q2 及单证据移除 | G4（T102）、G17（T110） |
| 人工抽审 | — | **自动审计覆盖 100% 被接受资产**；人工抽审分层，**起步不少于 60 个母体** | — | G28 |

> 反捷径附加要求：【文档】"每个注册类别至少 20 个母体或独立实例通过正向测试，
> 复杂薄壁、空腔、重复纹样、高光、二次破碎和重磨损均有**失败样例**。"（G28）

### 1.5 多种子与多尺寸

| 要求 | 文档原文 | 出处 |
|---|---|---|
| 训练多种子 | "**三 seed 描述训练波动，不扩独立样本**"；"3 个训练 seed 不增加母体数" | A12.15、G21.2、EXP08 |
| 统计单位 | "**母体簇才是主要统计单位**"；性能差用**母体簇配对双侧 95% 区间**，片/视图/query/seed **整簇重采样** | A12.15、G21.2 |
| 退化配对种子 | 每轴预生成空间场/随机排序，用强度缩放、嵌套删除、带宽控制做阶梯；**共用同一 `basis_id`** | G17、G25.1 |
| 每样本 seed 派生 | `seed64(master_seed, shape_lineage_id, event_id, fragment_id, module, variant)`；**不用 Python 内建 hash、不用 worker 编号或全局 RNG 游标** | G25.1（含代码块） |
| 独立 seed | 不同模块独立 seed；"修改光照不会改变碎裂结果" | G25.1 |
| 随机性分层 | `shape / material / pattern / cut / damage / camera / light / sensor / geometry / sampler` 独立子流 | `docs/a12/data_contract.md` §7（仓库现行合同） |
| 多尺寸 | 首版物理尺寸候选 **最大尺寸 80–300 mm、正常壁厚 2–10 mm**；极薄壁与厚陶块作**独立 stress 层** | G7.1 |
| 多尺寸对计数的影响 | "平均片数变化须重算母体、资源和工期" | A12.3 |
| 器型参数外推 | "对象级 split 之外**再做参数外推审计**"；器型族留出 | A12.3（T029）、G6.3 |
| 多随机基底对照 | 后端比较须**固定母体族、材料外观、碎片尺寸区间、视角预算与模型预算** | G10.3 |

---

## 2. 数据内容要求

### 2.1 数据产品清单（G3 / T101，24 类 D01–D24）

| 编号 | 数据产品 | 格式与用途（文档原文） | 本次是否必须 |
|---|---|---|---|
| D01 | 完整母体几何与参数 | mesh 数组或 GLB + JSON；器型、尺寸、厚度与来源 | 必须 |
| D02 | 完整母体连续纹样与材质 | 纹理图及程序 recipe；含外壁、内壁和新断面材质 | 必须 |
| D03 | 干净碎片封闭实体 | float32/float64 mesh 数组；Q0 几何权威资产 | 必须 |
| D04 | 干净断裂面及对应 | 面片 ID、接触 patch、面积、采样对应与有效 mask | 必须 |
| D05 | 完整关系图与装配真值 | CSR 邻接或边表与 SE3；**仅 TruthPack 可读** | 必须 |
| D06 | 实物磨损与缺角后的实体 | PhysicalPack 或 recipe；保留损失比例与祖先对应 | 必须 |
| D07 | 整片多视角 RGB | JPEG 训练图及小型无损确认集；**不是实拍** | 必须 |
| D08 | 断口局部 RGB | 原帧 + ROI 坐标或 crop；与整片保持相机关系 | 必须 |
| D09 | 片体和区域分割 mask | PNG 或 RLE；内外壁、断面、支撑、无效区 | 必须 |
| D10 | 深度距离与可见性 | float32 或明确量化规则的 uint16；先区分相机 z 和光线距离 | 必须 |
| D11 | 观测法向与真值法向 | 数值数组；真值只作监督，输入法向由观测几何估计 | 必须 |
| D12 | 部分点云及颜色 | 分片 Zarr 或二进制数组；**观测空间而非完整表面采样** | 必须 |
| D13 | 退化后网格与洞 | 可选 mesh；保留 raw 版本，补洞版单独标记 | 必须 |
| D14 | 估计局部几何描述 | 厚度/曲率/边界描述加有效性；**只从可见观测计算** | 必须 |
| D15 | 相机标定与采集工况 | K、畸变、分辨率、镜头、灯光和扫描会话 | 必须 |
| D16 | 质量与覆盖数据 | 可观察质量输入 + **独立 oracle 诊断**；字段权限分离 | 必须 |
| D17 | R0/R1/R2 关系训练行 | Parquet；标签来源、难例类型、损失权重 | 必须 |
| D18 | 固定检索候选列表 | query 池和候选池 manifest；支持多个真邻片 | 必须 |
| D19 | 开放库与无邻片查询 | `pool_id` 与 `mate_present`；无邻片状态**相对于候选库** | 必须 |
| D20 | 配对单因素退化阶梯 | `counterfactual_group` 与 recipe；同片共享随机基底 | 必须 |
| D21 | 实际照片重建子集 | COLMAP 工程、重建点云 mesh 与误差报告 | 主张必需子集（约 20 母体/400 片，G15.3） |
| D22 | 可达动作与逐步观测 episode | action 日志、代价、观察索引、终止与奖励定义 | 必须（基础 episode） |
| D23 | 受限的模拟出土上下文 | 有缺失/冲突和噪声的字段；**不能等价母体 ID** | 扩展 |
| D24 | 反证和机制解释监督 | 哪条证据能排除候选及局部对应；**仅有可信构造时生成** | 扩展 |

【文档】"D01 至 20 及 D22 固定规则动作/成本/STOP 基础 episode 为核心；
D21 照片重建与实拍校准是主张代理接近实际扫描的**必需验证子集**。
未校准则标 `PROXY_SCAN` 压力测试。D23 上下文、D24 解释和学习型多步策略为扩展。"（G3）

### 2.2 模态清单

| 模态 | 数组形状/类型 | 空值与配套字段 | 出处 |
|---|---|---|---|
| RGB | `[H,W,3] uint8`（线性源单独 float32） | 缺视图用 `presence`；**不塞零图假装已拍摄** | G6.4（T104） |
| 区域 mask | `[H,W]` 整数（禁止有损压缩、禁止插值出小数类） | — | G6.4、G23.1 |
| points（点云） | `[N,3] float32` 局部 mm | `point_valid` 为 N；空模态可为 `[0,3]` | G6.4 |
| normals（法向） | `[N,3] float32` 观测估计单位法向 | `normal_valid` 为 N，另记估计邻域与误差 | G6.4 |
| K / pose | K `[3,3]`、T `[4,4]` float64/32 | 相机原始与 crop 后内参**分别存**；装配 pose 隔离 | G6.4 |
| depth | `[H,W] float32` 或定义 scale 的 uint16 | invalid mask 独立；无效值不参与 loss/反投影 | G6.4 |
| surface_samples | 面 ID + 重心坐标 + 局部坐标 | 来源 GT 与观测对应 valid 独立，**不能混入 feature** | G6.4 |
| relation | `int8` 枚举 `R0/R1/R2/UNKNOWN` | **UNKNOWN 通过 `loss_mask` 剔除，不编码成 R0** | G6.4 |
| quality | 每视图、每区域命名的 `float32` 向量 | 每项附 valid 及来源 `OBS_EST` 或 `GT_ORACLE` | G6.4 |
| 观测几何（可选） | 深度反投影 + 多帧合并的部分点云 | 三条路线：理想可见几何 / 代理扫描退化 / 实际照片重建 | G15.1（T108） |
| 特征 / 标签 / 溯源 | 三个**分开**的 asset | 禁止用字典合并制造泄漏 | `docs/a12/data_contract.md` §1 |

【文档】每个数组必须带 `unit`、`frame_id`、`dtype`、`shape`、`asset_hash` 与 schema 版本；
"训练数据不因 padding 把无效点算成零坐标有效点；masked pooling 和 attention 必须消费 valid。
缺失深度、未知材料或未证实上下文**保持缺失**，不从 TruthPack 回填。"（G6.4）

【文档】点密度起步：**整片 2048–8192 点，断口 ROI 另给独立 2048–8192 点**，并记录实际有效点数；
"不足时 valid mask 和点权重保持真实，**不重复填点伪装有效密度**"。（G15.2）

### 2.3 真值层（clean / physical / visible）——三层必须独立

| 层 | 角色名（仓库现行） | 冻结内容 | hash / 版本要求 |
|---|---|---|---|
| **CleanTruth** | `clean_truth` | 历史拓扑 + 几何对应（`clip_shared_interfaces_to_leaf_fragments` → `contacts_above_frozen_area_threshold` → `geometric_correspondences` → `audit_and_freeze`） | 每层**独立 hash**；版本不匹配**拒收** |
| **PhysicalTruth** | `physical_truth` | 裁剪损失材料与当前贴合（`surviving_contact_area`、`evidence_visible`、`current_fit_valid`、`damage_validity`） | 带 `physical_revision` |
| **ObservationLabels** | `visible_labels` | 按相机遮挡定可见对应；`damage→render→observe` 后逐 PhysicalPack/ObsPack **重算** | 带 `obs_revision`、`camera_profile`、`correspondence_version` |

【文档】"CleanTruth 冻结历史拓扑和几何对应；PhysicalTruth 裁剪损失材料及当前贴合；
ObservationLabels 按相机遮挡定可见对应。**每层独立 hash，版本不匹配拒收**。
`oracle R_AB` 只标签/审计，**推理不能读取**。"（G12.4）
"**clean finalize 不得预先生成 `visible_valid`**。"（G30.3）
"两侧都残留、可见且映射误差合格才进入对应 loss；GT 投影仅监督审计。"（G12.2）

### 2.4 关系标签：R2 / R1 / R0 / 灰区 / UNKNOWN

| 标签 | 定义（文档原文） | 生成规则 | 防捷径 |
|---|---|---|---|
| **R2** | "同一次 clean 碎裂事件内，两块**当前叶子碎片共享实际材料断裂面，且面积超过预注册的数值有效阈值**" | 允许 1 个 query 有多个真邻片 | "仅点接触、边接触、母体外表面距离近、同环带或同一器物都**不能**自动记 R2" |
| **R1** | "**同一母体且无直接共享断面**" | 从当前碎裂事件同母体的非邻片抽取 | "不能用 `object_id` 直接判断" |
| **R0** | "**不同物理母体**" | 参数邻近母体或外观向量相近 | "器型近似不能改成同器" |
| **灰区 / TINY_CONTACT** | "小于面积阈值的真实微小接触**单独标记 `TINY_CONTACT`**，而不悄悄改成 R1" | 建议阈值"从 **0.1 平方毫米**数值噪声排除线起步，真实小接触留在灰区"；同时设**绝对量 + 相对母体表面量** | "发布时保留原始面积、阈值和灰区记录" |
| **UNKNOWN** | "关系未确认" | "物理配对不能确认就标 UNKNOWN"；争议保留 UNKNOWN | "UNKNOWN **退出监督分母**"、"UNKNOWN **不转负例**" |
| mate-absent | `mate_present = 0`；"从 pool 移除该 query 全部 R2 邻片" | 必须**证明 query 相对于冻结图库的完整邻片集合闭合** | "无邻片单列风险" |

**附加硬约束**（G12.1 / G12.3 / 2.章）：

- 邻接**对称且不自邻接**；"A 邻 B 和 B 邻 C **不推出** A 邻 C"（不传递）
- 来自同母体**不同替代碎裂事件**的碎片**不混放进一次候选库**（重复占据材料 + 标签歧义）
- `prebreak_component`：器身与盖原本可接触但**并非共享新断裂面**，不能误标 R2
- 二次破碎必须**更新已有共享断面**：A 拆为 A1/A2 后需按新几何裁剪原 A–B 的接触 patch，重新计算 A1–B、A2–B 有效共享面积；"**不能把 A 的所有邻边复制给全部子片**"
- 磨损**不能事后删去历史正例**；`historical_R2` 与 `current_fit_valid` 分开保存
- "整片彻底删除则删除其观测实例，**不制造空碎片仍可拼合的标签**"

### 2.5 关系难例的组成要求

【文档】G18.2 难例八类（T111）+ 起步配额：

| 难例类型 | 生成方式 | 标签 |
|---|---|---|
| 同器非邻 | 同母体非邻片 | R1 |
| 相似器型异器 | 参数邻近母体/外观相近 | R0 |
| 重复纹样 | 同环带非邻片或异器同模板 | R1 或 R0 |
| 几何近似 | 厚度/曲率相近或局部面型近似 | R1 或 R0 |
| 单证据冲突 | 纹样支持但断口不支持，或相反 | 记录冲突来源 |
| 磨损真邻片 | 对 R2 的一个或两个观测做嵌套损伤 | 历史 R2 保留，当前对应有效性另标 |
| 多邻片查询 | 完整邻接图含多个 R2 | Hit 与 CovRecall 分别计算 |
| 库中无邻片 | 从 pool 移除该 query 全部 R2 | `mate_present = 0` |

**起步每 query 负例组成**："8 个 R1、6 个形态近似 R0、4 个纹样近似 R0、2 个普通 R0"（共 20 个）；
"缺某类时按**预注册回退规则**补足并记录实际组成"；（G18.2）
"每 query 正例数不同，**全 R2 尽量参与训练**；损失按 query 归一化或使用概率采样纠正"。

【文档】不物化全库两两组合：10 万片无序两两约 **50 亿条**，按 64 字节/条约 **320 GB**；
示例规划："10 万片若平均 clean 邻接度为 3，约有 **15 万条无向 R2 边**。
每 query 离线保留 20 个负例会得到约 **200 万负例行**"；"平均度 3 只是**预算假设**，
不作为数据集真实结构，**不能强行丢邻边达到这个数量**"。（G18.1）

---

## 3. 退化要求

### 3.1 31 条可独立控制的退化轴（G16 / T109）

**分组计数**：实物 P × 8、成像 I × 10、重建 G × 8、输入 X × 5 = **31**。"新增 G08 伪凸起/假面/伪连接。"

| 轴 | 变量与算法 | 起步控制范围 |
|---|---|---|
| P01 | 独立断面磨光，仅材料移除 | 半径 0–0.5 mm、厚度守卫 |
| P02 | 断口边缘磨圆（局部 SDF 或倒角） | 半径 0–0.8 mm |
| P03 | 坯体侵蚀（ROI 内材料移除） | 深度 0–0.5 mm |
| P04 | 缺角（椭球或噪声刀具体差集） | 接触面积损失 0–80% |
| P05 | 纹样脱落（嵌套空间 mask） | 原纹样残留 100–0% |
| P06 | 污垢覆盖（平滑表面场） | 覆盖 0–80% |
| P07 | 表面磨蚀（局部形变或侵蚀） | 深度按壁厚守卫 |
| P08 | 局部开裂或掉釉（几何与材质分开） | 面积 0–30% |
| I01 | 失焦（深度相关 PSF 或高斯基线） | 等效 sigma 0–4 像素 |
| I02 | 运动模糊（定向核） | 长度 0–15 像素 |
| I03 | 传感器噪声（Poisson 与读出噪声） | 线性空间 SNR 分层 |
| I04 | 曝光（停数增减与裁切） | 候选 −2 至 +2 EV |
| I05 | 白平衡与颜色偏移（通道增益） | 按真实工况校准 |
| I06 | 釉面高光（光源与 BRDF 改变） | 高光面积 0–40% |
| I07 | 支撑或遮挡（3D 遮挡体） | 目标面积 0–60% |
| I08 | 视图不足（嵌套删除轨道视角） | **12 / 8 / 4 / 2 / 1 帧** |
| I09 | 分辨率损失（先降采样再 resize） | 长边 **1024 / 768 / 512 / 256** |
| I10 | 编码压缩（JPEG 质量或块效应） | 质量 **95–40** |
| G01 | 深度误差（相关场加离群点） | RMS 0–1 mm 分层 |
| G02 | 点云稀疏（嵌套采样） | **8192–512 点** |
| G03 | 区域孔洞（表面或图像 mask） | 局部覆盖 100–20% |
| G04 | 多帧漂移（帧级 SE3 扰动） | 平移 0–2 mm、旋转 0–3° |
| G05 | 网格简化（ROI 约束 QEM） | 按几何误差预算 |
| G06 | 尺度漂移（标尺或重建比例误差） | 候选 0–5% |
| G07 | 标定误差（焦距/主点/畸变扰动） | f 误差 0–3%、主点 0–5 px |
| G08 | 观测伪凸起/假面/假桥；**Truth 不变** | 高 0–0.5 mm、半径 0.2–2 mm、数量 0–30/ROI |
| X01 | 缺模态（全局或局部模态失效） | 独立 Bernoulli 或固定移除 |
| X02 | 分割误差（边界膨胀腐蚀与缺块） | 边界 0–5 px |
| X03 | 上下文缺失或错误（字段级扰动） | 缺失和冲突 0–50% |
| X04 | 质量估计失准（估计器校准扰动） | 高估/低估/随机校准 |
| X05 | 跨工况错配（镜头光照域变换） | 留出预设工况 |

### 3.2 档位数量

| 项 | 文档要求 | 出处 |
|---|---|---|
| 每轴档数 | **五档**（含零强度） | G28（T122）"退化成功：每轴 5 档与共同随机基底"、§1.2 核心交付范围 |
| pilot 阶段轴数 | **每组先 2 轴**（P/I/G/X 各 2 ⇒ 8 轴） | G4（T102） |
| 零档语义 | "**level 0 必须对每条轴是真正的 identity**" | `configs/a12/physical_recipes.json` 说明行（仓库现行合同） |
| 强度记录 | "每条记录同时保存**输入强度和输出测量值**，操作者才能知道算子实际删掉了什么信息" | G16 |
| 单调性 | "仅**不可逆移除或嵌套删除**要求相应量单调；质量等级、粗糙度、成像和检索分数**不一律单调**" | A12.15、G13.3 |
| 异常曲线 | "保留异常曲线，**不挑 seed**" | G13.3 |

### 3.3 配对（固定 basis）要求

| 要求 | 文档原文 | 出处 |
|---|---|---|
| 配对前提 | 配对需要**相同母体、碎片、候选池、初始物理状态和随机基底** | G17 |
| 固定 basis | "五档强度**共用同一 `basis_id`**"；`basis_policy: paired_across_levels` | `docs/a12/data_contract.md` §7；`configs/a12/degrade_recipes/*.yaml` |
| 配对记号 | `counterfactual_group_id` + recipe；同片共享随机基底 | G17、D20（T101） |
| 单因素纪律 | "**单因素实验保留其余参数、视图与随机底噪不变**" | G16 |
| 联合工况 | "joint 退化**不得任意堆叠所有轴的最重级**"；先定义五类工况（手机失焦 / 釉面高光 / 视图不足 / 断口重磨损 / 重建漂移），工况内设置相关参数 | G16 |
| 算子顺序 | "按**固定顺序**执行物理损伤 → 可见性 → 线性成像退化 → 编码 → 重建 → 输入派生；顺序改变时**建立新的 recipe 版本**，不能用旧 cache 命名" | G17 |
| 确认集物化 | "对确认集将所有规定版本**物化、哈希并冻结**；训练集只永久保存高成本实体和少量基础帧，低成本模糊/丢点等按 recipe **在线生成**" | G17、A12.6 |
| G08 特殊性 | "只修改 observed mesh/depth/cloud，**Physical 与 CleanTruth hash 不变**"；强度 0 原样返回 | G16.1 |

### 3.4 轴的用途划分：训练 / 压力 / 留出

| 用途 | 轴/档 | 文档依据 |
|---|---|---|
| **训练课程** | SY-Q0_OBS（clean 理想可见）+ SY-Q1（轻成像/代理扰动）起步 → 再加 SY-Q2（实测校准中等工况）→ SY-Q3/Q4 → SY-Q5（指定证据移除） | A12.9、G20.3 |
| **课程对照** | 必须与**同数据同总 step 的随机混合**对照；不能把更多算力写成课程收益 | G20.3、A12.9 |
| **clean 守卫** | "同时保留 clean 守卫" | G20.3 |
| **压力测试** | "**未经真实校准的退化标 stress**"；G08 未实拍校准时称压力测试；`PROXY_SCAN` 未校准则标未校准候选 | A12.15、G16.1、G15.1 |
| **留出（不可用于训练/调参）** | 器型族留出、纹样模板留出、**碎裂后端留出**、相机工况留出（X05 用"留出预设工况"）；确认集不参与模拟器、超参、ROI 或校准选择 | G6.3、G10.3、G20.3、T109 X05 |
| **只作机制压力、不计独立物理轴** | `normal_noise` 与 `curvature_noise` 若直接施加在 clean 描述上，**只能作为机制压力测试**；部署式实验应先扰动观测几何再重算法向与曲率；它们由 G01–G05 派生误差报告，**不再重复计作新的独立物理退化轴** | G16 |
| **不增加 31 轴计数** | `DIAG_SHARED_LOWPASS` 共享低通"仅研究频带移除，**不能叫独立磨损或 P01 物理资格，不增加 31 轴计数**" | G13.5 |
| **模态消融（SY-Q5）** | "去除断口几何/断口 RGB/纹样/3D/上下文的分支"；"**不保证比 SY-Q4 更难**" | G17（T110） |
| **单独命名的四类"无断口"条件** | 断面高频已消失 / 断面整体几何仍在 / 断口视图完全缺失 / 原断面材料被毁掉——**分别命名配置** | G17 |

> 【文档】"完全没有可辨断口时……它们允许研究其它模态能否保住候选，
> 但**不能要求所有情况必然达到相同召回**。"（G17）

---

## 4. 格式与接口要求

### 4.1 文件格式（G23.1 / T117，按数据访问方式选择）

| 数据 | 推荐保存方式 | 具体策略（文档原文要点） |
|---|---|---|
| 真值与元数据 | **Parquet + JSON manifest** | Parquet 按 split 与有限 bucket 分区；ZSTD 起步，压缩等级实测 |
| 权威 mesh | 连续数组 + offset，或小规模二进制资产 | 顶点/索引/材质/面源**独立数组**；**PLY 或 GLB 仅导出和检查** |
| 数值观测 | **Zarr** 分块并按需 sharding | 点云/depth 等数值；**每 shard 一个写者**，避免多进程写重叠块 |
| RGB | 已编码 **JPEG + tar 分片** | 训练顺序读取 **512 MB–1 GB shard**；确认集保留规定无损版本 |
| mask | **RLE 或 PNG** | 整数 ID，**无有损压缩**；ROI 优先坐标按需 crop |
| 退化变体 | 基础资产 + recipe | 线上便宜增强；高成本损伤实体与固定测试物化 |
| 编码器特征 | 版本化数值 cache | 冻结 encoder 时复用；变化即失效，**不作为权威原始数据** |

补充粒度：Zarr 初始候选为"每次训练样本或小 batch 大小的 chunk、**64 至 256 MB shard**"；
"图像 tar 保留完整 sample 边界，索引支持随机评估；
**不再给已 JPEG 压缩的数据套外层 gzip** 损伤随机读取。"（G23.1）

### 4.2 数据包与最低字段（G6.1 / T103）

| 数据包 | 关键字段（文档原文） | 读取权限 |
|---|---|---|
| **MotherPack** | `shape_lineage_id parent_id family params unit material source hash` | 母体几何来源；`shape_lineage` 涵盖同模型缩放或微扰衍生 |
| **TruthPack** | `event_id fragments surfaces R2_edges transforms correspondence QA` | **仅标签生成监督和审计可读** |
| **PhysicalPack** | `fragment_id damage_recipe mesh hash survivor_map lost_volume` | 磨损后真实实体状态；**不覆盖 clean 真值** |
| **ObsPack** | `opaque_sample_id RGB mask camera optional_geometry quality validity` | 部署观测同义字段；**按白名单**向模型提供 |
| **RelationPack** | `query_id candidate_id R_label hard_type surface_gt valid loss_mask` | **模型不读取 `R_label` 和 `hard_type` 作为特征** |
| **EpisodePack** | `initial_obs action_space action_cost observations done reward_spec` | 奖励计算隔离隐藏 GT |

【文档】"ID 是**追踪字段而非预测特征**。模型输入以白名单构建，
并测试序列化字典内**不存在** `parent_id`、`surface_pair_id`、`truth_pose`、`generator_seed` 或关系标签。
`opaque_sample_id` 在数据加载器内**仅用于索引，不做嵌入，不编码文件名**。"（G6.1）

### 4.3 单位与坐标系

| 项 | 要求 | 出处 |
|---|---|---|
| 权威几何单位 | **毫米（mm）**，右手坐标系 | G6.2 |
| 渲染端 | 可转为米，但**转化比例必须显式写入** | G6.2 |
| 局部归一化 | 模型可用，但**同时保存尺度和"尺度是否可观察"的 valid 标记** | G6.2 |
| 真实照片 | "**未经标尺推得的真实照片不可假定具有绝对毫米尺寸**" | G6.2 |
| 变换约定 | `T_AB` 把 **B 坐标转换到 A 坐标**；W 装配世界 / F 碎片局部 / S 随机扫描 / C 相机 | G6.2 |
| 模型可见几何 | **只有 S 空间或观测局部 F 空间**；`T_WF` 与跨碎片装配相对变换**只存 TruthPack** | G6.2 |
| 扫描姿态 | 每片**独立随机**；旋转从单位四元数或正规旋转群采样，**不用带偏差的三轴欧拉角均匀抽样** | G6.2 |
| 相机约定 | OpenCV：x 向右、y 向下、z 向前；**Blender 相机须经显式轴变换转换** | G6.2 |
| 投影回环 | 三维标定点→像素→深度反投影→回原点，检查像素和毫米误差 | G6.2 |
| crop/resize | 须**同步更新 K、ROI 与 mask**；"不允许只裁图而沿用原 cx、cy" | G6.2 |
| 深度语义 | 明确区分**相机 z 与光线距离**；`r != z` | G6.4、`docs/a12/data_contract.md` §2 |

### 4.4 hash / 版本 / provenance 要求

| 项 | 要求 | 出处 |
|---|---|---|
| 可复现 recipe | 记录 `schema_version code_commit asset_hash`、各模块 seed、参数单位、`operator_order`、后端版本与输出哈希 | G6.1 |
| 每步可重建 | 每步保存 `generator_version`、`random_seed`、父对象参数和变换历史 | A12.2 |
| 三层独立 hash | CleanTruth / PhysicalTruth / ObservationLabels **每层独立 hash，版本不匹配拒收** | G12.4 |
| 缓存键 | 含输入 asset hash、schema 版本、算子顺序、各模块 seed、参数与后端版本；**编码特征另含 encoder hash** | G25.1 |
| 训练缓存命名 | 按 `generator_version`、`asset_hash`、`degradation_seed`、`encoder_version` 命名 | A12.14 |
| 配置序列化 | "配置 JSON **按规范字段排序序列化**，浮点和单位有明确规范，**不直接拿未规范化的 YAML 原文**作为等价参数判断" | G25.1 |
| 重放三级 | "分别定义**配方可重放、几何在容差内相同、像素逐位相同**三个层级" | G25.2 |
| 确认集 | "固定测试**一律物化后哈希冻结**，不靠未来同 seed 跨机器重新渲染就声称确认集完全相同" | G25.2 |
| 哈希清单 | 每次运行交付 spec、data 及 split manifest、环境、config、权重、逐查询预测、母体指标、配对区间、成本、失败清单和 `hash_manifest` | A9 |
| 泄漏审计 | 覆盖 `ROI、融合、质量估计、候选过滤与检索全部阶段`，不只 forward | `docs/a12/data_contract.md` §4 |

### 4.5 release 与 split 冻结要求

| 项 | 要求 | 出处 |
|---|---|---|
| release 目录 | `releases/SYN-0001/`：`release.json`、`manifest.parquet`、`hashes.json`，下含 `truth/ mothers/ fragments/ observations/rgb/ observations/arrays/ recipes/ relations/ pools/ episodes/ qa/ provenance/ splits/` | G23.3 |
| 不可变层 | 母体、clean 碎裂、真值、发布配置、确认资产和 hash **不可变** | G23.3 |
| 只读性 | `mutable_release: false`（`Literal[False]`，schema 级约束） | `synlab/schemas/spec.py` |
| 准入门 | "**只允许 audit 通过的 `COMMITTED` 资产进入 release**" | G30.4 |
| 提交状态机 | `PENDING → RUNNING → OUTPUT_READY → QA_PASS → COMMITTED`；失败为 `RETRYABLE` 或 `QUARANTINED`；**COMMITTED 是读取器可见的唯一完成状态** | G25.2 |
| 提交顺序 | 临时文件 → flush/fsync → 数量/长度/hash 校验 → **原子 rename** → **单写者事务**提交 manifest | G25.2、`data_contract.md` §6 |
| 训练可见性 | "**未提交 shard 不被训练读取**"；"训练打开的 shard 不得被驱逐" | G25.2、G23.3 |
| split 冻结 | split 先冻结再生成；确认集**启封前**锁 `protocol_hash`（GT 闭合、谱系划分、图库 query 列表、原图、ROI 来源、模型 encoder、M/K、校准阈值、U 镜头能力、动作成本、主指标、gain、clean_guard、样本数、失败去向和 stop） | G6.3、H5 |
| 只启封一次 | "新母体确认集**只启封一次**"；"启封后调参**记录为开发**，下一主结论用新未见母体" | EXP08、G21.4 |
| 磁盘阈值 | **70% 预警 / 80% 限制新重任务 / 90% 停新任务** | A12.14、G23.3 |
| 失败不静默 | "**失败不能静默跳过**"；"超内存先限流/降并发，**不能静默降精度计成功**" | G1（T099）、G22.6 |

### 4.6 数值精度与量化（G24 / T119）

| 对象 | 方案 | 准入检查 |
|---|---|---|
| 权威几何 | **不直接采用全局 float16 毫米坐标**；推荐权威顶点 **float32**，布尔与审计在需要时用 **float64**；量化版本作**独立训练副本** | float16 在数百毫米位置量化间隔可达约 0.125–0.25 mm，"足以删除断口微细信息" |
| 局部坐标 | bbox + **uint16 可逆解码** | 误差约受每轴跨度 ÷65535 限制；检查断口最大误差 |
| 法向 | int16 或八面体编码 | 重归一化、角度误差；"不能量化后仍直接用旧曲率" |
| 深度 | 毫米 scale + uint16 或 float32 压缩 | 需声明范围、无效码与单位；"**16 位 PNG 不自动等于正确深度**" |
| 颜色 | RGB 训练 JPEG，确认集无损 | 对高频纹样与颜色校准逐层比较 |
| 拓扑索引 | 顶点数允许时 uint16，否则 uint32 | 溢出检查、共享表面源和面 ID 映射 |
| 关系与 mask | 稀疏 CSR / RLE / 字典编码 | 结构和值逐项可恢复；**不改关系标签** |

误差预算示例（文档算式）：每轴跨度 200 mm 的 uint16 网格步长约 **0.0031 mm**，
四舍五入每轴误差不超过约 **0.0016 mm**；
"clean 接触面偏差目标 **0.02 mm** 时，坐标量化最大误差候选上限取该预算的**五分之一即 0.004 mm**"；
不满足则保持 float32 或局部更细编码。**任何压缩实验都同时比较几何误差、局部对应和候选检索保留率。**（G24）

### 4.7 工程验收阈值（G28 / T122，工程门，非研究门）

| 检查 | 候选通过条件 |
|---|---|
| 功能完整 | 24 器物 / 12 材料 / 4 层 / 16 纹样 / 31 轴 / 基础 episode |
| 碎裂完整 | 4 个必做后端与二次破碎样例，均输出实体、断面、邻接、对应与谱系 |
| 几何有效 | 水密、正体积、无自交、无未解释退化面 |
| 体积守恒 | clean 所有片 + debris 对母体：相对误差候选 **< 0.1%**；tiny 去向有记录 |
| 无重叠 | 非共享数值边界的重叠候选 **< 母体体积 0.01%** |
| 共享面互补 | **候选 P95 距离 < 0.02 mm；互补法向中位 < 2 度** |
| 关系图 | R2 对称、无自环、无空腔假邻、无二次破碎复制错误 |
| 对应有效 | 候选 **< 0.5 px**；损失/不可见/伪面不造对应 |
| 纹样与层 | 与母体场一致；断面不继承器表彩绘 |
| 退化成功 | 每轴 **5 档**与共同随机基底；声明量实测；移除或嵌套删除的量单调 |
| 不泄漏 | 无 GT、seed、parent、`truth_pose`；pureBG 不带轮廓 |
| 划分隔离 | 训练/验证/确认**谱系交集为 0** |
| 可恢复 | 不同阶段强制退出重跑：无重复提交、无丢失成功项、无残缺被读取 |
| 预算可控 | 1000 片实测及预估误差；超内存/超空间自动限流；记录 P50 与 P95 |
| 压缩保真 | 原版与压缩版配对检查，符合预设几何和下游保留预算 |
| 可用训练 | 浅基线读取与有邻/无邻两种池；指标可复算；不以高分替代 GT 和 split 正确 |

### 4.8 下游接口（ObsPackAdapter）

【文档】"实现 `ObsPackAdapter`，将 D07–D16 转换为原文 A3 输入合同：
`global RGB`、`fracture RGB`、可选几何、可观察质量、`presence` 与 `validity`。
**合成标志写入 provenance 用于报告；不把 `source_domain` 直接用于猜关系。**
训练需要的 GT 在**独立 label 字典**，不与 feature 字典拼接。"（G20.1）

模块接口合同（G30.2）：
```
create_mother(spec, seed) -> MotherPack
fracture(mother, spec, seed) -> FragmentSet, TruthPack
damage(fragment, recipe, seed) -> PhysicalPack
render(physical, camera_spec, seed) -> FramePack
observe(frames, recipe, seed) -> ObsPack
build_relations(truth, obs, pool_spec) -> RelationPack
build_episodes(obs_library, action_spec) -> EpisodePack
audit(pack, contract) -> QAReport
commit(job_id, assets, qa) -> ManifestRecord
export_release(manifest, adapter) -> DatasetRelease
```

---

## 5. 下一批实验的具体目标与数字门限

> 文档中**被点名**的"下一步 / 第一阶段 / 首要验证 / 首版"共 6 处，逐条原样引用。

### 5.1 候选目标清单（文档原文点名）

| # | 文档点名位置 | 原文目标 | **数字门限** |
|---|---|---|---|
| 1 | **A12.13 SY1 生成器 MVP** | "参数化器型 + 连续纹样 + 程序碎裂 + 精确邻接图" | **约 100 母体 / 2000 片**；clean 与理想可见；进门条件：人工抽检邻接/纹样连续/几何真值正确 |
| 2 | **G22.6 1000 片精度与资源基准** | "冻结约 50 独立母体、目标 1000 接受片……**先 10 母体探峰值**" | **50 母体 / 1000 片**；覆盖薄壁空腔、高曲率、**0.2 mm 频带**、四必做后端；全部尝试与失败记录 |
| 3 | **G27.1 第 2–3 周** | 第 2 周：4 器型族封闭薄壳 + 母体表面场；第 3 周：平面与共享粗糙切割 + GT 对应 | 第 2 周"**不少于 100 母体种子**"；第 3 周"**约 2000 片闭环**，全部 R2 自动核验" |
| 4 | **G21.4 功效起点** | "8 至 12 pilot 母体测流程及簇方差；30 至 50 开发、**至少 20 确认**只是起点" | **8–12 pilot 母体**；**30–50 开发母体**；**≥20 确认母体**；固定 1 个主机制、默认**母体宏 Cov@10**、**3 个百分点**最小有意义增益候选 |
| 5 | **B2.2 真实数据侧同构门限** | "第一批目标为 8 至 12 个可得独立母体作为资格试点……方法开发逐步扩到 30 至 50 母体，独立确认另留**至少 20 母体**作为规划起点" | **8–12 / 30–50 / ≥20**（明确"这些数目**不是统计功效保证**"） |
| 6 | **G15.3 实际 MVS 子集** | "先从**约 20 母体 / 400 片**清单分层冻结素面、釉面、薄片、近摄、支撑遮挡代表片" | **20 母体 / 400 片**；每片 **30–120 重叠帧**是起点（"不把 12 帧训练预算当 MVS 保证"） |

### 5.2 风险与统计门限（下一批必须遵守）

| 门限 | 数值 | 出处 |
|---|---|---|
| 零事件单侧 95% 精确上界 | `1 − 0.05^(1/n)`：**n=20 → 约 13.9%；n=29 → 约 9.8%** | G21.4 |
| 风险门 | "风险 ≤10% 须**真实单侧上界过门**且有邻片接受覆盖达预注册门，**不靠全拒绝**" | G21.4 |
| 20 母体零误荐 | "**20 母体零误荐的单侧上界仍约 13.9%，不能自动过 10% 门**" | H5 |
| 性能区间 | 母体簇**配对双侧 95%** 差值区间判方向，并通过冻结 `gain` / `clean_guard` | G21.4 |
| 三 seed | 在**簇内合并**，而非扩 n | G21.4 |
| 主指标 | 默认**母体宏 Cov@10**；最小有意义增益候选 **3 个百分点** | G21.4 |
| 完整分母 | `CovRecall` 分母为**冻结全图库 N_G 的全部历史真邻片**，不按初检或证据可见筛掉；拒识仍在主分母 | G21.2 |
| 校验不足 | "样本或覆盖不足 **NOT_ESTABLISHED**" | H5 |
| 多重比较 | 每确认批**一个主比较**；少量预定次比较用 Holm 等校正或新确认集 | G21.4 |

### 5.3 资源与工期门限

| 项 | 数值 | 出处 |
|---|---|---|
| 六周合成人时 | **48 人时**（四人每周 8h）；六周总额 288 人时 | 8.4（T069） |
| 十二工作周 | **576 人时** = 完整实现及验收 **480** + 维护 **96** | 8.4 |
| GPU 日历（完整版阶段/周） | 主要训练 24h、确认回归 8h、**合成渲染 40h**、MVS profiling 8h、重试缓冲 8h，合计 **88h/周**候选 | 8.4（T071） |
| 渲染工时算式 | 10 万片 × 12 视图 = **120 万帧**；**0.5 s/帧 ≈ 167 GPU 小时**，**2 s/帧 ≈ 667 GPU 小时**（"仅算式示例，未含几何、IO 及重试"） | G22.5、G22.6 |
| 校准要求 | "应先做 **1000 片 profiling**，再选择缓存视图数和分辨率"；"**不得写成 5090 已达到对应速度**" | G22.5 |
| 存储账（10 万片示例） | 基础权威与观测小计 **约 362 GB**；加热缓存 150 + 临时 120 + checkpoint 80 = 350 GB；运行总预算 **约 855 GB** | G23.2（T118） |
| 深度全量代价 | "全部 120 万帧都保存 1024 方形 float32 深度，仅 depth 就约 **5 TB**" | G23.2 |
| 50 万片 | "仅基础 RGB 约 **900 GB**……**不能简单在 2TB 盘上保存同等视图全模态**" | G23.2 |
| 单机资源起步 | 几何 CPU worker 2–4；GPU 显存目标峰值 **24–26 GB**；进程 RSS 总目标约 **30 GB**；热缓存初始 **100–150 GB** | G22.1（T116） |

---

## 6. 差距分析：需求 vs 现状（真实数字）

> 现状数据来源（全部为本次**只读**脚本实测）：
> `data/a12/metadata.sqlite`、`data/a12_demo/demo_manifest.json`、
> `data/a12_exports/closed_loop/store/metadata.sqlite`（含 5 个冻结 release 的 `manifest.json`）、
> `data/` 目录文件清单、`docs/a12/registry.json`。

### 6.1 数据库与 manifest 总体实测

| 数据源 | 实测数字 |
|---|---|
| `data/a12/metadata.sqlite` `assets` | **247** 行 |
| `data/a12/metadata.sqlite` `runs` / `jobs` / `releases` / `events` | **9 / 4 / 0 / 356** |
| `data/a12_demo/demo_manifest.json` | `entries` = **40**（`by_kind`：mother 8、pattern 8、fracture 8、degrade_source 4、degrade 12）；`total` = OK 36 / BLOCKED 2 / FAILED 2；`runs` = 20；`axis_catalog` = 31 |
| `data/a12_exports/closed_loop/store/metadata.sqlite` `assets` | **175** 行（`runs` 7） |
| 冻结 release（`…/closed_loop/store/releases/`） | **5** 个：`rel_8049cf187288…`(95 资产)、`rel_fda083aa68a8…`(113)、`rel_b06f9f7e9508…`(139)、`rel_852ab2a1e4c3_1790880811`(165)、`rel_852ab2a1e4c3_1790905541`(165) |
| 最新冻结 release 覆盖 | `fragment_assets_in_scope: 42`、`mother_mesh: 21`、`vessels: [V01,V02,V13]`、`materials: [M01]`、**`r2_relations_in_scope: 0`**、`closure.files_checked: 165 / ok: true` |
| 最新 release 门状态 | **37 个门：PASS 12 / PENDING 25** |
| PASS 的门 | `coordinate_contract, core_ui_api, fixture_contract, fracture_operator_runs, loader_index_runnable, observation_operator_runs, operators_used_pass, read_recovery, readonly_commit, resource_profile, source_map, train_dev_lineage` |
| PENDING 的关键门 | `coverage_24_vessels, coverage_12_materials, coverage_16_patterns, coverage_4_layers, coverage_4_backends, coverage_31_axes, accepted_nested_10k/50k/100k, l2_qualification, relations_complete, leakage_audit, frozen_protocol, confirmation_complete, risk_calibration, training_runs, real_capture_dataset, phone_rgb_mvs, mvs_subset_real_run, proxy_calibration, capture_profile, mask_source, scale_source, legal_inputs, references_loadable, operators_used_pass*` |

### 6.2 `data/a12` 主库资产结构（247）

| 维度 | 实测分布 |
|---|---|
| 按 `role` | `obs_view` 48、`obs_fused_geometry` 32、`fragment_mesh` 24、`physical_component` 20、`degrade_measurement` 20、`mother_mesh` 13、`feature_bundle` 12、`label_bundle` 12、`provenance` 12、`pattern_channels` 10、`pattern_recipe` 10、`clean_truth` 8、`physical_truth` 8、`visible_labels` 8、`material_profile` 4、`obs_result` 4、`qa_report` 2 |
| 按 `split` | `train` 204、`dev` 29、`audit` 12、`NULL` 2 → **`confirm` = 0** |
| 按 `qa_status` | `QA_PENDING` 128、`QA_PASS` 111、`QA_FAIL` 8 |
| 按 `lineage_id`（去重 12） | **`audit_lineage` 116**、`LIN0000_V01_M01_PAT01` 30、`LIN0001_V02_M01_PAT01` 29、`LIN0002_V13_M01_PAT01` 29、`LIN0003_V01_M04_PAT01` 29、`pattern_audit_PAT01…PAT06` 各 2、`NULL` 2 |
| 真实母体（`meta.mother_id` 去重） | **5**：`LIN0000_V01_M01_PAT01`、`LIN0001_V02_M01_PAT01`、`LIN0002_V13_M01_PAT01`、`LIN0003_V01_M04_PAT01`、`V01-M01-101` |
| 真实碎裂事件（`event_id` 去重） | **4** |
| 碎片 / 组件（`fragment_id` / `component_id` 去重） | **8 / 5** |
| 器型覆盖 | **V01、V02、V13**（3 / 24） |
| 材料覆盖 | **M01、M04**（2 / 12） |
| 纹样覆盖 | **PAT01–PAT06**（6 / 16） |
| 层组合 | 目录中无 `layer_combo` 维度字段的独立覆盖统计（【推断】按 `material_profile.layer_ids` 仅见 `[1]`） |
| 输入档/路线 | 仅 `SENSOR_PROXY` / `proxy_scan`（16 条） |
| 关系标签（`relations[].kind`） | **`R2` 8、`UNKNOWN` 8**；无 R1 / R0 / 灰区计数 |
| `r2_count` 分布 | `{0: 20, 1: 16}` |
| `mate_present` | `{None: 16, False: 20}` → **无 `true`（无 mate-present 查询）** |
| 资产 meta 出现过的 `axis_id` | **28 个**（P02 / P04 / P08 未出现） |
| `degrade_measurement` 资产 | 20（配对 basis 记录） |
| 独立 `basis_id`（去重） | 27 |

### 6.3 `data/a12_demo`（40 条 manifest）实测

| 维度 | 实测 |
|---|---|
| entries | **40**：mother 8 / pattern 8 / fracture 8 / degrade_source 4 / degrade 12 |
| 状态 | OK 36、BLOCKED 2、FAILED 2 |
| 母体 | **8**（V01,V02,V03,V04,V06,V07,V13,V18），**全部 M03** |
| 纹样 | 8（每一母体一条 `pattern_recipe`） |
| 碎裂 | 8 次尝试：`plane_shared_cut` OK ×3、`secondary_fracture` OK ×1、`rough_shared_cut` **FAILED ×2**、`warped_partition` **BLOCKED**、`fracture_modes` **BLOCKED** |
| 后端注册状态 | `plane_shared_cut` IMPLEMENTED、`rough_shared_cut` IMPLEMENTED、`secondary_fracture` IMPLEMENTED、`warped_partition` **PENDING**、`fracture_modes` **MISSING** |
| 已生成轴 | **12**：`G03,G05,G08,I01,I03,I09,I10,P03,P05,P06,X01,X04`（`axis_catalog` 31 项中 `generated=true` 者） |
| 未生成轴 | **19**：其余全部（含 P01,P02,P04,P07,P08,I02,I04,I05,I06,I07,I08,G01,G02,G04,G06,G07,X02,X03,X05） |
| 单元素实测耗时 | mother 均值 **1.43 s**（0.71–2.27）；pattern 均值 **8.36 s**（2.11–14.91）；fracture 均值 **28.28 s**（0.57–117.30）；degrade_source 均值 **1.77 s**；degrade 均值 **6.47 s**（1.79–50.36） |
| 环境结论（manifest 原文） | ① `rough_shared_cut` 在默认 **0.01 mm** 预算下报 `PRECISION_NOT_REALIZED`，实测 `realized_error_mm ≈ 0.2260`；② 本机**没有 Blender/bpy**，渲染只有软件光栅器（`capability_probe()` 实报 `blender` 不可用）；③ **仓库没有任何真实实物数据**（`data_scope=SYNTHETIC`）；④ `observe` 在 `hole_count=2` 时 `_carve_holes` 抛 `IndexError`（示例改 `hole_count=0` 绕过，**未修复**） |

### 6.4 文件格式实测（`data/a12` + `data/a12_demo` + `data/a12_exports/closed_loop`）

| 扩展名 | 文件数 | 合计 |
|---|---|---|
| `.json` | 890 | 150.24 MB |
| `.npz` | 454 | 417.69 MB |
| `.bin` | 330 | 20.69 MB |
| `.npy` | 104 | 9.72 MB |
| `.png` | 92 | 18.95 MB |
| `.exr` | 48 | 1.61 MB |
| `.ply` | 17 | 0.01 MB |
| `.parquet` | **9** | 0.30 MB |
| `.tar` | **1** | 2.27 MB |
| `.db` / `.sqlite` / `-wal` / `-shm` | 21 | 20.83 MB |
| `.glb` / `.zarr` / `.jpeg` / `.jpg` | **0** | — |
| **合计** | — | **643.11 MB** |

### 6.5 逐条对照表（需求 / 现状 / 缺口 / 满足方式）

| # | 需求（文档） | 现状（实测） | 缺口 | 满足方式 |
|---|---|---|---|---|
| 1 | pilot **约 100 独立母体**（A12.13 SY1、G4、G27 第 2 周） | **5** 个真实母体（4 个 `LIN000x` + 1 个 pattern-audit 母体） | **−95** | 用 `configs/a12/next_experiment.yaml` 跑 `target_mothers: 100`；需先过 doctor 与 10 母体峰值探针 |
| 2 | **1000 片基准 / 约 50 母体**（G22.6） | 最新冻结 release `fragment_assets_in_scope: 42`；主库 `fragment_mesh` 24 | **−958 片** | 同一配置跑到第 50 母体即得 1000 片检查点；须补 P50/P95 与 RSS/VRAM 分段报告 |
| 3 | **约 2000 接受片**（SY1 / G27 第 3 周） | 24 `fragment_mesh`（含 dev/train），**接受片远不足** | **−1976** | 提高 `target_piece_range` 至 [12,28] 并接受失败重试；失败必须留在分母 |
| 4 | **confirm split = 10%** 且启封前冻结（G6.3、H5） | `split` 只有 train/dev/audit，**`confirm` = 0**；release 门 `confirmation_complete: PENDING`、`frozen_protocol: PENDING` | 缺整个确认集与 `protocol_hash` | 生成时按 80/10/10 划分；确认资产**物化 + 哈希冻结**；保管者独立于调参 |
| 5 | 每类 **≥20 母体**：24 器物（⇒≥480）/ 16 纹样 / 12 材料（G28、G8.3） | 器物 3/24、材料 2/12、纹样 6/16；层组合与后端覆盖门全部 PENDING | 完整覆盖门**不可能**在 100 母体内达成 | 100 母体 pilot 只做**集成/资格**；完整覆盖需**≥480 母体**的第二批（见 §7） |
| 6 | **四必做碎裂后端**（G4、G10.4） | 实现 3 个；`warped_partition` **PENDING**、`fracture_modes` **MISSING**；`coverage_4_backends: PENDING` | 缺形变 Voronoi/Power（Gmsh 共形网格）与 fracture-modes | 需实现 `warped_partition`（G10.4：Gmsh 共形四面体 + 共享位移）；`fracture_modes` 属可选但受许可约束 |
| 7 | **31 轴 × 5 档**（G16、G28） | 注册表层面 **31 轴全部 `IMPLEMENTED`**（本次 `synlab validate` 实测）；但 demo 只有 **12 轴** `generated=true`；主库资产 meta 出现 **28 个** `axis_id`；release 门 `coverage_31_axes: PENDING` | 缺 19 轴在真实母体上的**物化/审计**（注册 ≠ 已产出），以及全部轴的 **5 档阶梯**（现状 level 只有 1–4） | 按 G4"pilot 每组先 2 轴"先补 P/I/G/X 各 2 轴共 8 轴的**五档配对阶梯**；再逐组扩满 |
| 8 | 配对退化 recipe，**`basis_policy: paired_across_levels`**（G17） | 只有 **2** 个 paired recipe 文件：`paired_plane_levels.yaml`（P03 L2）、`paired_edgewear_blur_bump.yaml`（P02 L2 + I01 L1 + G08 L2） | 覆盖 **P02/P03/I01/G08 共 4 轴**；缺 I、G 第二轴与 **X 组全部** | 需新增 paired recipe 文件（**本次写入范围不允许**，见 §7 必须项） |
| 9 | 模态齐全：RGB / mask / depth / normal / 点云 / ROI / quality / 相机（G6.4、D07–D16） | `obs_view` 48、`obs_fused_geometry` 32、`obs_result` 4、`feature_bundle` 12、`label_bundle` 12；`.png` 92、`.exr` 48、`.npy` 104 | 缺**断口局部 RGB（D08）**、**深度（D10）**的成规模物化、**mask（D09）**独立资产、**D15 相机标定资产**、**D16 质量+oracle 分离资产** | 由 `next_experiment.yaml` 的 `observation` 块产生；`persist_depth: selected_qa_only` 与 G23.2 一致 |
| 10 | 三层真值 clean / physical / visible **各层独立 hash**（G12.4） | 三层都存在但各仅 **8** 条（closed_loop 各 9 条）；`truth_incomplete` 字段存在 | 数量严重不足；`r2_relations_in_scope: 0` ⇒ **无 R2 正例** | 生成批次需产出三层并冻结；必须出现 `r2_count > 0` 的 query |
| 11 | 关系标签 R2/R1/R0/灰区/UNKNOWN **齐全**（G12.1、G18.2） | 实测只有 `R2` 8 与 `UNKNOWN` 8；**无 R1、无 R0、无灰区 `TINY_CONTACT`**；`relations_complete: PENDING` | 缺 R1、R0、灰区；缺 open-set pool 的 mate-present / mate-absent 两类 | 需 `relation_pool` + `query_roster` 覆盖两类池；GT 闭合 manifest 独立复核 |
| 12 | 开放库 `pool_id` + `mate_present` **两类都要有**（G18.3、D19） | `mate_present` 只有 `{None, False}`，**无 true** | 无 mate-present 查询 ⇒ 主指标分母为空 | 生成 pool 时必须包含有邻片的 query |
| 13 | 格式：真值/元数据 **Parquet**、数值观测 **Zarr**、RGB **JPEG + tar 分片**、mask **RLE/PNG**（G23.1） | `.parquet` **9** 个（0.30 MB）；**无 `.zarr`**；**无 `.jpeg/.jpg`**；`.tar` **1** 个（2.27 MB）；图像主要是 `.png`/`.exr`；`.npz` 454 个 | Zarr 与 JPEG+tar 分片**完全缺失**；Parquet 覆盖极薄 | 导出层需按 G23.1 落地；`shard_target_mb` 已有配置位（512） |
| 14 | 每轴 **5 档**、零档为真 identity、单调性检查（G28、G13.3） | 主库 `level` 分布 `{1: 33, 2: 29, 3: 29, 4: 29}` → **只有 1–4 档，无 level 0 资产** | 缺 level 0 基线；缺逐轴单调性报告 | 每轴补 level 0（identity，原样返回）并输出逐轴测量表 |
| 15 | **views = 12 / 长边 1024**（G14.1、G30.1） | closed_loop 配置为 **4 视图 / 256 px**；demo 渲染为 **320×240**（且只有软件光栅器） | 视图数与分辨率不足；**无 Blender 无法验收 1024 px 质量** | 需补 Blender/bpy 或显式发布 `precision_profile`；`renderer: auto` 会在无 Blender 时退回光栅器 |
| 16 | 点云 **8192 点**起步（G15.2、G30.1） | closed_loop 为 **2048 点**；主库 `point_cloud__n_points` 实测 **5822** | 未达 8192（但 5822 属 2048–8192 起步区间内，**不构成违规**） | 配置设 `point_count: 8192`，与 G30.1 一致 |
| 17 | 共享面互补 **P95 < 0.02 mm、法向中位 < 2°**（G28） | `rough_shared_cut` 在 **0.01 mm** 请求下实测 `realized_error_mm ≈ 0.2260`，demo 2 次 `PRECISION_BUDGET_EXCEEDED` | **精度门未达成**；`precision_profile` 未发布 | 三选一：提高分块/cell 预算；换 `plane_shared_cut` 起步（G9.1 第 2 步"先做零振幅平面切割验证"）；或按 G9.4 发布已声明精度档并限制最小结构主张 |
| 18 | **`leakage_audit` 通过**（G28、A12.12） | 门状态 `leakage_audit: PENDING`；`train_dev_lineage: PASS` | 缺完整泄漏审计（含背景轮廓、网格编号、纹样种子、渲染器特征负控） | 需 shortcut audit：parent-object split、seed split、renderer/camera 随机化、器型参数留出、纹样模板留出 |
| 19 | provenance / 版本 / hash（G6.1、G25） | `provenance` 12 条（主库）+ 21 条（closed_loop），含 `code_fingerprint`（commit、`source_tree_hash`、`dirty=false`）、`backend_fingerprints`（cv2 5.0.0 / gmsh 4.15.2 / manifold3d 3.5.4 / open3d 0.19.0 / pycolmap 3.11.1 / scipy 1.18.1 / torch 2.5.1+cpu / trimesh 5.1.0） | 每资产 provenance 齐全；缺**批次级** `manifest.parquet` + `hashes.json` | `release.json / manifest.parquet / hashes.json` 三件套需按 G23.3 落地 |
| 20 | **不可变 release**（G23.3、G30.4） | 主库 `data/a12/releases` **空**，`releases` 表 0 行；冻结 release 只存在于 `data/a12_exports/closed_loop/store/releases/`（5 个，profile 全部 `SANDBOX_CORE`） | 主库无 release；已有 release 全部是 sandbox profile，**非 PILOT** | 新批次需产出 `profile: PILOT` 的不可变 release |
| 21 | **≥20 确认母体**、风险上界可测（G21.4、H5） | 无确认 split | 20 母体零误荐上界仍约 13.9%，**不足以自动过 10% 门** | 确认母体需 >20（文档给出 n=29 → 9.8% 的算式），或在有邻片接受覆盖达门的前提下另议 |
| 22 | 实际 MVS 子集 **20 母体 / 400 片 / 30–120 帧**（G15.3） | 无任何真实数据；`real_capture_dataset: PENDING`、`mvs_subset_real_run: PENDING`、`phone_rgb_mvs: PENDING` | 完全缺失（且属真实采集侧，本仓库当前无实物数据） | 需真实样品与 COLMAP 流程；**不由合成配置解决** |

### 6.6 现状与"下一批"的量化差距小结

| 指标 | 文档下一批门限 | 现状 | 倍差 |
|---|---|---|---|
| 独立母体 | 100 | 5 | **20×** |
| 接受片 | 2000 | 24 `fragment_mesh` | **≈83×** |
| 确认 split | ≥20 母体（10%） | 0 | 从 0 建 |
| 已物化退化轴 | 8（pilot：每组 2 轴） | 12（但仅 1 档，且无 level 0） | 档位维度 0/5 |
| 覆盖门（器物/材料/纹样/层/后端/轴） | 24/12/16/4/4/31 | 3/2/6/—/3/12(部分) | 6 个门全 PENDING |
| R2 正例 | 需构成主指标分母 | **0**（release 内） | 主指标当前不可算 |

---

## 7. 为满足下一批实验还缺什么（按"必须/可选"分级）

> 工时/机时为**粗略量级估计**，标注了推导依据与不确定度。文档未给出逐项工时的地方一律标【工程判断】。
> 唯一有文档依据的工时框架：六周合成 **48 人时**、十二工作周 **576 人时**（480 实现+验收 / 96 维护）、
> 完整版阶段 GPU **88 h/周**（其中合成渲染 40 h）（8.4 / T069 / T071）。

### 7.1 必须项（不补则下一批数据无法达到文档门限）

| # | 缺什么 | 为什么必须（文档依据） | 粗略工时 / 机时 | 依据等级 |
|---|---|---|---|---|
| M1 | **形变 Voronoi/Power 后端 `warped_partition`**（Gmsh 共形四面体 + 共享位移） | 四必做后端之三；`coverage_4_backends: PENDING`；G10.4 要求"共形网格 + 共同 warp"，且"体网格不合格时保留失败而不填掉空腔" | **3–6 人日**（Gmsh 适配器 + 共享 PLC 拓扑登记 + 位移守卫 + 回归）；机时 **数小时–数十小时 CPU**（1000 片基准内可测） | 【工程判断】+ G10.4 |
| M2 | **`rough_shared_cut` 精度达标或发布 `precision_profile`** | G28 要求 P95 < 0.02 mm；实测 0.01 mm 预算下 `realized_error_mm ≈ 0.2260`，demo 2 次 FAIL | 方案 A（提预算/分块）：**2–5 人日** + 大量 CPU；方案 B（发布已声明精度档）：**0.5–1 人日**文档 + 限制主张 | 【工程判断】+ G9.4 / G22.6 |
| M3 | **补齐 pilot 8 轴的配对五档 recipe 文件**（P/I/G/X 各 2 轴） | G4"pilot 每组先 2 轴"；G17 要求 `paired_across_levels`；现只有 4 轴（P02/P03/I01/G08） | **1–2 人日**（写 recipe + 逐轴目标量检查）；机时按 G22.6 1000 片基准并入 | 【工程判断】+ G4 / G17 |
| M4 | **每轴 level 0（真 identity）资产与逐轴单调性报告** | G28"每轴 5 档与共同随机基底"；`physical_recipes.json` 说明行"level 0 必须是真正 identity"；现状无 level 0 | **0.5–1 人日**；机时可忽略 | 【工程判断】+ G28 |
| M5 | **confirm split 与冻结 `protocol_hash`** | G6.3 80/10/10；H5 确认前锁 14 项；`confirmation_complete` / `frozen_protocol` 均 PENDING | **1–2 人日**（划分脚本 + 冻结清单 + 独立保管流程） | 【工程判断】+ G6.3 / H5 |
| M6 | **R1 / R0 / 灰区 `TINY_CONTACT` / mate-present 池** | G12.1、G18.2、D17–D19；现状 R2 与 UNKNOWN 之外全空，`r2_relations_in_scope: 0` | **2–4 人日**（关系构造 + 面积阈值双口径 + 独立复核） | 【工程判断】+ G12.1 / G18 |
| M7 | **格式落地：Zarr 数值观测 + JPEG/tar 分片 + Parquet 索引** | G23.1 逐项规定；现状 Zarr/JPEG 为 **0** | **2–4 人日**（导出层）；机时按 2000 片 × 12 视图估 **3.3–13.3 GPU 小时**（文档 0.5–2 s/帧算式，G22.5） | 【工程判断】+ G23.1 / G22.5 |
| M8 | **Blender/bpy 可用性或显式降级声明** | G14.1 要求长边 1024、G14.2 要求 Cycles 通道与整数 ID 渲染；实测 `blender` 不可用，只有软件光栅器 | 环境搭建 **0.5–1 人日**；否则必须发布降级声明并限制主张 | 【实测】+ G14.1/G14.2 |
| M9 | **`leakage_audit` 与 `coverage_*` 门可过的最小覆盖** | G28 划分隔离"谱系交集为 0"；A12.12 shortcut audit 五类留出 | **2–4 人日**（审计脚本 + 负控，含 pureBG 不带轮廓） | 【工程判断】+ G28 / A12.12 |
| M10 | **1000 片 profiling 报告（P50/P95、RSS/VRAM、每接受片成本）** | G22.6 与 G27.3 明确要求；无此报告不得扩容 | **1–2 人日** 分析；机时 = 1000 片生成（见下方机时账） | 【工程判断】+ G22.6 |
| M11 | **主库不可变 `PILOT` release（`release.json` / `manifest.parquet` / `hashes.json`）** | G23.3、G30.4"只允许 audit 通过的 COMMITTED 资产进入 release"；主库 `releases` 表 0 行 | **1–2 人日**；含引用闭包校验与恢复抽样 | 【工程判断】+ G23.3 |

**机时总账（【工程判断】，基于 demo 实测单元素耗时外推）**

以 100 母体 / 2000 接受片、`target_piece_range [12,28]`、12 视图为目标：

| 环节 | 外推算式 | 量级 |
|---|---|---|
| 母体生成 | 100 × 1.43 s | ≈ **0.04 CPU 小时** |
| 纹样生成 | 100 × 8.36 s | ≈ **0.23 CPU 小时** |
| 碎裂（含重试） | demo 接受率 **4/8 = 50%** ⇒ 约 4000 次尝试 × 28.28 s | ≈ **31 CPU 小时** |
| 退化/观测 | 2000 × 6.47 s（**demo 为 4 视图/320×240**） | ≈ **3.6 CPU 小时**（低估） |
| 渲染（12 视图/1024 px） | 24000 帧 × 0.5–2 s（文档算式） | ≈ **3.3–13.3 GPU 小时** |
| 断口 ROI 额外帧 | 若断口 crop ×4/片 ×70 KB ⇒ 再加 **约 0.6 GB** | 空间为主 |
| **合计** | CPU 约 **35 h** + GPU 约 **3–13 h** | **1–2 个工作日单机** |

> ⚠️ 上述不能当作承诺：① demo 是 8 母体、4 视图、320×240 的软件光栅器；
> ② `rough_shared_cut` 在当前预算下 2/2 失败，失败重试会显著抬高碎裂机时；
> ③ 文档明确"**应先做 1000 片 profiling，再选择缓存视图数和分辨率**"（G22.5）。

### 7.2 可选项（不补不阻塞下一批，但影响主张强度）

| # | 缺什么 | 影响 | 粗略工时 |
|---|---|---|---|
| O1 | `fracture_modes` 物理碎裂插件 | 可选后端（G4/G11）；受限许可，主生成器不应强依赖 | 3–8 人日（隔离环境 + 薄壁资格） |
| O2 | D21 实际照片重建子集（20 母体 / 400 片 / 30–120 帧） | 主张"代理扫描接近实际扫描"的**必需验证子集**；但属真实采集侧 | 依赖实物样品与 COLMAP |
| O3 | D23 受限模拟出土上下文、D24 反证/机制解释监督 | 扩展项；D24"仅有可信构造时生成" | 2–4 人日 |
| O4 | episode 环境（5 类基础 episode + 动作成本） | G19 列为"完整核心"；但下一批数据的**首要**目标不是它 | 3–6 人日 |
| O5 | 31 轴全部 5 档 | 完整 V1.0 门限；pilot 只需 8 轴 | 每轴 0.5–1 人日 + 机时 |
| O6 | 50 万片扩容 | "需有**独立收益证据**与容量计划，不因为程序能生成就默认扩到最大数"（G27.3） | 独立预算 |
| O7 | `observe` 在 `hole_count>0` 的 `IndexError` | demo 环境结论记录了该缺陷（`data/**` 不在本次写入范围） | 0.5 人日 |
| O8 | `normal_noise` / `curvature_noise` 独立轴 | 文档明确"**不再重复计作新的独立物理退化轴**" | 不需新增轴，只需派生误差报告 |

### 7.3 依赖顺序（文档给定的关键路径）

【文档】"实验室为**几何 GT → 独立损伤 → 观测对应 → 31 轴和覆盖 → 资源恢复 → 不可变完整发布**。
**依赖未过不跳门。**"（8.4）
【文档】扩容闸门："**100 至 2000 片阶段先修正确性**；1 万片阶段检查各层覆盖与 P95 资源；
十万片阶段要求生成成功和失败都有审计、磁盘预算加余量可满足、训练读取没有明显 IO 瓶颈且固定确认集已冻结。"（G27.3）

---

## 8. 产数据配置草案说明（`configs/a12/next_experiment.yaml`）

- 状态：**待执行**（draft）。字段均为 `synlab.v3` / `GenerationSpec` 可接受字段；ID 全部取自 `docs/a12/registry.json` 中 `status=IMPLEMENTED` 的真实 ID。
- **校验结果（本次实测，只读）**：`.venv\Scripts\python.exe -m synlab.cli validate --config configs/a12/next_experiment.yaml`
  → **exit 0 / `OK` / `warnings: []` / `spec_hash: sha256:2afbe600d2c9896186597ea87151d362a4f079989bbc8daa3e30b8850c439297`**。
  注册表展开确认：vessel 24（全 IMPLEMENTED）、material 12（全 IMPLEMENTED）、layer_combo 4（全 IMPLEMENTED）、
  pattern 16（全 IMPLEMENTED）、axis 31（全 IMPLEMENTED）、fracture_backend 5（IMPLEMENTED 3 / PENDING 1 / MISSING 1）。
- 目标定位：文档点名的**下一批 = pilot 资格批次（A12.13 SY1 约 100 母体 / 2000 片）**，并让 **G22.6 的 1000 片基准**（跑到第 50 母体）自然成为内层检查点。
- **未修改** `synlab/**`、`tools/**`、`frontend/**`、`data/**` 及任何其它 `configs/**`。

### 8.1 每个数字的来源

| 配置字段 | 取值 | 来源 | 类型 |
|---|---|---|---|
| `schema` | `synlab.v3` | `synlab/schemas/spec.py::SCHEMA_GENERATION` | 【代码约束】 |
| `data_scope` | `SYNTHETIC` | 文档"所有合成结果必须显式标记 SYNTHETIC，真实测试集永远独立"（A12） | 【文档】 |
| `release_profile` | `PILOT` | A12.13 SY1 / L1 pilot；`release_profile` 枚举含 `PILOT` | 【文档】+【代码约束】 |
| `experiment_purpose` | `DEVELOPMENT` | "探索仅 train／dev"（G21.4） | 【文档】 |
| `master_seed` | `20261001` | 与既有 `pilot.yaml`、`closed_loop.yaml`、demo manifest 的 `master_seed` 一致 | 【工程判断】 |
| `units` | `mm` | "权威几何单位统一为毫米，采用右手坐标系"（G6.2） | 【文档】 |
| `dataset.target_mothers` | `100` | "首版用 100 个母体…预算约 2000 片"（G4）；"约 100 母体／2000 片"（A12.13 SY1）；"不少于 100 母体种子"（G27 第 2 周）；"固定 100 母体"（E-SYN-01） | 【文档】 |
| `dataset.target_fragments_estimate` | `2000` | 同上（G4 / A12.13 / G27 第 3 周"约 2000 片闭环"） | 【文档】 |
| `dataset.shape_lineage_split` | `{train: 0.8, dev: 0.1, confirm: 0.1}` | "推荐内部训练 80%、开发验证 10%、确认测试 10%"（G6.3） | 【文档】 |
| `dataset.split_before_generation` | `true` | "**先冻结母体谱系划分**，再生成碎片、纹样、破裂事件和观测"（G6.3） | 【文档】 |
| `dataset.replacement_fractures_share_lineage` | `true` | "相同基础 mesh 的尺度变化、纹样更换、微形变及二次破碎全部继承 `shape_lineage_id` 并处于同一 split"（G6.3） | 【文档】 |
| `dataset.include_all_components` | `true` | "任何侧可能产生多个碎片，**全部登记**或按冻结 tiny 策略归档"（G9.1 第 3 步） | 【文档】 |
| `dataset.debris_policy` | `quarantine_and_record` | "掉下的屑片要登记为 debris 或明确从候选库排除"（G13.2）；"tiny 去向有记录"（G28） | 【文档】 |
| `dataset.vessel_ids` | V01–V24（全部 24） | 完整规划 "24 器物品种"（G4/T102）；每类须有独立生成入口（G7.4）。**配额由 `registry_balanced` 分摊到约 4 母体/器型** | 【文档】+【工程判断】 |
| `dataset.material_ids` | M01–M12（全部 12） | "完整覆盖为 24 器物、**12 材料**、4 层状组合、16 纹样"（G4）；V1.0 要求 12 材料族均能生成/切碎/退化/过 GT 审计（G7.5） | 【文档】 |
| `dataset.pattern_ids` | PAT01–PAT16（全部 16） | "完整版本至少产生 **16 类各 20 个独立母体**的样例"（G8.3）；G8.1 列 16 族 | 【文档】 |
| `dataset.layer_combo_ids` | L01–L04（全部 4） | "4 层状组合"（G4/T102）；registry 中 L01–L04 均 `IMPLEMENTED` | 【文档】 |
| `dataset.parameter_bounds_ref` | `configs/a12/registry_bounds.json` | 与 `pilot.yaml`/`coverage.yaml` 一致；边界值"来自 plan 7–9 节，是开发起点而非实测分布主张"（该文件 note） | 【仓库现行】 |
| `sampling.method` | `latin_hypercube` | "参数采样采用分层或 Latin Hypercube 起步"（G4）；"连续参数默认 Latin Hypercube"（Codex 规格 §7.3） | 【文档】 |
| `sampling.quota_policy` | `registry_balanced` | 与既有 pilot/coverage 配置一致；"离散类别用配额"（Codex 规格 §7.3） | 【仓库现行】+【文档】 |
| `sampling.seed_stride` / `sobol_power_of_two` | `1` / `true` | 与既有配置一致；"连续 Sobol 替换需按 2 的幂生成"（Codex 规格 §7.3） | 【仓库现行】+【文档】 |
| `pattern.coordinate_space` | `mother_surface_mm` | "用母体三维位置与 `surface_tag` 查询场……避免每片独立 UV 重排产生不连续图案"（G8） | 【文档】 |
| `pattern.periodic_azimuth` | `true` | "周向要满足周期条件"（G8）；"检查母体周向接缝"（G8.3） | 【文档】 |
| `pattern.geometry_before_fracture` | `true` | "纹样先附着完整母体，再被碎裂截取"（G8）；`config.py` 强制：非 none 高度策略必须 `geometry_before_fracture` | 【文档】+【代码约束】 |
| `pattern.height_policy` | `none` | 与 `pilot.yaml` 一致；PAT14/PAT15 的 relief/engrave 由 `patterns/families.py` **按族默认**给出（`{"PAT14": "relief", "PAT15": "engrave"}`），全局 `none` 不阻断其几何高度 | 【工程判断】+【代码事实】 |
| `fracture.backend` | `rough_shared_cut` | G9"首选碎裂算法 共享非平面界面切割"；与 `pilot.yaml`/`coverage.yaml` 一致 | 【文档】+【仓库现行】 |
| `fracture.target_piece_range` | `[12, 28]` | 与 `coverage.yaml` 一致；G9.2"原型按目标 **8 至 30 片**分层" | 【文档】+【仓库现行】 |
| `fracture.min_feature_wavelength_mm` | `0.24` | 与 `pilot.yaml`/`coverage.yaml` 一致；G9.4 以 **0.2 mm 最短波长**为基准（0.24 是仓库既有取值） | 【仓库现行】+【文档】 |
| `fracture.shared_surface_max_error_mm` | `0.01` | 与 `pilot.yaml`/`coverage.yaml` 一致；严于 G28 的 0.02 mm 门 | 【仓库现行】+【文档】 |
| `fracture.rough_amplitude_mm` | `[0.02, 0.3]` | G9.1 第 2 步"候选局部粗糙振幅 **0.02 至 0.3 毫米**" | 【文档】 |
| `fracture.seed_count_range` | `[12, 28]` | 与 `coverage.yaml` 一致；registry_bounds `seed_count [8,30]` | 【仓库现行】 |
| `fracture.secondary_probability` | `0.15` | 与 `coverage.yaml` 一致；二次破碎为四必做后端之一（G4） | 【仓库现行】+【文档】 |
| `fracture.max_attempts` | `3` | 与既有配置一致；"数值失败最多按冻结策略重试…每次参数变化形成新 attempt 并记录"（G25.2） | 【仓库现行】+【文档】 |
| `physical.recipes` | `[P03_depth_light, P01_polish_mid]` | pilot"每组先 2 轴"（G4/T102）→ 实物组取 P01（独立断面磨光，G13.1）与 P03（坯体侵蚀，G13.4）；两者都在 `configs/a12/physical_recipes.json` 中且属 G13.5 的守卫集合 P01/P02/P03 | 【文档】+【工程判断】 |
| `observation.input_profile` | `SENSOR_PROXY` | G15.1 三路线中"代理扫描退化"；未实测校准前**不得**称校准工况（G17） | 【文档】 |
| `observation.routes` | `[proxy_scan]` | 同上；`ObservationRoute` 枚举值 | 【文档】+【代码约束】 |
| `observation.views_per_fragment` | `12` | "原型默认 **12 个全局观察视角**，分 3 层高度每层 4 个方位"（G14.1）；G30.1 示例 `global_views: 12` | 【文档】 |
| `observation.image_long_edge_px` | `1024` | "全局训练图起步 **1024 方形或按长边 1024**"（G14.1）；G30.1 示例 `long_edge_px: 1024` | 【文档】 |
| `observation.point_count` | `8192` | "全片 **2048 至 8192 点**作为起步"（G15.2）；G30.1 `point_budget: 8192`；G23.2 按 8192 点计 | 【文档】 |
| `observation.persist_depth` | `selected_qa_only` | "深度、normal 等大数组只在需要的模型输入或确认子集物化"（G23.2）；G30.1 同值 | 【文档】 |
| `observation.persist_fused_geometry` | `true` | `pilot.yaml`/`coverage.yaml` 一致；G23.1"数值观测 Zarr 分块" | 【仓库现行】 |
| `observation.renderer` | `auto` | `pilot.yaml` 一致。⚠️ 本机实测 **Blender 不可用**，会退回软件光栅器 ⇒ 1024 px 质量门未达成（见 §6.5 #15） | 【仓库现行】+【实测风险】 |
| `resources.*` | worker 4 / RSS 30 GB / GPU 26 GB / 磁盘 0.70-0.80-0.90 | G22.1（T116）"几何 CPU worker 2–4"、"工作任务总 RSS 约 30 GB 内"、"GPU 显存目标峰值约 24–26 GB 内"；磁盘 70/80/90 阈值见 A12.14 | 【文档】 |
| `storage.shard_target_mb` | `512` | G23.1"训练顺序读取 **512 MB 至 1 GB shard**" | 【文档】 |
| `storage.mutable_release` | `false` | schema 强制 `Literal[False]`；"不可变权威层"（G23.3） | 【代码约束】+【文档】 |
| `quality.fail_closed` / `freeze_before_confirmation` | `true` / `true` | 与既有配置一致；"只允许 audit 通过的 COMMITTED 资产进入 release"（G30.4）、"在发布前冻结"（G6.3） | 【仓库现行】+【文档】 |
| `degraded_recipe_refs` | 两个既有 paired recipe | 仓库现存**仅有**这两个 paired recipe 文件（P03 L2；P02 L2 + I01 L1 + G08 L2），均为 `basis_policy: paired_across_levels`，满足 G17 配对要求 | 【仓库现行】+【文档】 |
| `notes` | 见 yaml | 说明本批次的 4 处已知风险 | 【工程判断】 |

### 8.2 本草案**不能**满足、必须随执行一起记录的事

1. **覆盖门**：100 母体内 24 器型各得约 4 母体，**远低于 G28 的"每类 ≥20"**；
   完整覆盖需要 **≥480 母体**的第二批（本文 §6.5 #5）。A12.13 的 SY1 门本身也**不要求**完整覆盖。
2. **精度门**：`rough_shared_cut` + 0.01 mm 预算在本构建下实测 `realized_error_mm ≈ 0.226`，
   demo 中 2/2 失败。执行前须按 M2 处理，否则大量资产会进隔离队列。
3. **渲染门**：`renderer: auto` 在无 Blender 环境退回软件光栅器，
   **1024 px / 12 视图的成像质量主张不成立**（G14.1/G14.2）。
4. **配对轴覆盖**：`degraded_recipe_refs` 只能引用现有 2 个文件，
   覆盖 P02/P03/I01/G08 共 4 轴，**未达到 pilot 每组 2 轴共 8 轴**（M3）。

---

## 9. 来源与不确定项

### 9.1 主要来源章节（本文引用密度最高）

| 主题 | 章节 | 对应表 |
|---|---|---|
| 合成支线定位与路线 | A12、A12.1–A12.16 | T027–T039 |
| 数据产品 24 类 | G3 | T101 |
| 覆盖规划（24/12/4/16/5/31/6） | G4 | T102 |
| 数据合同：六种 Pack / 坐标 / 划分 / 数组 | G6.1–G6.4 | T103、T104 |
| 退化 31 轴 | G16 | T109 |
| 质量阶梯 SY-Q0…SY-Q5 | G17 | T110 |
| 关系与难例 | G12.1–G12.4、G18.1–G18.4 | T111 |
| 实验矩阵 | G21.1 | T115 |
| 功效/风险上界/搜索 | G21.4（普通段落） | — |
| 1000 片基准与资源 | G22.6 | — |
| 存储格式与容量 | G23.1–G23.3 | T117、T118 |
| 数值精度与量化 | G24 | T119 |
| 调度/恢复/可复现 | G25.1–G25.3 | — |
| 实施排期与扩容闸门 | G27.1–G27.3 | T121 |
| 验收矩阵 | G28 | T122 |
| 配置示例与模块接口 | G30.1–G30.4 | — |
| 交付清单 | G31 | T124 |
| 统一合同与确认签收 | H1–H7 | T125–T128 |
| 资源与 GPU 日历 | 8.4 | T069–T071 |
| 真实数据侧门限 | B2.2、B7、B9.1、EXP08 | — |
| 指标分母与手算 | 2.2.1、A9.1 | T023 |

### 9.2 明确标注为不确定/推断的项

| # | 项 | 性质 | 说明 |
|---|---|---|---|
| U1 | **表格编号** | 【方法限制】 | 文档**无表号/题注**，本文 `T###` 是按 body 顺序自编的定位符。若文档后续版本增删表格，`T###` 会漂移；引用时请**同时用章节号**。 |
| U2 | 层组合的**独立覆盖计数** | 【推断】 | 主库资产 meta 中未见独立 `layer_combo_id` 统计字段；本文按 `material_profile.layer_ids` 观察（仅见 `[1]`）推断层组合覆盖不足。**未在 release coverage 里找到 layer 维度字段**。 |
| U3 | 主库 28 个 `axis_id` 与 demo 12 个 `generated` 轴的**关系** | 【推断】 | 主库 116 条 `audit_lineage` 资产的 `axis_id` 出现 28 个轴名（P02/P04/P08 缺席），但 demo manifest 的 `axis_catalog` 只对 **12 轴**标 `generated=true`。两者口径不同（审计扫描 vs 物化生成），本文**未**断言"28 轴已生成"。以 release `coverage_31_axes: PENDING` 为准。 |
| U4 | 100 母体 pilot 的 **quota 分摊结果** | 【推断】 | `registry_balanced` 的具体分摊算法未在文档中给出；本文按"等分"估算约 4 母体/器型、约 8/材料、约 6/纹样。实际配额由 `synlab` 采样器决定，**执行前须以 `synlab budget --dry-run` 实测**。 |
| U5 | `target_piece_range [12,28]` 与 2000 片的**一致性** | 【推断】 | 100 母体 × 平均 20 片 = 2000 片，与 G4"每次目标 20 片"自洽；但 `[12,28]` 来自 `coverage.yaml`，G4 原文只说"目标 20 片"与"原型按目标 8 至 30 片分层"。**区间上下限为仓库既有取值，非文档对该批次的明文要求。** |
| U6 | `physical.recipes` 选 **P01 + P03** | 【工程判断】 | 文档只说"pilot 每组先 2 轴"，未点名具体轴。选 P01（断面磨光，G13.1）与 P03（坯体侵蚀，G13.4）是因二者属 G13.5 的守卫集合且 `physical_recipes.json` 中已有对应 level 1/2 recipe。**不是文档点名。** |
| U7 | `renderer: auto` 的**实际解析结果** | 【实测 + 风险】 | demo manifest 记录本机 `blender` 不可用、只有软件光栅器。设为 `auto` 不会报错但会静默降级；这与 G22.6"不能静默降精度计成功"存在张力。**执行前必须跑 `synlab doctor` 确认渲染能力，或在报告中显式声明降级。** |
| U8 | 机时/工时估计 | 【工程判断】 | §7 的机时全部由 **8 母体 / 4 视图 / 320×240 软件光栅器**的 demo 实测外推到 100 母体 / 12 视图 / 1024 px，**必然低估**；文档唯一给定的算式是 0.5–2 s/帧（G22.5），并被文档自己声明为"仅算式示例"。**不得作为承诺。** |
| U9 | "第一阶段/下一步"的**唯一**答案 | 【推断】 | 文档同时点名 SY1（100/2000）、G22.6（50/1000）、G27 第 2–3 周、G21.4（8–12/30–50/≥20）等多处"第一步"。本文判定**下一批 = pilot 资格批次**，理由是它同时满足 SY1/L1/G27 第 2–3 周，且 1000 片基准可作为其内层检查点。**这是本文的选择，不是文档的单一指定。** |
| U10 | 20 母体确认集是否足够 | 【文档已答】 | 文档已明确："20 母体零误荐的单侧上界仍约 13.9%，**不能自动过 10% 门**"（H5）。本文照录，不额外推断。 |
| U11 | `docs/a12/registry.json` 的**中文名** | 【工具限制】 | 本次从 PowerShell 控制台读取 registry 名称时中文显示为乱码（控制台编码），但字段结构与英文后缀（plain/bands/stripes/…、earthenware/porcelain/…、revolve/prism/…）完整可读，ID 与 `status` 可靠。名称映射据 `A12_Codex_Execution_Plan_V1.2.md` §7.2/§8.1 与 docx G7.4/G7.5/G8.1 表交叉核对。**不影响任何 ID 使用。** |
| U12 | 31 轴中 `normal_noise` / `curvature_noise` 的**轴号** | 【文档已答】 | 两者**不占独立轴号**（G16 表为 P01–P08/I01–I10/G01–G08/X01–X05 共 31），文档另说明它们"由 G01 至 G05 派生误差报告，不再重复计作新的独立物理退化轴"。**本文不把它们当作第 32/33 轴。** |

### 9.3 读取方法是否失败的说明

- **没有读取失败项**：128 个 body 表格与 1807 个段落全部读出（含合并单元格去重、`w:eastAsia` 中文正常）。
- 唯一工具层限制：PowerShell 控制台回显中文乱码（`$OutputEncoding` 问题），已通过**把 python 输出写入 UTF-8 文件再读**规避；所有引用数字均来自 UTF-8 中间产物，**不经控制台**。
- 若后续需要独立复核：中间产物在 `%TEMP%\v144_extract\out\`（`full.txt` 为 `<段落索引>[<样式>] 文本` 与 `<<<TABLE n>>>` 标记的全文渲染）。

### 9.4 本文未做的事（边界声明）

1. **未修改任何代码或既有配置**：写入范围仅 `docs/a12/v144_data_requirements.md` 与 `configs/a12/next_experiment.yaml`。
2. **未执行任何生成任务**：所有现状数字来自只读 SQLite / JSON / 文件清单查询与 `-Recurse` 文件计数。
3. **未验证 `next_experiment.yaml` 的可运行性**，仅验证其字段落在 `GenerationSpec` 允许集合内、ID 均在注册表中。
4. **未把历史 FAIL / STOP / `NOT_ESTABLISHED` 判决改写成新口径**（文档明确禁止）。
