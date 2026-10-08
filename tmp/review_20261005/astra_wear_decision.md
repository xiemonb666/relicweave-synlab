# A12 P02/P03 geometry decision — 2026-10-05

**建议：停止一般网格的接缝修补；先实现一个严格限域、只读、精确的高度图证书，验证原有候选，不改变磨损位移。通用 P02/P03 仍不能宣告修复。** 不批准 proposal 中尚无具体算法的通用 subset/self-intersection bypass。粗糙 slab 的 P03 是首个候选；P02 若不满足同样前提，保留 UNKNOWN，不为两个轴同时变绿而扩域。

这比立刻更换磨损算子小：`api.py::_rough_slab_probe` 是细分盒体顶面加 z 向粗糙度，源网格有成为高度图实体的明确结构；`NB.recessed_body` 的法向移动可能保留该结构，也可能使其失效，必须检查，不能从源的结构推断候选合格。本次未执行数组资格探针，因此冻结 P03/P02 是否合格均为 **UNKNOWN**。

## 为什么不继续现有修复

已读 `degradation_resume/report.md`、`proposal.json`、当前 `physical_narrowband.py`、`narrowband.py`、`physical/sdf.py` 及离线质量附录。7 个退化面删除后产生 21 条边界边，Mesh64 重现；共形修复的坏三角形位于 unchanged lineage，单修 7 个洞并未解决质量。可以在**严格共面**面片内重三角化且不改变材料，但没有证据证明这些坏面属于可这样修复的面片。继续扩大修补域、挪点、snap 或提高 simplify 容差，都需要新的几何误差/材料合同，不是无损修复。

当前绑定确有 `Manifold.set_tolerance`、`simplify`、`to_mesh64`；前两者允许简化及表面移动。官方也只给出 ε-valid 输入/输出合同，并说明退化三角形有时无法在不移动过多的情况下消除。因此不能把 `status()==NoError`、空的浮点 difference、或换精度当精确包含证书。[Manifold API](https://manifoldcad.org/docs/html/classmanifold_1_1_manifold.html)

Open3D 的 `is_edge_manifold(False)`、`is_vertex_manifold()`、`get_self_intersecting_triangles()` 可补充工程 QA；但 **v0.19.0 的自交函数跳过任何共享顶点的面片对**，遗漏相邻面翻折后超出共有边/点的重叠。更不能靠它加随机 signed-distance 采样证明 proposal。[版本源码，1264–1305 行](https://github.com/isl-org/Open3D/blob/v0.19.0/cpp/open3d/geometry/TriangleMesh.cpp#L1264)

## 可落实的最小证书

建议新增纯验证模块 `synlab/degrade/heightgraph_certificate.py`，API 为 `certify_heightgraph_subset(source, candidate, partition, axis) -> {status, reasons, source_hash, result_hash, certificate}`。先在 tmp 保存数组上独立验证，审阅后才接 `_round_edge` / `_erode_interface`；不改共享 `sdf.py`、不改 `_offset_body`。第一版限定单个简单域、单体、底面和竖直侧壁不变、边界固定；只允许坐标轴置换/反号，避免为了套模型而旋转或投影改变原网格。

证书针对**实际 float64 坐标所定义的分片线性实体**。每个有限坐标由 `float.as_integer_ratio()` / 标准库 `fractions.Fraction` 转为精确有理数，不四舍五入、不设“近似共面等于共面”。NumPy 可负责无漏检的包围盒候选枚举；最终判定用有理数。Shapely/Open3D 只做加速或交叉诊断，不能承担精确谓词。

1. 核验完整 face partition：源和候选所有面恰好覆盖 upper、lower、side；每个上下 patch 都是投影到同一简单多边形 D 的嵌入三角剖分。核验盘拓扑、简单边界、严格非零投影面积及一致朝向；精确二维三角形交集必须恰为组合上共有的边/点或空集，**不得跳过相邻面**。核验覆盖 D，无重叠、无 T 接缝、无遗漏。侧壁必须恰好为 D 边界上的竖直幕面，覆盖相应上下边界之间的区域；不能只检查侧壁顶点。
2. 得到源 `S={(x,y,z): (x,y)∈D, b(x,y)≤z≤s(x,y)}` 和候选 `C={(x,y,z): (x,y)∈D, b(x,y)≤z≤c(x,y)}`。底面及侧壁保持同一几何集合、rim 完全一致。高度图内的三角形不必有相同 xy 顶点，因而仍可验证当前 normal-offset 算子。
3. 对 source-upper/candidate-upper 的每一对投影三角形，使用**精确凸多边形裁剪**产生交集；在交集所有顶点（包括新产生的边交点）检查 `c≤s`。对 candidate-upper/lower 的交集同理检查 `b<c`；同时验证源 `b<s`。线性函数差在每个凸交集上的极值发生在顶点，所以这些是全域检查，不是采样。所有候选对必须完整枚举，预算耗尽返回 UNKNOWN。
4. 上述条件给出 `C⊆S`，并因各高度图嵌入、严格正厚度及侧幕面正确拼接排除自交。这是一个明确的**受限多面体证明**，不是通用 3D Boolean 的重写。实现正确性仍需审查和反例测试；公式不是已实现的证据。
5. 独立检查 delivered 网格的组合流形、定向、严格正 signed volume、非退化和既定 q/最小高度/aspect 质量门槛。`_assemble` 会经 `component_split -> clean_mesh` 再处理：证书必须绑定注册后实际交付坐标/面集合；若其 hash/表示发生变化，重新验证或拒绝，不能沿用 preclip 证书。体积损失及磨损幅度也在交付几何上测量。

这种证书仅使用现有 Python/NumPy 加标准库，不安装引擎；需要编写并验证小型二维精确裁剪器。第一阶段的交付应是资格/证书报告，而不是直接把分支接生产。域外、预算耗尽或前提无法核实返回 UNKNOWN；找到确切外逸/交叠见证返回 FAIL 并保存 face IDs 和有理坐标。若 P03 冻结候选因投影翻转、侧壁变化或真实外逸失败，终止该候选；不要自动削减深度来通过。

## 三个必要反例与验收边界

- **顶点内不等于面内**：把 U 形平面域 `[0,3]×[0,1] ∪ [0,1]×[1,3] ∪ [2,3]×[1,3]` 挤出到 `z∈[0,1]`；三角形顶点 `(0.5,2,0.5),(2.5,2,0.5),(1.5,0.5,0.5)` 都在材料内，其重心 `(1.5,1.5,0.5)` 在缺口外。仅顶点 signed-distance 必须失败；本限域证书须拒绝不满足实体表示的输入。
- **相邻面也可有非法重叠**：共用索引顶点 O 的两片 `[(0,0),(2,0),(0,2)]` 与 `[(0,0),(1,0.2),(0.2,1)]` 共面且重叠有正面积。单调用上述 Open3D 自交 API 会跳过这一对；精确投影交集检查必须拒绝，不能因共有 O 而跳过。
- **新的 overlay 顶点不可遗漏**：在方形四角高度均为 0 的粗三角面下放一个内部凹坑源顶点 `s(0,0)=-1`，候选仍是角点均为 0 的平面。四角比较全相等，候选却填平凹坑、增加材料。源/候选交叠剖分须在凹坑点证伪 `c≤s`。另加合法零位移/共面接触作为 PASS 对照，防止把所有接触都判 UNKNOWN。

最终小范围检查：冻结 P03 几何资格与证书；一个合法高度图样本经过真实 `physical.api.apply_damage` 和 component registration 后证书仍有效；上述三个负例；冻结 P02 若不在域内稳定返回 UNKNOWN。不要改旧测试去断言 wall guard 已通过，也不要用“测试体成功”宣告 VF/PG 任意碎片受支持。

## 明确保留的 UNKNOWN 与后续选择

P03 `wall_guard=UNKNOWN` 必须保持。`b<c` 只证明没有穿透；沿固定轴的正间距不是器壁最小欧氏厚度，更不是 0.6 mm 壁厚资格。几何证书不能晋级 physical truth、观测捕获或邻片标签。已有 `wear.py` 中“exact float64 signed distance”“clamp 后永不穿透”的文字也不能视为证明，不在本次改动范围。

一般非高度图碎片仍为 UNKNOWN；若业务要求立即覆盖这类输入，当前依赖没有现成的精确 subset+self-intersection 资格 API。下一步应从 PG/VF 的材料坐标/可信局部柱状单元保留表示，并在同一单元内定义材料移除，单独版本化算子及采样误差。固定方向 erosion 会改变现在的法向语义，不能静默替换；全局 SDF 重提取也不能自动保证对原 polyhedral source 的严格子集。当前优先选择受限证书，而非引入新引擎或重新运行已知失效的布尔链。

本次仅文档决策：未写生产代码，未执行 CAD/solver/几何探针或测试，未安装依赖；未递归委派。
