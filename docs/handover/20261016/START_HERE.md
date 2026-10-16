# 2026-10-16 跨仓交接入口

**交接状态：开发暂停，目标仍 OPEN。** 截至 2026-10-16，几何、外观和接口工作有局部 PASS，但完整合格物理包仍为 **0**。暂停交付验证包含 VF 66、PG 55、A12 90 项离线 focused checks（合计 211），没有运行求解器或更改功能代码；测试范围详见证据索引。

阅读入口发布在 A12 仓库的 `docs/handover/20261016/`；continuation 状态与数学说明保存在 A12 [`docs/continuation/`](../../continuation/)；workspace-support 来源按用途分别归档于 [`workspace_support/docs/continuation/`](../../../workspace_support/docs/continuation/) 与 [`workspace_support/experiments/`](../../../workspace_support/experiments/)。恢复步骤见 [workspace-support 恢复说明](./WORKSPACE_SUPPORT_RECOVERY.md)。文中 `vesselforge/...`、`pgfrag/...`、`relicweave-synlab/...` 等路径以三个同级仓库及共享 workspace root 布局为基准；单独克隆 A12 不包含所有这些路径。A12 仓库内的 continuation 页面可从本目录使用相对链接访问；跨仓代码/证据链接应以独立 `DELIVERY_RECEIPT` 记录的 GitHub refs 为准。

## 先记住的五件事

1. **run05 是几何/来源链证据，不是物理或断裂 PASS。** `vesselforge/experiments/continuation_20261016/reference_v6_tetra/run05/partition_output/result.json` 与 workspace 独立读回 `experiments/continuation_20261016/root_v6_run05_readback.json` 证明 86,624 个正 T4、CAD 体积相对误差 0.240308%、356 个双父界面三角形、44,182 个带 16 个原始面 ID 的外表面三角形。MSH 为 25,579 个 T4 引用节点；NPZ 另有 169 个未使用节点，不能误说两个格式节点总数相同。
2. **v6 native 初始化预检已经冻结，但没有启动。** `pgfrag/data/continuation_20261016/reference_v6_preflight/run_control.json` 为 `READY_FOR_SINGLE_NATIVE_INITIALIZATION_PREFLIGHT`，预算状态是 `WHOLE_OUTPUT_FORECAST_PASS_RUN_NOT_STARTED`；另有两份 preparation FAIL，均发生在 native process 启动前。没有 `native_preflight/run01`、execution record 或 watchdog 结果。恢复时须先复核冻结输入与预算，并取得新的明确运行决定；这不是断裂授权。
3. **旧 native 控制产生的两个闭合分量和六张 RGB-D 图仍是 research-only。** 该 A12 数据的 `physical_pass=false`、`pretrain_eligible=false`、`deployment_eligible=false`、`production_a12_complete=false`。窄范围 bonded-compliance 通过不等于实物或材料物理资格。
4. **extrinsic 首次负耗散的 652 步事件尚未被解除。** 原始有符号路径给出负增量，22/24 个 QP 在该步负功；这是需解释的失效/数值证据，不能取绝对值、钳位或归类为无害符号约定。h、h/2、h/4 campaign 已准备并冻结审阅，**没有启动**；只有 coupon 的 zero-step getter/shape 检查完成。
5. **“文件存在”“快照已冻结”“几何 PASS”都不等于可交付、可用于物理推断的完整母体或数据包。** Aberdeen 候选轮廓仍不是测量重建；run05 的 read-only mother-binding receipt 已存在且 validator 已执行，只说明结构 CAD binding。实际母体尚未完成 root acceptance；9 个 validator unit checks 也不等于 acceptance。Apsida v3 扫描仍有 7 个 pinched vertex links，只能作视觉参考；Met 50899 蓝白纹样来自已烧成照片，仍是局部外观 proxy，没有完成 ornament 精修或烧成化学标定。

## 阅读顺序

1. [开发接手手册](./DEVELOPER_HANDOVER.md)：用户目标、三仓职责、当前准确状态、开发环境和安全恢复顺序。
2. [证据索引](./EVIDENCE_INDEX.md)：每项主张对应的 workspace 相对文件、状态及能证明/不能证明的边界。
3. [文档审阅与整改](./DOCUMENT_REVIEW.md)：历史/当前状态混杂、PASS 误读、链接、资源与安装复现问题及修复方案。
4. [机器可读暂停状态](./PAUSE_STATE.json)：供新开发者快速读取当前工作、待办和不得误运行的项目。
5. [暂停交付测试命令与精确测试文件清单](./PAUSE_VALIDATION.json)：区分三仓 focused tests 的数量、执行范围和资格边界。
6. [V1.48 2026-10-16 日期化方案更新](../../master/20261016/RelicWeave_V1.48_Engineering_Update_20261016.docx)：与 2026-10-09 V1.48 原合同档并存。
   最终版 231/231 页已经完成渲染与逐页视觉检查，正文/页脚修改范围和完整检查记录见 [总方案 QA](../../master/20261016/FINAL_RENDER_QA.json)。
7. [2026-10-16 continuation 状态](../../continuation/20261016/STATUS.md)、[extrinsic 数学与事件记录](../../continuation/20261016/EXTRINSIC_EVENT_MATH.md)、[蓝白曲面映射数学](../../continuation/20261016/PANEL_MAPPING_MATH.md)，以及 [2026-10-15 真实器型要求](../../continuation/20261015/REAL_WORLD_REQUIREMENTS.md)。

## 恢复工作的起点

从 A12 的 `docs/handover/20261016/` 入口阅读 continuation 与 workspace-support 归档；再查看独立 `DELIVERY_RECEIPT` 核对三仓最终 branch、commit SHA、remote 和数据发布边界。继续工作前复核代码/数据清单、来源许可、大文件和 v6 preflight 冻结 hash 与预算。所有未启动实验都保持未启动，只有取得新的明确运行决定后才执行专用一次性脚本。

暂停快照中的本地 checkout 分支均为 `backup/forge-work-20261003`；VF/PG 远端默认分支同名，A12 远端默认分支是 `main`。A12 当前 `HEAD` 相对 `origin/main` 领先 16 个 commits，祖先关系允许 fast-forward，不需要 force。该信息描述暂停快照；当前交付 refs 以 `DELIVERY_RECEIPT` 为准。暂停时没有观察到仍运行中的本项目 Python/WSL solver。约 6.8 GB raw data 由本地 manifest 保留，不应等同项目源码全量提交；`_temp_matplotlib` 是外部 runtime cache，应排除。

完整资格目标仍然是：以有来源、有尺寸与不确定度的日用及考古器物为输入，构建可审核的全器型几何与外观；在有来源绑定和已校准材料的前提下完成物理断裂、正面积裂面和闭合碎片；从结果生成不泄漏隐藏真值的观测与训练/检索数据，并通过独立资格审查。目前上述整条链尚未完成。
