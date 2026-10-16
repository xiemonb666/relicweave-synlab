#!/usr/bin/env python3
"""Read-only OOXML text and structural comparison for the three RelicWeave files."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}
W = "{" + NS["w"] + "}"
REL = "{" + NS["pr"] + "}"


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def xml_text(el: ET.Element) -> str:
    out: list[str] = []
    for node in el.iter():
        name = local(node.tag)
        if name in ("t", "delText", "instrText"):
            out.append(node.text or "")
        elif name == "tab":
            out.append("\t")
        elif name in ("br", "cr"):
            out.append("\n")
    return "".join(out)


def paragraph_props(p: ET.Element) -> tuple[str, str | None]:
    ppr = p.find("w:pPr", NS)
    style = ""
    outline = None
    if ppr is not None:
        ps = ppr.find("w:pStyle", NS)
        if ps is not None:
            style = ps.get(W + "val", "")
        ol = ppr.find("w:outlineLvl", NS)
        if ol is not None:
            outline = ol.get(W + "val")
    return style, outline


def paragraph_bookmarks(p: ET.Element) -> list[dict[str, str]]:
    vals = []
    for el in p.iter():
        if local(el.tag) in ("bookmarkStart", "bookmarkEnd"):
            vals.append({
                "kind": local(el.tag),
                "id": el.get(W + "id", ""),
                "name": el.get(W + "name", ""),
            })
    return vals


def paragraph_hyperlinks(p: ET.Element) -> list[str]:
    return [el.get("{" + NS["r"] + "}id", "") for el in p.iter() if local(el.tag) == "hyperlink"]


def rels_for(zf: zipfile.ZipFile) -> dict[str, list[dict[str, str]]]:
    rels = {}
    for name in zf.namelist():
        if not name.endswith(".rels"):
            continue
        try:
            root = ET.fromstring(zf.read(name))
        except ET.ParseError:
            continue
        rows = []
        for rel in root.findall("pr:Relationship", NS):
            rows.append({
                "id": rel.get("Id", ""),
                "type": rel.get("Type", ""),
                "target": rel.get("Target", ""),
                "target_mode": rel.get("TargetMode", ""),
            })
        rels[name] = rows
    return rels


def bookmarks_all(zf: zipfile.ZipFile) -> list[dict[str, str]]:
    found = []
    for part in zf.namelist():
        if not re.fullmatch(r"word/(document|header\d+|footer\d+|footnotes|endnotes|comments)\.xml", part):
            continue
        try:
            root = ET.fromstring(zf.read(part))
        except ET.ParseError:
            continue
        for el in root.iter():
            if local(el.tag) == "bookmarkStart":
                found.append({"part": part, "id": el.get(W + "id", ""), "name": el.get(W + "name", "")})
    return found


def styles_all(zf: zipfile.ZipFile) -> dict[str, dict]:
    if "word/styles.xml" not in zf.namelist():
        return {}
    root = ET.fromstring(zf.read("word/styles.xml"))
    out = {}
    for style in root.findall("w:style", NS):
        sid = style.get(W + "styleId", "")
        name_el = style.find("w:name", NS)
        based_el = style.find("w:basedOn", NS)
        next_el = style.find("w:next", NS)
        outline = style.find("w:pPr/w:outlineLvl", NS)
        out[sid] = {
            "style_id": sid,
            "type": style.get(W + "type", ""),
            "default": style.get(W + "default", ""),
            "name": name_el.get(W + "val", "") if name_el is not None else "",
            "based_on": based_el.get(W + "val", "") if based_el is not None else "",
            "next": next_el.get(W + "val", "") if next_el is not None else "",
            "outline_level": outline.get(W + "val", "") if outline is not None else "",
            "pPr_xml": ET.tostring(style.find("w:pPr", NS), encoding="unicode") if style.find("w:pPr", NS) is not None else "",
            "rPr_xml": ET.tostring(style.find("w:rPr", NS), encoding="unicode") if style.find("w:rPr", NS) is not None else "",
        }
    return out


def table_paragraphs(tbl: ET.Element, route: str) -> list[dict]:
    """Walk a table once in row/cell order; include nested table paragraphs exactly once."""
    result = []
    nested_counts: dict[str, int] = {}
    def walk_table(table: ET.Element, table_route: str):
        for tr_no, tr in enumerate(table.findall("w:tr", NS), start=1):
            for tc_no, tc in enumerate(tr.findall("w:tc", NS), start=1):
                cell_route = f"{table_route}/row{tr_no}/cell{tc_no}"
                p_no = 0
                nested_no = 0
                for child in list(tc):
                    name = local(child.tag)
                    if name == "p":
                        p_no += 1
                        style, outline = paragraph_props(child)
                        result.append({"route": f"{cell_route}/p{p_no}", "text": xml_text(child), "style": style, "outline_level": outline, "bookmarks": paragraph_bookmarks(child)})
                    elif name == "tbl":
                        nested_no += 1
                        walk_table(child, f"{cell_route}/nested_table{nested_no}")
    walk_table(tbl, route)
    return result


def direct_body_blocks(body: ET.Element) -> list[dict]:
    out = []
    heading = ""
    direct_idx = 0
    for child in list(body):
        name = local(child.tag)
        if name == "p":
            style, outline = paragraph_props(child)
            text = xml_text(child)
            is_heading = style.lower().startswith("heading") or outline is not None
            if is_heading and text.strip():
                heading = text.strip()
            out.append({"idx": direct_idx, "kind": "paragraph", "text": text, "style": style, "outline_level": outline, "is_heading": is_heading, "heading": text if is_heading else heading, "bookmarks": paragraph_bookmarks(child)})
            direct_idx += 1
        elif name == "tbl":
            cells = table_paragraphs(child, f"table{1 + sum(1 for x in out if x['kind'] == 'table')}")
            cell_texts = [c["text"] for c in cells]
            tblpr = child.find("w:tblPr", NS)
            ts = tblpr.find("w:tblStyle", NS) if tblpr is not None else None
            table_style = ts.get(W + "val", "") if ts is not None else ""
            out.append({"idx": direct_idx, "kind": "table", "text": "\n".join(cell_texts), "cell_texts": cell_texts, "cell_paragraphs": cells, "cell_paragraph_count": len(cells), "table_style": table_style, "heading": heading})
            direct_idx += 1
    return out


def p_record(p: ET.Element, idx: int, route: str, enclosing: str) -> dict:
    text = xml_text(p)
    style, outline = paragraph_props(p)
    is_heading = style.lower().startswith("heading") or outline is not None
    rec = {
        "idx": idx,
        "kind": "paragraph" if route == "body" else "table_cell_paragraph",
        "route": route,
        "text": text,
        "style": style,
        "outline_level": outline,
        "is_heading": is_heading,
        "heading": text if is_heading else enclosing,
        "bookmarks": paragraph_bookmarks(p),
        "hyperlink_rel_ids": paragraph_hyperlinks(p),
    }
    return rec


def add_paragraphs_and_tables(parent: ET.Element, blocks: list[dict], idx: int,
                              route: str, heading_state: list[str]) -> int:
    for child_num, child in enumerate(list(parent)):
        tag = local(child.tag)
        if tag == "p":
            rec = p_record(child, idx, route, heading_state[0])
            if rec["is_heading"] and rec["text"].strip():
                heading_state[0] = rec["text"].strip()
                rec["heading"] = heading_state[0]
            blocks.append(rec)
            idx += 1
        elif tag == "tbl":
            table_no = 1 + sum(1 for b in blocks if b.get("kind") == "table_start" and b.get("route") == route)
            blocks.append({"idx": idx, "kind": "table_start", "route": route, "table_no": table_no})
            idx += 1
            for tr_no, tr in enumerate(child.findall("w:tr", NS), start=1):
                for tc_no, tc in enumerate(tr.findall("w:tc", NS), start=1):
                    cell_route = f"{route}/table{table_no}/row{tr_no}/cell{tc_no}"
                    idx = add_paragraphs_and_tables(tc, blocks, idx, cell_route, heading_state)
            blocks.append({"idx": idx, "kind": "table_end", "route": route, "table_no": table_no})
            idx += 1
    return idx


def extract_docx(path: Path) -> dict:
    data = path.read_bytes()
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        doc = ET.fromstring(zf.read("word/document.xml"))
        body = doc.find("w:body", NS)
        blocks: list[dict] = []
        body_idx = 0
        heading_state = [""]
        if body is not None:
            body_idx = add_paragraphs_and_tables(body, blocks, body_idx, "body", heading_state)
            direct_blocks = direct_body_blocks(body)
        else:
            direct_blocks = []
        # Capture ordered text from ancillary Word story parts (headers, footers, notes, comments).
        stories: dict[str, list[dict]] = {}
        for part in names:
            if not re.fullmatch(r"word/(header\d+|footer\d+|footnotes|endnotes|comments)\.xml", part):
                continue
            try:
                root = ET.fromstring(zf.read(part))
            except ET.ParseError:
                continue
            items = []
            for i, p in enumerate(root.findall(".//w:p", NS)):
                items.append({"idx": i, "text": xml_text(p), "style": paragraph_props(p)[0], "bookmarks": paragraph_bookmarks(p)})
            stories[part] = items
        # Map the main document relationship IDs to their resolved package declarations.
        document_rels = next((v for k, v in rels_for(zf).items() if k == "word/_rels/document.xml.rels"), [])
        rel_by_id = {r["id"]: r for r in document_rels}
        for b in blocks:
            if b.get("hyperlink_rel_ids"):
                b["hyperlinks"] = [rel_by_id.get(relid, {"id": relid, "missing": True}) for relid in b["hyperlink_rel_ids"]]
        return {
            "file": str(path.resolve()),
            "name": path.name,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "zip_entries": len(names),
            "part_names": sorted(names),
            "part_hashes": {part: {"bytes": len(zf.read(part)), "sha256": hashlib.sha256(zf.read(part)).hexdigest()} for part in names},
            "blocks": blocks,
            "direct_body_blocks": direct_blocks,
            "body_text": "\n".join(b["text"] for b in blocks if b.get("kind") in ("paragraph", "table_cell_paragraph")),
            "stories": stories,
            "bookmarks": bookmarks_all(zf),
            "relationships": rels_for(zf),
            "document_relationships": document_rels,
            "styles": styles_all(zf),
        }


def norm(text: str) -> str:
    # Only whitespace is normalized for alignment; the exact source text stays in the manifest.
    return re.sub(r"\s+", " ", text).strip()


def seq_blocks(doc: dict) -> list[dict]:
    return [b for b in doc["blocks"] if b.get("kind") in ("paragraph", "table_cell_paragraph")]


def ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm(a).casefold(), norm(b).casefold(), autojunk=False).ratio()


def op_record(tag: str, before: list[dict], after: list[dict], align_method: str = "normalized_text") -> dict:
    return {
        "op": tag,
        "alignment_method": align_method,
        "before": before,
        "after": after,
    }


def align_gap(a: list[dict], b: list[dict]) -> list[dict]:
    """Pair likely paragraph/cell rewrites inside a changed interval, retaining separate adds/deletes."""
    if not a:
        return [op_record("add", [], [x], "unmatched_gap") for x in b]
    if not b:
        return [op_record("delete", [x], [], "unmatched_gap") for x in a]
    # Second-level diff over the changed window catches stable internal sentences and order shifts.
    sm = difflib.SequenceMatcher(None, [norm(x["text"]) for x in a], [norm(x["text"]) for x in b], autojunk=False)
    result = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        aa, bb = a[i1:i2], b[j1:j2]
        if tag == "equal":
            result.extend(op_record("equal", [x], [y]) for x, y in zip(aa, bb))
        elif tag == "replace":
            # Pair only positionally plausible rewrites, allowing changes in length or cell structure.
            remaining_a = list(aa)
            remaining_b = list(bb)
            pairs = []
            while remaining_a and remaining_b:
                best = None
                for ai, x in enumerate(remaining_a):
                    for bi, y in enumerate(remaining_b):
                        sc = ratio(x["text"], y["text"])
                        # Context/route is a tiebreaker, not a content substitute.
                        if x.get("route", "") == y.get("route", ""):
                            sc += 0.04
                        dist = abs(ai - bi)
                        key = (sc - 0.002 * dist, -dist, -ai, -bi)
                        if best is None or key > best[0]:
                            best = (key, ai, bi, sc)
                if best is None or best[3] < 0.30:
                    break
                _, ai, bi, sc = best
                x = remaining_a.pop(ai)
                y = remaining_b.pop(bi)
                pairs.append((x, y, sc))
            # Keep source order by placing any remaining deletions/additions at their original position.
            for x, y, sc in pairs:
                result.append(op_record("replace", [x], [y], f"similarity_{sc:.3f}"))
            result.extend(op_record("delete", [x], [], "low_similarity") for x in remaining_a)
            result.extend(op_record("add", [], [y], "low_similarity") for y in remaining_b)
        elif tag == "delete":
            result.extend(op_record("delete", [x], [], "sequence_matcher") for x in aa)
        elif tag == "insert":
            result.extend(op_record("add", [], [x], "sequence_matcher") for x in bb)
    return result


def compare_docs(before: dict, after: dict) -> dict:
    a, b = seq_blocks(before), seq_blocks(after)
    sm = difflib.SequenceMatcher(None, [norm(x["text"]) for x in a], [norm(x["text"]) for x in b], autojunk=False)
    ops = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        aa, bb = a[i1:i2], b[j1:j2]
        if tag == "equal":
            ops.extend(op_record("equal", [x], [y]) for x, y in zip(aa, bb))
        else:
            ops.extend(align_gap(aa, bb))
    stats = {k: sum(1 for x in ops if x["op"] == k) for k in ("equal", "replace", "add", "delete")}
    return {"before": before["name"], "after": after["name"], "stats": stats, "operations": ops}


def compare_direct_body(before: dict, after: dict) -> dict:
    a, b = before["direct_body_blocks"], after["direct_body_blocks"]
    seqkey = lambda x: x["kind"] + "\0" + norm(x["text"])
    sm = difflib.SequenceMatcher(None, [seqkey(x) for x in a], [seqkey(x) for x in b], autojunk=False)
    ops = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        aa, bb = a[i1:i2], b[j1:j2]
        if tag in ("replace", "delete"):
            ops.extend({"op": "delete", "before": [x], "after": []} for x in aa)
        if tag in ("replace", "insert"):
            ops.extend({"op": "add", "before": [], "after": [x]} for x in bb)
    stats = {k: sum(1 for x in ops if x["op"] == k) for k in ("add", "delete")}
    stats["equal"] = sum(1 for x in a if any(seqkey(x) == seqkey(y) for y in b))
    stats["replace"] = 0
    return {"before": before["name"], "after": after["name"], "stats": stats, "operations": ops}


def compact_block(block: dict) -> dict:
    return {k: block.get(k) for k in ("idx", "kind", "route", "text", "style", "outline_level", "is_heading", "heading", "bookmarks", "hyperlinks") if k in block}


def concise_diff(diff: dict) -> dict:
    return {"before": diff["before"], "after": diff["after"], "stats": diff["stats"], "operations": [
        {**op, "before": [compact_block(x) for x in op["before"]], "after": [compact_block(x) for x in op["after"]]}
        for op in diff["operations"] if op["op"] != "equal"
    ]}


def write_markdown(path: Path, docs: dict[str, dict], diffs: list[dict]) -> None:
    user = docs["user"]
    lines = [
        "# RelicWeave V1.47 user update: structural and semantic diff",
        "",
        "Read-only comparison of the user V1.47 document against the integrated V1.46 baseline and current V1.47 A12/VesselForge/PGFrag closeout. Exact source wording is retained below. Alignment normalizes whitespace only; replacements use similarity matching within changed intervals and are marked with the match method. A low-similarity or unmatched item remains an add/delete. Table cell paragraphs are traversed once in OOXML order, including nested tables, to avoid duplicate extraction.",
        "",
        "## Source integrity",
        "",
        "| Source | Bytes | SHA-256 | Text blocks | Table cell paragraphs | Headings | Bookmarks |",
        "|---|---:|---|---:|---:|---:|---:|",
    ]
    for key, d in docs.items():
        bs = seq_blocks(d)
        cells = sum(1 for b in bs if b["kind"] == "table_cell_paragraph")
        heads = sum(1 for b in bs if b["is_heading"])
        lines.append(f"| {d['name']} | {d['bytes']} | `{d['sha256']}` | {len(bs)} | {cells} | {heads} | {len(d['bookmarks'])} |")
    lines += ["", "All three source files are treated as immutable inputs. JSON contains the complete paragraph/cell stream, heading metadata, bookmarks, ancillary story text, and relationship declarations.", "", "## Diff totals", ""]
    for d in diffs:
        s = d["stats"]
        lines.append(f"- **{d['before']} → {d['after']}**: {s['equal']} aligned equal blocks; {s['replace']} probable replacements; {s['add']} additions; {s['delete']} deletions.")
    lines += ["", "## Detailed changed-block manifest", ""]
    for d in diffs:
        lines.append(f"### {d['before']} → {d['after']}")
        lines.append("")
        for n, op in enumerate((x for x in d["operations"] if x["op"] != "equal"), 1):
            lines.append(f"#### {n}. {op['op'].upper()} · align={op['alignment_method']}")
            lines.append("")
            for side, rows in (("Before", op["before"]), ("After", op["after"])):
                if not rows:
                    continue
                lines.append(f"**{side}:**")
                for x in rows:
                    heading = x.get("heading") or "(no enclosing heading)"
                    route = x.get("route", "")
                    lines.append(f"- block {x['idx']} · {x['kind']} · {route} · heading: {heading}")
                    lines.append("")
                    lines.append("  ```text")
                    lines.extend("  " + part for part in x["text"].splitlines() or [""])
                    lines.append("  ```")
                    if x.get("bookmarks"):
                        lines.append(f"  Bookmarks: `{json.dumps(x['bookmarks'], ensure_ascii=False)}`")
                lines.append("")
        lines.append("")
    lines += ["## Interpretation limits and review flags", "", "- Paragraph-level alignment is a locator, not an adjudication that wording is equivalent. Inspect all low-similarity replacements and adjacent additions/deletions in source context.", "- The comparison establishes what changed in the documents; it does not establish that a new technical claim is feasible or experimentally validated.", "- Parent review requested specific attention to the workflow transition **core fragments → ranked candidates → accept/reject/recapture/STOP**, any hidden-ground-truth leakage, and computational or physical feasibility. Those are interpretation checks to apply to the exact deltas above; this report does not infer validation evidence from proposal wording.", "- Full SHA-256 hashes and complete structured extraction are in the paired JSON file.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    args = ap.parse_args()
    ws, out = args.workspace.resolve(), args.outdir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "baseline": ws / "RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx",
        "current": ws / "RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx",
        "user": ws / "RelicWeave_V1.47.docx",
    }
    docs = {k: extract_docx(p) for k, p in paths.items()}
    diffs = [compare_docs(docs["baseline"], docs["user"]), compare_docs(docs["current"], docs["user"])]
    direct_diffs = [compare_direct_body(docs["baseline"], docs["user"]), compare_direct_body(docs["current"], docs["user"])]
    full = {"schema_version": 2, "normalization": "Unicode unchanged; whitespace runs collapsed only for matching; exact text preserved", "documents": docs, "diffs": diffs, "direct_body_diffs": direct_diffs}
    (out / "diff_v147_user_structural.json").write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
    readable = [concise_diff(d) for d in diffs]
    (out / "diff_v147_user_manifest.json").write_text(json.dumps({"schema_version": 2, "documents": {k: {key: d[key] for key in ("name", "file", "bytes", "sha256", "zip_entries")} for k, d in docs.items()}, "diffs": readable, "direct_body_diffs": direct_diffs}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(out / "diff_v147_user_report.md", docs, diffs)
    print(json.dumps({"outdir": str(out), "documents": {k: {"name": d["name"], "bytes": d["bytes"], "sha256": d["sha256"], "blocks": len(seq_blocks(d)), "headings": sum(1 for b in seq_blocks(d) if b["is_heading"]), "bookmarks": len(d["bookmarks"])} for k, d in docs.items()}, "diffs": [{"before": d["before"], "after": d["after"], "stats": d["stats"]} for d in diffs]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
