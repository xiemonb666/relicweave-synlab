# 三层真值合同（CleanTruth / PhysicalTruth / VisibleLabels）

`synlab/truth/api.py` 是计划 §11 的落地实现。本文件说明**判据、编码与审计**，供下游
（relations / degrade / physical / 训练与诊断）引用。所有阈值取自 `synlab/fracture/spec.py`
（冻结常量），不在本模块里重复定义。

## 0. 门面与调用顺序

```python
clean   = finalize_clean_truth(mother, fracture_result)      # §11.2 第 1 层
pt      = update_residual_truth(clean, physical_result)      # §11.2 第 2 层
visible = update_visibility_truth(pt, observation)           # §11.2 第 3 层
```

持久化：`commit_truth(store, obj, role=..., lineage_id=..., split=..., ancestry=(...))`
与 `load_truth(store, asset_id, role=None)`；另有 `build_labels(clean, visible=None, features=...)`
与 `relation_audit(clean)`、`truth_summary(obj)`。

## 1. CleanTruth：R2 / TINY_CONTACT / R1 / UNKNOWN（§11.1）

每个接口 patch 先按**测量**分类，再把同一 fragment 对的多个 patch 合并成一条边（最强类别优先，
面积求和；R2/TINY 保留实测共享面积，R1/UNKNOWN 记 0 并把原始测量留在 `meta["patch_evidence"]`）。

R2 需要**同时**满足：

1. **双方都是新断面**：patch 两侧面的 `origin_kind == interface`（母体外表、装配面、外表面贴近 → 直接 R1）；
2. **来源唯一**：`source_triangles` 非空且全部 ≥ 0，且 `ambiguity_area_ratio ≤ 0.02`；否则 UNKNOWN；
3. **材料背书**：patch 采样点位于母体实心材料**内部**（`mother.mesh.contains`），
   比例 < 0.90 → UNKNOWN（reason `cavity_adjacency_or_outside_material`，即“穿空腔相邻/外表贴近”）；
4. **面积双阈值**：`area ≥ max(0.1 mm², 1e-4 × 母体材料面积)`；低于 `max(1e-3, 1e-6 × 母体面积)` 记
   `TINY_CONTACT`（保存原面积，不做负例），介于两者之间也记 `TINY_CONTACT`（数值灰区）；
5. **几何预算**：`gap_p95 ≤ 0.02 mm` 且法向反向 `p95 ≤ 2°`，否则 UNKNOWN（`valid=False`）。

结构性质（`relation_audit` 独立复核）：

* 键是**规范化有序对** `(min, max)`，对称、**无自环**；自环 patch 被拒并计入 `qa.rejected_self_loop_patches`；
* **不传递**：只有真实存在的 patch 才产生 R2（2/3/4 块手算 fixture 验证了“链式 R2 但没有对角 R2”）；
* `UNKNOWN` **恒** `loss_mask=False`，且永远不会被改写成 R0；
* 没有任何 patch 的 fragment 对记为 R1（同一次互斥事件、无直接断裂面），点/边接触因此天然落入
  TINY/R1/UNKNOWN，而不是被强行标成 R2。

对应点（`CorrespondenceSample`）来自事件层按重心坐标采样的行：

* `association_kind = EXACT_SURVIVOR` 仅当 `not ambiguous` 且 `residual_mm ≤ 1e-4 mm`；
* 其余为 `UNKNOWN_MAPPING`（`valid=False`）；`VERIFIED_RECESSION` 只有在存在**已验证**的退让场时才
  计数，本构建没有该场，因此恒为 0（不编造）；
* 其所属 fragment 对不是 R2 的样本一律降级为 `UNKNOWN_MAPPING`。

## 2. PhysicalTruth：损伤后残余（§11.2）

* 逐 clean fragment 汇总损伤后组件（`component_ids`、`damaged_volume_mm3`、`retained_ratio`、`present`）；
* `survivor_patches`：每个旧 patch 用采样点到损伤后组件的最近距离（容差 0.05 mm）估计**存活面积**；
* `association_counts` 按 §30.6 三类统计（本构建 `VERIFIED_RECESSION = 0`，原因已记录）；
* `current_fit_valid`：仅当组件仍以 1e-6 相对体积解释 clean 片时为 True；
* **历史 R2 不变**：`clean.relations` 的边对象按身份携带（`clean_relations_carried_by_identity`），
   损伤绝不把正关系改写为负例（`no_negative_relabelling`），三项都进 `qa.checks`。

## 3. VisibleLabels：可见性（§11.2 / §30.6）

判据（写入 `qa.rule`，逐 view 统计）：

```
visible = 落在交付图像内 AND 相机 z>0 AND |z − 渲染深度| ≤ max(0.5 mm, 4 × mm/px)
          AND id_map ≥ 0 AND 非 uncertain_mask AND deployment_mask 覆盖
```

一次 observation 只渲染一个组件，因此**对侧记为“本次未观测”（不是“不可见”）**，不假设、不补全。
没有被任何 view 覆盖的样本不进入对应 loss，也不会被当成负匹配；`truth_incomplete` 明确标注。

## 4. 持久化编码（与既有读取方一致）

`commit_truth` 同时写两种已文档化的关系编码，避免下游分叉：

* **blob** `relations`：JSON 列表 `[{a,b,kind,interface_id,area_mm2,valid,loss_mask,reason}]`
  （L0 闸门用 `store.load_bytes(asset_id, "relations")` 读）；
* **meta** `relations` / `relations_json`（`synlab.relations.gallery` 读），外加
  `relation_count` / `r2_count` / `mother_id` / `event_id` / `fragment_ids` / `history` /
  `truth_incomplete`；
* 数组在 `arrays.npz`：`corr_*`（对应点、法向、重心、面 id、残差、权重、类别码）、
  `iface_*`（patch 面积、gap、法向、歧义、采样点与偏移）。
* `qa` 原样写入资产 QA，`qa_status = QA_PASS/QA_FAIL` 由 `qa["pass"]` 决定。

4. **面积阈值是逐 fragment 对判定**（计划 §11.1）：接口按采样分块记录成多个 patch，因此 R2 判定必须
   在“对”这一层汇总共享面积后再比阈值，绝不能逐 patch 比。**当前落盘版本仍是逐 patch 判定**（L0 实测
   `r2_pairs = 0`），补丁 `docs/a12/_patch_truth_pair_area.py` 已备好但因 `synlab/truth/api.py` 被其他
   进程占用而未能应用；在应用之前，`r2_count/r2_pairs` 的 0 值必须按“未完成”读取。

## 5. `build_labels`：labels 与 features 隔离（A01）

`build_labels(clean, visible=None, features=<特征载荷>)` 返回
`{"labels": …, "features": <原样返回>, "separation": …}`：

* 特征载荷**按身份原样返回**，labels 不写入 features；
* 复用 `synlab.observe.features.assert_no_leakage`（前向白名单）做递归泄漏检查，并额外检查
  labels 键与 `roles.FORBIDDEN_FEATURE_FIELDS` 的交集；命中即抛 `LEAKAGE_DETECTED`，不静默通过。

## 6. 测试（`tests/a12/truth/`）

* `test_relations.py`（9 条）：2 块=1 条 R2（面积 400 mm²）、3 块=链式 R2（对角 R1）、4 块=手算 4 条
  R2 + 2 条 R1、穿空腔=UNKNOWN+`loss_mask=False`、装配接触=R1、点/边接触=TINY（保留 0.02 mm²）、
  歧义=UNKNOWN、对称无自环、面积双阈值随母体缩放；
* `test_persistence.py`（5 条）：clean 往返（关系/blob/数组/接口采样点）、physical+visible 往返、
  role 不匹配拒绝、labels/features 隔离（含 `relation_kind` 等答案字段必须被拒）、穿空腔关系往返后
  仍是 UNKNOWN 且 `r2_count == 0`。

本机对重负载进程会直接杀（退出码 -1），因此这两个文件按文件运行（各自 exit 0）。
