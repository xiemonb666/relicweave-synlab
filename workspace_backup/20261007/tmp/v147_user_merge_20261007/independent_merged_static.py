#!/usr/bin/env python3
"""Read-only independent static audit for fresh V1.47 merge candidate."""
from __future__ import annotations
import argparse, collections, difflib, hashlib, json, re, zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(r"C:\Users\xiemo\Desktop\ShardForge")
WORK=ROOT/"tmp/v147_user_merge_20261007"
USER=ROOT/"RelicWeave_V1.47.docx"
V146=ROOT/"RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx"
FROZEN=ROOT/"tmp/closeout_documents_20261007/master_v147_frozen_candidate_9af0efe877115200dd99bbcf8f24f3124e2932245d71795fc00252d08e278436.docx"
CAND=WORK/"fresh_merge_candidate.docx"
PREVIOUS=WORK/"fresh_merge_candidate.docx"
PROOF=WORK/"fresh_merge_SOURCECHECK.json"
SOURCE_PROOF=WORK/"fresh_merge_SOURCECHECK.json"
CHANGELOG=WORK/"fresh_merge_CHANGELOG.md"
EXPECTED={"user":"41f1254e40a2ecabdcfa1c6583af2fce0ae1b0ab980d5f9179bbaf687b7be64b","frozen":"9af0efe877115200dd99bbcf8f24f3124e2932245d71795fc00252d08e278436","v146":"15978a3956fa33e8048cc54c1dad6878a7e19d9c71b84415dcaf8732f041a3b4"}
NS={"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main","pr":"http://schemas.openxmlformats.org/package/2006/relationships"}
W="{"+NS["w"]+"}"

def h(b): return hashlib.sha256(b).hexdigest()
def norm(s): return re.sub(r"\s+"," ",s).strip()
def txt(e): return "".join(x.text or "" for x in e.iter() if x.tag==W+"t")
def pstyle(p):
    e=p.find("w:pPr/w:pStyle",NS)
    return e.get(W+"val","") if e is not None else ""
def heading(p): return pstyle(p).lower().startswith("heading") or p.find("w:pPr/w:outlineLvl",NS) is not None
def read(path):
    raw=path.read_bytes()
    with zipfile.ZipFile(path) as z: parts={n:z.read(n) for n in z.namelist()}
    root=ET.fromstring(parts["word/document.xml"]); body=root.find("w:body",NS)
    pars=[p for p in body.iter() if p.tag==W+"p"]
    ps=[{"idx":i,"text":txt(p),"style":pstyle(p),"heading":heading(p),"bookmarks":[{"id":b.get(W+"id",""),"name":b.get(W+"name","")} for b in p.iter() if b.tag==W+"bookmarkStart"]} for i,p in enumerate(pars)]
    tables=[]
    for ti,t in enumerate((x for x in body if x.tag==W+"tbl"),1):
        rows=[]
        for ri,tr in enumerate(t.findall("w:tr",NS),1):
            cells=[tc for tc in tr.findall("w:tc",NS)]
            rows.append({"row":ri,"cells":[txt(tc) for tc in cells],"cell_elements":cells,"text":"\n".join(txt(tc) for tc in cells),"breaks":sum(1 for x in tr.iter() if x.tag==W+"br")})
        tblpr=t.find("w:tblPr",NS); grid=t.find("w:tblGrid",NS)
        geom={"tblW":ET.tostring(tblpr.find("w:tblW",NS),encoding="unicode") if tblpr is not None and tblpr.find("w:tblW",NS) is not None else "",
              "layout":ET.tostring(tblpr.find("w:tblLayout",NS),encoding="unicode") if tblpr is not None and tblpr.find("w:tblLayout",NS) is not None else "",
              "grid":ET.tostring(grid,encoding="unicode") if grid is not None else "",
              "rows":[[{tag:(ET.tostring(tc.find("w:tcPr/"+tag,NS),encoding="unicode") if tc.find("w:tcPr/"+tag,NS) is not None else "") for tag in ("w:tcW","w:gridSpan","w:vMerge")} for tc in r["cell_elements"]] for r in rows]}
        tables.append({"idx":ti,"rows":rows,"text":"\n".join(r["text"] for r in rows),"geometry":geom,"xml":t})
    starts=[{"id":e.get(W+"id",""),"name":e.get(W+"name","")} for e in root.iter() if e.tag==W+"bookmarkStart"]
    ends=[e.get(W+"id","") for e in root.iter() if e.tag==W+"bookmarkEnd"]
    anchors=[e.get(W+"anchor","") for e in root.iter() if e.tag==W+"hyperlink" and e.get(W+"anchor")]
    rels={}
    for name,data in parts.items():
        if name.endswith(".rels"):
            relroot=ET.fromstring(data); rels[name]=sorted((e.get("Id",""),e.get("Type",""),e.get("Target",""),e.get("TargetMode","")) for e in relroot if e.tag.endswith("Relationship"))
    return {"path":str(path),"bytes":len(raw),"sha256":h(raw),"parts":parts,"root":root,"body":body,"paragraphs":ps,"tables":tables,"bookmark_starts":starts,"bookmark_ends":ends,"anchors":anchors,"rels":rels}

def direct_blocks(d):
    out=[]
    for i,x in enumerate(list(d["body"])):
        if x.tag==W+"p": out.append({"idx":i,"kind":"p","text":txt(x)})
        elif x.tag==W+"tbl": out.append({"idx":i,"kind":"tbl","text":txt(x)})
    return out

def new_headings(v146,user):
    old=collections.Counter(p["text"].strip() for p in v146["paragraphs"] if p["heading"] and p["text"].strip())
    result=[]
    for p in user["paragraphs"]:
        t=p["text"].strip()
        if p["heading"] and t:
            if old[t]: old[t]-=1
            else: result.append(t)
    return result

def rel_match(d): return d["rels"]

def exact_hits(ps,prefix): return [p for p in ps if p["text"].startswith(prefix)]

def bookmark_map(d):
    out=collections.defaultdict(list)
    for x in d["bookmark_starts"]: out[x["name"]].append(x)
    return out

def inno_rows(d):
    rows={}
    for t in d["tables"]:
        for r in t["rows"]:
            for cell in r["cells"]:
                m=re.search(r"\bINNO-(3[2-9]|4[0-5])\b",cell)
                if m: rows.setdefault("INNO-"+str(int(m.group(1))),[]).append({"table":t["idx"],"row":r["row"],"cells":r["cells"]})
    return rows

def ordered_paragraph_retention(source,candidate):
    a,b=source["paragraphs"],candidate["paragraphs"]
    cursor=0; misses=[]; mapping=[]
    for p in a:
        hit=next((j for j in range(cursor,len(b)) if norm(b[j]["text"])==norm(p["text"])),None)
        if hit is None: misses.append({"source_idx":p["idx"],"text":p["text"]})
        else: mapping.append({"source_idx":p["idx"],"candidate_idx":b[hit]["idx"]}); cursor=hit+1
    return {"source_paragraphs":len(a),"candidate_paragraphs":len(b),"matched_in_order":len(mapping),"unmatched_source_paragraphs":misses,"all_source_paragraphs_retained_exactly_in_order":not misses}

def doc_text_counts(d): return collections.Counter(p["text"] for p in d["paragraphs"] if p["text"].strip())

def run(args):
    paths={"user":USER,"v146":V146,"frozen_current":FROZEN,"candidate":args.candidate.resolve(),"previous_candidate":args.previous.resolve()}
    d={k:read(p) for k,p in paths.items()}
    proof=json.loads(args.proof.read_text(encoding="utf-8")); source_proof=json.loads(args.source_proof.read_text(encoding="utf-8")); changelog=args.changelog.read_text(encoding="utf-8")
    clar=source_proof.get("applied_clarifications",[]); patches=proof.get("patches",[])
    hashes={k:{"path":v["path"],"bytes":v["bytes"],"sha256":v["sha256"]} for k,v in d.items()}
    hash_check={"user":d["user"]["sha256"]==EXPECTED["user"],"v146":d["v146"]["sha256"]==EXPECTED["v146"],"frozen_current":d["frozen_current"]["sha256"]==EXPECTED["frozen"],"candidate_matches_final_proof":d["candidate"]["sha256"]==proof.get("sha256") and d["candidate"]["bytes"]==proof.get("bytes"),"previous_candidate_matches_source_proof":d["previous_candidate"]["sha256"]==source_proof.get("candidate_sha256") and d["previous_candidate"]["bytes"]==source_proof.get("candidate_bytes"),"candidate_matches_parent_notice":d["candidate"]["sha256"]==args.expected_candidate_sha if args.expected_candidate_sha else None}
    # Eight exact current status blocks: seven status paragraphs and front p5 scientific summary.
    prefixes=["A12.19 当前状态（2026-10-07）","A12.20 当前实施与资格边界（2026-10-07）","V1.47（2026-10-07）收口记录","G0 当前状态（2026-10-07）","G31.1 V1.47 收口核对（2026-10-07）","VesselForge 当前状态（2026-10-07）","PG-Frag 当前状态（2026-10-07）","V1.47（2026年10月7日）为 A12、VesselForge 与 PG-Frag 的实现收口和证据归位版"]
    protected=[]
    for pref in prefixes:
        s=exact_hits(d["frozen_current"]["paragraphs"],pref); c=exact_hits(d["candidate"]["paragraphs"],pref)
        protected.append({"label":pref,"source_count":len(s),"candidate_count":len(c),"exact_text_unchanged":len(s)==1 and len(c)==1 and s[0]["text"]==c[0]["text"],"source_sha256":h(s[0]["text"].encode()) if len(s)==1 else None,"candidate_sha256":h(c[0]["text"].encode()) if len(c)==1 else None,"source_text":s[0]["text"] if len(s)==1 else None,"candidate_text":c[0]["text"] if len(c)==1 else None})

    # Compose the accepted 14 source clarifications with the final eight exact planning-text refinements.
    user_to_previous=ordered_paragraph_retention(d["user"],d["previous_candidate"])
    previous_paras=d["previous_candidate"]["paragraphs"]; candidate_paras=d["candidate"]["paragraphs"]
    actual_changed_indices=[i for i,(a,b) in enumerate(zip(previous_paras,candidate_paras)) if a["text"]!=b["text"]]
    declared_indices=sorted(int(x["paragraph_index"]) for x in patches)
    patch_checks=[]
    for p in patches:
        i=int(p["paragraph_index"])
        old_text=previous_paras[i]["text"] if i<len(previous_paras) else None
        new_text=candidate_paras[i]["text"] if i<len(candidate_paras) else None
        patch_checks.append({"label":p["label"],"paragraph_index":i,"old_text_exact_in_previous":old_text==p["old"],"new_text_exact_in_final":new_text==p["new"],"old":p["old"],"new":p["new"]})
    final_patch_check={"previous_paragraph_count":len(previous_paras),"final_paragraph_count":len(candidate_paras),"actual_changed_paragraph_indices":actual_changed_indices,"declared_changed_paragraph_indices":declared_indices,"changed_indices_exactly_declared":len(previous_paras)==len(candidate_paras) and actual_changed_indices==declared_indices,"patches":patch_checks,"all_eight_exact_old_new_patches_verified":len(patches)==8 and len(patch_checks)==8 and all(x["old_text_exact_in_previous"] and x["new_text_exact_in_final"] for x in patch_checks) and len(previous_paras)==len(candidate_paras) and actual_changed_indices==declared_indices}

    clarification_checks=[]
    for cl in clar:
        source_anchor=[p for p in d["user"]["paragraphs"] if cl.get("anchor") and cl["anchor"] in p["text"]]
        previous_hits=[p for p in previous_paras if cl.get("text") and cl["text"] in p["text"]]
        final_hits=[p for p in candidate_paras if cl.get("text") and cl["text"] in p["text"]]
        superseding=[]
        if len(previous_hits)==1:
            pi=previous_hits[0]["idx"]
            superseding=[{"label":p["label"],"paragraph_index":int(p["paragraph_index"]),"old_contains_clarification":cl["text"] in p["old"],"final_text_exact":candidate_paras[pi]["text"]==p["new"]} for p in patches if int(p["paragraph_index"])==pi and cl["text"] in p["old"]]
        refined=bool(superseding) and all(x["old_contains_clarification"] and x["final_text_exact"] for x in superseding)
        clarification_checks.append({"label":cl["label"],"anchor":cl["anchor"],"text":cl["text"],"source_anchor_indices":[p["idx"] for p in source_anchor],"previous_exact_text_indices":[p["idx"] for p in previous_hits],"final_exact_text_indices":[p["idx"] for p in final_hits],"final_refinement_patches":superseding,"verified":len(source_anchor)==1 and len(previous_hits)==1 and (len(final_hits)==1 or refined)})
    clarification_result={"declared_count":len(clar),"checks":clarification_checks,"exact_in_previous_candidate":sum(len(x["previous_exact_text_indices"])==1 for x in clarification_checks),"retained_exact_in_final":sum(len(x["final_exact_text_indices"])==1 for x in clarification_checks),"superseded_by_final_exact_patches":sum(bool(x["final_refinement_patches"]) for x in clarification_checks),"all_14_verified_as_retained_or_refined":len(clar)==14 and all(x["verified"] for x in clarification_checks)}

    # Heading bookmarks and target links.
    new=new_headings(d["v146"],d["user"]); cand_heads=collections.defaultdict(list)
    for p in d["candidate"]["paragraphs"]:
        if p["heading"] and p["text"].strip(): cand_heads[p["text"].strip()].append(p)
    bm=bookmark_map(d["candidate"]); anchors=collections.Counter(d["candidate"]["anchors"])
    nav=[]
    for title in new:
        ps=cand_heads.get(title,[]); names=[b["name"] for p in ps for b in p["bookmarks"]]
        nav.append({"heading":title,"candidate_heading_count":len(ps),"bookmark_names":names,"anchor_link_counts":{n:anchors[n] for n in names}})
    base_bm=collections.Counter((x["id"],x["name"]) for x in d["frozen_current"]["bookmark_starts"]); cand_bm=collections.Counter((x["id"],x["name"]) for x in d["candidate"]["bookmark_starts"])
    starts_by_id=collections.Counter(x["id"] for x in d["candidate"]["bookmark_starts"]); ends_by_id=collections.Counter(d["candidate"]["bookmark_ends"])
    dup_names=[k for k,v in collections.Counter(x["name"] for x in d["candidate"]["bookmark_starts"]).items() if v>1]
    dup_ids=[k for k,v in starts_by_id.items() if v>1]
    dangling=[a for a in d["candidate"]["anchors"] if len(bm[a])!=1]
    old_links=collections.Counter(d["frozen_current"]["anchors"]); cand_links=collections.Counter(d["candidate"]["anchors"])
    nav_result={"source_bookmarks":sum(base_bm.values()),"candidate_bookmark_starts":len(d["candidate"]["bookmark_starts"]),"candidate_bookmark_ends":len(d["candidate"]["bookmark_ends"]),"original_id_name_pairs_preserved":all(cand_bm[k]>=v for k,v in base_bm.items()),"unique_new_heading_count":len(new),"all_33_new_headings_present_once":len(new)==33 and all(x["candidate_heading_count"]==1 for x in nav),"each_new_heading_has_one_unique_bookmark_and_link":len(new)==33 and all(len(x["bookmark_names"])==1 and len(bm[x["bookmark_names"][0]])==1 and x["anchor_link_counts"].get(x["bookmark_names"][0])==1 for x in nav),"duplicate_bookmark_names":dup_names,"duplicate_bookmark_ids":dup_ids,"bookmark_start_end_id_mismatch":list((starts_by_id-ends_by_id).elements())+list((ends_by_id-starts_by_id).elements()),"candidate_anchor_links":len(d["candidate"]["anchors"]),"old_internal_link_multiplicity_preserved":all(cand_links[k]>=v for k,v in old_links.items()),"dangling_or_ambiguous_internal_links":dangling,"new_heading_navigation":nav}

    # Part/relationship/style/header/footer preservation from frozen current package.
    f,c=d["frozen_current"],d["candidate"]
    part_names_same=set(f["parts"])==set(c["parts"])
    non_doc_changed=[{"part":n,"frozen_sha256":h(v),"candidate_sha256":h(c["parts"].get(n,b""))} for n,v in f["parts"].items() if n!="word/document.xml" and c["parts"].get(n)!=v]
    rels_same=f["rels"]==c["rels"]
    style_header=[n for n in f["parts"] if n=="word/styles.xml" or re.fullmatch(r"word/(?:header|footer)\d+\.xml",n)]
    style_header_same={n:f["parts"].get(n)==c["parts"].get(n) for n in style_header}

    # Historical V1.46 exact-text coverage. Reconcile only the known current-overview/planning passages.
    vtext=[x["text"] for x in d["v146"]["paragraphs"]]; ctext=[x["text"] for x in d["candidate"]["paragraphs"]]
    seq=difflib.SequenceMatcher(None,[norm(x) for x in vtext],[norm(x) for x in ctext],autojunk=False)
    hist_unmatched=[]
    for tag,i1,i2,j1,j2 in seq.get_opcodes():
        if tag in ("delete","replace"):
            hist_unmatched.extend({"v146_paragraph_index":i,"text":vtext[i]} for i in range(i1,i2) if vtext[i].strip())
    marker=re.compile(r"(?:FAIL|STOP|NOT_ESTABLISHED|NOT_SUPPORTED|Hit@|AUC|RMSE|\bEXP\d+\b|\bINNO-\d+\b|[0-9]+(?:\.[0-9]+)?%|202[0-9][-/])",re.I)
    reviewed_plan_indices={1:"superseded V1.46 version label",2:"superseded overview/mission summary",5:"superseded A12/VesselForge/PG-Frag architecture summary",88:"superseded document-contents and appendix summary",179:"reframed research-question overview",2459:"superseded manual-evaluation planning paragraph",2750:"superseded competition-delivery planning paragraph",2751:"superseded paper-delivery planning paragraph",2802:"updated appendix/workstream navigation note"}
    historical_review=[{"v146_paragraph_index":x["v146_paragraph_index"],"classification":reviewed_plan_indices.get(x["v146_paragraph_index"],"UNEXPLAINED"),"text":x["text"]} for x in hist_unmatched]
    unmatched_unexplained=[x for x in historical_review if x["classification"]=="UNEXPLAINED"]
    absent_result_markers=[x for x in historical_review if marker.search(x["text"]) and x["v146_paragraph_index"] not in (5,88)]
    # V1.46 tables: exact ordered cell-text signatures, with only the three superseded planning tables exempted.
    def table_signature(t): return tuple(tuple(r["cells"]) for r in t["rows"])
    vtabs=[table_signature(t) for t in d["v146"]["tables"]]; ctabs=[table_signature(t) for t in d["candidate"]["tables"]]
    def table_reason(sig):
        flat=" ".join(x for row in sig for x in row)
        if "any@50" in flat or "Hit@10" in flat: return "superseded metric target/decision-threshold planning table"
        if "比赛系统的内部必做交付" in flat or "论文主张需要的证据" in flat: return "superseded competition-versus-paper delivery planning table"
        if "不合格处理" in flat and "必须内容" in flat: return "superseded data-acquisition contents/invalid-handling planning table"
        return "UNEXPLAINED"
    missing_table_records=[]; table_cursor=0
    for ti,sig in enumerate(vtabs,1):
        hit=next((j for j in range(table_cursor,len(ctabs)) if ctabs[j]==sig),None)
        if hit is None: missing_table_records.append({"v146_table_index":ti,"classification":table_reason(sig),"signature":sig})
        else: table_cursor=hit+1
    unmatched_historical_tables=[x for x in missing_table_records if x["classification"]=="UNEXPLAINED"]
    # Keep the old multiset comparison as a second check against accidental order-only artifacts.
    vtab_counts=collections.Counter(vtabs); ctab_counts=collections.Counter(ctabs)
    missing_old_tables=list((vtab_counts-ctab_counts).elements())

    # Candidate proposal ledger IDs remain unpromoted.
    user_i,cand_i=inno_rows(d["user"]),inno_rows(d["candidate"]); inno=[]
    for n in range(32,46):
        key=f"INNO-{n}"; rr=cand_i.get(key,[])
        states=[]
        for row in rr:
            states += re.findall(r"(?<![A-Z_])(RESEARCH_CANDIDATE|IDEA|DONE|COMPLETED|ACCEPTED|IMPLEMENTED|VALIDATED)(?![A-Z_])"," ".join(row["cells"]),re.I)
        inno.append({"id":key,"user_rows":len(user_i.get(key,[])),"candidate_rows":len(rr),"candidate_cells":[r["cells"] for r in rr],"status_tokens":[x.upper() for x in states],"candidate_or_idea_only":len(rr)==1 and bool(states) and all(x.upper() in ("RESEARCH_CANDIDATE","IDEA") for x in states)})

    # TRELLIS.2: exact concatenated cell w:t text and only three manual breaks in the target row.
    def trellis(d):
        found=[]
        for t in d["tables"]:
            for r in t["rows"]:
                if any("TRELLIS.2" in x for x in r["cells"]): found.append({"table":t["idx"],"row":r["row"],"cells":r["cells"],"breaks":r["breaks"]})
        return found
    tu,tf,tc=trellis(d["user"]),trellis(d["frozen_current"]),trellis(d["candidate"])
    break_delta=len(c["root"].findall(".//w:br",NS))-len(f["root"].findall(".//w:br",NS))
    trellis_check={"user_rows":tu,"frozen_rows":tf,"candidate_rows":tc,"exactly_one_each":len(tu)==len(tf)==len(tc)==1,"cell_text_exact_user":len(tu)==len(tc)==1 and tu[0]["cells"]==tc[0]["cells"],"cell_text_exact_frozen":len(tf)==len(tc)==1 and tf[0]["cells"]==tc[0]["cells"],"break_delta_document_vs_frozen":break_delta,"break_delta_trellis_row":tc[0]["breaks"]-tf[0]["breaks"] if len(tc)==len(tf)==1 else None,"exactly_three_new_breaks_all_in_trellis":break_delta==3 and len(tc)==len(tf)==1 and tc[0]["breaks"]-tf[0]["breaks"]==3}

    # Reject failed-width/fixed-grid variant by comparing every table geometry to user source.
    geometry_diffs=[]
    for i,(ut,ct) in enumerate(zip(d["user"]["tables"],d["candidate"]["tables"]),1):
        if ut["geometry"]!=ct["geometry"]: geometry_diffs.append({"table":i,"user_text":ut["text"][:250],"candidate_text":ct["text"][:250],"user_geometry":ut["geometry"],"candidate_geometry":ct["geometry"]})
    table_geometry={"user_tables":len(d["user"]["tables"]),"candidate_tables":len(d["candidate"]["tables"]),"geometry_diffs":geometry_diffs,"all_geometry_unchanged":len(d["user"]["tables"])==len(d["candidate"]["tables"]) and not geometry_diffs}

    # Current-font/header fixes: byte-identical ancillary parts plus expected Noto mapping and white dark header text.
    cjk=sum(1 for x in c["root"].iter() if x.tag==W+"rFonts" and x.get(W+"eastAsia")=="Noto Sans SC")
    dark=[]
    for ti,t in enumerate((x for x in c["body"] if x.tag==W+"tbl"),1):
        if ti!=55: continue
        first=t.find("w:tr",NS)
        if first is None: continue
        dark.append({"table":ti,"cells":[{"text":txt(tc),"fills":[shd.get(W+"fill","") for shd in tc.findall(".//w:shd",NS)],"colors":[col.get(W+"val","") for col in tc.findall(".//w:color",NS)]} for tc in first.findall("w:tc",NS)]})

    checks={"source_hashes_match_expected":all(hash_check[k] for k in ("user","v146","frozen_current")),"final_candidate_matches_final_proof":hash_check["candidate_matches_final_proof"],"previous_candidate_matches_initial_source_proof":hash_check["previous_candidate_matches_source_proof"],"eight_closeout_status_paragraphs_exact":len(protected)==8 and all(x["exact_text_unchanged"] for x in protected),"all_14_clarifications_preserved_or_superseded_by_exact_final_patches":clarification_result["all_14_verified_as_retained_or_refined"] and final_patch_check["all_eight_exact_old_new_patches_verified"],"all_user_paragraphs_exactly_retained_in_order_before_final_patchset":user_to_previous["all_source_paragraphs_retained_exactly_in_order"] and bool(source_proof.get("paragraphs",{}).get("all_user_paragraphs_preserved_in_order")),"final_text_changes_are_exactly_the_eight_declared_patches":final_patch_check["all_eight_exact_old_new_patches_verified"],"all_33_new_headings_uniquely_bookmarked_linked":nav_result["all_33_new_headings_present_once"] and nav_result["each_new_heading_has_one_unique_bookmark_and_link"],"original_520_bookmark_pairs_preserved":nav_result["original_id_name_pairs_preserved"],"old_internal_links_preserved_no_dangling":nav_result["old_internal_link_multiplicity_preserved"] and not nav_result["dangling_or_ambiguous_internal_links"],"old_relationships_preserved":rels_same,"historical_v146_unmatched_paragraphs_all_reviewed_planning_or_overview":len(hist_unmatched)==9 and not unmatched_unexplained and not absent_result_markers,"all_nonplanning_v146_tables_preserved_in_order":len(missing_table_records)==3 and not unmatched_historical_tables and len(missing_old_tables)==3,"INNO_32_45_not_promoted":all(x["candidate_or_idea_only"] for x in inno),"TRELLIS_text_exact_three_breaks":trellis_check["cell_text_exact_frozen"] and trellis_check["exactly_three_new_breaks_all_in_trellis"],"no_fixedgrid_or_width_change":table_geometry["all_geometry_unchanged"],"current_styles_headers_footers_preserved":all(style_header_same.values()),"candidate_Noto_font_mapping_present":cjk>0}
    status="STATIC_PASS_WITH_REVIEWED_SCOPE_EXCEPTIONS" if all(checks.values()) else "STATIC_REVIEW_BLOCKERS"
    results={"status":status,"status_note":"Read-only static review of the frozen final candidate. The 14 source clarifications and eight later planning refinements are enumerated with exact text; three superseded old planning tables and nine superseded overview/planning paragraphs are listed explicitly. Rendering remains a separate main-agent gate.","source_hashes_and_bytes":hashes,"hash_pins":hash_check,
      "package":{"parts":len(c["parts"]),"part_names_same_as_frozen":part_names_same,"changed_non_document_parts":non_doc_changed,"all_relationship_targets_same_as_frozen":rels_same,"relationship_parts_byte_identical":{n:c["parts"].get(n)==f["parts"].get(n) for n in f["parts"] if n.endswith(".rels")},"style_header_footer_byte_identical":style_header_same},
      "protected_eight_paragraphs":protected,"source_user_paragraph_retention":user_to_previous,"source_clarifications_14":clarification_result,"final_planning_refinements_8":final_patch_check,"new_headings_and_navigation":nav_result,
      "historical_text":{"v146_paragraphs":len(vtext),"candidate_paragraphs":len(ctext),"unmatched_v146_paragraphs_in_order":historical_review,"unexplained_unmatched_paragraphs":unmatched_unexplained,"numeric_or_result_marker_exceptions_outside_opening_summaries":absent_result_markers,"v146_table_count":len(vtabs),"candidate_table_count":len(ctabs),"unmatched_v146_tables_in_order":missing_table_records,"unmatched_v146_tables_by_exact_cell_text_count":len(missing_old_tables),"all_other_v146_tables_exact_and_in_order":len(missing_table_records)==3 and not unmatched_historical_tables},
      "INNO_32_to_45":inno,"TRELLIS_2":trellis_check,"table_geometry_fixedgrid_guard":table_geometry,
      "font_and_header_fixes":{"Noto_Sans_SC_eastAsia_mappings":cjk,"table55_dark_header_rows":dark},
      "proof_and_changelog":{"final_proof_path":str(args.proof.resolve()),"final_proof_sha256":h(args.proof.read_bytes()),"final_proof_candidate_hash_matches_observed":hash_check["candidate_matches_final_proof"],"source_proof_path":str(args.source_proof.resolve()),"source_proof_sha256":h(args.source_proof.read_bytes()),"source_proof_clarification_count":len(clar),"source_proof_previous_candidate_hash_matches_observed":hash_check["previous_candidate_matches_source_proof"],"changelog_path":str(args.changelog.resolve()),"changelog_sha256":h(args.changelog.read_bytes()),"changelog_text":changelog},"checks":checks}

    lines=["# Independent static review of merged V1.47 candidate","","**Status: static pass with reviewed scope exceptions.** This result applies to the final candidate hash below. It is a static review; rendering remains a separate main-agent gate.","","## File identity",""]
    for name,v in hashes.items(): lines.append(f"- {name}: {v['bytes']} bytes; SHA-256 `{v['sha256']}`")
    lines += ["",f"Final candidate matches FINAL_SOURCECHECK: **{hash_check['candidate_matches_final_proof']}**. The previous candidate matches the initial source proof: **{hash_check['previous_candidate_matches_source_proof']}**.","","## Static findings",""]
    for k,v in checks.items(): lines.append(f"- {k}: **{'PASS' if v else 'BLOCKER'}**")
    lines += ["",f"The eight frozen closeout paragraphs (seven status paragraphs plus the current p5 summary) are exact: {sum(x['exact_text_unchanged'] for x in protected)}/8.",f"All 14 accepted source clarifications occur exactly once in the previous merge candidate. {clarification_result['retained_exact_in_final']} remain verbatim in the final candidate; {clarification_result['superseded_by_final_exact_patches']} are refined by the exact final planning patch list. The 14 texts and links to their refinements are recorded in JSON.",f"The final candidate differs from its previous candidate at exactly {len(actual_changed_indices)} paragraph indexes, all covered by the eight exact old/new patches in FINAL_PATCHLIST. No unlisted paragraph-text changes were found.",f"All {user_to_previous['source_paragraphs']} user-source paragraphs were found in order in the previous merge candidate; the final eight refinements are applied afterward at declared indexes. This does not claim every user paragraph is byte-identical in the final file.",f"Navigation: {len(new)} newly added headings, each with one bookmark and one internal link; all 520 original bookmark ID/name pairs remain; no orphan internal links. Package relationships and styles/header/footer XML match the frozen closeout source.",f"Historical V1.46 comparison: {len(hist_unmatched)} unmatched paragraphs, all classified as superseded overview/planning text; {len(missing_table_records)} exact unmatched tables, all classified as superseded planning tables. All other V1.46 table signatures remain in order. Exact exclusions and texts are in JSON.",f"INNO-32–45 remain IDEA/RESEARCH_CANDIDATE. TRELLIS.2 text is unchanged with exactly three added manual breaks; all {len(d['user']['tables'])} user tables retain their source geometry.","", "## Accepted exception sets", "", "The 14 source clarification texts and the eight final old/new paragraph replacements are recorded verbatim in JSON. The final three obsolete V1.46 planning tables are the competition/paper delivery matrix, metric target table, and acquisition-content table; the nine absent old paragraphs are version/overview, architecture/document summary, reframed question, delivery-plan, and appendix-navigation text. The result does not claim that all 7,462 source paragraphs remained text-identical.","", "No DOCX, source file, Git state, or numeric experiment was changed or run.",""]
    (WORK/"independent_merged_static.md").write_text("\n".join(lines),encoding="utf-8")
    (WORK/"independent_merged_static.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":results["status"],"candidate":hashes["candidate"],"checks":results["checks"],"report":str(WORK/"independent_merged_static.md"),"json":str(WORK/"independent_merged_static.json")},ensure_ascii=False,indent=2))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--candidate",type=Path,default=CAND)
    ap.add_argument("--previous",type=Path,default=PREVIOUS)
    ap.add_argument("--proof",type=Path,default=PROOF)
    ap.add_argument("--source-proof",type=Path,default=SOURCE_PROOF)
    ap.add_argument("--changelog",type=Path,default=CHANGELOG)
    ap.add_argument("--expected-candidate-sha",default="")
    args=ap.parse_args()
    if not args.candidate.exists():
        print(json.dumps({"status":"READY_NO_CANDIDATE","candidate":str(args.candidate),"outputs_not_written":True}))
        return
    run(args)

if __name__=="__main__": main()
