# A12 SynLab 交接文档（HANDOVER）

**写给接手者**（新会话 / 新 agent / 本人隔日回来）。本文只写"**怎么继续**"与"**别踩什么坑**"，状态数字见 `docs/a12/status.md`，未完成项见 `docs/a12/open_items.md`，算法选型政策见 `docs/a12/engineering_policy.md`（**必读，强制**）。
**生成时间**：2026-10-02 深夜（额度耗尽前）。

---

## 0. 一句话背景

**A12 SynLab**（仓库 `relicweave-synlab`）是为 **"低质量局部观测下的碎片邻片候选检索"** 任务合成**大规模、可信、可消融**训练数据的平台。核心目标：**输入一块碎片 → 检索邻片候选**；最终路线是"**宽泛随机预训练 + 真实统计校准 + 小样本真微调**"。用户是领域专家，**会亲自看图判断"像不像真实器物"**，所以**图像与几何的真实感是硬指标**。

**仓库**：`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab` · 远端 `https://github.com/xiemonb666/relicweave-synlab`（私有，`main`）
**解释器**：`.venv\Scripts\python.exe`（torch 2.11.0+cu128，CUDA 可用；**不要再 pip 装 torch**）

---

## 1. 立即要做的三件事（接手第一小时）

```powershell
cd C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab
# ① 看状态与未完成项
type docs\a12\status.md ; type docs\a12\open_items.md ; type docs\a12\engineering_policy.md
# ② 恢复周期提交（若已停）
Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "tools\commit_loop.py","900","96" -WorkingDirectory (Get-Location) -WindowStyle Hidden
# ③ 恢复服务（后端指向最新库 + 前端预览）
Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "tests\a12\api_ui\_serve.py","--store-root","data\a12_trainable\store","--port","8077","--role","researcher" -WorkingDirectory (Get-Location) -WindowStyle Hidden
Start-Process -FilePath (Get-Command node).Source -ArgumentList "node_modules/vite/bin/vite.js","preview","--port","4188","--strictPort" -WorkingDirectory "frontend" -WindowStyle Hidden
# 验证：http://127.0.0.1:8077/api/synlab/health 与 http://localhost:4188/synlab/showcase 都应 200
```

**当前唯一主线**：**断裂几何（SDF 隐式薄片）**——断口仍是平面，SDF 线是既定替代路径（政策 R1 已关闭旧的"四叉树共形化"路线）。

---

## 2. 本晚在跑的 5 条线（额度耗尽时会全部阵亡；重启方法见 §6）

| 线 | 任务 | 应交付什么 | 落地路径 |
|---|---|---|---|
| **断裂几何 SDF** | 位移高度场薄片 + 边界缝合（兜底：真 3D 窄带 marching cubes） | 水密/共轭≈0/守恒/gap P95<0.02 mm/坡度几度~20°/分带 Ra 非零/三材料差异 + **深度图出现真浮雕** + RGB 并排图 | 新建 `synlab/fracture/implicit/**`、`data/a12_reports/implicit/**`、`docs/a12/fracture_implicit.md` |
| **外观 A1/A2/A3** | A1 按断口法向从契约 5 灯态**择优选灯**（V10/M11、V21/M06 现背光 → 通路恒零）· A2 默认档 **SNR≥10**（现噪声 100.6 vs 信号 24.7）· A3 `procedural_albedo` 逐面色块（**占面片感 84%**）改连续带限纹理 | before/after dDN / SNR / facet 阶跃 / 纹理主频；A/B 图 | `synlab/observe/**`、`data/a12_reports/physical_layer/**`、`docs/a12/fracture_appearance.md` |
| **31 轴退化审计** | 把 P03 方法推广全轴：声明 vs 实际路由；逐轴 before/after 漂移/水密；漂移补 **p95/p99**；`choose_spacing` 预算显式化 | 全轴对照表 31 行 + 逐轴实测 | `synlab/{physical,degrade}/**`、`docs/a12/degrade_axis_routing.md` |
| **负例资格分歧修复** | `PoolIndex`/`RelationsIndex.confirmed()` 改为**消费** `valid`/`loss_mask`（禁止按 kind 重算）；加入契约断言 + 失败注入；报 before/after 负例供给 | 断言全绿 + 代价数字 | `synlab/{training,relations}/**`、`synlab/qc/pool_contract.py`、`docs/a12/relation_negatives.md` |
| **（已完成）实验就绪导出** | 6 组消融开关的合并包 | `data/a12_exports/experiment_ready/training_package`（1375 文件 / 5.21 GB） | 见 `docs/a12/export_guide.md` §12、`ablation_experiments.md` §8 |

---

## 3. 断裂线的现状与"完成判据"（**最重要的一条主线**）

**现状**：断口几何**仍是平面**（`Ra=1.103e-07 mm`；3/4 具 `<1 mm` Ra 恰好 0.000；**深度图均匀无浮雕**——Lead 亲自看过）。
**已就位的前提**：三角化统一（16/16 面积恰 1.0、平面逐位回归通过）· 形态学**已接线但默认关**（未开抛 `OPERATOR_NOT_REALIZED`，**不静默降级**）· **法向→明暗通路已实现并逐位证明等价**（dDN 随 Ra 单调、与 mm/px 无关）· 断口 ROI 特写（mm/px 3.84×、断面像素 62.6×）· **包内已有 566/582 个 patch 带真实亚毫米起伏（最大 0.10452 mm）** 作为内部参照。
**已关闭**：四叉树共形化路线（按 R1：T 型接头消解达标但刀体仍不水密 1623 坏边，**每轮换新根因**——最后是轮廓顶点度 {2:3967,4:933,6:629,8:61}）。证据在 `docs/a12/fracture_realism.md` §11、`data/a12_reports/tjunction/**`。

**六条完成判据（缺一不可，Lead 逐项核）**：
1. `hist=={"2"}`、坏边 0、`is_watertight`、绕向一致、正体积；
2. **平面路径逐位回归未破**（`plane_shared_cut` 与 `rough(rms=0)` 的 mesh_hash/数组/体积/审计全同；基线 `sha256:ddf8191e…` / 生产 box20 `sha256:07d5a59a…`）；
3. rough 的**共享面 P95 < 0.02 mm**；
4. 形态学**审计 + 共轭距离 P95 + `Ra`/`Rz`/相关长度/脊线密度**均有实测值；
5. 坡度 P95 **几度~20°**（现模型 53° 太陡）；
6. **视觉**：深度图有非均匀浮雕、RGB 无程序化条纹/摩尔纹、能辨认断口位置、材料间外观明显不同。

**不得**用上采样/后处理/外观纹理**伪装**几何起伏（政策明文）。

---

## 4. 关键路径索引（接手必备）

| 类型 | 路径 |
|---|---|
| 权威计划 | `A12_Codex_Execution_Plan_V1.2.md`（2290 行）· `RelicWeave_V1.44_Optimized_Complete_Plan.docx`（项目总纲） |
| 状态/清单/政策 | `docs/a12/status.md` · `open_items.md` · `engineering_policy.md` · `decision_record.md` + `configs/a12/decision_defaults.json` |
| 契约 | `configs/a12/capture_contract.json`（108 字段/133 指针）· `docs/a12/rig_contract.md`（35 行覆盖矩阵）· `synlab/schemas/view_channels.json` |
| 精度 | `docs/a12/precision_audit.md` + `data/a12_reports/precision_audit.json` |
| 断裂/外观 | `docs/a12/{fracture_realism.md,fracture_visible.md,fracture_appearance.md,physical_layer_wiring.md,fracture_calibration.md}` · `data/a12_reports/physical_layer/**`（**图在这里**） |
| 训练/导出 | `docs/a12/{training_run.md,export_guide.md,ablation_experiments.md,relation_negatives.md,smallfixes_report.md}` |
| 数据（**不入 git**） | 最新库 `data/a12_trainable/store`（463 资产）· 实验就绪包 `data/a12_exports/experiment_ready/training_package` · 旧代归档 `data/_archive_pre_fix/`（36.3 GB） |
| 关键工具 | `tools/commit_loop.py`（周期提交）· `tools/load_package.py`（加载器/数据卡/`--check`）· `tools/check_data_quality.py`（可训性闸门）· `tools/a12_pool_contract.py` · `tools/a12_experiment_ready_export.py` · `tools/a12_chunked_smoke.py` |
| 验证命令 | `pytest tests/a12/{fracture,observe,storage,qc,relations,training} -q`（**必须重定向到文件再读**） |

---

## 5. 已固化的裁决与不可协商的诚实规则

**已裁决（不要推翻，除非有新证据）**：
- **D1–D12 + A1–A4** 见 `decision_record.md` / `open_items.md`：`ActionProposal` 并集+显式可选·`M`/`δ` 用可复算定义（δ=簇 bootstrap CI 半宽，dev 上冻结）·主指标冻结 7 项·**断面权威定义 = `interface_id >= 0`**（`origin_kind` 为派生）·结构光 v1 排除但合成深度可作上界并标 `synthetic_only`·§8 九类**必须生成并标注**（不删除）·`bag_id` 属采集上下文（允许进部署视图 + 声明）·`loss_mask` 是唯一监督门·外观 A1/A2/A3/A4。
- **工程政策 R1–R5**：三补丁停手 · 构造性优先 · 先 spike 后落地 · 保留干净基线 · 不放宽判据。

**不可协商**：
1. **不伪造**：不得伪造标签/负例/对应关系/统计；`UNKNOWN` 永不当负例（`loss_mask=False`）；
2. **不放宽**：不得为让结果好看而放宽审计/泄漏/QA/门限；QA 变更必须**版本化**（现 `a12.qa.v2`）；
3. **标注代际**：拿不到的模态必须标 `rig_obtainable=false`/`claim_allowed=false`；`0.1 mm 精度`等**禁入能力主张**；
4. **数据代际分离**：只能靠**资产 meta**（`mask_semantics`/`damage_semantics`/`obs_semantics`/`registry_version`），**绝不用 run_id/时间戳**；混代数据会被 `check_data_quality.py` 判不可训练；
5. **移动而非删除**旧数据，并登记 `superseded_by_*`。

---

## 6. 操作坑（这一晚踩过的，别重复）

| 坑 | 症状 | 正确做法 |
|---|---|---|
| **按进程名杀进程** | 有 agent 用 `Get-Process python \| Where Path -like '*relicweave*' \| Stop-Process` → **杀掉 16 个 venv 进程**（批产/GPU 基准全灭） | 只按**精确 PID 或端口**操作；`Get-NetTCPConnection -LocalPort N` 找 PID |
| **重负载长跑** | 进程被宿主**杀（exit -1）** | 小规模、`--batch 1`、`--resume`、**每步写盘** |
| **pytest 输出被管道截断** | 管道关闭 stdout → exit -1 | **重定向到文件再读**：`... > out.txt 2>&1; type out.txt` |
| **控制台 GBK 乱码** | traceback 变成乱码，浪费排查 | `Out-File -Encoding utf8` 后用 `Get-Content -Encoding utf8` |
| **shell 是 PowerShell 5.1** | 无 `pwsh.exe`；`.ps1` 被执行策略禁止（`UnauthorizedAccess`） | 用 **Python 脚本**代替（如 `tools/commit_loop.py`） |
| **`Set-Content -Encoding utf8` 带 BOM** | 文件注入 `\ufeff`，inline exec 报 `invalid non-printable character` | Python 读源码可行；内联 exec 用 `read_text(encoding="utf-8-sig")` |
| **并发写同一文件** | `cut.py`/`pipeline.py` 被写出 `SyntaxError`；一晚多次 | **单写者纪律**：每个文件/目录同一时刻只允许一个 agent；任务书写明写域 |
| **git 混入临时文件** | `_s1_probe*.py`、`tmp/**` 被提交（111 个） | 已 `.gitignore` 掉；接手时保持"临时文件别放仓库根" |
| **子 agent 无法中断** | `send_message`/`interrupt_agent` 对 subagent 报 `not found` | 只能**治理**：归档在飞文件 + `git checkout --` 回退 + 记录结论（见 `open_items.md` T 型线处置） |
| **额度耗尽** | agent 在 20–60 分钟处猝死 | 周期提交循环保底；**交接文档 + 状态板**必须随时最新；重要结论**立刻落盘** |

---

## 7. 下一步优先级（接手直接照做）

1. **断裂几何 SDF**：先出最小可用（单连通 patch + 位移薄片 + 缝合）→ 过六条判据 → **Lead 看图**（深度图有浮雕是第一证据）。若"高度场无法表达悬垂"（玻璃贝壳），转 **3D 窄带 MC**。
2. **外观三条**（A1 灯态择优 / A2 SNR≥10 / A3 带限纹理）——几何到位后一起做，否则"通路就绪但信号被掩盖"。
3. **31 轴审计 + 负例资格修复**的结论合并进数据契约（漂移 p95/p99、资格单真源）。
4. **补物化**：`degrade` 仅 **9/31 轴**有物化档位（33 档）→ 需专门一条物化线；`correspondence` 仍 **0/9**（`id_map` face_id 空间不一致，需改 `synlab/observe/**`）。
5. **合并导出 v2**：把 ROI 视图族（现仅 `research/roi_views/`，跨 store 身份未证）与新增退化档、SDF 断口一起重导；更新 `ablation_index.json`。
6. **发布收口**：验收 **FAIL 4/PENDING 6/NOT_RUN 6**、PILOT **10/12**、12 个旧 release 标 `superseded` 并发新 `rel_*`、基线重算。
7. **需硬件（不可在本机完成）**：真实标定（5 字段 0 命中）· 真实迁移结论 · 独立母体 ≥20 · `REAL_CAPTURE`；**"像不像真实"在拿到实物断口样本前只能标 `assumption` + 用户目视判定**。

---

## 8. 快速自检（接手后 10 分钟内跑完）

```powershell
$py = ".venv\Scripts\python.exe"
& $py tools\load_package.py --package data\a12_exports\experiment_ready\training_package   # 期望 exit 0，rank n_allowed 1496、negatives 3120、effective_queries 44
& $py tools\load_package.py --package data\a12_exports\experiment_ready\training_package --check  # 期望 exit 0
& $py tools\check_data_quality.py --store data\a12_trainable\store                        # 0=可训练 / 3=不可训练（读原因）
& $py tools\a12_pool_contract.py --step all                                               # 期望 exit 0（13 断言 × 4 实现 × 2 上下文）
& $py -m synlab.cli validate --config configs\a12\next_experiment.yaml                    # 期望 exit 0（冻结配置，勿改）
pytest tests\a12\storage -q > _handover_pytest.txt 2>&1 ; type _handover_pytest.txt       # 期望 119 passed
```

**若这些数字对不上，先怀疑"数据代际"（`data/_archive_pre_fix` 与最新库并存），再看 `status.md` 的"已完成"是否被后续改动破坏。**

---

## 9. 交接边界（我交出去时确定的状态）

- **代码**：已提交推送（`main`，工作树 0 处未提交；最近 `3d800d7` 主快照 + `3879997` 清理）；**数据不入库**（靠生成器 + 数据卡 + `manifest_hash` 复现）。
- **服务**：后端 8077 → `data/a12_trainable/store`；前端 4188 展示页可用。
- **在跑**：4 条 agent 线（断裂 SDF / 外观 / 31 轴 / 资格修复）+ 周期提交循环；**它们会因额度随时中断**，重启方法见 §6，交付验收标准见 §3。
- **最重要的未完成项**：**断口几何仍平**——其余一切（外观通路、ROI、包、消融、契约、QA）都已就位，**只等几何**。
