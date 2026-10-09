# RelicWeave V1.48 — A12 合同对齐版

**当前交付版本：V1.48。** 本版是基于用户提供的 V1.47 创新版与 V1.47 收尾版完成的 A12 合同对齐版。正文保留 V1.47 主线设计原文和其历史版号；这项保留用于设计沿革追踪，不表示 V1.48 没有进行本次合同对齐更新。

## 文档与审阅结果

最终 DOCX 为 228 页，SHA-256 为 23a42e5f4cca40ef733edc9365c15bd0d5fdff647f8821fddec9c649e52b1455。Root 接受的最终视觉 coverage 覆盖全部 228 页，且文件完整性核对通过。此 PASS 仅表示本次文档的页面视觉审阅和文件完整性检查通过；不表示工程功能验收、材料/模型资格或物理资格通过。

最终 coverage 文件：

- final_visual_coverage.json — 352,826 B，SHA-256 3211cdfc3525e3bd4ac22b548504805130945dba5efbd84caadbf234b3cebf55
- final_visual_coverage.md — 3,734 B，SHA-256 83f1e2eb02b38797ce9e816cc674fde4eef201ace83b6a2214df1483a93ccb68

最终独立来源审阅由独立审阅者从原始材料重新计算，未复用 writer 中间审阅结论。归档中的最终报告为：

- independent_source_review.md — 7,739 B，SHA-256 20b3399fe722360567d5d417ad2b5f5814514b15e1e8b7a92d240a7a0a130a60
- independent_source_review.json — 18,233 B，SHA-256 2eb4b1d1bf734659d16183159f4e61a062919b3c02a2840f2b865420d2fce4d5

writer 中间独立审阅记录标记为 UNACCEPTED_SUPERSEDED，不作为本版结论依据；最终报告从原始数据独立重建。

## 工程与资格边界

以下完成度均为工程估计范围，不是通过率或物理资格百分比：

- PG-Frag：25–35%
- VesselForge：30–40%
- A12：30–40%

MC01–MC07 为 SPECIFIED / NOT_RUN。成员恢复接口目前只有设计说明，尚未实现；开发仍暂停。物理资格包数量为 0。本次文档发布、视觉 PASS 或归档均不改变这些边界，也不代表任何实验模型获得物理资格。

## 历史状态的解释

此前合同审计、来源审阅或渲染审阅记录中的 DOCX PENDING / WAITING 是各自形成时的阶段快照，原文件保持不变。最终独立来源审阅、228 页 visual coverage 和本 README 取代这些阶段状态，用于说明当前 V1.48 交付情况。

marker.log、render.log 与 artifact.md 是历史运行/状态材料，不是最终 QA 结论。render.log 包含一次布局渲染尝试退出码为 1；artifact.md 留有当时 “QA pending” 的表述。应以最终 render manifest、上述 coverage 和独立审阅报告为准。

## 原始输入和归档映射

用户提供的两份 V1.47 原始 DOCX 已逐字节保存在既有路径，本次仅引用，不重复复制：

- workspace_backup/20261007/RelicWeave_V1.47.docx
- workspace_backup/20261007/RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx

archive_manifest.json 与 archive_manifest.md 记录来源工作区路径、归档目标、字节数和 SHA-256。为避免自哈希递归，两份映射文件不记录自身或彼此的哈希；独立交付回执将在归档提交后记录两者的最终哈希。render_manifest.json 是规范渲染清单；render_run_manifest.json 单独对应 final_render_layout/render_manifest.json。

## 复现条件

本次工作的原始工作区根目录为：

C:\Users\xiemo\Desktop\ShardForge

A12 仓库根目录为：

C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab

文档源材料与构建记录原位于：

C:\Users\xiemo\Desktop\ShardForge\tmp\master_contract_update_20261009

归档保留来源副本和路径映射，不是可直接移植运行的独立构建包。若要复现历史构建，应在新的工作区恢复原有相对目录、输入文件、patch plan、source/review 材料及必要输出目录；将 authoring receipt pin 的构建器快照恢复到原脚本相对路径，再按 receipt 中的命令和参数执行。不要覆盖现有工作区。

authoring receipt 指向的精确构建器源码 SHA-256 为 5a74044e56ea08b61a0ad27675d7abc4364c945ede42bd0741080bc6140310e2，归档于 history/source_snapshots/build_master_docx_actual_5a74044e.py。active build_master_docx.py 和 prefinal 源码快照是不同版本，按各自 SHA 单独保留；重现回执所记历史构建时应使用精确快照。

aggregate_visual_qa.py 支持 --manifest 与 --qa-dir，但仍需要对应的 QA 页面图像和输入记录。渲染环境依赖本机运行时及字体。日志记录的 LibreOffice 路径为：

C:\Users\xiemo\Desktop\ShardForge\third_party\doc-render-runtime\LibreOffice-26.8.0\program\soffice.exe

上述 LibreOffice、字体安装、文档工具运行时、缓存和完整 PNG/PDF 中间产物未包含在归档内。依赖版本及调用信息见 render_environment 与 authoring receipt。脚本默认路径假设原工作区布局；归档目录中的辅助文件必须先按路径映射恢复到原相对位置，不能直接从 docs/master/20261009/ 启动并期待完整复现。

## 归档状态

本目录为 V1.48 合同对齐版的文档与证据归档。提交、远端核验和本地备份结果以独立备份交付回执为准。归档不改变工程资格或暂停开发状态。