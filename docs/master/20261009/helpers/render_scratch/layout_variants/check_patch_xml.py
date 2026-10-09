import hashlib
import sys
import zipfile
from pathlib import Path

TASK = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TASK))
import build_master_docx as b

snapshot = TASK / "prefinal_layout_snapshot" / "RelicWeave_V1.48_ContractAligned.docx"
final = TASK.parent.parent / "RelicWeave_V1.48_ContractAligned.docx"

with zipfile.ZipFile(snapshot) as z:
    source = z.read("word/document.xml")
with zipfile.ZipFile(final) as z:
    current = z.read("word/document.xml")

_, records = b._table_layout_targets(source)
spans = b._raw_table_spans(source)
items = []
for rec in records:
    markers = [x.encode("utf-8") for x in rec["raw_markers"]]
    hits = [(a, e) for a, e in spans if all(m in source[a:e] for m in markers)]
    if len(hits) != 1:
        raise ValueError(f"source marker ambiguity for {rec['key']}")
    items.append((hits[0][0], hits[0][1], rec))

correct = source
for start, end, rec in sorted(items, reverse=True, key=lambda x: x[0]):
    segment, _, _ = b._apply_one_table_widths(correct[start:end], rec)
    correct = correct[:start] + segment + correct[end:]

transformed, _ = b.transform_approved_table_widths(source)
print("source", hashlib.sha256(source).hexdigest())
print("current", hashlib.sha256(current).hexdigest())
print("helper", hashlib.sha256(transformed).hexdigest())
print("correct-descending", hashlib.sha256(correct).hexdigest())
print("current-is-correct", current == correct)
print("helper-is-correct", transformed == correct)

root = b.ET.fromstring(current)
for key, spec in b.ROOT_APPROVED_TABLE_LAYOUTS.items():
    matches = []
    for table in root.iter(b.q("tbl")):
        text = "|".join(b.visible_text(cell) for row in table.findall("./w:tr", b.NS) for cell in row.findall("./w:tc", b.NS))
        if all(marker in text for marker in spec["markers"]):
            grid = table.find("./w:tblGrid", b.NS)
            grid_widths = [int(col.get(b.q("w"))) for col in grid.findall("./w:gridCol", b.NS)]
            rows = table.findall("./w:tr", b.NS)
            cells = [[int(cell.find("./w:tcPr/w:tcW", b.NS).get(b.q("w"))) for cell in row.findall("./w:tc", b.NS)] for row in rows]
            matches.append((grid_widths, cells))
    print(key, matches)
