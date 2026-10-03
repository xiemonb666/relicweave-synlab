# PG-Frag v12 技术建议裁决（2026-10-03）

本记录将 PGFrag/VesselForge 指南 v12 转成可执行边界，不代表升级完成或现实验收。项目目标与验收以 RelicWeave V1.44 总计划及用户明确要求为准；v12 是可替换的技术建议。原始 Word 文档保持不变。

审阅输入：[v12 按 OOXML 顺序提取的正文与表格](../../tmp/review_20261003/implementation/a12_depth_noise/v12_review/guide_v12_extracted.txt)，源 DOCX SHA256：`8dc9eb4abeaf11161c049d1e798d529884ccffe2bdf638af1f5c301f2a0a4509`。机械提取和版本差异摘要见同目录的 `guide_v11_v12_summary.md`；摘要不替代对需求的解释。

## 工程路线

- 优先接入成熟、可验证并且许可证合适的几何、物理和求解库；用明确的版本、能力声明、失败状态和替换接口包住依赖。
- 将数值 worker 与控制面隔离。先有正确的 CPU 基准，再 profiling；只有证据表明值得时才晋级 GPU。数据接口用紧凑数组、分块和少复制设计，避免让大网格往返 Python 对象。
- 首版不要求新增 C++ Native Core，也不要求重写 CUDA。CadQuery/OCC 与 Peridynamics.jl 各自运行在受支持的原生运行时；Python 负责编排、适配和验证。使用 Python API 本身不足以证明性能热点位于 Python 解释器。
- 不因 v12 中的 Node/TypeScript 建议重写现有 A12 API、数据库或队列。VesselForge、PG-Frag 与 RelicWeave 之间先稳定公共 Job/Result 契约；只有独立服务出现实际需要时，才另行决策服务实现语言。

## 首条可验收链路

首版维持 VesselForge → PG-Frag → A12 的小型垂直链路。先贯通几何输入、真实 bond/fragment 事件、native 接触求解、断面与 lineage、观测绑定和全数据标注；多器型、浮雕和逐轴扩展退化随后推进。分别记录“接口骨架贯通”“数值性质通过”“材料参数已标定”“视觉与实物对照通过”，不得把其中一层的通过写成另一层已验收。

保持独立的产品边界：VesselForge 输出通用器物资产，PG-Frag 处理通用实体与材料事件，RelicWeave 消费结果进行历史片段关系研究。A12 代码是新核心的迁移与适配参考，不是 VF/PG 的核心依赖；运行时方向是 VF/PG 结果进入 A12。

## 物理与数据解释边界

- 不固定碎片数量、不通过挑 seed 凑目标数。N=1、粉末、缺失或侵蚀碎片都应按物理输出保留并标注，不能为满足关系样本数而过滤。
- `R2` 需要共同断裂事件、母体 material coordinates 和两侧表面 lineage 的可审计证据。broken bond、当前接触或几何相似性都不能单独推出 `historic_R2=true`。
- 分开记录 `historic_R2`、`current_fit`、`evidence_visible` 和退化后的 `loss_mask`。部署可见输入不得泄漏 truth/supervision；未知状态继续标为 UNKNOWN，而不转成负例。
- 未标定材料参数时，只能报告 `UNVALIDATED_PROTOTYPE` 或等价状态。玩具材料参数可验证接口和数值基本性质，不能支撑“真实陶瓷物理已验收”的结论。
- 现有实际失败维持原 `PENDING`/`FAIL`；新方案不自动覆盖旧门槛，也不回写冻结配置或历史产物。语义变化需版本化并重算新结果。

## GPU 与资源验收

CUDA 后端目前为 `NOT_IMPLEMENTED`。本机或未来 RTX 5090 的存在不会自动加速 Peridynamics.jl 的 CPU 求解。批量运行前须验证目标 backend 的设备兼容性，并用同一组小用例比较 CPU/GPU 的误差、稳定性和复现性，再测量内存峰值与吞吐。对百万级高保真自由度不承诺可在 32 GB 显存中运行；必须用目标离散尺度与事件时长实测后再规划。

## 支持依据

- NVIDIA CUDA Programming Guide 在 1.1.3 节指出，成熟库与框架通常能提高效率和产出；CUDA 也不限定为 C++：[Introduction, §1.1.3](https://docs.nvidia.com/cuda/cuda-programming-guide/01-introduction/introduction.html)。CUDA 平台页支持语言无关性与 PTX/硬件兼容说明：[CUDA platform](https://docs.nvidia.com/cuda/cuda-programming-guide/01-introduction/cuda-platform.html)。
- pybind11 支持 NumPy/buffer 接口；零拷贝仍需管理生命周期、stride 与数据转换：[NumPy and buffer protocol](https://pybind11.readthedocs.io/en/stable/advanced/pycpp/numpy.html)。
- Peridynamics.jl 文档与仓库展示 CPU 线程/MPI 路线；这不证明当前本地 GPU 支持：[Peridynamics.jl](https://github.com/kaipartmann/Peridynamics.jl)。
