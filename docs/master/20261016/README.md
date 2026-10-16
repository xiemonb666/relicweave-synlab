# RelicWeave V1.48 工程进度修订构建记录

本目录中的 `RelicWeave_V1.48_Engineering_Update_20261016.docx` 是从只读 V1.48 归档副本构建的独立修订件。源 SHA-256：`23a42e5f4cca40ef733edc9365c15bd0d5fdff647f8821fddec9c649e52b1455`。输出 SHA-256：`b134f7a781b62bbf8946a269343d8eeedbc87c2697c83dcb55e0ab83cf97fd62`。

修订涉及 `word/document.xml` 与 `word/footer2.xml`：前者增加截至 2026-10-16 的工程状态与交接快照，更新 1.2 当前事实台账，补充 A12、VesselForge、PG-Frag 的当前状态交叉引用，并把 2026-10-07/09 的状态明确保留为历史；后者只把页脚日期改为 2026年10月16日，PAGE/NUMPAGES 字段运行保持不变。没有更改研究主线、A01–A36 历史判决、MC01–MC07 合同状态或任何物理实验结果。V1.48 版号保留；原 2026-10-09 文档未覆盖。

`source_part_preservation.json` 逐项记录 ZIP part payload 的 SHA-256；仅 `word/document.xml` 和 `word/footer2.xml` 属于声明修订范围，其余 part 的解压内容均与源件字节一致。`anchor_history_verification.json` 记录原始段落锚点、历史文本、1.2 表原行与其余 194 张表的未改验证，并确认正文 XML 与渲染 v1 完全相同、页脚字段运行保留。

构建命令（从工作区根目录运行）：

```powershell
& "C:\Users\xiemo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -X utf8 "C:\Users\xiemo\Desktop\ShardForge\tmp\engineering_handover_20261016\build_v148_update.py" --input "C:\Users\xiemo\Desktop\ShardForge\RelicWeave_V1.48_ContractAligned.docx" --output "C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\docs\master\20261016\RelicWeave_V1.48_Engineering_Update_20261016.docx" --receipt-dir "C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\docs\master\20261016" --overwrite
```

状态：**最终版全量渲染与 231/231 页视觉检查通过**，主代理已复核关键状态页和有跨页备注的页面。更新日期及页码字段也经全 231 页 PDF 文本独立读回；详见 [FINAL_RENDER_QA.json](FINAL_RENDER_QA.json)。图像和 PDF 为本地 QA 中间件，交付文件为 DOCX。

可移植构建入口（从 A12 仓库根目录，Python 3.11+，另安装 `python-docx` 与 `lxml`）：

```powershell
python docs/master/20261016/build_v148_update.py --input docs/master/20261009/RelicWeave_V1.48_ContractAligned.docx --output path/to/RelicWeave_V1.48_Engineering_Update_20261016.docx --receipt-dir path/to/build-receipts
```

该命令用于将来重建，不属于恢复开发或运行求解器。构建器会校验原档哈希；重新构建后须重新渲染和检查，当前 QA 仅绑定上方最终 DOCX 哈希。
