import copy
import re
import zipfile
from pathlib import Path

SPECS = [
    {"markers": [b"pat_inter", b"thick_rmse_rel", b"Top-200"], "rows": 8,
     "old": [798, 2299, 2298, 2298, 2299], "new": [2100, 2299, 1500, 1794, 2299]},
    {"markers": [b"thick_trigram_inter", b"curv_K_inter", b"P@200"], "rows": 7,
     "old": [798, 2299, 2298, 2298, 2299], "new": [2300, 1548, 1547, 2298, 2299]},
]


def table_spans(data):
    spans, depth, start = [], 0, -1
    for match in re.finditer(rb"</?w:tbl\b[^>]*>", data):
        tag = match.group(0)
        if tag.startswith(b"</"):
            depth -= 1
            if depth == 0:
                spans.append((start, match.end()))
                start = -1
        else:
            if depth == 0:
                start = match.start()
            depth += 1
    if depth:
        raise ValueError("unbalanced w:tbl elements")
    return spans


def set_tag_widths(segment, current, replacement):
    pattern = re.compile(rb"<w:tcW\b[^>]*/?>")
    matches = list(pattern.finditer(segment))
    if len(matches) != len(current):
        raise ValueError(f"unexpected tcW count: {len(matches)}")
    pieces, cursor = [], 0
    for match, old, new in zip(matches, current, replacement):
        tag = match.group(0)
        attr = re.search(rb'(w:w=")([0-9]+)(")', tag)
        if not attr or int(attr.group(2)) != old:
            raise ValueError("unexpected tcW width")
        updated = tag[:attr.start()] + attr.group(1) + str(new).encode() + attr.group(3) + tag[attr.end():]
        pieces.extend((segment[cursor:match.start()], updated))
        cursor = match.end()
    pieces.append(segment[cursor:])
    return b"".join(pieces)

BASE = Path(__file__).resolve().parents[2]
FINAL = BASE.parent.parent / "RelicWeave_V1.48_ContractAligned.docx"
OUT = Path(__file__).resolve().parent / "grid_only_both.docx"

with zipfile.ZipFile(FINAL, "r") as src:
    infos = src.infolist()
    parts = {info.filename: src.read(info.filename) for info in infos}
    doc = parts["word/document.xml"]
    spans = table_spans(doc)
    edits = []
    for spec in SPECS:
        hits = [(a, b) for a, b in spans if all(m in doc[a:b] for m in spec["markers"])]
        if len(hits) != 1:
            raise ValueError("target metric table not unique")
        edits.append((hits[0][0], hits[0][1], spec))
    for start, end, spec in sorted(edits, reverse=True, key=lambda item: item[0]):
        segment = doc[start:end]
        segment = set_tag_widths(segment, spec["new"] * spec["rows"], spec["old"] * spec["rows"])
        doc = doc[:start] + segment + doc[end:]
    with zipfile.ZipFile(OUT, "x", allowZip64=True) as dst:
        dst.comment = src.comment
        for info in infos:
            payload = doc if info.filename == "word/document.xml" else parts[info.filename]
            dst.writestr(copy.copy(info), payload)

print(f"{OUT.name} bytes={OUT.stat().st_size}")
