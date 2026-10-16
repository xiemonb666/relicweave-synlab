#!/usr/bin/env python3
"""Read-only final layout delta audit: accepted 70aa candidate -> layout final."""
import argparse, copy, hashlib, json, zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(r"C:\Users\xiemo\Desktop\ShardForge")
WORK=ROOT/"tmp/v147_user_merge_20261007"
BASE=WORK/"fresh_merge_final_candidate.docx"
FINAL=WORK/"fresh_merge_layout_final_candidate.docx"
MD=WORK/"independent_layout_final.md"
OUT=WORK/"independent_layout_final.json"
BASE_SHA="70aa097680aa1920528ba4b6d9646821ac78b367618c0e9b8dbc36439fa38044"
FINAL_SHA="883c831648d0697f456228f4d862deda8a36ff9740ecd6aadb3a3ebfdfdffc7d"
WNS="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W="{"+WNS+"}"
NS={"w":WNS}

def sha(b): return hashlib.sha256(b).hexdigest()
def tag(s): return W+s
def text(e): return "".join(x.text or "" for x in e.iter() if x.tag==tag("t"))
def canon(e): return ET.canonicalize(xml_data=ET.tostring(e,encoding="unicode"),strip_text=False)
def paras(root): return [x for x in root.iter() if x.tag==tag("p")]
def rows(tbl): return tbl.findall("w:tr",NS)
def after(p):
    ppr=p.find("w:pPr",NS); sp=ppr.find("w:spacing",NS) if ppr is not None else None
    return sp.get(tag("after")) if sp is not None else None
def flag(p,name):
    ppr=p.find("w:pPr",NS)
    el=ppr.find("w:"+name,NS) if ppr is not None else None
    if el is None: return False
    return el.get(tag("val"),"true").lower() not in ("0","false","off")
def style(p):
    el=p.find("w:pPr/w:pStyle",NS)
    return el.get(tag("val"),"") if el is not None else ""
def load(path):
    raw=path.read_bytes()
    with zipfile.ZipFile(path) as z: parts={n:z.read(n) for n in z.namelist()}
    root=ET.fromstring(parts["word/document.xml"]); body=root.find("w:body",NS)
    return {"path":str(path.resolve()),"bytes":len(raw),"sha256":sha(raw),"parts":parts,"root":root,"body":body,
      "tokens":[x.text or "" for x in root.iter() if x.tag==tag("t")],
      "starts":[(x.get(tag("id"),""),x.get(tag("name"),"")) for x in root.iter() if x.tag==tag("bookmarkStart")],
      "ends":[x.get(tag("id"),"") for x in root.iter() if x.tag==tag("bookmarkEnd")],
      "anchors":[x.get(tag("anchor"),"") for x in root.iter() if x.tag==tag("hyperlink") and x.get(tag("anchor"))],
      "tables":[x for x in body if x.tag==tag("tbl")]}

def remove_keep_flags(p):
    ppr=p.find("w:pPr",NS)
    if ppr is not None:
        for name in ("keepNext","keepLines"):
            el=ppr.find("w:"+name,NS)
            if el is not None: ppr.remove(el)
        if len(ppr)==0 and not ppr.attrib and not (ppr.text or "").strip(): p.remove(ppr)

def reset_after(p,value):
    ppr=p.find("w:pPr",NS)
    if ppr is None: return value is None
    sp=ppr.find("w:spacing",NS)
    if value is None:
        if sp is not None:
            sp.attrib.pop(tag("after"),None)
            if not sp.attrib and len(sp)==0 and not (sp.text or "").strip(): ppr.remove(sp)
        return True
    if sp is None: return False
    sp.set(tag("after"),value)
    return True

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--candidate",type=Path,default=FINAL)
    ap.add_argument("--expected-sha",default=FINAL_SHA)
    args=ap.parse_args()
    if not args.candidate.exists():
        print(json.dumps({"status":"READY_NO_FINAL_CANDIDATE","candidate":str(args.candidate),"outputs_written":False}))
        return
    base=load(BASE); final=load(args.candidate.resolve())
    marker="Solver-native contact"
    found=[]
    for ti,t in enumerate(base["tables"],1):
        for ri,r in enumerate(rows(t),1):
            if marker.casefold() in text(r).casefold(): found.append((ti,ri,t,r))
    unique=len(found)==1
    if unique:
        ti,ri,source_table,source_row=found[0]
        source_paras=source_row.findall(".//w:p",NS)
        final_table=final["tables"][ti-1] if ti<=len(final["tables"]) else None
        body_children=list(final["body"])
        final_table_body_index=body_children.index(final_table) if final_table is not None else -1
        next_blocks=body_children[final_table_body_index+1:final_table_body_index+4] if final_table_body_index>=0 else []
        clones=next_blocks if len(next_blocks)==3 and all(x.tag==tag("p") for x in next_blocks) else []
    else:
        ti=ri=-1; source_table=source_row=final_table=None; source_paras=[]; final_table_body_index=-1; clones=[]
    source_texts=[text(p) for p in source_paras]; clone_texts=[text(p) for p in clones]
    clone_text_exact=len(source_paras)==3 and len(clones)==3 and source_texts==clone_texts
    clone_xml_exact=True
    if clone_text_exact:
        for a,b in zip(source_paras,clones):
            old_normalized=copy.deepcopy(a); new_normalized=copy.deepcopy(b)
            remove_keep_flags(old_normalized); remove_keep_flags(new_normalized)
            if canon(new_normalized)!=canon(old_normalized): clone_xml_exact=False
    keep_next=[flag(p,"keepNext") for p in clones]
    keep_lines=[flag(p,"keepLines") for p in clones]
    final_rows=rows(final_table) if final_table is not None else []
    row_counts=[{"table":i+1,"base":len(rows(a)),"final":len(rows(b))}
                for i,(a,b) in enumerate(zip(base["tables"],final["tables"])) if len(rows(a))!=len(rows(b))]
    table_shape_ok=len(base["tables"])==len(final["tables"])==194 and len(row_counts)==1 and row_counts[0]=={"table":ti,"base":5,"final":4}

    base_paras=paras(base["root"]); final_paras=paras(final["root"])
    headings=[i for i,p in enumerate(base_paras) if text(p)=="B13 技术参考" and style(p)=="Heading1"]
    ref_indices=list(range(headings[0]+1,headings[0]+6)) if len(headings)==1 else []
    ref_pairs=[{"paragraph_index":i,"text":text(base_paras[i]),"base_after":after(base_paras[i]),"final_after":after(final_paras[i])}
               for i in ref_indices if i<len(base_paras) and i<len(final_paras)]
    spacing_changed=len(ref_pairs)==5 and all(x["base_after"]=="100" and x["final_after"]=="20" for x in ref_pairs)
    spacing_delta=-80 if spacing_changed else None
    paragraph_xml_diffs=[i for i,(a,b) in enumerate(zip(base_paras,final_paras)) if canon(a)!=canon(b)]
    clone_indices=[i for i,p in enumerate(final_paras) if any(p is q for q in clones)]
    expected_para_diffs=sorted(set(ref_indices+clone_indices))

    # Remove the approved final row, inserted clones, and after-only adjustment; the remaining body C14N must match.
    bnorm=copy.deepcopy(base["body"]); fnorm=copy.deepcopy(final["body"])
    btab=[x for x in bnorm if x.tag==tag("tbl")]; ftab=[x for x in fnorm if x.tag==tag("tbl")]
    row_removed=False; clones_removed=False; spacing_reset=False
    if unique and ti<=len(btab) and ti<=len(ftab):
        target_rows=rows(btab[ti-1])
        if len(target_rows)==5:
            btab[ti-1].remove(target_rows[-1]); row_removed=True
        fc=list(fnorm); ftarget=ftab[ti-1]; fidx=fc.index(ftarget); moved=fc[fidx+1:fidx+4]
        if len(moved)==3 and all(x.tag==tag("p") for x in moved):
            for p in moved: fnorm.remove(p)
            clones_removed=True
        oldp=paras(bnorm); newp=paras(fnorm)
        if len(oldp)==len(newp) and len(ref_indices)==5:
            spacing_reset=all(reset_after(newp[i],after(oldp[i])) for i in ref_indices)
    body_c14n_equal=canon(bnorm)==canon(fnorm)

    parts_same=set(base["parts"])==set(final["parts"])
    changed_non_doc=[n for n in base["parts"] if n!="word/document.xml" and final["parts"].get(n)!=base["parts"][n]]
    rel_parts=[n for n in base["parts"] if n.endswith(".rels")]
    rels_same=all(final["parts"].get(n)==base["parts"][n] for n in rel_parts)
    prefixes=["A12.19 当前状态（2026-10-07）","A12.20 当前实施与资格边界（2026-10-07）","V1.47（2026-10-07）收口记录","G0 当前状态（2026-10-07）","G31.1 V1.47 收口核对（2026-10-07）","VesselForge 当前状态（2026-10-07）","PG-Frag 当前状态（2026-10-07）","V1.47（2026年10月7日）为 A12、VesselForge 与 PG-Frag 的实现收口和证据归位版"]
    statuses=[]
    for prefix in prefixes:
        a=[p for p in paras(base["root"]) if text(p).startswith(prefix)]
        b=[p for p in paras(final["root"]) if text(p).startswith(prefix)]
        statuses.append({"prefix":prefix,"base_count":len(a),"final_count":len(b),"exact":len(a)==len(b)==1 and text(a[0])==text(b[0])})
    starts=base["starts"]==final["starts"] and len(final["starts"])==553
    ends=base["ends"]==final["ends"]
    links=base["anchors"]==final["anchors"] and len(final["anchors"])==113
    duplicate_names=len(final["starts"])!=len(set(n for _,n in final["starts"]))
    dangling=[a for a in final["anchors"] if sum(1 for _,n in final["starts"] if n==a)!=1]
    token_equal=base["tokens"]==final["tokens"] and len(base["tokens"])==len(final["tokens"])==18217
    checks={"base_70aa_sha_matches_pin":base["sha256"]==BASE_SHA,"final_sha_matches_pin":final["sha256"]==args.expected_sha,
      "same_23_part_set_and_all_22_non_document_parts_exact":parts_same and len(base["parts"])==23 and len(changed_non_doc)==0,
      "all_relationship_parts_byte_identical":rels_same,"all_18217_wt_tokens_exact_in_order":token_equal,
      "all_8_status_paragraphs_exact":len(statuses)==8 and all(x["exact"] for x in statuses),
      "all_553_bookmarks_and_113_internal_links_exact":starts and ends and links and not duplicate_names and not dangling,
      "194_tables_and_only_target_row_5_to_4":table_shape_ok and unique and ri==5,
      "three_row_paragraphs_cloned_after_target_table":clone_text_exact and final_table_body_index>=0,
      "cloned_paragraph_xml_exact_except_keep_flags":clone_xml_exact,
      "keepNext_label_and_first_explanation_keepLines_all_three":keep_next==[True,True,False] and keep_lines==[True,True,True],
      "five_B13_reference_spacing_after_changes_100_to_20":spacing_changed,
      "paragraph_C14N_diffs_are_only_five_refs_plus_three_relocated_clones":paragraph_xml_diffs==expected_para_diffs,
      "all_other_body_C14N_identical":body_c14n_equal and row_removed and clones_removed and spacing_reset}
    result={"status":"LAYOUT_STATIC_PASS" if all(checks.values()) else "LAYOUT_STATIC_BLOCKER",
      "base":{"path":base["path"],"bytes":base["bytes"],"sha256":base["sha256"]},
      "final":{"path":final["path"],"bytes":final["bytes"],"sha256":final["sha256"]},
      "checks":checks,"layout_delta":{"table_index":ti,"source_last_row_index":ri,
        "base_row_count":len(rows(source_table)) if source_table is not None else None,"final_row_count":len(final_rows),
        "source_row_text":text(source_row) if source_row is not None else None,"source_paragraph_texts":source_texts,"relocated_body_paragraph_texts":clone_texts,
        "keepNext":keep_next,"keepLines":keep_lines,"changed_table_row_counts":row_counts,
        "B13_reference_spacing_after":{"paragraphs":ref_pairs,"expected_change":"100 to 20 for five citation paragraphs","numeric_delta_each":spacing_delta},
        "paragraph_C14N_diff_indices":paragraph_xml_diffs,"expected_diff_indices":expected_para_diffs,
        "body_C14N_equal_after_reversing_declared_layout_changes":body_c14n_equal},
      "integrity":{"base_wt_count":len(base["tokens"]),"final_wt_count":len(final["tokens"]),
        "base_concatenated_wt_sha256":sha("".join(base["tokens"]).encode("utf-8")),
        "final_concatenated_wt_sha256":sha("".join(final["tokens"]).encode("utf-8")),
        "status_paragraphs":statuses,"base_bookmarks":len(base["starts"]),"final_bookmarks":len(final["starts"]),
        "base_internal_links":len(base["anchors"]),"final_internal_links":len(final["anchors"]),
        "duplicate_bookmark_names":duplicate_names,"dangling_anchors":dangling},
      "package":{"base_parts":len(base["parts"]),"final_parts":len(final["parts"]),
        "changed_non_document_parts":changed_non_doc,"relationship_parts":rel_parts}}
    lines=["# Independent final layout static audit","",f"Status: **{result['status']}**","",
      f"Accepted 70aa base: {base['bytes']} bytes; SHA-256 {base['sha256']}.",
      f"Layout final: {final['bytes']} bytes; SHA-256 {final['sha256']}.","","## Checks",""]
    lines += [f"- {k}: **{'PASS' if v else 'BLOCKER'}**" for k,v in checks.items()]
    lines += ["",f"Ordered w:t tokens: {len(base['tokens'])} in both files; exact sequence equal: {token_equal}.",
      f"Solver-native contact row: table {ti}, row {ri}; 5→4 rows; three body paragraph clones exact: {clone_text_exact}.",
      f"B13 reference spacing after changes: {len(ref_pairs)} paragraphs, base 100 → final 20 twips.",
      f"All other body C14N identical after reversing only these layout moves: {body_c14n_equal}.",
      "The accepted semantic merge is inherited from the reviewed 70aa base; this report assesses only the subsequent layout delta.",
      "No DOCX was modified or rendered.",""]
    MD.write_text("\n".join(lines),encoding="utf-8")
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":result["status"],"final_sha256":final["sha256"],"bytes":final["bytes"],"checks":checks,
      "report":str(MD),"json":str(OUT)},ensure_ascii=False,indent=2))

if __name__=="__main__": main()
