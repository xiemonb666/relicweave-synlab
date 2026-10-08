#!/usr/bin/env python3
"""Compare package parts, relationships, bookmarks, styles, and direct body blocks."""
from __future__ import annotations
import json, re
from collections import Counter, defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parent
D=json.loads((ROOT/"diff_v147_user_structural.json").read_text(encoding="utf-8"))
docs=D["documents"]
def norm(s): return re.sub(r"\s+", " ", s).strip()
def signature(s): return tuple(s.get(k,"") for k in ("type","default","name","based_on","next","outline_level","pPr_xml","rPr_xml"))
lines=["# DOCX package structure comparison", ""]
lines += ["## Package part sets", ""]
for k,d in docs.items(): lines.append(f"- **{k} {d['name']}**: {d['zip_entries']} ZIP parts")
for a,b in (("baseline","user"),("current","user")):
    pa,pb=set(docs[a]["part_names"]),set(docs[b]["part_names"])
    lines += ["",f"### {a} → {b}","",f"Part paths added ({len(pb-pa)}): "+(", ".join(sorted(pb-pa)) or "none"),f"Part paths removed ({len(pa-pb)}): "+(", ".join(sorted(pa-pb)) or "none")]

lines += ["", "## Direct body block alignment: each top-level w:p or w:tbl is one block", ""]
for d in D.get("direct_body_diffs",[]):
    before=docs["baseline"] if d["before"].startswith("RelicWeave_V1.46") else docs["current"]
    after=docs["user"]
    ops=d["operations"]
    added=[op["after"][0] for op in ops if op["op"]=="add"]
    deleted=[op["before"][0] for op in ops if op["op"]=="delete"]
    lines += [f"### {d['before']} → {d['after']}","",f"Direct top-level blocks: before={len(before['direct_body_blocks'])}, after={len(after['direct_body_blocks'])}; operations={len(ops)} (added {len(added)}, removed {len(deleted)}).",f"Added kinds: {dict(Counter(x['kind'] for x in added))}; removed kinds: {dict(Counter(x['kind'] for x in deleted))}.",""]
    for op,label in (("add","ADD"),("delete","REMOVE")):
        rows=added if op=="add" else deleted
        for x in rows:
            snip=norm(x["text"])
            if len(snip)>600: snip=snip[:600]+"…"
            lines.append(f"- {label} body block {x['idx']} · {x['kind']} · heading: {x.get('heading','')} · cell paragraphs: {x.get('cell_paragraph_count','—')}")
            if snip: lines.append(f"  - {snip}")
    lines.append("")

lines += ["## document.xml.rels comparison", ""]
def relmap(d): return {x['id']:(x['type'],x['target'],x['target_mode']) for x in d['document_relationships']}
for a,b in (("baseline","user"),("current","user")):
    ra,rb=relmap(docs[a]),relmap(docs[b])
    added=sorted((k,v) for k,v in rb.items() if k not in ra)
    removed=sorted((k,v) for k,v in ra.items() if k not in rb)
    changed=sorted((k,ra[k],rb[k]) for k in ra.keys() & rb.keys() if ra[k]!=rb[k])
    lines += [f"### {a} → {b}","",f"Counts: before={len(ra)}, after={len(rb)}, added={len(added)}, removed={len(removed)}, changed={len(changed)}."]
    for label,rows in (("Added",added),("Removed",removed),("Changed",changed)):
        for row in rows: lines.append(f"- {label}: `{row}`")
    if not added and not removed and not changed: lines.append("- No relationship ID/type/target/mode changes.")
    lines.append("")

lines += ["## Relationships in all .rels parts", ""]
def allrel(d):
    out={}
    for part,rows in d['relationships'].items():
        for r in rows: out[(part,r['id'])]=(r['type'],r['target'],r['target_mode'])
    return out
for a,b in (("baseline","user"),("current","user")):
    ra,rb=allrel(docs[a]),allrel(docs[b])
    added=sorted((k,v) for k,v in rb.items() if k not in ra)
    removed=sorted((k,v) for k,v in ra.items() if k not in rb)
    changed=sorted((k,ra[k],rb[k]) for k in ra.keys() & rb.keys() if ra[k]!=rb[k])
    lines += [f"### {a} → {b}","",f"All relationship declarations: before={len(ra)}, after={len(rb)}, added={len(added)}, removed={len(removed)}, changed={len(changed)}."]
    if not added and not removed and not changed: lines.append("- No relationship ID/type/target/mode changes.")
    else:
        for label,rows in (("Added",added),("Removed",removed),("Changed",changed)):
            for row in rows: lines.append(f"- {label}: `{row}`")
    lines.append("")

lines += ["## Bookmark identity comparison", ""]
def bmset(d): return {(x.get('part',''),x.get('id',''),x.get('name','')) for x in d['bookmarks']}
for a,b in (("baseline","user"),("current","user")):
    aa,bb=bmset(docs[a]),bmset(docs[b])
    lines += [f"### {a} → {b}","",f"Bookmark starts: before={len(aa)}, after={len(bb)}, added={len(bb-aa)}, removed={len(aa-bb)}."]
    for x in sorted(bb-aa): lines.append(f"- Added `{x}`")
    for x in sorted(aa-bb): lines.append(f"- Removed `{x}`")
    if aa==bb: lines.append("- The set of `(part, bookmark ID, bookmark name)` identities is unchanged.")
    lines.append("")

lines += ["## Styles used by changed text blocks", ""]
used=defaultdict(set)
for pair in D['diffs']:
    for op in pair['operations']:
        if op['op']=="equal": continue
        for side in ("before","after"):
            for x in op[side]:
                style=x.get('style','')
                doc_key="user" if side=="after" else ("baseline" if pair['before'].startswith("RelicWeave_V1.46") else "current")
                if style: used[style].add(doc_key)
style_ids=set().union(*(set(d['styles']) for d in docs.values()))
for style in sorted(used):
    lines.append(f"- `{style}` used in changed blocks ({', '.join(sorted(used[style]))})")
    for key in sorted(used[style]):
        s=docs[key]['styles'].get(style)
        if s: lines.append(f"  - {key}: name={s['name']!r}; type={s['type']}; based_on={s['based_on']!r}; outline={s['outline_level']!r}")
        else: lines.append(f"  - {key}: style definition missing")
for a,b in (("baseline","user"),("current","user")):
    sa,sb=docs[a]['styles'],docs[b]['styles']
    add=sorted(sb.keys()-sa.keys()); rem=sorted(sa.keys()-sb.keys())
    ch=sorted(k for k in sa.keys()&sb.keys() if signature(sa[k])!=signature(sb[k]))
    lines += ["",f"### Style definitions {a} → {b}","",f"Definitions: before={len(sa)}, after={len(sb)}, added={add}, removed={rem}, changed={ch}."]
    if not add and not rem and not ch: lines.append("- No style-definition changes.")
    lines.append("")
(ROOT/"diff_v147_user_structure.md").write_text("\n".join(lines),encoding="utf-8")
print(f"wrote {ROOT/'diff_v147_user_structure.md'}")
