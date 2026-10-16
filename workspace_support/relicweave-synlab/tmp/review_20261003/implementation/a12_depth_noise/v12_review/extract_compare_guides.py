from __future__ import annotations

import difflib
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}
W = "{" + NS["w"] + "}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_style_names(doc: zipfile.ZipFile) -> dict[str, str]:
    try:
        root = ET.fromstring(doc.read("word/styles.xml"))
    except KeyError:
        return {}
    result = {}
    for style in root.findall("w:style", NS):
        style_id = style.get(W + "styleId", "")
        name = style.find("w:name", NS)
        if style_id:
            result[style_id] = name.get(W + "val", style_id) if name is not None else style_id
    return result


def paragraph_text(node: ET.Element) -> str:
    parts = []
    for child in node.iter():
        if child.tag == W + "t":
            parts.append(child.text or "")
        elif child.tag == W + "tab":
            parts.append("\t")
        elif child.tag in (W + "br", W + "cr"):
            parts.append("\n")
    return "".join(parts).strip()


def paragraph_style(node: ET.Element, styles: dict[str, str]) -> tuple[str, str]:
    ppr = node.find("w:pPr", NS)
    pstyle = ppr.find("w:pStyle", NS) if ppr is not None else None
    style_id = pstyle.get(W + "val", "") if pstyle is not None else ""
    return style_id, styles.get(style_id, style_id)


def heading_like(style_id: str, style_name: str, text: str) -> bool:
    return (style_id.lower().startswith("heading")
            or style_name.lower().startswith("heading")
            or style_name.lower() in {"title", "subtitle"}
            or bool(re.match(r"^(第[一二三四五六七八九十0-9]+章|附录\s*[A-ZＡ-Ｚ0-9]|Appendix\s+[A-Z0-9]|Chapter\s+\d+)", text, re.I)))


def cell_text(cell: ET.Element) -> str:
    return " / ".join(text for text in
                      (paragraph_text(p) for p in cell.findall(".//w:p", NS)) if text)


def extract(path: Path, out_text: Path) -> dict:
    with zipfile.ZipFile(path) as doc:
        root = ET.fromstring(doc.read("word/document.xml"))
        styles = read_style_names(doc)
    body = root.find("w:body", NS)
    if body is None:
        raise RuntimeError(f"No w:body in {path}")
    blocks: list[str] = []
    headings: list[dict[str, str]] = []
    paragraph_count = 0
    table_paragraph_count = 0
    table_count = 0
    row_count = 0
    cell_count = 0
    for child in list(body):
        if child.tag == W + "p":
            text = paragraph_text(child)
            if not text:
                continue
            paragraph_count += 1
            style_id, style_name = paragraph_style(child, styles)
            if heading_like(style_id, style_name, text):
                headings.append({"style_id": style_id, "style_name": style_name,
                                 "text": text})
            blocks.append(f"[P style={style_id or 'Normal'}] {text}")
        elif child.tag == W + "tbl":
            table_count += 1
            for row_idx, row in enumerate(child.findall("w:tr", NS), start=1):
                cells = row.findall("w:tc", NS)
                cell_count += len(cells)
                row_count += 1
                table_paragraph_count += sum(
                    bool(paragraph_text(p))
                    for cell in cells for p in cell.findall(".//w:p", NS))
                values = [cell_text(cell) for cell in cells]
                blocks.append(f"[TABLE {table_count} ROW {row_idx}] " + " || ".join(values))
    out_text.write_text("\n".join(blocks) + "\n", encoding="utf-8")
    return {
        "source": str(path),
        "sha256": sha256(path),
        "extracted_text_sha256": sha256(out_text),
        "paragraphs_nonempty": paragraph_count + table_paragraph_count,
        "body_paragraphs_nonempty": paragraph_count,
        "table_cell_paragraphs_nonempty": table_paragraph_count,
        "tables": table_count,
        "table_rows": row_count,
        "table_cells": cell_count,
        "ordered_blocks": len(blocks),
        "headings": headings,
        "extracted_text": str(out_text),
    }


def main() -> int:
    v11, v12, out_dir = map(Path, sys.argv[1:4])
    out_dir.mkdir(parents=True, exist_ok=True)
    m11 = extract(v11, out_dir / "guide_v11_extracted.txt")
    m12 = extract(v12, out_dir / "guide_v12_extracted.txt")
    b11 = (out_dir / "guide_v11_extracted.txt").read_text(encoding="utf-8").splitlines()
    b12 = (out_dir / "guide_v12_extracted.txt").read_text(encoding="utf-8").splitlines()
    matcher = difflib.SequenceMatcher(a=b11, b=b12, autojunk=False)
    opcodes = matcher.get_opcodes()
    changes = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue
        changes.append({"type": tag, "v11_lines": [i1 + 1, i2], "v12_lines": [j1 + 1, j2],
                        "removed": b11[i1:i2], "added": b12[j1:j2]})
    diff_lines = list(difflib.unified_diff(b11, b12, fromfile="guide_v11", tofile="guide_v12",
                                          lineterm=""))
    (out_dir / "guide_v11_v12.diff").write_text("\n".join(diff_lines) + "\n",
                                                encoding="utf-8")
    h11 = [h["text"] for h in m11["headings"]]
    h12 = [h["text"] for h in m12["headings"]]
    metadata = {"v11": m11, "v12": m12,
                "heading_changes": {
                    "added": [x for x in h12 if x not in h11],
                    "removed": [x for x in h11 if x not in h12],
                },
                "diff": {"opcode_count": len(opcodes),
                         "changed_opcode_count": len(changes),
                         "added_line_count": sum(len(x["added"]) for x in changes),
                         "removed_line_count": sum(len(x["removed"]) for x in changes),
                         "changes": changes}}
    (out_dir / "guide_v11_v12_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = [
        "# PGFrag Guide v11/v12 extraction and structural diff",
        "",
        f"- v11 DOCX SHA256: `{m11['sha256']}`",
        f"- v12 DOCX SHA256: `{m12['sha256']}`",
        f"- v11 text SHA256: `{m11['extracted_text_sha256']}`",
        f"- v12 text SHA256: `{m12['extracted_text_sha256']}`",
        f"- v11 counts: {m11['paragraphs_nonempty']} nonempty paragraphs, {m11['tables']} tables, "
        f"{m11['table_rows']} table rows, {m11['ordered_blocks']} ordered blocks.",
        f"- v12 counts: {m12['paragraphs_nonempty']} nonempty paragraphs, {m12['tables']} tables, "
        f"{m12['table_rows']} table rows, {m12['ordered_blocks']} ordered blocks.",
        f"- Text diff: {len(changes)} changed opcode groups, "
        f"{metadata['diff']['added_line_count']} added blocks, "
        f"{metadata['diff']['removed_line_count']} removed blocks.",
        "",
        "## v11 headings",
        "",
        *[f"- {text}" for text in h11],
        "",
        "## v12 headings",
        "",
        *[f"- {text}" for text in h12],
        "",
        "## Heading additions/removals",
        "",
        "Added: " + ("; ".join(metadata["heading_changes"]["added"]) or "none"),
        "Removed: " + ("; ".join(metadata["heading_changes"]["removed"]) or "none"),
        "",
        "This is a mechanical OOXML-order extraction and text diff; it does not interpret technical changes.",
        "See `guide_v11_v12.diff` and both extracted text files for evidence.",
    ]
    (out_dir / "guide_v11_v12_summary.md").write_text("\n".join(summary) + "\n",
                                                       encoding="utf-8")
    print(json.dumps({"v11_sha256": m11["sha256"], "v12_sha256": m12["sha256"],
                      "v11_paragraphs": m11["paragraphs_nonempty"],
                      "v12_paragraphs": m12["paragraphs_nonempty"],
                      "v11_tables": m11["tables"], "v12_tables": m12["tables"],
                      "changed_groups": len(changes),
                      "summary": str(out_dir / "guide_v11_v12_summary.md")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
