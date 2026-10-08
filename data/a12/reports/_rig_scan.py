"""Read-only helper: locate rig/capture-related text in the V1.44 docx extraction artifacts.

Never modifies the docx or the repo; prints hits so the contract can carry exact
`T###/p###` pointers.  Evidence source: %TEMP%\\v144_extract\\out\\blocks.json
(docx body order: paragraphs + tables, produced by python-docx in an earlier deep read).
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

G = os.path.join(os.environ.get("TEMP", ""), "v144_extract", "out")
BLOCKS = os.path.join(G, "blocks.json")

blocks = json.load(open(BLOCKS, encoding="utf-8"))

# para index (p###) == body block order restricted to paragraphs; tbl index (T###) == body order restricted to tables
paras = [b for b in blocks if b["kind"] == "p"]
tables = [b for b in blocks if b["kind"] == "tbl"]
for n, b in enumerate(paras, 1):
    b["pid"] = n
for n, b in enumerate(tables, 1):
    b["tid"] = n

# nearest preceding heading for each block
cur = ""
for b in blocks:
    if b["kind"] == "p" and b.get("style", "").startswith(("Heading", "SYN Section", "SYN Subsection")):
        cur = b["text"].strip()
    b["head"] = cur
for b in paras:
    pass
hmap = {}
cur = ""
for b in blocks:
    if b["kind"] == "p" and str(b.get("style", "")).startswith(("Heading", "SYN Section", "SYN Subsection")):
        cur = b["text"].strip()
    if b["kind"] == "p":
        hmap[b["pid"]] = cur
    else:
        hmap["t%d" % b["tid"]] = cur

KEY = re.compile(
    r"Luckfox|RV1103|SC3336|2304|1296|84°|84 ?度|滚动快门|卷帘|手动对焦|对焦|工作距离|mm/px|"
    r"0\.039|0\.078|0\.117|0\.156|0\.195|灯|色温|CRI|偏振|偏光|导轨|行程|净空|位置误差|P95|"
    r"预算|1195|1435|1800|2000|掩码|mask|质量向量|blur|coverage|occlusion|点云|点密度|"
    r"账本|ledger|标定|内参|外参|畸变|px_per_mm|sparse|dense|mesh|MVS|2048|8192|"
    r"断口|近摄|翻转|翻面|同步|双目|光度立体|深度|旋转|出土|上下文|SY-Q|Q1|Q2|Q3|"
    r"重叠|层|曝光|ISO|元数据|采集清单|SOP|标尺|身份"
)


def para_hits(pattern):
    out = []
    for b in paras:
        if pattern.search(b["text"]):
            out.append(b)
    return out


def table_hits(pattern):
    out = []
    for t in tables:
        flat = " ".join(" | ".join(str(c) for c in row) for row in t["rows"])
        if pattern.search(flat):
            out.append((t, flat))
    return out


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "paras"
    pat = re.compile(sys.argv[2], re.I) if len(sys.argv) > 2 else KEY
    lim = int(sys.argv[3]) if len(sys.argv) > 3 else 10 ** 9
    if mode in ("paras", "both"):
        hits = para_hits(pat)
        print("### PARAGRAPH HITS: %d" % len(hits))
        for b in hits[:lim]:
            print("[p%04d|%s|%s] %s" % (b["pid"], b.get("style"), b["head"][:40], b["text"].strip()[:900]))
    if mode in ("tables", "both"):
        hits = table_hits(pat)
        print("### TABLE HITS: %d" % len(hits))
        for t, flat in hits[:lim]:
            print("[t%03d|%s] rows=%d cols=%d :: %s" % (t["tid"], hmap.get("t%d" % t["tid"], "")[:40], t["n_rows"], t["n_cols"], flat[:1200]))
