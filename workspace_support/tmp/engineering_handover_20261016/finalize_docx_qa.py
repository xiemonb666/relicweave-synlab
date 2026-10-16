"""Publish final review receipts without changing the reviewed DOCX."""
from pathlib import Path
import hashlib
import json
import shutil
import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "tmp/engineering_handover_20261016"
DEST = ROOT / "relicweave-synlab/docs/master/20261016"
NAME = "RelicWeave_V1.48_Engineering_Update_20261016.docx"
EXPECTED = "b134f7a781b62bbf8946a269343d8eeedbc87c2697c83dcb55e0ab83cf97fd62"
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(DEST / NAME) == EXPECTED
reviews = sorted((WORK / "qa").glob("qa_v2_*.json"))
assert len(reviews) == 8
coverage = []
records = []
for path in reviews:
    data = json.loads(path.read_text(encoding="utf-8"))
    pages = data["checked_pages"]
    assert not data.get("defects"), (path, data.get("defects"))
    assert "pass" in data["verdict"].lower(), (path, data["verdict"])
    coverage.extend(pages)
    records.append({"file": "qa_views/" + path.name, "sha256": sha(path), "pages": pages})
assert sorted(coverage) == list(range(1, 232)), "Missing or duplicate page reviews"
pdf = WORK / "render_v2" / NAME.replace(".docx", ".pdf")
with pdfium.PdfDocument(pdf) as document:
    assert len(document) == 231
    footer_failures = []
    for number, page in enumerate(document, 1):
        textpage = page.get_textpage()
        # LibreOffice writes running header/footer before body in PDF text order.
        prefix = "".join(textpage.get_text_range()[:120].split())
        if "2026年10月16日" not in prefix or f"{number}/231" not in prefix:
            footer_failures.append(number)
        textpage.close()
        page.close()
    assert not footer_failures, footer_failures
receipt = {
    "as_of": "2026-10-16",
    "docx": NAME,
    "docx_sha256": EXPECTED,
    "page_count": 231,
    "render": "render_v2; LibreOffice project runtime and canonical render_docx helper",
    "visual_pages_reviewed": sorted(coverage),
    "unique_visual_page_count": len(set(coverage)),
    "review_parts": records,
    "root_independent_visual_spot_checks": [1,2,3,4,5,65,121,122,130,131,180,188,189,198,199,208,209,211,212,215,216,222,223,224,225],
    "footer_pdf_text_readback": {"engine": "pypdfium2", "checked_pages": 231, "updated_date_and_page_fields_present_all_pages": True},
    "root_adjudication": [
        "Body whitespace and readable paragraph/table/code continuations are retained; no blocking clipping or overlap was found.",
        "The reported page 180 missing header/footer was independently disproved by reopening the exact final PNG; the reviewer corrected its report.",
        "Some reviewer footer notes said date appeared only on every third page. Full PDF text readback verifies the updated date and page/total fields on all 231 pages; these footer notes do not describe an output defect."
    ],
    "source_preservation": "Only word/document.xml and word/footer2.xml changed; see source_part_preservation.json and anchor_history_verification.json.",
    "verdict": "PASS_FULL_FINAL_RENDER_AND_VISUAL_QA",
    "limits": "Layout/status revision review, not a revalidation of every historical scientific claim, external reference or physical experiment. PNG/PDF QA intermediates remain local."
}
(DEST / "qa_views").mkdir(exist_ok=True)
for path in reviews:
    shutil.copy2(path, DEST / "qa_views" / path.name)
(DEST / "FINAL_RENDER_QA.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
for name in ["source_part_preservation.json", "anchor_history_verification.json"]:
    p = DEST / name
    data = json.loads(p.read_text(encoding="utf-8"))
    data["render_status"] = receipt["verdict"]
    data["final_render_qa_receipt"] = "FINAL_RENDER_QA.json"
    if "delivery_status" in data:
        data["delivery_status"] = "REVIEWED_READY_FOR_GITHUB_DELIVERY"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
readme = DEST / "README.md"
text = readme.read_text(encoding="utf-8")
text = text.replace("状态：**等待主代理完成全量渲染、逐页 PNG 检查和最终布局 QA**。当前不将本文件报告为已通过视觉验收或最终发布。", "状态：**最终版全量渲染与 231/231 页视觉检查通过**，主代理已复核关键状态页和有跨页备注的页面。更新日期及页码字段也经全 231 页 PDF 文本独立读回；详见 [FINAL_RENDER_QA.json](FINAL_RENDER_QA.json)。图像和 PDF 为本地 QA 中间件，交付文件为 DOCX。")
text += "\n可移植构建入口（从 A12 仓库根目录，Python 3.11+，另安装 `python-docx` 与 `lxml`）：\n\n```powershell\npython docs/master/20261016/build_v148_update.py --input docs/master/20261009/RelicWeave_V1.48_ContractAligned.docx --output path/to/RelicWeave_V1.48_Engineering_Update_20261016.docx --receipt-dir path/to/build-receipts\n```\n\n该命令用于将来重建，不属于恢复开发或运行求解器。构建器会校验原档哈希；重新构建后须重新渲染和检查，当前 QA 仅绑定上方最终 DOCX 哈希。\n"
readme.write_text(text, encoding="utf-8")
shutil.copy2(WORK / "build_v148_update.py", DEST / "build_v148_update.py")
shutil.copy2(DEST / NAME, ROOT / NAME)
assert sha(ROOT / NAME) == EXPECTED
print(json.dumps({"docx_sha256": EXPECTED, "visual_pages": len(set(coverage)), "footer_pages":231, "verdict": receipt["verdict"]}))
