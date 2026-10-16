# 备份交付回执

本回执记录 2026-10-08 完成的代码与证据备份。三个 GitHub 分支和三个本地 Git bundle 均指向下列同一提交。归档包含已验收、未验收及仍属实验状态的源码；归档本身不授予数值、材料、几何、物理或产品资格。

本回执的固定位置为 A12 仓库的 docs/handover/20261007/BACKUP_DELIVERY_RECEIPT.md，机器可读版本为同目录的 BACKUP_DELIVERY_RECEIPT.json。它们在三项已记录代码提交之后生成，不属于下表的任一提交，也不会再为记录自身而制造第四个提交或哈希循环。

## GitHub 代码提交

| 仓库 | 分支 | 提交及父提交 | 改动路径 | push |
|---|---|---|---:|---|
| PGFrag | backup/forge-work-20261003 | [21aa69dd131031944a3139b482abf6a0069da023](https://github.com/xiemonb666/pgfrag/commit/21aa69dd131031944a3139b482abf6a0069da023)，父提交 cc0e79773ce34bdebe9124d3fe60c078a85a2f5d | 1,576 | rc=0，远端相同 |
| VesselForge | backup/forge-work-20261003 | [73116cf40bd8620e3142667dccd644cc16c47aac](https://github.com/xiemonb666/vesselforge/commit/73116cf40bd8620e3142667dccd644cc16c47aac)，父提交 30b7e23aa696eafb3a39f9368de55382c9206069 | 428 | rc=0，远端相同 |
| RelicWeave SynLab | backup/forge-work-20261003 | [8271f53ae668468368b7fc61de53e7e5502a112e](https://github.com/xiemonb666/relicweave-synlab/commit/8271f53ae668468368b7fc61de53e7e5502a112e)，父提交 7cfb7fbb63c0d9170871f72cbfd8586a4c416c56 | 4,736 | rc=0，push 后 ls-remote rc=0 且远端相同 |

独立 postverify 报告为 [independent_final_postverify_20261008.json](../../../../tmp/backup_coordinator/closeout_20261007/independent_final_postverify_20261008.json)，4,491 B，SHA-256 9effc2947774bd91cafde433d8b476b968204190be8c4e54b80d862642038f02，结果 PASS。它复核了提交父子关系、分支、路径集合、远端 HEAD、索引清洁度以及源到目标和 Git blob 的哈希。报告计有 8,646 个 source 记录、6,784 个唯一目标、1,968 个 tracked 源映射、100 个证据引用、28 个别名映射和 90 个原始快照；无阻断或未授权路径。

## 清单、可移植索引和证据

主 action manifest 为 [CONTROL_ACTION_MANIFEST.json](../../backup/20261007/CONTROL_ACTION_MANIFEST.json)，10,340,581 B，SHA-256 89b7b6ce06a9253ea75ecdda65ec34c0cc5ed2c55a525687da7d8950b0278376。它包含 6,746 个精确动作、合计 145,827,644 B。对应 inventory 为 workspace 内 tmp/backup_coordinator/closeout_20261007/inventory.json，24,715,066 B，SHA-256 27e2aba7fdb0e6c877335c431fdda727ad2b8941fe95fc98a9e4765b126cc0fb。独立凭据扫描为 1,024 B，SHA-256 ff99feb862f931c89ff342b8e5a02a277979d9e486bc74b07eec2425b698943c。

三个 canonical 控制导出均位于 A12 仓库内，可在单独克隆该仓库后读取：

| 文件 | 位置 | 大小 | SHA-256 |
|---|---|---:|---|
| CODE_COVERAGE.md | [docs/handover/20261007/CODE_COVERAGE.md](CODE_COVERAGE.md) | 1,395 B | 0fe20cca8f66ceab20f2c197e48e1a651018412ea49c5128d2908a89be0c9c6d |
| WORKSPACE_SOURCE_MAP.json | [workspace_backup/20261007/WORKSPACE_SOURCE_MAP.json](../../../workspace_backup/20261007/WORKSPACE_SOURCE_MAP.json) | 7,172,256 B | 6120f0fd16eb9b296e60eeaf68e86786a5b9f1a14aacb9a93eab24f1cd61d768 |
| CONTROL_ACTION_MANIFEST.json | [docs/backup/20261007/CONTROL_ACTION_MANIFEST.json](../../backup/20261007/CONTROL_ACTION_MANIFEST.json) | 10,340,581 B | 与主 action manifest 相同 |

## 文档保全

下列 DOCX 原件和最终合并文档均按原始字节归档在 workspace_backup/20261007/。最终合并文档经过 225 页检查；交接文档经过 13 页检查。238 页的汇总 QA 为 [LAYOUT_FINAL_QA_COVERAGE.json](../../../workspace_backup/20261007/tmp/v147_user_merge_20261007/LAYOUT_FINAL_QA_COVERAGE.json)，119,386 B，SHA-256 8692754e75ab91e7ef823f7501343bb476731923922c46b4bfa3679edc4b0f52；汇总结果全 PASS。

| 文档 | 归档路径 | 原始大小 | SHA-256 |
|---|---|---:|---|
| 用户提供的 RelicWeave_V1.47.docx | [workspace_backup/20261007/RelicWeave_V1.47.docx](../../../workspace_backup/20261007/RelicWeave_V1.47.docx) | 779,513 B | 41f1254e40a2ecabdcfa1c6583af2fce0ae1b0ab980d5f9179bbaf687b7be64b |
| RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx（最终合并稿） | [workspace_backup/20261007/RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx](../../../workspace_backup/20261007/RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx) | 786,150 B | 883c831648d0697f456228f4d862deda8a36ff9740ecd6aadb3a3ebfdfdffc7d |
| RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx | [workspace_backup/20261007/RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx](../../../workspace_backup/20261007/RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx) | 733,634 B | 15978a3956fa33e8048cc54c1dad6878a7e19d9c71b84415dcaf8732f041a3b4 |
| RelicWeave_V1.46_Implementation_Update_20261005.docx | [workspace_backup/20261007/RelicWeave_V1.46_Implementation_Update_20261005.docx](../../../workspace_backup/20261007/RelicWeave_V1.46_Implementation_Update_20261005.docx) | 738,618 B | 85f3bb0e6115e208ce51c666d77ee756a4e2b74d67e8d039283574bb6764b531 |
| RelicWeave_V1.44_Optimized_Complete_Plan.docx | [workspace_backup/20261007/RelicWeave_V1.44_Optimized_Complete_Plan.docx](../../../workspace_backup/20261007/RelicWeave_V1.44_Optimized_Complete_Plan.docx) | 546,163 B | 4507ead923d60cc8dc20c2a31e532394f4d8ab406a5703bf09eeb606ab6f6374 |
| PGFrag_VesselForge_Guide_v11.docx | [workspace_backup/20261007/PGFrag_VesselForge_Guide_v11.docx](../../../workspace_backup/20261007/PGFrag_VesselForge_Guide_v11.docx) | 67,529 B | 1eb926d3be9d081f236db2b0c47f573a9e283e51295e9bb2969b5c0d32224d19 |
| PGFrag_VesselForge_Guide_v12.docx | [workspace_backup/20261007/PGFrag_VesselForge_Guide_v12.docx](../../../workspace_backup/20261007/PGFrag_VesselForge_Guide_v12.docx) | 72,348 B | 8dc9eb4abeaf11161c049d1e798d529884ccffe2bdf638af1f5c301f2a0a4509 |
| RelicWeave_A12_VesselForge_PGFrag_Handover_20261007.docx | [docs/handover/20261007/RelicWeave_A12_VesselForge_PGFrag_Handover_20261007.docx](RelicWeave_A12_VesselForge_PGFrag_Handover_20261007.docx) | 64,641 B | c8b4e57340c7c9d485aeb5c6aa298ba90ac166870c9d8d0a7d414d35051f7fd2 |
| HANDOVER.md | [docs/handover/20261007/HANDOVER.md](HANDOVER.md) | 41,396 B | f226a153f8aed2da04e07298f1277cd74071370d52cf74a4967702c2792f7a53 |

A12 的 canonical 交接文件为 [HANDOVER.md](HANDOVER.md) 和 [RelicWeave_A12_VesselForge_PGFrag_Handover_20261007.docx](RelicWeave_A12_VesselForge_PGFrag_Handover_20261007.docx)。保留在 workspace_backup 中的 V1.47 输入件可从 [原始文档归档目录](../../../workspace_backup/20261007/) 及 WORKSPACE_SOURCE_MAP.json 找到。

## 本地归档

项目源码 ZIP 位于 workspace 的 local_backups/20261008/selected_project_sources_20261008_6c9830bd.zip，58,060,401 B，SHA-256 54f3cc323892c35c9d3ae41a373760b93220c54d1adee16d9a5262b5c7ffbaa7。其 receipt 为 selected_project_sources_20261008_6c9830bd.receipt.json，1,331 B，SHA-256 d66b6804e4e75b04e849e2d371e6be0d9edd319971321c13c86a034d54802f00。ZIP 包含 6,742 个唯一源码项、6,748 行源映射，全部条目哈希和字节数均通过校验，映射缺失为 0。

三个本地 bundle 含完整可达 Git 历史，均经 git bundle verify 和 list-heads 校验，退出码均为 0：

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| local_backups/20261008/pgfrag_21aa69dd131031944a3139b482abf6a0069da023.bundle | 141,433,241 B | 2e077621822345780217df12470562d1b18f0e6fec9bb1bf7aefa9d19a28e256 |
| local_backups/20261008/vesselforge_73116cf40bd8620e3142667dccd644cc16c47aac.bundle | 7,398,049 B | ef8ae54e0939f7e29a2ab1b22b7ad1b4dc9cb6c0ca003bb941e2f0c80896919b |
| local_backups/20261008/relicweave-synlab_8271f53ae668468368b7fc61de53e7e5502a112e.bundle | 111,367,478 B | ae4c37802f980f6e9a7c9a67931c65f7f119127830fa31ae19762aa515884c06 |

## 原路径映射及恢复说明

六个字体 QA helper 原本位于会被 Git 视作 runtime 的 font_runtime 路径。为保留脚本字节而不归档运行时目录，它们复制到 font_tools 别名目录；postverify 确认别名与原文件逐字节相同，原始路径、别名、归档目标及 SHA 映射在 WORKSPACE_SOURCE_MAP.json 中。六个文件是 create_font_probe.py、extract_fontfixed_01_locations.py、inspect_full_pdf_fonts.py、refine_fontfixed_locations_pdfplumber.py、run_font_probe_then_full.ps1 和 verify_pdf_font_probe.py。

两份历史 count-only 扫描报告保留在本地原路径及源码 ZIP 映射中，但被明确排除在 Git action manifest 之外；本回执不称它们已 Git 备份：

| 本地原路径 | 大小 | SHA-256 |
|---|---:|---|
| tmp/backup_coordinator/closeout_20261007/independent_credential_scan_current_inventory_20261007.json | 837 B | da7fd676389232bb0e2a4f694e90079787a3c6c4577a79655e14a5638303d5e8 |
| tmp/backup_coordinator/closeout_20261007/stale_coverage_before_fix_20261008/independent_final_credential_scan_20261008.json | 1,024 B | 512e6fd3c28d52a1577c3fc0e5086b03265b79f1a34e36c96e9f04af652f716a |

冻结执行器中的唯一 20 字节凭据扫描命中是 AWS 官方格式文档中的公开示例（执行器 line 237，样例 SHA-256 1a5d44a2dca19669d72edf4c4f1c27c4c1ca4b4408fbb17f6ce4ad452d78ddb3），与 [AWS 官方文档](https://docs.aws.amazon.com/sdkref/latest/guide/file-format.html)示例匹配。该判断只适用于此来源和该指纹，没有扩大为通用豁免。

恢复本地 bundle 时，先比较文件哈希，再克隆到尚不存在的新目录，最后在已克隆仓库上下文中验证 bundle。例如：

    Get-FileHash -LiteralPath "C:\Users\xiemo\Desktop\ShardForge\local_backups\20261008\pgfrag_21aa69dd131031944a3139b482abf6a0069da023.bundle" -Algorithm SHA256
    git -c core.longpaths=true -c core.autocrlf=false clone --branch backup/forge-work-20261003 --single-branch "C:\Users\xiemo\Desktop\ShardForge\local_backups\20261008\pgfrag_21aa69dd131031944a3139b482abf6a0069da023.bundle" "C:\restore\pgfrag"
    git -C "C:\restore\pgfrag" bundle verify "C:\Users\xiemo\Desktop\ShardForge\local_backups\20261008\pgfrag_21aa69dd131031944a3139b482abf6a0069da023.bundle"

克隆目标目录需不存在；这些示例不会覆盖已有 checkout。比较 Get-FileHash 的结果与上方 PGFrag bundle 所列 SHA-256。

也可从上方提交链接克隆 GitHub 分支。需要复原 workspace 原路径和原始字节时，按 WORKSPACE_SOURCE_MAP.json 使用 source path、archive destination 和 SHA 映射。Windows 上仅对命令使用 core.longpaths=true 和 core.autocrlf=false；本次没有写入全局或仓库级 Git/注册表配置。

## 执行边界

初次 SynLab 暂存遇到 Windows 长路径错误。经逐项确认精确的 4,736 个批准路径后，只在恢复进程内启用 core.longpaths=true。冻结执行器在提交前的 ls-remote 读取遇到 Schannel 连接关闭错误且没有返回码；该读取没有被记为成功，也没有据此推断远端状态。随后使用相同冻结执行器和已确认的批准清单完成检查及暂存，并通过仅对该次提交生效的 A12 SynLab 身份和 core.autocrlf=false/core.longpaths=true 完成本地提交。普通 non-force push 使用 HTTP/1.1 及有限低速阈值，实际 rc=0；紧随其后的 bounded ls-remote rc=0，确认远端提交与本地一致。

恢复时仅在内存中把参数 supplementary_root_go_confirmed 适配到冻结执行器所读取的 root_go_supplementary_confirmed，两个值均为已批准的相同 SHA。冻结执行器 SHA-256 为 9a27e1a9980fb99c144ee3dd63fe3c38405aa9b78eb03179c3ebceaba7cc1306，执行源码未被修改。提交及网络操作的原始日志和 SHA 均记录在 execution_receipt.json。

仓库 bundle 与这些归档不包含本机 Python、Git、CAD 或文档渲染运行时、虚拟环境、node_modules、缓存和安装器；恢复环境时需在目标机器安装相应工具。归档记录的是项目源码与证据快照，不证明任何未验收源、实验或计算具有物理、材料、几何或产品资格。
