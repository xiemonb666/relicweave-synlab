#!/usr/bin/env python3
"""Write compact decision-ready comparison for main-agent merge review."""
from __future__ import annotations
import hashlib, json, re
from pathlib import Path

ROOT=Path(__file__).resolve().parent
D=json.loads((ROOT/"diff_v147_user_structural.json").read_text(encoding="utf-8"))
docs=D["documents"]
baseline_user=D["diffs"][0]
current_user=D["diffs"][1]
def norm(s): return re.sub(r"\s+"," ",s).strip()
def bodyseq(doc): return [x for x in doc["blocks"] if x.get("kind") in ("paragraph","table_cell_paragraph")]

def find_text(doc, starts):
    for b in bodyseq(doc):
        if b["text"].startswith(starts): return b
    return None

def clean_op(op):
    def block(x): return {k:x.get(k) for k in ("idx","kind","route","text","style","outline_level","is_heading","heading","bookmarks") if k in x}
    return {"operation":op["op"],"alignment":op.get("alignment_method"),"before":[block(x) for x in op["before"]],"after":[block(x) for x in op["after"]]}

def idx_key(op):
    x=(op.get("after") or op.get("before") or [{}])[0]
    return x.get("idx",10**9)

new_heads=[]
for op in baseline_user["operations"]:
    if op["op"]!="add": continue
    for b in op["after"]:
        if b.get("is_heading") and b.get("text"," ").strip():
            item={"block":b["idx"],"heading":b["text"].strip()}
            if item["heading"] not in {h["heading"] for h in new_heads}: new_heads.append(item)
new_heads.sort(key=lambda x:x["block"])

all_add=[b for op in baseline_user["operations"] if op["op"]=="add" for b in op["after"]]
all_empty=sum(not b.get("text","").strip() for b in all_add)
base_seq=bodyseq(docs["baseline"]); user_seq=bodyseq(docs["user"]); current_seq=bodyseq(docs["current"])

# Seven exact current closeout status paragraphs omitted from the user's standalone revision.
status_prefixes=("A12.19 当前状态", "A12.20 当前实施与资格边界", "V1.47（2026-10-07）收口记录", "G0 当前状态", "G31.1 V1.47 收口核对", "VesselForge 当前状态", "PG-Frag 当前状态")
status_rows=[]
for op in current_user["operations"]:
    if op["op"]!="delete": continue
    for b in op["before"]:
        if b.get("text","").startswith(status_prefixes):
            status_rows.append({"source_block":b["idx"],"heading":b.get("heading",""),"text":b["text"]})
status_rows.sort(key=lambda x:x["source_block"])

replacements=[clean_op(op) for op in baseline_user["operations"] if op["op"]=="replace"]
replacements.sort(key=idx_key)
current_deletes=[clean_op(op) for op in current_user["operations"] if op["op"]=="delete"]
current_deletes.sort(key=idx_key)

part_rows={}
for a,b in (("baseline","user"),("current","user")):
    da,db=docs[a],docs[b]
    pa,pb=set(da["part_names"]),set(db["part_names"])
    changed=[]
    for part in sorted(pa&pb):
        ha=da["part_hashes"][part]["sha256"]; hb=db["part_hashes"][part]["sha256"]
        if ha!=hb: changed.append({"part":part,"before_sha256":ha,"after_sha256":hb,"before_bytes":da["part_hashes"][part]["bytes"],"after_bytes":db["part_hashes"][part]["bytes"]})
    part_rows[f"{a}_to_user"]={"parts_before":len(pa),"parts_after":len(pb),"added":sorted(pb-pa),"removed":sorted(pa-pb),"changed_part_payloads":changed}

def relmap(doc): return {r["id"]:(r["type"],r["target"],r["target_mode"]) for r in doc["document_relationships"]}
relationship_rows={}
for a in ("baseline","current"):
    ra,rb=relmap(docs[a]),relmap(docs["user"])
    relationship_rows[f"{a}_to_user"]={"before":len(ra),"after":len(rb),"added":sorted((k,v) for k,v in rb.items() if k not in ra),"removed":sorted((k,v) for k,v in ra.items() if k not in rb),"changed":sorted((k,ra[k],rb[k]) for k in ra.keys()&rb.keys() if ra[k]!=rb[k])}

def style_sig(s): return tuple(s.get(k,"") for k in ("type","default","name","based_on","next","outline_level","pPr_xml","rPr_xml"))
style_diff={}
for a in ("baseline","current"):
    sa,sb=docs[a]["styles"],docs["user"]["styles"]
    style_diff[f"{a}_to_user"]={"before_count":len(sa),"after_count":len(sb),"added":sorted(sb.keys()-sa.keys()),"removed":sorted(sa.keys()-sb.keys()),"changed":sorted(k for k in sa.keys()&sb.keys() if style_sig(sa[k])!=style_sig(sb[k]))}
used_paragraph_styles=sorted({b.get("style","") for b in all_add if b.get("style")})
added_body_ops=D["direct_body_diffs"][0]["operations"]
used_table_styles=sorted({b.get("table_style","") for op in added_body_ops if op["op"]=="add" for b in op["after"] if b.get("kind")=="table" and b.get("table_style")})
changed_style_ids=set(style_diff["current_to_user"]["changed"])
style_review={"paragraph_styles_used_in_additions":used_paragraph_styles,"table_styles_used_in_added_tables":used_table_styles,"all_exist_in_current_closeout":all(x in docs["current"]["styles"] for x in used_paragraph_styles+used_table_styles),"changed_between_current_and_user_intersection":sorted(changed_style_ids.intersection(set(used_paragraph_styles+used_table_styles))),"definitions_baseline_vs_user":style_diff["baseline_to_user"],"definitions_current_vs_user":style_diff["current_to_user"]}

direct=[]
for d in D["direct_body_diffs"]:
    rows=[x["after"][0] for x in d["operations"] if x["op"]=="add"]
    dels=[x["before"][0] for x in d["operations"] if x["op"]=="delete"]
    direct.append({"before":d["before"],"after":d["after"],"direct_top_level_block_counts":{"before":len(docs["baseline"]["direct_body_blocks"] if d["before"].startswith("RelicWeave_V1.46") else docs["current"]["direct_body_blocks"]),"after":len(docs["user"]["direct_body_blocks"])},"alignment_added_blocks":len(rows),"alignment_removed_blocks":len(dels),"added_tables":sum(x.get("kind")=="table" for x in rows),"removed_tables":sum(x.get("kind")=="table" for x in dels)})

key_source_texts={
 "new_unified_mission":find_text(docs["user"],"主问题升级为："),
 "new_historical_gt_rule":find_text(docs["user"],"UA-IFRMN 必须显式尊重现行标签定义"),
 "new_closed_vessel_gt_rule":find_text(docs["user"],"Level 3评测要求每个eligible object拥有member_manifest"),
 "new_truthpack_access_rule":find_text(docs["user"],"A12新增一类paired counterfactual release"),
 "new_ui_workflow":find_text(docs["user"],"结果页采用“三层视图”"),
 "new_current_intro":find_text(docs["user"],"V1.47在V1.46双子基础设施版本上统一最新项目主线"),
}
key_source_texts={k:({"source_block":v["idx"],"heading":v.get("heading",""),"text":v["text"]} if v else None) for k,v in key_source_texts.items()}

summary={
 "scope":"Read-only structural/semantic comparison. No source DOCX was edited; no merge or numerical experiment was run.",
 "source_integrity":{k:{key:d[key] for key in ("name","file","bytes","sha256","zip_entries") } for k,d in docs.items()},
 "paragraph_stream_counts":{"baseline":len(base_seq),"current_closeout":len(current_seq),"user":len(user_seq),"baseline_to_user":{"equal":baseline_user["stats"]["equal"],"probable_replacements":baseline_user["stats"]["replace"],"added":baseline_user["stats"]["add"],"deleted":baseline_user["stats"]["delete"],"added_blank_blocks":all_empty,"net_paragraphs":len(user_seq)-len(base_seq)},"current_closeout_to_user":{"equal":current_user["stats"]["equal"],"probable_replacements":current_user["stats"]["replace"],"added":current_user["stats"]["add"],"deleted":current_user["stats"]["delete"],"net_paragraphs":len(user_seq)-len(current_seq)},"headings":{"baseline":sum(bool(b.get('is_heading')) for b in base_seq),"user":sum(bool(b.get('is_heading')) for b in user_seq),"net_added":sum(bool(b.get('is_heading')) for b in user_seq)-sum(bool(b.get('is_heading')) for b in base_seq)}},
 "direct_body_alignment_each_top_level_w_p_or_w_tbl_one_block":direct,
 "new_heading_ids_and_titles":new_heads,
 "semantic_change_groups":[
  {"group":"Task and product scope","sections":["1.3","2.0","2.1","2.2","2.2.2","2.4","D6.5","D10.2"],"finding":"Expands from direct R2 neighbor retrieval to Level 1 R2 retrieval, Level 2 same-vessel R1/R2 retrieval, and Level 3 closed-gallery member-set recovery. Adds expert workflow and value evidence framing; still preserves UNKNOWN, human review, recapture/stop at mission level."},
  {"group":"UA-IFRMN relational research candidate","sections":["A6.14–A6.24","EXP12"],"finding":"Adds uncertainty-aware soft typed relation memory, distinct R2 local and vessel identity memory, contact-conditioned identity expansion, scalar-vs-latent feedback tests, evidence provenance/de-correlation, joint reread/revision, and Oracle→predicted→corrupted relation gates. Explicitly candidate/hypothesis; not a completed model result."},
  {"group":"Whole-vessel membership and evaluation","sections":["A6.25","EXP11","B2.3","B3","D6.5"],"finding":"Defines V_G(q), Vessel Precision/Recall/F1, complete member manifests, missing-fragment disposition and UNKNOWN; restricts Level 3 primary evaluation to closed membership sets. UI separates R2, R1/R2 same-vessel candidates, and the predicted set with human accept/reject/revision."},
  {"group":"High-degradation robustness and synthetic-to-real","sections":["A6.26","EXP10","A12.21–A12.23"],"finding":"Adds paired/counterfactual D0→Dn degradation curves, traditional and static-learning comparisons under the same legal observation permissions, physical degradation failure points, real-domain confirmation, whole-vessel episode generation, and synthetic-data value gates based on real-domain gains."},
  {"group":"Research positioning and delivery","sections":["A6.14","A6.22–A6.24","A6.27–A6.28","10–10.3","11"],"finding":"Adds literature map, explicit no-go novelty claims, conference evidence thresholds, and separate competition/paper evidence plans; old short section-10 delivery paragraphs are removed and replaced by the new section-10 material."},
  {"group":"Historical-data governance","sections":["1.3","history-use paragraph"],"finding":"States current task claims may update while A–F historical values/FAIL/STOP/hash remain frozen; new Level 2/3 claims require new frozen experiments and cannot be inferred from old Hit@K/pair results."}
 ],
 "changed_headings":new_heads,
 "replacements_baseline_to_user":replacements,
 "exact_closeout_status_paragraphs_missing_from_user_doc":status_rows,
 "other_current_closeout_text_removed_or_superseded":[clean_op(op) for op in current_user["operations"] if op["op"]=="delete" and not any(b.get("text","").startswith(status_prefixes) for b in op["before"])],
 "key_exact_new_texts":key_source_texts,
 "package_parts":part_rows,
 "relationships":relationship_rows,
 "bookmark_identity_comparison":{"baseline_count":len(docs["baseline"]["bookmarks"]),"user_count":len(docs["user"]["bookmarks"]),"current_count":len(docs["current"]["bookmarks"]),"baseline_user_changed":sorted(set((x.get('part',''),x['id'],x['name']) for x in docs['baseline']['bookmarks']) ^ set((x.get('part',''),x['id'],x['name']) for x in docs['user']['bookmarks'])),"current_user_changed":sorted(set((x.get('part',''),x['id'],x['name']) for x in docs['current']['bookmarks']) ^ set((x.get('part',''),x['id'],x['name']) for x in docs['user']['bookmarks']))},
 "changed_block_styles":style_review,
 "review_findings_and_feasibility":[
  {"area":"GT leakage boundary","finding":"A6.16 says final A–C relation still depends on direct-contact evidence and historical-adjacency truth; historical GT must remain label/evaluation-only at inference. The V1.47 A12.21 addition separately says TruthPack is only for evaluation, and A6.20 intentionally includes an Oracle-R2 upper-bound arm. Keep Oracle labels isolated from predicted-R2 product inference and split by vessel/parent/episode to prevent identity leakage."},
  {"area":"Current implementation status","finding":"The user update is mostly target/specification language. The seven exact closeout paragraphs are absent from it and should be retained: A12.19, A12.20, closeout history record, G0, G31.1, VesselForge status, and PG-Frag status. Those paragraphs state no full physics-qualified package or end-to-end retrieval result; 31 axes/155 QA combinations are software QA, only 9 axes/36 nonzero levels are measured and uncalibrated from one parent; 16 pattern IDs lack historical validation; 12 material IDs lack physical calibration; native C4 is source-only; PG-Frag toy/moving-front evidence has not established fragmentation."},
  {"area":"Computational/algorithmic feasibility","finding":"The proposed graph/memory loop is a research-scale system, not a drop-in pairwise reranker. The source itself flags possible O(N²) whole-graph recomputation and says to cap update radius/candidate count. Start with fixed Top-K, bounded relation neighborhoods, limited reread rounds, and report wall-clock/memory; graduate only after Oracle-R2 shows headroom and predicted/corrupted-R2 retains it."},
  {"area":"Physical/data feasibility","finding":"Level 3 requires a genuinely closed member manifest and known missing-fragment disposition; synthetic episodes can test mechanics but cannot establish real-vessel recovery. High-degradation claims require calibrated axes plus real-domain paired confirmation; current closeout shows the physical qualification and real retrieval evidence are absent."},
  {"area":"Workflow contract","finding":"The added D6.5 path explicitly covers capture/import→coarse retrieval→R2→initial vessel memory→R1 discovery→human verification→set update/stop, with accept/reject, revision, UNKNOWN, and a research-mode warning before Level 3 validation. Mission-level text retains recapture/stop, though recapture is not an explicit action in that D6.5 demo sequence."},
  {"area":"Literature/newness","finding":"The user document gives a useful prior-art map and explicitly forbids broad 'first autoregressive' or 'first feedback' claims. The references and novelty remain unverified in this scoped read-only diff; require separate current-source verification before submission."}
 ],
 "merge_recommendation":"Use the current V1.47 closeout as the merge base. Transplant the user document's new specification sections and intentionally changed task/metric/UI text after review, while preserving the seven exact closeout status paragraphs, existing closeout evidence and style/header/font fixes. Keep current style definitions: the user file is style-identical to V1.46, while current closeout changed style definitions; all paragraph/table styles used by new additions already exist in current closeout. Reconcile the two removed legacy competition/paper paragraphs with the expanded section 10 rather than blindly deleting execution content. The source package has the same part paths, relationship IDs/targets, and bookmark `(part,id,name)` identities, so no new relationship or bookmark migration is indicated. This recommendation is structural; no merge was performed."
}
summary["historical_result_scope"]={"changed_historical_result_paragraphs":[],"finding":"Alignment shows no historical experiment-result/old numeric-result blocks changed. New content is additive in the current task/research sections, A6 research ledger, A12.21–A12.23, B2/B3 GT contract, D6/D10, and section 10; the history-use paragraph is updated to state that old results remain frozen. No bookmark or relationship identities changed."}

# Compact markdown companion.
md=["# V1.47 user update diff summary","", "## Decision summary","", "The user V1.47 file is a specification update built from the V1.46 integrated baseline. It adds a three-level retrieval goal, whole-vessel membership evaluation, high-degradation tests, and the UA-IFRMN research candidate. It omits the seven current closeout status paragraphs. Use the current closeout as the merge base and transplant the reviewed specification deltas while retaining its status and font/style fixes.","", "## Counts and integrity","",f"- Paragraph/cell stream: baseline **{len(base_seq)}**, current closeout **{len(current_seq)}**, user V1.47 **{len(user_seq)}**. Baseline→user: **{baseline_user['stats']['add']} adds**, **{baseline_user['stats']['delete']} deletes**, **{baseline_user['stats']['replace']} probable replacements**; net **+{len(user_seq)-len(base_seq)}** blocks. Current closeout→user: {current_user['stats']['add']} adds, {current_user['stats']['delete']} deletes, {current_user['stats']['replace']} replacements.",f"- Headings: 339 → 372 (**+{len(new_heads)} added heading entries by alignment**).","- All three packages contain the same 23 part paths. All 14 document relationships and all 19 package relationship declarations match; all 520 bookmark `(part,id,name)` identities match.","- V1.46 and user style definitions match. Current closeout differs in 75 style definitions; incoming paragraphs use Heading2, Heading3, Normal, and SYNBody, which all exist in the current closeout. Preserve its font/style fix.","- No historical experiment-result or old numeric-result paragraph changed. New appendix content adds A12.21–A12.23; the updated history-use paragraph says old results remain frozen.","", "## Main deltas","", "1. **Task scope:** R2 direct-neighbor retrieval becomes Level 1; Level 2 adds same-vessel R1/R2 retrieval; Level 3 targets a closed-gallery member set from one query fragment. It is not full geometric assembly or restoration.","2. **UA-IFRMN:** proposes typed soft relations, separate direct-contact and same-vessel reasoning, R2 local and vessel identity memory, candidate-conditioned feedback, evidence provenance, reversible rereading, and bounded stopping. It is explicitly a research candidate.","3. **Evaluation:** adds Vessel Precision/Recall/F1 and complete member manifests; restricts Level 3 claims to closed membership sets with missing-fragment disposition and UNKNOWN preserved.","4. **Robustness:** adds paired D0→Dn degradation comparisons, matched traditional and static-learning baselines, real-domain confirmation, whole-vessel episodes, and real-domain utility gates for synthetic scale-up.","5. **Product/workflow:** adds separate R2, R1/R2, and predicted vessel-set views; human accept/reject with revisions; research-mode labeling before Level 3 validation. Mission language preserves recapture/STOP, but D6.5 demo path does not name recapture as a UI action.","6. **Governance/delivery:** adds frozen-history rules, narrows novelty claims, and replaces two shorter old contest/paper plan paragraphs with new section 10.","", "## Added section headings","",*[f"- block {x['block']}: {x['heading']}" for x in new_heads],"", "## Critical boundary","", "A6.16 refers to historical adjacency truth when finalizing R2/R1/UNKNOWN; keep that truth as training labels/evaluation only, never an inference-time feature. The document separately says TruthPack is evaluation-only and presents Oracle-R2 as a controlled upper-bound experiment, which is compatible if the separation is enforced. The current closeout still reports zero complete physics-qualified package and no established end-to-end retrieval benefit; the user's proposed metrics, gates, and architecture are not achieved results.","", "## Exact replacements and omitted closeout status","", "The paired JSON carries exact old/new replacement text plus the seven status paragraphs. The full detailed paragraph/table-cell manifest is `diff_v147_user_manifest.json`; the larger structural extraction and readable full report are diagnostic artifacts, not merge inputs.","", "## Feasibility and merge path","", "Level 3 is feasible first on explicitly closed synthetic episodes, then on a separately closed real cohort; incomplete natural collections can support Level 1/2 only. UA-IFRMN should start with bounded Top-K graphs and limited reread radius/rounds because full-graph refresh may be O(N²). Preserve the user's own oracle→predicted→corrupted go/no-go sequence; do not claim a real-domain result until current physical/data qualification gaps are closed.","", "Merge from current closeout; import the reviewed new sections and replacement wording; retain the seven closeout status paragraphs and current style/header/font fixes. Reconcile the removed old delivery paragraphs with section 10. No merge or source-file edit was done.","", "## Source hashes","",*[f"- {d['name']}: {d['bytes']} bytes, SHA-256 `{d['sha256']}`" for d in docs.values()],""]
(ROOT/"diff_summary.md").write_text("\n".join(md),encoding="utf-8")
(ROOT/"diff_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"summary_markdown":str(ROOT/"diff_summary.md"),"summary_json":str(ROOT/"diff_summary.json"),"added_headings":len(new_heads),"added_blank_blocks":all_empty,"closeout_status_paragraphs":len(status_rows),"used_paragraph_styles":used_paragraph_styles,"used_table_styles":used_table_styles,"style_intersection_changes":style_review["changed_between_current_and_user_intersection"]},ensure_ascii=False,indent=2))
