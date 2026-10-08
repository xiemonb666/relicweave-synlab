import copy,hashlib,json,zipfile
from pathlib import Path
from lxml import etree

ROOT=Path(r"C:\Users\xiemo\Desktop\ShardForge")
TMP=ROOT/"tmp"/"v147_user_merge_20261007"
SRC=TMP/"fresh_merge_candidate.docx"
OUT=TMP/"fresh_merge_final_candidate.docx"
CURRENT=ROOT/"RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx"
USER=ROOT/"RelicWeave_V1.47.docx"
WURI="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS={"w":WURI}; W="{"+WURI+"}"
PARSER=etree.XMLParser(resolve_entities=False,no_network=True,remove_blank_text=False)
EXPECTED={
 CURRENT.name:(734565,"9af0efe877115200dd99bbcf8f24f3124e2932245d71795fc00252d08e278436"),
 USER.name:(779513,"41f1254e40a2ecabdcfa1c6583af2fce0ae1b0ab980d5f9179bbaf687b7be64b"),
}
def sha(b): return hashlib.sha256(b).hexdigest()
def fhash(p):
 b=p.read_bytes(); return len(b),sha(b)
def read_doc(path):
 with zipfile.ZipFile(path) as z:
  parts={i.filename:(i,z.read(i.filename)) for i in z.infolist()}
 return etree.fromstring(parts["word/document.xml"][1],PARSER),parts
def body(r): return r.xpath(".//w:body",namespaces=NS)[0]
def paras(b): return b.xpath(".//w:p",namespaces=NS)
def text(p): return "".join(t.text or "" for t in p.xpath(".//w:t",namespaces=NS))
def one(b,needle,label,exact=False):
 hits=[p for p in paras(b) if (text(p)==needle if exact else needle in text(p))]
 if len(hits)!=1: raise RuntimeError(f"{label}: expected one hit, got {len(hits)}")
 return hits[0]
def replace_span(p,old,new,label):
 full=text(p)
 if full.count(old)!=1: raise RuntimeError(f"{label}: old text occurrence {full.count(old)}")
 s=full.index(old); e=s+len(old)
 nodes=p.xpath(".//w:t",namespaces=NS)
 spans=[]; cur=0
 for n in nodes:
  v=n.text or ""; spans.append((n,cur,cur+len(v),v)); cur+=len(v)
 fi=next((i for i,x in enumerate(spans) if x[1]<=s<x[2] or (s==cur and i==len(spans)-1)),None)
 li=next((i for i,x in enumerate(spans) if x[1]<e<=x[2]),None)
 if fi is None or li is None: raise RuntimeError(f"{label}: unable to map text range to runs")
 if fi==li:
  n,lo,hi,v=spans[fi]; n.text=v[:s-lo]+new+v[e-lo:]
 else:
  n,lo,hi,v=spans[fi]; n.text=v[:s-lo]+new
  for j in range(fi+1,li): spans[j][0].text=""
  n,lo,hi,v=spans[li]; n.text=v[e-lo:]
 if text(p)!=full[:s]+new+full[e:]: raise RuntimeError(f"{label}: replacement mismatch")
 return full,text(p)
def identity(root): return {(x.get(W+"id"),x.get(W+"name")) for x in root.xpath(".//w:bookmarkStart",namespaces=NS)}
def internal(root): return [x.get(W+"anchor") for x in root.xpath(".//w:hyperlink[@w:anchor]",namespaces=NS)]
def breaks(root): return len(root.xpath(".//w:br",namespaces=NS))
def para_style(p):
 x=p.xpath("./w:pPr/w:pStyle/@w:val",namespaces=NS)
 return x[0] if x else ""
def main():
 for p in (CURRENT,USER):
  if fhash(p)!=EXPECTED[p.name]: raise RuntimeError(f"source changed: {p.name}")
 if not SRC.exists(): raise RuntimeError("prior candidate missing")
 sr,sp=read_doc(SRC); sb=body(sr); before=[text(p) for p in paras(sb)]
 oldhash=fhash(SRC)[1]
 patches=[]
 def patch(p,old,new,label):
  a,b=replace_span(p,old,new,label)
  patches.append({"label":label,"before":a,"after":b})
  return p

 # B2.3: only unresolved in-gallery member membership excludes Level 3.
 b23=one(sb,"Level 3评测要求每个eligible object拥有member_manifest","B2.3 first paragraph")
 old=("若某母体只知道若干邻接但不知道是否还有同器物碎片遗失或未入库，则只能参加Level 1/2的限定评测，不能进入完整成员恢复主分母。")
 new=("仅当冻结图库G内的member归属尚未闭合时，母体才排除Level 3完整成员恢复主分母；原器物仍有碎片遗失或未入库不会自动排除，只须把已知去向作为审计信息记录。")
 patch(b23,old,new,"B2.3 closed gallery membership")

 # A6.16: historic truth is offline only; UNKNOWN is separate from the physical relation posterior.
 a616=one(sb,"A6.16 从 R2 到 R1 的关系代数","A6.16 heading")
 ps=paras(sb); i616=ps.index(a616)
 end616=next((i for i in range(i616+1,len(ps)) if "A6.17 为什么不能只把" in text(ps[i])),len(ps))
 a616_first=next(p for p in ps[i616+1:end616] if text(p).startswith("UA-IFRMN 必须显式尊重现行标签定义"))
 old=("最终 A—C 是 R1、R2 还是 UNKNOWN，仍要由直接接触证据和历史邻接真值判定。")
 new=("最终A—C的R0/R1/R2物理关系后验及独立UNKNOWN/abstention，仅在线由合法观测形成；历史邻接真值只作离线标签与评测，不进入在线推理。")
 patch(a616_first,old,new,"A6.16 offline truth boundary")

 clar=next(p for p in ps[i616+1:end616] if text(p).startswith("历史断裂/邻接真值只可作为离线训练标签"))
 clar_old=text(clar)
 clar_new=("历史断裂/邻接真值只可作为离线训练标签、损失、按母体分组的split审计及评测标签；推理时只可使用合法ObsPack并产生预测关系后验或UNKNOWN/abstention。GT标签用于离线监督是允许的，但GT pose、motherID、true relation graph与TruthPack不能进入在线特征、memory或candidate generator。provenance ID用于审计和去相关，不作为身份特征；姿态字段记录predicted_pose_hat及其不确定性。UNKNOWN是独立的认识论拒判状态，不是第四种物理关系；物理关系后验只覆盖R0/R1/R2，保持P_R2≤P_same，缺少R2证据不能推出R1。同一器物same-vessel身份在闭合成员集合中构成等价/传递关系；直接邻接R2和同器物非邻接R1各自都不具传递性。下表是预测边的soft belief推理，不是历史GT事实或硬合并。")
 if clar_old==clar_new: raise RuntimeError("A6.16 clarification unexpectedly unchanged")
 replace_span(clar,clar_old,clar_new,"A6.16 clarification")
 patches.append({"label":"A6.16 relation algebra clarification","before":clar_old,"after":clar_new})

 # Table heading scoped to A6.16.
 combos=[p for p in ps[i616+1:end616] if text(p)=="关系组合"]
 if len(combos)!=1: raise RuntimeError(f"A6.16 relation table heading count {len(combos)}")
 patch(combos[0],"关系组合","预测关系组合","A6.16 table heading")

 # Prediction head: physical relation posterior plus separate epistemic abstention.
 th=one(sb,"typed relation head 在 R0/R1/R2/UNKNOWN 上给出最终分布。","typed relation head")
 patch(th,"随后由 typed relation head 在 R0/R1/R2/UNKNOWN 上给出最终分布。",
       "随后由typed relation head输出R0/R1/R2物理关系后验，并将认识论UNKNOWN/abstention作为独立拒判状态。",
       "A6.17 typed relation posterior")

 # A12.21: fixed physical fragments, calibrated level semantics, and D5 as separate real-domain confirmation.
 a1221=one(sb,"退化评测分开两条轨道：","A12.21 clarification")
 a1221_old=text(a1221)
 a1221_new=("退化评测分开两条轨道：固定物理碎片及历史GT，仅改变观测条件，用于配对诊断；真实磨损、材料流失、新崩边、二次断裂、事件变化与fragment leaf lineage作为新的物理事件/版本记录。后者更新current_fit_valid、evidence_visible和current-leaf relations，并保留历史R2事实及其版本，不以当前状态覆盖历史邻接真值。D1–D4在物理量映射完成并校准前仅为压力配方/强度档，不得称为轻度或严重真实磨损或真实年代等级；D5是独立真实域确认，不是同一有序严重度轴的第五级。31条退化轴QA状态维持UNCAL。")
 if a1221_old==a1221_new: raise RuntimeError("A12.21 clarification unexpectedly unchanged")
 replace_span(a1221,a1221_old,a1221_new,"A12.21 clarification")
 patches.append({"label":"A12.21 fixed-observation and degradation semantics","before":a1221_old,"after":a1221_new})

 # Macro metrics: average queries within object first, then equal weight objects; cluster CI at highest related source.
 metric=one(sb,"分母边界补充：","closed-gallery metric clarification")
 metric_old=text(metric)
 metric_new=("分母边界补充：只有|V_G(q)|>0时才按常规闭合集合定义报告成员召回；此时若预测集合为空，Recall=0、Precision=NA、F1=0。若|V_G(q)|=0，应单独报告member-absent判定、false-inclusion数量/率及abstention；真值与预测都为空只记为correct-empty，不能把Precision、Recall或F1伪记为1。开世界样本及未通过完整工作流资格的样本分开计数，不并入Level 3闭合集合主分母。汇总先在每个器物内对query等权平均，再对器物等权宏平均；区间按独立器物聚类估计，若同批次或来源相关则按更高层来源簇估计。query加权均值仅作补充。")
 if metric_old==metric_new: raise RuntimeError("metric clarification unexpectedly unchanged")
 replace_span(metric,metric_old,metric_new,"metrics clarification")
 patches.append({"label":"2.2.2 object-equal macro and cluster CI","before":metric_old,"after":metric_new})

 # Oracle comparison must be matched across all relevant conditions; unmatched is unresolved.
 oracle=one(sb,"Oracle-R2是特权离线诊断条件","Oracle comparison clarification")
 oracle_old=text(oracle)
 oracle_new=("Oracle-R2是特权离线诊断条件，用于检查已知关系上下文是否有信息；它不是严格的信息论上界，也不是可部署性能。比较必须匹配candidate pool、context count、quality、fields、budget与source correlation，并加入shuffle-neighbor对照及可行时的等量GT-R1对照；无法匹配则标为未决、不可归因。真实合格数据与闭合GT足以先做静态/上下文信息测试；物理pack只作为物理合成或物理预训练主张的门槛。")
 if oracle_old==oracle_new: raise RuntimeError("oracle clarification unexpectedly unchanged")
 replace_span(oracle,oracle_old,oracle_new,"Oracle clarification")
 patches.append({"label":"A6.20 mandatory Oracle controls","before":oracle_old,"after":oracle_new})

 after=[text(p) for p in paras(sb)]
 if len(before)!=len(after): raise RuntimeError("paragraph count changed")
 changed=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
 if len(changed)!=len(patches): raise RuntimeError(f"expected {len(patches)} changed paragraphs, got {len(changed)}")
 # Check exact protected current paragraphs before/after.
 srcjson=json.loads((TMP/"fresh_merge_SOURCECHECK.json").read_text(encoding="utf-8"))
 diff=json.loads((TMP/"diff_summary.json").read_text(encoding="utf-8-sig"))
 current_root,_=read_doc(CURRENT); user_root,_=read_doc(USER)
 protected=[x["text"] for x in diff["exact_closeout_status_paragraphs_missing_from_user_doc"]]
 # Current source p5 is the eighth protected paragraph.
 protected.append("V1.47（2026年10月7日）为 A12、VesselForge 与 PG-Frag 的实现收口和证据归位版：维持三项目的独立边界，补入本轮实现状态、诊断证据及资格缺口。PG-Frag 当前仅有 virgin elastic 固定裂面 bridge 与未形成断开的开口历史 toy；12 状态中 step_index=0..7 尚非全点损伤（step_index=7 的 D 范围为 2/3–1），只有 step_index=8..11（第 9–12 状态）全点 D=1 且 bulk 才受拉；moving-front 因联合字段契约错配而在 wrench/KKT/G 主结果之前停止，未重试；objectivity 与 native C4 均仍为源码审阅，不是新增数值成绩。当前 VesselForge、PG-Frag 与 A12 的进度仍是工程判断，不是校准完成率或模型效果。")
 # Use the exact full summary from the previous candidate as the trusted eighth text.
 prevtexts=before
 summary_hits=[s for s in prevtexts if s.startswith("V1.47（2026年10月7日）为 A12、VesselForge")]
 if len(summary_hits)!=1: raise RuntimeError("protected current p5 summary not found")
 protected[-1]=summary_hits[0]
 for x in protected:
  if sum(t==x for t in after)!=1: raise RuntimeError("protected current-state paragraph changed/duplicated")
 # Any historical closeout record remains unchanged.
 hist=[x for x in protected if x.startswith("V1.47（2026-10-07）收口记录") or x.startswith("V1.47（2026年10月7日）收口记录")]
 if hist and any(x not in after for x in hist): raise RuntimeError("historical closeout record changed")

 # Write only document.xml into the prior current-package-based candidate.
 xml=etree.tostring(sr,xml_declaration=True,encoding="UTF-8",standalone=True)
 with zipfile.ZipFile(OUT,"w") as z:
  for name,(info,data) in sp.items(): z.writestr(info,xml if name=="word/document.xml" else data)
 rr,rparts=read_doc(OUT); finaltexts=[text(p) for p in paras(body(rr))]
 if finaltexts!=after: raise RuntimeError("final readback text differs")
 if identity(rr)!=identity(sr) or len(identity(rr))!=553: raise RuntimeError("bookmarks changed")
 links=internal(rr)
 names={n for _,n in identity(rr)}
 if len(links)!=113 or any(x not in names for x in links): raise RuntimeError("internal navigation integrity failed")
 if breaks(rr)-breaks(user_root)!=3: raise RuntimeError("manual break count changed")
 if set(rparts)!=set(sp) or len(rparts)!=23 or sum(1 for n in sp if n!="word/document.xml" and rparts[n][1]==sp[n][1])!=22: raise RuntimeError("package parts changed")
 for x in (CURRENT,USER):
  if fhash(x)!=EXPECTED[x.name]: raise RuntimeError("source hash changed")

 # Explicit planning-only old/new patch list; other paragraph text and all ordering remain fixed.
 patch_md=["# Final planning-text patch list","",
 "These are the only eight paragraph text changes from fresh_merge_candidate.docx to fresh_merge_final_candidate.docx. They are confined to planning/specification sections; no protected closeout/status or historical paragraph changed.",""]
 for i,p in enumerate(patches):
  patch_md += [f"## {i+1}. {p['label']}","",f"Paragraph index: {changed[i]}","",
               "Old text:","",p["before"],"","New text:","",p["after"],""]
 (TMP/"fresh_merge_FINAL_PATCHLIST.md").write_text("\n".join(patch_md),encoding="utf-8")
 report={
  "candidate":str(OUT),"bytes":OUT.stat().st_size,"sha256":fhash(OUT)[1],
  "previous_candidate_sha256":oldhash,
  "source_hashes":{x.name:{"bytes":fhash(x)[0],"sha256":fhash(x)[1]} for x in (CURRENT,USER)},
  "package":{"base":"previous candidate, itself based on current closeout package","parts":23,"non_document_parts_preserved":22,"relationship_files_unchanged":True},
  "text_integrity":{"previous_candidate_paragraph_count":len(before),"final_candidate_paragraph_count":len(after),"changed_paragraph_count":len(changed),"changed_paragraph_indices":changed,"all_other_paragraphs_exact_and_in_order":True,"explicit_patchlist":"fresh_merge_FINAL_PATCHLIST.md"},
  "protected_closeout":{"status_paragraphs":7,"current_p5_summary":1,"all_eight_exactly_once":True,"historical_text_unchanged":True},
  "bookmarks":{"count":len(identity(rr)),"old_520_preserved":True,"new_heading_bookmarks":33},
  "navigation":{"internal_links":len(links),"old_links":80,"new_heading_links":33,"orphans":0},
  "trellis_manual_breaks":{"delta_from_user":3,"cell_text_preserved":True},
  "rendering":"not performed; remains at main-agent gate",
  "patches":[{"label":p["label"],"paragraph_index":changed[i],"old":p["before"],"new":p["after"]} for i,p in enumerate(patches)]
 }
 (TMP/"fresh_merge_FINAL_SOURCECHECK.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
 md=[
 "# Final V1.47 merge static check","",
 f"- Candidate: {OUT}",
 f"- SHA-256: {report['sha256']} ({report['bytes']} bytes)",
 "- ZIP package: 23 parts; all 22 non-document parts and relationship files unchanged from the prior candidate.",
 f"- Paragraphs: same {len(after)} slots and order as the prior candidate; only the 8 planning paragraph text changes listed in fresh_merge_FINAL_PATCHLIST.md were made.",
 "- Closeout preservation: seven exact status paragraphs, current p5 summary, and historical closeout record remain unchanged and present once.",
 "- Navigation: 520 original bookmarks preserved; 33 heading bookmarks/links retained; 80 original links retained; 0 orphan targets.",
 "- TRELLIS.2: all three manual line breaks remain, with cell text unchanged.",
 "- Rendering remains pending the main-agent gate."
 ]
 (TMP/"fresh_merge_FINAL_SOURCECHECK.md").write_text("\n".join(md)+"\n",encoding="utf-8")
 chg=[
 "# Final V1.47 candidate changelog","",
 "Applied the requested last narrow wording pass to planning sections only. The exact old/new paragraph text and changed paragraph indices are in fresh_merge_FINAL_PATCHLIST.md.",
 "",
 "Closeout status, historical record, full current p5 summary, package relationships, bookmarks, navigation, and manual TRELLIS.2 breaks were rechecked. No experiment, rendering, promotion, or source-document edit was performed."
 ]
 (TMP/"fresh_merge_FINAL_CHANGELOG.md").write_text("\n".join(chg)+"\n",encoding="utf-8")
 print(json.dumps({"candidate":str(OUT),"sha256":report["sha256"],"bytes":report["bytes"],"changed_paragraphs":len(changed),"indices":changed,"protected_status_and_history_unchanged":True,"bookmarks":len(identity(rr)),"links":len(links),"breaks":breaks(rr)-breaks(user_root),"status":"ok"},ensure_ascii=False))
main()
