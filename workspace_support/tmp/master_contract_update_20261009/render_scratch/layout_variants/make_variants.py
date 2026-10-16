import copy
import hashlib
import re
import zipfile
from pathlib import Path


BASE = Path(__file__).resolve().parents[2]
FINAL = BASE.parent.parent / "RelicWeave_V1.48_ContractAligned.docx"
OUT = Path(__file__).resolve().parent

SPECS = {
    "table1_only": {
        "markers": [b"pat_inter", b"thick_rmse_rel", b"Top-200"],
        "rows": 8,
        "old": [798, 2299, 2298, 2298, 2299],
        "new": [2100, 2299, 1500, 1794, 2299],
    },
    "table2_only": {
        "markers": [b"thick_trigram_inter", b"curv_K_inter", b"P@200"],
        "rows": 7,
        "old": [798, 2299, 2298, 2298, 2299],
        "new": [2300, 1548, 1547, 2298, 2299],
    },
}


def table_spans(data):
    spans = []
    depth = 0
    start = -1
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


def set_tag_widths(segment, tag_name, current, replacement):
    pattern = re.compile(rb"<" + tag_name + rb"\b[^>]*/?>")
    matches = list(pattern.finditer(segment))
    if len(matches) != len(current) or len(current) != len(replacement):
        raise ValueError(f"unexpected {tag_name!r} count: {len(matches)}")
    pieces = []
    cursor = 0
    for match, old, new in zip(matches, current, replacement):
        tag = match.group(0)
        attr = re.search(rb'(w:w=")([0-9]+)(")', tag)
        if not attr or int(attr.group(2)) != old:
            raise ValueError(f"unexpected width in {tag_name!r}")
        new_tag = tag[:attr.start()] + attr.group(1) + str(new).encode() + attr.group(3) + tag[attr.end():]
        pieces.extend((segment[cursor:match.start()], new_tag))
        cursor = match.end()
    pieces.append(segment[cursor:])
    return b"".join(pieces)


def revert_one(data, spec):
    spans = table_spans(data)
    found = [(a, b) for a, b in spans if all(m in data[a:b] for m in spec["markers"])]
    if len(found) != 1:
        raise ValueError("table marker not unique")
    start, end = found[0]
    segment = data[start:end]
    cells = spec["rows"]
    new = spec["new"]
    old = spec["old"]
    segment = set_tag_widths(segment, b"w:gridCol", new, old)
    segment = set_tag_widths(segment, b"w:tcW", new * cells, old * cells)
    return data[:start] + segment + data[end:]


with zipfile.ZipFile(FINAL, "r") as src:
    infos = src.infolist()
    parts = {info.filename: src.read(info.filename) for info in infos}
    source_doc = parts["word/document.xml"]
    for keep_name in SPECS:
        patched = source_doc
        for revert_name, spec in SPECS.items():
            if revert_name != keep_name:
                patched = revert_one(patched, spec)
        out_path = OUT / f"{keep_name}.docx"
        with zipfile.ZipFile(out_path, "x", allowZip64=True) as dst:
            dst.comment = src.comment
            for info in infos:
                payload = patched if info.filename == "word/document.xml" else parts[info.filename]
                dst.writestr(copy.copy(info), payload)
        print(f"{out_path.name} sha256={hashlib.sha256(out_path.read_bytes()).hexdigest()}")
