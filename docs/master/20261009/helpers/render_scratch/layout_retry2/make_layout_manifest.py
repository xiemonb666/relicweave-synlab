import hashlib
import json
import re
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path

TASK = Path(__file__).resolve().parents[2]
WORKSPACE = TASK.parent.parent
DOCX = WORKSPACE / "RelicWeave_V1.48_ContractAligned.docx"
RENDER = TASK / "final_render_layout"
PDF = RENDER / "RelicWeave_V1.48_ContractAligned.pdf"
OUT = RENDER / "render_manifest.json"
PDFINFO = Path(r"C:\Users\xiemo\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdfinfo.exe")


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if OUT.exists():
    raise FileExistsError(OUT)
if not DOCX.exists() or not PDF.exists():
    raise FileNotFoundError("final DOCX or emitted PDF is missing")
pngs = sorted(RENDER.glob("page-*.png"), key=lambda p: int(re.search(r"page-(\d+)\.png$", p.name).group(1)))
page_numbers = [int(re.search(r"page-(\d+)\.png$", p.name).group(1)) for p in pngs]
if page_numbers != list(range(1, 229)):
    raise ValueError(f"expected 228 contiguous page PNGs, found {page_numbers[:4]}...{page_numbers[-4:] if page_numbers else []}")

pdfinfo = subprocess.run([str(PDFINFO), str(PDF)], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout
pages_match = re.search(r"^Pages:\s+(\d+)", pdfinfo, re.MULTILINE)
size_match = re.search(r"^Page size:\s+(.+)$", pdfinfo, re.MULTILINE)
if not pages_match or not size_match or int(pages_match.group(1)) != len(pngs):
    raise ValueError("PDF page count does not match rendered page images")

page_records = []
for number, path in zip(page_numbers, pngs):
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        raise ValueError(f"invalid PNG page: {path}")
    width, height = struct.unpack(">II", data[16:24])
    if (width, height) != (1547, 2002):
        raise ValueError(f"unexpected PNG dimensions on page {number}: {(width, height)}")
    page_records.append({
        "page": number,
        "path": str(path.resolve()),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "dimensions_px": [width, height],
    })

manifest = {
    "schema": "final_render_manifest.v1",
    "status": "PASS",
    "freeze_label": "FINAL_RENDER_FROZEN",
    "visual_qa_status": "WAITING_FOR_ROOT_FINAL_QA",
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "renderer": {
        "exit_code": 0,
        "path": r"C:\Users\xiemo\.codex\plugins\cache\openai-primary-runtime\documents\26.1007.11041\skills\documents\render_docx.py",
        "libreoffice": r"C:\Users\xiemo\Desktop\ShardForge\third_party\doc-render-runtime\LibreOffice-26.8.0\program\soffice.exe",
        "scratch": str((TASK / "render_scratch" / "layout_retry2").resolve()),
        "args": ["--output_dir", str(RENDER.resolve()), "--emit_pdf", "--verbose"],
    },
    "docx": {"path": str(DOCX.resolve()), "bytes": DOCX.stat().st_size, "sha256": sha(DOCX)},
    "pdf": {
        "path": str(PDF.resolve()),
        "bytes": PDF.stat().st_size,
        "sha256": sha(PDF),
        "page_count": int(pages_match.group(1)),
        "page_size": size_match.group(1).strip(),
    },
    "render_directory": str(RENDER.resolve()),
    "png_count": len(pngs),
    "page_numbers": {"unique_count": len(set(page_numbers)), "duplicates": [], "missing": [], "out_of_range": [], "pdf_page_count_matches_pngs": True},
    "integrity_errors": [],
    "pages": page_records,
}
OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"manifest": str(OUT.resolve()), "docx_sha256": manifest["docx"]["sha256"], "pdf_sha256": manifest["pdf"]["sha256"], "pdf_pages": manifest["pdf"]["page_count"], "png_count": manifest["png_count"], "png_sha256_page_118": page_records[117]["sha256"], "png_sha256_page_120": page_records[119]["sha256"]}, ensure_ascii=False, indent=2))
