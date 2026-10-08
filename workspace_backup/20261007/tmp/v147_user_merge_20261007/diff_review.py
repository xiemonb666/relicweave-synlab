#!/usr/bin/env python3
"""Produce compact navigation/closeout analysis from the read-only extraction."""
from __future__ import annotations
import difflib, json, re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
data = json.loads((ROOT / "diff_v147_user_structural.json").read_text(encoding="utf-8"))
docs = data["documents"]
def norm(s): return re.sub(r"\s+", " ", s).strip()
def seq(doc): return [x for x in doc["blocks"] if x.get("kind") in ("paragraph", "table_cell_paragraph")]

def compare(a, b):
    aa, bb = seq(a), seq(b)
    sm = difflib.SequenceMatcher(None, [norm(x["text"]) for x in aa], [norm(x["text"]) for x in bb], autojunk=False)
    ops=[]
    for tag,i1,i2,j1,j2 in sm.get_opcodes():
        if tag == "equal": continue
        for x in aa[i1:i2]: ops.append(("delete", x, None))
        for y in bb[j1:j2]: ops.append(("add", None, y))
    return ops

def main():
    out=[]
    detail=[]
    for label, dif in (("BASELINE→USER", data["diffs"][0]), ("CURRENT_CLOSEOUT→USER", data["diffs"][1])):
        adds=[op["after"][0] for op in dif["operations"] if op["op"]=="add" and op["after"]]
        reps=[op for op in dif["operations"] if op["op"]=="replace"]
        dels=[op for op in dif["operations"] if op["op"]=="delete"]
        groups=defaultdict(list)
        for x in adds: groups[x.get("heading") or "(no heading)"].append(x)
        out += [f"## {label}", "", f"Add blocks: {len(adds)}; replacements: {len(reps)}; deletions: {len(dels)}", "", "### Additions by enclosing heading", ""]
        for heading, rows in sorted(groups.items(), key=lambda kv: min(x["idx"] for x in kv[1])):
            chars=sum(len(x["text"]) for x in rows)
            out.append(f"- block {min(x['idx'] for x in rows)}–{max(x['idx'] for x in rows)} · {len(rows)} blocks · {chars} chars · {heading}")
        detail += [f"## {label}", ""]
        for heading, rows in sorted(groups.items(), key=lambda kv: min(x["idx"] for x in kv[1])):
            nonempty=[x for x in rows if x["text"].strip()]
            if not nonempty: continue
            detail += [f"### {heading}", ""]
            for x in nonempty:
                detail += [f"- block {x['idx']} · {x['kind']} · {x.get('route')}", "", "```text", x["text"], "```", ""]
        out += ["", "### Replacements/deletions by heading", ""]
        for op in reps:
            for x in op["before"]:
                out.append(f"- REPLACE block {x['idx']} · {x.get('heading')}: {norm(x['text'])[:220]}")
            for x in op["after"]:
                out.append(f"  → USER block {x['idx']} · {x.get('heading')}: {norm(x['text'])[:220]}")
        for op in dels:
            for x in op["before"]:
                out.append(f"- DELETE block {x['idx']} · {x.get('heading')}: {norm(x['text'])[:240]}")
        detail += [f"### {label} replacement and deletion context", ""]
        for op in reps:
            for x in op["before"]: detail += [f"REPLACED BASELINE block {x['idx']} · {x.get('heading')}", "```text", x["text"], "```", ""]
            for x in op["after"]: detail += [f"REPLACEMENT USER block {x['idx']} · {x.get('heading')}", "```text", x["text"], "```", ""]
        for op in dels:
            for x in op["before"]: detail += [f"DELETED BASELINE block {x['idx']} · {x.get('heading')}", "```text", x["text"], "```", ""]
        out += [""]
    out += ["## Baseline→current closeout exact delta", ""]
    for action, old, new in compare(docs["baseline"], docs["current"]):
        x = old if old else new
        out.append(f"### {action.upper()} block {x['idx']} · {x.get('heading') or '(no heading)'} · {x.get('route')}")
        out.append("")
        out.append("```text")
        out.extend(x["text"].splitlines() or [""])
        out.append("```")
        out.append("")
    (ROOT / "diff_v147_user_navigation.md").write_text("\n".join(out), encoding="utf-8")
    (ROOT / "diff_v147_user_added_text.md").write_text("\n".join(detail), encoding="utf-8")
    print(f"wrote {ROOT / 'diff_v147_user_navigation.md'}")

if __name__ == "__main__": main()
