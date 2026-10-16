from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

DOC = Path(r"C:\Users\xiemo\Desktop\ShardForge\RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx")
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
TARGETS = (
    "A12.19", "A12.20", "G31.1", "G0 ", "11 本次归位与历史记录",
    "附录I VesselForge", "附录J PG-Frag",
)

with ZipFile(DOC) as zf:
    root = ET.fromstring(zf.read("word/document.xml"))
body = root.find("w:body", NS)
blocks = []
para_i = 0
table_i = 0
for child in list(body):
    local = child.tag.rsplit("}", 1)[-1]
    if local == "p":
        text = "".join(t.text or "" for t in child.findall(".//w:t", NS))
        style = child.find("w:pPr/w:pStyle", NS)
        style_id = style.get(f"{{{NS['w']}}}val") if style is not None else ""
        blocks.append(("p", para_i, style_id, text, child))
        para_i += 1
    elif local == "tbl":
        text = " | ".join("".join(t.text or "" for t in p.findall(".//w:t", NS)) for p in child.findall(".//w:p", NS))
        blocks.append(("tbl", table_i, "", text, child))
        table_i += 1

hit_indices = []
for i, (kind, idx, style, text, _) in enumerate(blocks):
    if any(token in text for token in TARGETS):
        hit_indices.append(i)
for i in hit_indices:
    kind, idx, style, text, _ = blocks[i]
    short = text.replace("\n", " ")
    print(f"{kind}[{idx}] style={style}: {short}")
