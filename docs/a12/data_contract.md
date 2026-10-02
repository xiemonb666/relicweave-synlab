# docs/a12/data_contract.md — 数据合同、坐标、权限

权威定义在代码：`synlab/schemas/runtime.py`（运行期类型）、`synlab/schemas/spec.py`（配置）、
`synlab/roles.py`（角色/单位/frame/来源枚举）、`synlab/storage/store.py`（资产库）。
本文件说明字段语义与禁止事项。

## 1. 六种 Pack

| Pack | 角色常量 | 必需内容 |
|---|---|---|
| MotherPack | `mother_mesh`, `mother_meta`, `material_profile` | lineage、参数、闭合 mesh、surface tag、chart、材料场、hash、单位 |
| TruthPack | `clean_truth`, `physical_truth`, `visible_labels` | event/revision、叶片、接口 patch、历史 R2、装配变换、重心对应、QA |
| PhysicalPack | `physical_component`, `physical_result` | 损伤 recipe、mesh、survivor map、丢失体积、revision/hash |
| ObsPack | `obs_view`, `obs_result`, `obs_fused_geometry` | opaque sample ID、RGB、部署 mask/ROI、相机、部分几何、OBS_EST 质量、presence/validity |
| RelationPack | `relation_pool`, `query_roster` | query/candidate、R 标签、灰区、hard type、监督 valid、loss mask、pool |
| EpisodePack | `episode_trace` | 初始观察、动作空间、成本、状态、STOP、奖励规格 |

`features` / `labels` / `provenance` 是三个**分开**的 asset（`feature_bundle` / `label_bundle` / `provenance`），
不允许用字典合并制造泄漏。

## 2. 数组与有效性

| 字段 | 形状/类型 | 规则 |
|---|---|---|
| RGB | `[H,W,3] uint8`；线性源单独 float32 | 记录来源、响应、编码与原始 hash |
| integer label | `[H,W] int32` | 研究语义标签，**禁止插值**出小数类别 |
| deployment mask | `[H,W] bool` | 可获取/估计来源，与 GT 标签分开 |
| points | `[N,3] float32` | `scale_valid=true` 才是局部 mm；否则 arbitrary/reconstruction unit；空模态 `[0,3]` 且 `presence=false` |
| normals | `[N,3] float32` | 从受损观测估计；`normal_valid` 单列 |
| depth_z | `[H,W] float32` | 相机 z，mm；invalid mask 独立；**`r != z`** |
| K / T | `[3,3]` / `[4,4]` | frame 名称与变换方向显式（`T_AB` 把 B 映到 A） |
| quality | `[V,R,Cq] float32` | 每项 valid、来源与估计版本 |
| tokens | `[L,256]` 起步 | L 可变；位置、模态、source grouping、valid |

padding 在 attention/pooling/loss 全部按 valid mask 排除。

## 3. 坐标与像素

* 权威几何：**毫米，右手系**。GLB 展示层用米制/Y-up，经 `T_display_authority` 一次转换（100 mm 立方体验收）。
* 像素中心：OpenCV 约定（左上像素中心 = (0,0)）；导出 COLMAP 时 `cx+0.5, cy+0.5`；往返必须同步坐标与 K。
* crop/resize：`u' = s_x(u-x_0+0.5)-0.5`，`K' = A K`；letterbox 加 pad 平移；EXIF 真实作用于像素。
* 虚拟 U 移动改变沿光轴的相机外参并重新渲染，**不用 resize/crop 模拟物理靠近**。

## 4. 白名单（可进入 forward）

允许：实际 RGB、可获得/预测 mask 与 ROI、OBS_EST 质量、可用相机与标定、受损观测点云/网格及有效尺度、合法上下文。

禁止（`synlab/roles.py::FORBIDDEN_FEATURE_FIELDS`，由 `assert_no_leakage` 递归检查）：
parent/object/bag ID、seed、generator family ID、interface ID、关系答案、historical_R2、mate_present、
truth pose、`T_WF`、clean 隐藏表面、GT 厚度/法向/曲率、精确损伤强度、spurious_mask、hard_case_tag、
lineage_id/mother_id/fragment_id/event_id/split/variant/axis_id/level。

审计覆盖 ROI、融合、质量估计、候选过滤与检索全部阶段，不只 forward。

## 5. 谱系与划分

先划 `shape_lineage_id` 再生成。同基础 mesh 的缩放/换色/微扰/替代断裂/二次破碎/同源扫描属于同谱系。
默认 train/dev/confirm = 80/10/10，确认集开启前冻结。替代碎裂不混池（重叠占据原材料）。
器身与盖保留 `prebreak_component`，原装配接触不算新断裂 R2。

## 6. 资产与发布

* blob 只做字节去重；asset 的 role/schema/unit/frame/`interpretation_hash`/ancestry 独立。
* 提交顺序：临时文件 → flush/fsync → 数量/长度/hash 校验 → 原子 rename → 单写者事务提交。
* release 只引用 COMMITTED + QA_PASS 资产，校验完整引用闭包，manifest 不可变。
* 同字节不同语义（如 clean 与部署输入）允许共存，靠 role 与 interpretation_hash 区分。

## 7. 随机性

每个模块独立子流：`shape/material/pattern/cut/damage/camera/light/sensor/geometry/sampler`。
`pattern.evaluate` 只读冻结系数。执行重试只增加 `execution_attempt`，不改内容 seed；
换 seed/网格预算/算法参数 = 新的 `generation_variant`/`spec_hash`。
五档强度共用同一 `basis_id`。
