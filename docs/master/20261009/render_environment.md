# 总方案 DOCX 渲染环境交接

本次只读核对了渲染技能、运行时与 10 月 7 日既有渲染和全页 QA；没有启动渲染，没有改主 DOCX 或源码，也没有执行写入标记。

主文档 `RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx` 与既有 QA 输入 `fresh_merge_layout_final_candidate.docx` 的 SHA-256 相同：`883c831648d0697f456228f4d862deda8a36ff9740ecd6aadb3a3ebfdfdffc7d`。因此现有 225 页基线 QA 对应当前主文档的同一份内容。

既有目录 `tmp/v147_user_merge_20261007/fresh_merge_layout_final_render` 有 225 张 PNG 和一份 225 页 Letter PDF。PNG 为 1547 × 2002 像素。`LAYOUT_FINAL_QA_COVERAGE.json` 状态为 PASS：13 段逐页检查 225/225、PNG SHA 匹配 225/225、通过 225 页、问题 0。完整分段列于本文件末尾及配套 JSON。

基线 QA 记录了来源 DOCX SHA 和逐页 PNG SHA，但没有记录 PDF SHA。新版本每页记录应包含最终 DOCX SHA、同次渲染 PDF SHA、该页 PNG SHA、页号、审阅人、原始细节检查标志、状态和问题。这样可以把每页的人工结论绑定到确切的三个文件。

## 可复用运行时

- Workspace dependency loader 确认使用 bundled Python：`C:/Users/xiemo/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`，Node：`C:/Users/xiemo/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe`。
- 当前权威 renderer：`C:/Users/xiemo/.codex/plugins/cache/openai-primary-runtime/documents/26.1007.11041/skills/documents/render_docx.py`。
- 已找到且存在的 bundled LibreOffice：`C:/Users/xiemo/Desktop/ShardForge/third_party/doc-render-runtime/LibreOffice-26.8.0/program/soffice.exe`。最新 10 月 7 日 `render.log` 显示渲染实际调用了这一绝对路径；无需安装或重新准备环境。
- Poppler 在 bundled dependencies：`C:/Users/xiemo/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin`；其中 `pdfinfo.exe` 和 `pdftoppm.exe` 存在。
- Windows 版 renderer 从 PATH 解析 `soffice.exe`，没有 `--soffice` 参数。因此在渲染进程 PATH 中把上面的 LibreOffice `program` 目录放第一，Poppler 第二，`C:/Windows/System32` 第三。

## 建议的最终渲染调用

输出目录建议用新建的 `tmp/master_contract_update_20261009/final_render`，scratch 用 `tmp/master_contract_update_20261009/render_scratch`。开始前确认输出目录为空，避免把旧页图混进新版本。

renderer 默认最大尺寸是 1600 × 2000 像素，并按 DOCX 页面尺寸计算 DPI。既有 Letter 页图为 1547 × 2002；保持默认尺寸并逐页以 original detail 打开，满足清晰度要求。除非看到页面尺寸异常，不要传 `--dpi`，因为它会跳过自动计算。

用 `--emit_pdf` 保存同次渲染的中间 PDF，便于记录其 SHA；用 `--verbose` 保留 LibreOffice 调用日志。示例 PowerShell 环境与调用：

    $python = 'C:/Users/xiemo/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    $renderer = 'C:/Users/xiemo/.codex/plugins/cache/openai-primary-runtime/documents/26.1007.11041/skills/documents/render_docx.py'
    $loProgram = 'C:/Users/xiemo/Desktop/ShardForge/third_party/doc-render-runtime/LibreOffice-26.8.0/program'
    $poppler = 'C:/Users/xiemo/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin'
    $scratch = 'C:/Users/xiemo/Desktop/ShardForge/tmp/master_contract_update_20261009/render_scratch'
    $out = 'C:/Users/xiemo/Desktop/ShardForge/tmp/master_contract_update_20261009/final_render'
    $env:TEMP = $scratch
    $env:TMP = $scratch
    $env:TMPDIR = $scratch
    $env:XDG_CONFIG_HOME = "$scratch/xdg_config"
    $env:XDG_CACHE_HOME = "$scratch/xdg_cache"
    $env:APPDATA = "$scratch/appdata"
    $env:LOCALAPPDATA = "$scratch/localappdata"
    $env:PATH = "$loProgram;$poppler;$env:SystemRoot/System32"
    & $python $renderer $finalDocx --output_dir $out --emit_pdf --verbose

renderer 会为 LibreOffice 自动创建唯一 `soffice_profile_*` 和转换临时目录，并为子进程设置独立 HOME；调用方不必手工维护 LibreOffice profile。旧日志里有 `Could not find platform independent libraries <prefix>`，但转换和 PNG 输出成功，随后完整 QA 也通过；判定本次结果时仍应核对退出码、页数和文件完整性。

## 逐页审阅安排

对最终版所有 PNG 单页打开、原始细节审阅，不用 contact sheet、OCR 或抽查替代。按每段 12–18 页分给 Luna；225 页可直接沿用已经验证过的 13 段：

- 001–018
- 019–036
- 037–054
- 055–072
- 073–090
- 091–108
- 109–126
- 127–144
- 145–162
- 163–180
- 181–198
- 199–216
- 217–225

每个页记录需绑定最终 DOCX SHA、同次 PDF SHA 和 PNG SHA；逐页写明 inspected=true、pass/issue、问题说明和 reviewer。主代理再单独打开包含实际改动的页；如果改动影响分页，也看对应的分页边界页。

## 字体证据与注意项

当前 DOCX 的 OOXML 字体引用包含 Liberation Sans、DejaVu Sans Mono、Noto Sans SC/CJK SC、Cambria 和 MS 明朝。当前 Windows 字体枚举能看到 Noto Sans SC，但看不到 Liberation Sans、DejaVu Sans Mono 或 Droid Sans Fallback。现有 V1.46 字体收据证明旧任务曾用当前会话临时注册 Liberation Sans 和 Droid Sans Fallback，通过一页探针和 205 页 PDF 字体嵌入检查，随后把五个字体全部移除。

这份字体收据不是 10 月 7 日 V1.47 PDF 的字体清单；10 月 7 日页面视觉 QA 已逐页通过，但日志没有记录字体注册状态或 PDF 字体清单。沿用现有渲染工具链即可；不要重跑旧安装/setup 脚本。若最终改动页出现字形或换行异常，再检查保留的字体资产和旧脚本所用的会话级注册流程。

## 写入标记

文档技能的 marker 实际路径为 `C:/Users/xiemo/.codex/plugins/cache/openai-primary-runtime/documents/26.1007.11041/skills/documents/container_tools/mark_artifact_operation_started.mjs`。writer 预计输出一个 DOCX，第一次编辑命令前应恰好执行一次：

    & 'C:/Users/xiemo/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' 'C:/Users/xiemo/.codex/plugins/cache/openai-primary-runtime/documents/26.1007.11041/skills/documents/container_tools/mark_artifact_operation_started.mjs' --operation-kind edit --expected-output-count 1 --output-format docx

本次子任务没有执行 marker。
