import collections
import json
import re
import sys
import unicodedata
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

from pypdf import PdfReader


OLD_DOCX = Path(r"C:\Users\xiemo\Desktop\ShardForge\RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx")
UPDATED_DOCX = Path(r"C:\Users\xiemo\Desktop\ShardForge\RelicWeave_V1.46_Implementation_Update_20261005.docx")
PDF = Path(r"C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\doc_render_fontfixed_01\RelicWeave_V1.46_Implementation_Update_20261005.pdf")
OUT_DIR = Path(r"C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\doc_renderer_environment\font_runtime")
PDF_TEXT = OUT_DIR / "fontfixed_01_pdf_text_by_page.txt"
REPORT = OUT_DIR / "fontfixed_01_new_paragraph_locations.json"

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
TOKEN_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)


def para_text(paragraph: ET.Element) -> str:
    parts = []
    for element in paragraph.iter():
        if element.tag == f"{{{NS['w']}}}t":
            parts.append(element.text or "")
        elif element.tag == f"{{{NS['w']}}}tab":
            parts.append("\t")
        elif element.tag in (f"{{{NS['w']}}}br", f"{{{NS['w']}}}cr"):
            parts.append("\n")
    return "".join(parts)


def paragraphs(docx_path: Path) -> list[str]:
    with zipfile.ZipFile(docx_path, "r") as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    body = root.find("w:body", NS)
    if body is None:
        raise RuntimeError(f"Missing w:body in {docx_path}")
    return [para_text(p) for p in body.iter(f"{{{NS['w']}}}p")]


def comparison_key(value: str) -> str:
    value = unicodedata.normalize("NFC", value).replace("\u00ad", "")
    return re.sub(r"\s+", " ", value).strip()


def tokens(value: str) -> list[str]:
    value = unicodedata.normalize("NFKC", value).replace("\u00ad", "")
    return [token.casefold() for token in TOKEN_RE.findall(value)]


def find_subsequence(haystack: list[str], needle: list[str]) -> list[int]:
    if not needle or len(needle) > len(haystack):
        return []
    starts = []
    first = needle[0]
    limit = len(haystack) - len(needle) + 1
    for start in range(limit):
        if haystack[start] == first and haystack[start : start + len(needle)] == needle:
            starts.append(start)
    return starts


def locate(para_tokens: list[str], page_tokens: list[list[str]]) -> dict:
    if not para_tokens:
        return {"pages": [], "method": "empty"}
    flat = []
    flat_pages = []
    for page_num, page in enumerate(page_tokens, start=1):
        flat.extend(page)
        flat_pages.extend([page_num] * len(page))

    starts = find_subsequence(flat, para_tokens)
    if starts:
        spans = []
        for start in starts:
            end = start + len(para_tokens) - 1
            spans.append((flat_pages[start], flat_pages[end]))
        unique_spans = sorted(set(spans))
        pages = sorted({p for span in unique_spans for p in range(span[0], span[1] + 1)})
        return {"pages": pages, "spans": [list(span) for span in unique_spans], "method": "full_token_sequence"}

    anchor_len = min(12, max(5, len(para_tokens) // 4))
    first_anchor = para_tokens[:anchor_len]
    last_anchor = para_tokens[-anchor_len:]
    first_hits = []
    last_hits = []
    for page_num, page in enumerate(page_tokens, start=1):
        if find_subsequence(page, first_anchor):
            first_hits.append(page_num)
        if find_subsequence(page, last_anchor):
            last_hits.append(page_num)
    overlap = sorted(set(first_hits) & set(last_hits))
    if overlap:
        return {"pages": overlap, "method": "first_last_anchors_same_page", "anchor_tokens": anchor_len}
    if first_hits and last_hits:
        candidates = [(a, b) for a in first_hits for b in last_hits if a <= b]
        if candidates:
            span = min(candidates, key=lambda pair: pair[1] - pair[0])
            return {"pages": list(range(span[0], span[1] + 1)), "spans": [list(span)], "method": "first_last_anchors_split", "anchor_tokens": anchor_len}
    longest = min(8, len(para_tokens))
    for n in range(longest, 2, -1):
        hits = []
        for offset in range(0, len(para_tokens) - n + 1):
            anchor = para_tokens[offset : offset + n]
            page_hits = [page_num for page_num, page in enumerate(page_tokens, start=1) if find_subsequence(page, anchor)]
            if page_hits:
                hits.append((n, offset, anchor, page_hits))
        if hits:
            hits.sort(key=lambda item: (-item[0], item[1], len(item[3])))
            best = hits[0]
            return {"pages": best[3], "method": "longest_contiguous_anchor", "anchor_tokens": best[0], "anchor_offset": best[1]}
    return {"pages": [], "method": "not_found"}


def main() -> None:
    old_paras = paragraphs(OLD_DOCX)
    new_paras = paragraphs(UPDATED_DOCX)
    remaining = collections.Counter(comparison_key(p) for p in old_paras)
    added = []
    for index, text in enumerate(new_paras, start=1):
        key = comparison_key(text)
        if remaining[key] > 0:
            remaining[key] -= 1
        elif key:
            added.append({"docx_paragraph_index": index, "text": text})

    reader = PdfReader(str(PDF))
    extracted_pages = [(page.extract_text() or "") for page in reader.pages]
    with PDF_TEXT.open("w", encoding="utf-8") as f:
        for page_num, text in enumerate(extracted_pages, start=1):
            f.write(f"\n===== PAGE {page_num} =====\n")
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
    page_tokens = [tokens(text) for text in extracted_pages]
    for item in added:
        item["token_count"] = len(tokens(item["text"]))
        item["location"] = locate(tokens(item["text"]), page_tokens)

    report = {
        "old_docx": str(OLD_DOCX),
        "updated_docx": str(UPDATED_DOCX),
        "rendered_pdf": str(PDF),
        "pdf_page_count": len(reader.pages),
        "old_body_paragraph_count": len(old_paras),
        "updated_body_paragraph_count": len(new_paras),
        "new_nonempty_paragraph_count": len(added),
        "pdf_text_by_page": str(PDF_TEXT),
        "paragraphs": added,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "pdf_page_count": report["pdf_page_count"],
        "old_body_paragraph_count": len(old_paras),
        "updated_body_paragraph_count": len(new_paras),
        "new_nonempty_paragraph_count": len(added),
        "report": str(REPORT),
        "pdf_text_by_page": str(PDF_TEXT),
        "paragraph_locations": [
            {
                "docx_paragraph_index": x["docx_paragraph_index"],
                "token_count": x["token_count"],
                "pages": x["location"]["pages"],
                "method": x["location"]["method"],
            }
            for x in added
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
