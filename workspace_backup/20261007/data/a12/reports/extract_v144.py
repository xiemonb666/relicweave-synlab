# Read-only extraction of RelicWeave_V1.44_Optimized_Complete_Plan.docx
# Emits: outline.md (all headings), tables/tNNN.md (one file per table),
#        body.txt (paragraphs with markers), index.json
import json, os, re, sys
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.oxml.ns import qn

SRC = r"C:\Users\xiemo\Desktop\ShardForge\RelicWeave_V1.44_Optimized_Complete_Plan.docx"
OUT = r"C:\Users\xiemo\Desktop\ShardForge\data\a12\reports"
TDIR = os.path.join(OUT, "tables")
os.makedirs(TDIR, exist_ok=True)

doc = Document(SRC)
body = doc.element.body

def iter_block_items(parent):
    for child in parent.iterchildren():
        if child.tag == qn('w:p'):
            yield Paragraph(child, doc)
        elif child.tag == qn('w:tbl'):
            yield Table(child, doc)

def cell_text(cell):
    # join paragraphs of a cell; keep line breaks
    parts = []
    for p in cell.paragraphs:
        t = p.text.strip()
        if t:
            parts.append(t)
    return " / ".join(parts)

def table_to_lines(tbl):
    lines = []
    for ri, row in enumerate(tbl.rows):
        seen = set()
        vals = []
        for cell in row.cells:
            key = id(cell._tc)
            if key in seen:
                continue
            seen.add(key)
            vals.append(cell_text(cell))
        lines.append("| " + " | ".join(vals) + " |")
    return lines

HEAD_RE = re.compile(r'^(Heading|heading|标题)\s*(\d)?', re.I)

headings = []      # (idx, level, text)
tables_meta = []   # (tidx, section_heading, nrows, ncols)
out_body = []
current_h1 = ""
current_path = []
tidx = 0
pcount = 0
block_i = 0

for block in iter_block_items(body):
    block_i += 1
    if isinstance(block, Paragraph):
        pcount += 1
        text = block.text.strip()
        style = block.style.name if block.style is not None else ""
        is_head = (style.lower().startswith("heading") or style in ("Title", "Subtitle")
                   or style.startswith("标题") or style.startswith("SYN Section")
                   or style.startswith("SYN Subsection"))
        if is_head:
            lvl = 0
            m = re.search(r'(\d+)', style)
            if m:
                lvl = int(m.group(1))
            elif style.lower() == "title":
                lvl = 0
            elif style.startswith("SYN Section"):
                lvl = 1
            elif style.startswith("SYN Subsection"):
                lvl = 2
            headings.append({"idx": len(headings), "p_index": pcount, "block": block_i,
                             "level": lvl, "style": style, "text": text})
            out_body.append(f"\n### [H{lvl}] {text}\n")
        else:
            if text:
                out_body.append(f"[p{pcount}|{style}] {text}")
    else:
        tidx += 1
        lines = table_to_lines(block)
        nrows = len(block.rows)
        ncols = max((len(r.cells) for r in block.rows), default=0)
        # determine enclosing heading: last heading seen
        enclosing = ""
        for h in reversed(headings):
            if h["block"] < block_i:
                enclosing = h["text"]
                break
        tables_meta.append({"t": tidx, "after_p": pcount, "block": block_i,
                            "section": enclosing, "rows": nrows, "cols": ncols})
        path = os.path.join(TDIR, f"t{tidx:03d}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# Table t{tidx:03d}  (rows={nrows}, cols={ncols})\n")
            f.write(f"# enclosing heading (by order): {enclosing}\n")
            f.write(f"# after paragraph p{pcount}\n\n")
            if enclosing:
                f.write(f"**{enclosing}**\n\n")
            f.write("\n".join(lines) + "\n")
        out_body.append(f"\n<<<TABLE t{tidx:03d} rows={nrows} cols={ncols}>>>\n")

with open(os.path.join(OUT, "outline.md"), "w", encoding="utf-8") as f:
    for h in headings:
        f.write(f"{'  '*h['level']}[H{h['level']}] (p{h['p_index']}) {h['text']}\n")

with open(os.path.join(OUT, "body.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(out_body))

with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
    json.dump({"paragraphs": pcount, "tables": tidx, "headings": headings,
               "tables_meta": tables_meta}, f, ensure_ascii=False, indent=1)

print("paragraphs(with empty):", pcount)
print("headings:", len(headings))
print("tables:", tidx)
print("body.txt lines:", len(out_body))
