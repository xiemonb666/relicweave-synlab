#!/usr/bin/env python3
import copy, hashlib, json, re, zipfile
from collections import Counter
from pathlib import Path
from lxml import etree

ROOT=Path(r"C:\Users\xiemo\Desktop\ShardForge")
TMP=ROOT/"tmp"/"v147_user_merge_20261007"
CURRENT=ROOT/"RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx"
USER=ROOT/"RelicWeave_V1.47.docx"
OUT=TMP/"fresh_merge_candidate.docx"
DIFF=TMP/"diff_summary.json"
DOC="word/document.xml"
WURI="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS={"w":WURI}
W="{"+WURI+"}"
XMLSPACE="{http://www.w3.org/XML/1998/namespace}space"
EXPECTED={
 CURRENT.name:(734565,"9af0efe877115200dd99bbcf8f24f3124e2932245d71795fc00252d08e278436"),
 USER.name:(779513,"41f1254e40a2ecabdcfa1c6583af2fce0ae1b0ab980d5f9179bbaf687b7be64b"),
}
PARSER=etree.XMLParser(resolve_entities=False,no_network=True,remove_blank_text=False)

def sha(b): return hashlib.sha256(b).hexdigest()
def fhash(p):
 b=p.read_bytes(); return len(b),sha(b)
def read_doc(p):
 with zipfile.ZipFile(p) as z:
  parts={i.filename:(i,z.read(i.filename)) for i in z.infolist()}
 return etree.fromstring(parts[DOC][1],PARSER),parts
def body(root):
 x=root.xpath(".//w:body",namespaces=NS)
 if len(x)!=1: raise RuntimeError(f"body count {len(x)}")
 return x[0]
def ptext(p): return "".join(t.text or "" for t in p.xpath(".//w:t",namespaces=NS))
def paras(b): return b.xpath(".//w:p",namespaces=NS)
def exact_para(b,s,label):
 h=[p for p in paras(b) if ptext(p)==s]
 if len(h)!=1: raise RuntimeError(f"{label}: expected one exact paragraph, got {len(h)}")
 return h[0]
def contains_para(b,s,label):
 h=[p for p in paras(b) if s in ptext(p)]
 if len(h)!=1: raise RuntimeError(f"{label}: expected one anchor, got {len(h)}: {s}")
 return h[0]
def insert_after(anchor,node):
 par=anchor.getparent(); par.insert(par.index(anchor)+1,node)
def make_para(text):
 p=etree.Element(W+"p")
 pp=etree.SubElement(p,W+"pPr")
 sty=etree.SubElement(pp,W+"pStyle"); sty.set(W+"val","Normal")
 sp=etree.SubElement(pp,W+"spacing"); sp.set(W+"before","60"); sp.set(W+"after","60")
 r=etree.SubElement(p,W+"r"); rp=etree.SubElement(r,W+"rPr")
 rf=etree.SubElement(rp,W+"rFonts")
 for k in ("ascii","hAnsi","eastAsia","cs"): rf.set(W+k,"Noto Sans SC")
 t=etree.SubElement(r,W+"t"); t.set(XMLSPACE,"preserve"); t.text=text
 return p
def add_clarification(b,anchor,text,label):
 a=contains_para(b,anchor,label+" anchor")
 insert_after(a,make_para(text))
 return {"label":label,"anchor":anchor,"text":text}
def bms(root):
 return {(x.get(W+"id"),x.get(W+"name")) for x in root.xpath(".//w:bookmarkStart",namespaces=NS)}
def ids(root):
 vals=[]
 for x in root.xpath(".//w:bookmarkStart",namespaces=NS):
  try: vals.append(int(x.get(W+"id")))
  except Exception: raise RuntimeError("invalid bookmark id")
 return vals
def links(root): return [x.get(W+"anchor") for x in root.xpath(".//w:hyperlink[@w:anchor]",namespaces=NS)]
def add_bookmark(p,bid,name):
 if p.xpath(".//w:bookmarkStart|.//w:bookmarkEnd",namespaces=NS): raise RuntimeError("heading already bookmarked")
 s=etree.Element(W+"bookmarkStart"); s.set(W+"id",str(bid)); s.set(W+"name",name)
 e=etree.Element(W+"bookmarkEnd"); e.set(W+"id",str(bid))
 p.insert(1 if len(p) and p[0].tag==W+"pPr" else 0,s); p.append(e)
def add_nav(b,after,targets):
 p=etree.Element(W+"p"); pp=etree.SubElement(p,W+"pPr")
 sty=etree.SubElement(pp,W+"pStyle"); sty.set(W+"val","Normal")
 ind=etree.SubElement(pp,W+"ind"); ind.set(W+"left","120"); ind.set(W+"right","120")
 sp=etree.SubElement(pp,W+"spacing"); sp.set(W+"before","80"); sp.set(W+"after","80")
 r=etree.SubElement(p,W+"r"); t=etree.SubElement(r,W+"t"); t.set(XMLSPACE,"preserve"); t.text="V1.47新增内容导航："
 for label,name in targets:
  r=etree.SubElement(p,W+"r"); t=etree.SubElement(r,W+"t"); t.set(XMLSPACE,"preserve"); t.text=" · "
  h=etree.SubElement(p,W+"hyperlink"); h.set(W+"anchor",name); h.set(W+"history","1")
  rr=etree.SubElement(h,W+"r"); rp=etree.SubElement(rr,W+"rPr")
  rs=etree.SubElement(rp,W+"rStyle"); rs.set(W+"val","Hyperlink")
  tt=etree.SubElement(rr,W+"t"); tt.text=label
 insert_after(after,p)
def patch_fonts(root):
 n=0
 for rf in root.xpath(".//w:rFonts[@w:eastAsia='Droid Sans Fallback']",namespaces=NS):
  rf.set(W+"eastAsia","Noto Sans SC"); n+=1
 return n
def rowtext(row): return "".join(t.text or "" for t in row.xpath(".//w:t",namespaces=NS))
def is_dark(fill):
 if not fill or fill.lower() in ("auto","none"): return False
 f=fill.lstrip("#")
 if len(f)==3: f="".join(c*2 for c in f)
 if not re.fullmatch("[0-9a-fA-F]{6}",f): return False
 r,g,b=(int(f[i:i+2],16) for i in (0,2,4))
 return .2126*r+.7152*g+.0722*b < 145
def patch_dark_headers(root):
 out=[]
 for ti,tbl in enumerate(root.xpath(".//w:body//w:tbl",namespaces=NS),1):
  rows=tbl.xpath("./w:tr",namespaces=NS)
  if not rows: continue
  row=rows[0]; cells=row.xpath("./w:tc",namespaces=NS); darkcells=[]
  for ci,c in enumerate(cells):
   fills=[x.get(W+"fill") for x in c.xpath("./w:tcPr/w:shd",namespaces=NS)]
   fs=[f for f in fills if is_dark(f)]
   if fs: darkcells.append((ci,c,fs[0]))
  if len(darkcells)<max(1,(len(cells)+1)//2): continue
  changed=0
  for ci,c,fill in darkcells:
   for run in c.xpath(".//w:r[.//w:t]",namespaces=NS):
    rp=run.find(W+"rPr")
    if rp is None: rp=etree.Element(W+"rPr"); run.insert(0,rp)
    color=rp.find(W+"color")
    if color is None: color=etree.SubElement(rp,W+"color")
    if color.get(W+"val","").upper()!="FFFFFF":
     color.attrib.clear(); color.set(W+"val","FFFFFF"); changed+=1
  if changed: out.append({"table":ti,"fill_cells":[x[0]+1 for x in darkcells],"fills":[x[2] for x in darkcells],"runs_changed":changed,"header":rowtext(row)[:140]})
 return out
def add_break(p,boundary):
 full=ptext(p)
 if full.count(boundary)!=1: raise RuntimeError(f"break boundary count {full.count(boundary)}: {boundary}")
 pos=full.index(boundary)+len(boundary); cum=0
 for t in p.xpath(".//w:t",namespaces=NS):
  s=t.text or ""; end=cum+len(s)
  if pos<=end:
   par=t.getparent(); ix=par.index(t); br=etree.Element(W+"br")
   if pos==end: par.insert(ix+1,br)
   else:
    aft=copy.deepcopy(t); cut=pos-cum; t.text=s[:cut]; aft.text=s[cut:]
    par.insert(ix+1,br); par.insert(ix+2,aft)
   return
  cum=end
 raise RuntimeError("could not place w:br")
def xmlbytes(root): return etree.tostring(root,xml_declaration=True,encoding="UTF-8",standalone=True)

def main():
 TMP.mkdir(parents=True,exist_ok=True)
 for p in (CURRENT,USER):
  if fhash(p)!=EXPECTED[p.name]: raise RuntimeError(f"pinned input mismatch: {p.name} {fhash(p)}")
 diff=json.loads(DIFF.read_text(encoding="utf-8-sig"))
 cr,cp=read_doc(CURRENT); ur,up=read_doc(USER); cb,ub=body(cr),body(ur)
 source_user=[ptext(p) for p in paras(ub)]
 if len(cp)!=23 or len(up)!=23 or set(cp)!=set(up): raise RuntimeError("package part mismatch")
 if cp["word/_rels/document.xml.rels"][1]!=up["word/_rels/document.xml.rels"][1]: raise RuntimeError("document rels mismatch")
 if cp["_rels/.rels"][1]!=up["_rels/.rels"][1]: raise RuntimeError("package rels mismatch")

 statuses=diff["exact_closeout_status_paragraphs_missing_from_user_doc"]
 if len(statuses)!=7: raise RuntimeError(f"status count {len(statuses)}")
 current_paras=paras(cb)
 status_anchors=[
  ("研究输出采用同一批母体的配对质量曲线","A12.19 current status"),
  ("VesselForge和PG-Frag必须各自拥有独立仓库","A12.20 qualification status"),
  ("V1.46将VesselForge与PG-Frag正式作为两个独立基础设施子项目接入A12","historical closeout record"),
  ("禁止在relicweave-synlab中复制VesselForge的CAD","G0 current status"),
  ("专项签收需提交：16纹样族的recipe","G31.1 current status"),
  ("来源基线：VesselForge × PG-Frag 技术路线总纲 v1.1（2026-10-03）","VesselForge current status"),
  ("来源基线：VesselForge × PG-Frag 技术路线总纲 v1.1（2026-10-03）","PG-Frag current status"),
 ]
 inserted_status=[]
 for i,(rec,(needle,label)) in enumerate(zip(statuses,status_anchors)):
  exact=rec["text"]; src=[p for p in current_paras if ptext(p)==exact]
  if len(src)!=1: raise RuntimeError(f"{label} source match {len(src)}")
  hits=[p for p in paras(ub) if needle in ptext(p)]
  if label=="VesselForge current status":
   hits=[p for p in hits if ptext(p).startswith(needle)]
   if len(hits)==2: hits=[hits[0]]
  elif label=="PG-Frag current status":
   hits=[p for p in hits if ptext(p).startswith(needle)]
   if len(hits)==2: hits=[hits[-1]]
  if len(hits)!=1: raise RuntimeError(f"{label} target match {len(hits)}")
  clone=copy.deepcopy(src[0])
  if ptext(clone)!=exact: raise RuntimeError(f"{label} clone text mismatch")
  insert_after(hits[0],clone)
  inserted_status.append({"label":label,"source_text_sha256":sha(exact.encode()),"anchor":needle})

 curps=paras(cb); intro_text=diff["key_exact_new_texts"]["new_current_intro"]["text"]
 intro=exact_para(ub,intro_text,"user p5 intro")
 if len(curps)<=5: raise RuntimeError("current p5 absent")
 summary=copy.deepcopy(curps[5]); summary_text=ptext(summary)
 insert_after(intro,summary)

 patches=[
 ("V1.47采用“现行执行正文覆盖过时规划、历史证据只增不改”","本轮范围仅为V1.47文档收口、研究候选转移与可行性审阅，不启动新开发、运行或新增数值结论。新列为P0的研究候选只表示后续研究优先级，不覆盖当前PG-Frag、VesselForge与A12的物理实现、资格和资源优先级，也不自动重开已停止工作；重新进入开发须由用户明确发起，并另行冻结范围与证据门槛。","scope and priority"),
 ("对query q定义V_G(q)","分母边界补充：只有|V_G(q)|>0时才按常规闭合集合定义报告成员召回；此时若预测集合为空，Recall=0、Precision=NA、F1=0。若|V_G(q)|=0，应单独报告member-absent判定、false-inclusion数量/率及abstention；真值与预测都为空只记为correct-empty，不能把Precision、Recall或F1伪记为1。开世界样本及未通过完整工作流资格的样本分开计数，不并入Level 3闭合集合主分母。汇总按器物等权宏平均，区间按独立器物聚类估计；query加权均值仅作补充。","closed-gallery metrics"),
 ("R1是“同器物且无直接历史断裂接触”","此处member_set闭合仅指冻结图库G中、排除query自身后，同一器物的已入库成员集合已闭合；不要求把所有物理上遗失或未采集的碎片补回。未入库碎片去向作为解释与审计元数据记录。成员集合闭合和R2直接邻接图闭合分别审核，R2漏边不改变member set，也不把缺失R2自动标成R1。","membership versus R2 closure"),
 ("最终 A—C 是 R1、R2 还是 UNKNOWN","历史断裂/邻接真值只可作为离线训练标签、损失、按母体分组的split审计及评测标签；推理时只可使用合法ObsPack。GT标签用于离线监督是允许的，但GT pose、motherID、true relation graph与TruthPack不能进入在线特征、memory或candidate generator。provenance ID用于审计和去相关，不作为身份特征；姿态字段记录predicted_pose_hat及其不确定性。UNKNOWN表示认识论上的证据不足/拒判，不是第四种物理关系；应保持P_R2≤P_same，缺少R2证据不能推出R1。","offline truth and relation ontology"),
 ("R2 更依赖断口局部互补、接触几何","硬负例应覆盖同纹样、同模具或同批次但属于不同器物的样本，并把边界含混的候选组成ambiguity group，证据不足时允许UNKNOWN/拒判。材质、风格或形状先验只提供兼容性，不单独构成同一器物身份的充分证明。","hard negatives and abstention"),
 ("这条创新线最大的风险不是“能不能利用正确 R2”","belief revision只更新模型当前posterior或候选状态，不改写历史GT事实。只有GT复核或新碎裂事件/叶片谱系的新label_version可以改变事实，并保留旧版本与来源。校准posterior必须使用冻结DEV校准器并报告coverage-risk；posterior本身不等同置信区间。模型间一致或跨轮稳定属于相关输出，单独稳定不构成新增独立证据，也不能触发不可撤销写入。","revision and calibration"),
 ("训练不得从一开始就把完整 UA-IFRMN 端到端同时打开","Oracle-R2是特权离线诊断条件，用于检查已知关系上下文是否有信息；它不是严格的信息论上界，也不是可部署性能。比较时尽量匹配候选集合、上下文数量/质量与预算，并加入shuffle-neighbor对照及可行时的等量GT-R1对照。真实合格数据与闭合GT足以先做静态/上下文信息测试；物理pack只作为物理合成或物理预训练主张的门槛。","Oracle diagnostic and feasibility"),
 ("A6.21 必做实验矩阵：先证明“邻片上下文有信息”","B1 Scalar Feedback必须保留为基线；只有在匹配的特权上下文已显示正向信息时，B2 Latent Feedback才可继续作为机制测试，不能要求B1先取得正收益。若Oracle/对照因标注容量或协议不足无法判读，应记录为资源STOP或未决，不外推为“关系上下文普遍没有信息”。","B1/B2 decision gate"),
 ("EXP12 R2→R1关系上下文与错误传播","腐化率是预注册的压力测试配方，不是现实错误率估计。按错误类型和分母分别报告漏掉真R2、误报R2、typed relation互换、错误成员纳入/遗漏及来源相关错误；另用留出预测误差率和回放来源相关性描述真实误差。加入空R2 seed下回退静态基线、成员误纳/漏纳注入、coverage-risk与端到端成本。0/5/10/20/30%仅表示压力配方，不得表述为已知现实发生率。","EXP12 corruption protocol"),
 ("每个release必须同时提供传统算法合法输入","退化评测分开两条轨道：固定观测的合成扰动/历史GT回放用于配对诊断；真实磨损、材料流失、新崩边、二次断裂、事件变化与fragment leaf lineage作为新的物理事件/版本记录。后者更新current_fit_valid、evidence_visible和current-leaf relations，并保留历史R2事实及其版本，不以当前状态覆盖历史邻接真值。","historical truth and physical events"),
 ("Step 0 — 编码而不压扁：对 query 和候选库生成 Fragment Token Bank","Fragment Token Bank应采用磁盘/CPU缓存并按query初检后的Top-K候选按需读取局部token；不把全gallery的局部token bank常驻GPU，也不构造全库N×N关系张量。","bounded token bank"),
 ("单一 P(R2) 只表达最终置信度","推理资源须预先限定K、局部token数L、迭代数、假设数与重读半径，并报告单query P95时延、峰值VRAM/RAM和端到端FLOPs。RTX 5090规格不能代替目标负载实测；当前吞吐量仍未测，故资源可行性保持未确立。","bounded inference cost"),
 ("来源分为两类：会议／期刊正式论文用于建立强对照","版本/venue校正：SARe采用arXiv v2标题“Structure-Aware Generative 3D Fragment Reassembly”，其方法描述对应query-aligned局部几何、task-native结构监督与point flow、几何验证及重采样；GARF若按ICCV 2025 proceedings引用，应写two-session flow matching，即one-step initialization加multi-step refinement，不沿用更早预印本把one-step preassembly当作完整推理过程。TORA标注为ECCV 2026 accepted，MV-RoMa为CVPR 2026 accepted，Coconut以COLM 2025 accepted为当前venue（ICLR workshop仅作历史补充）。这些来源只提供方法灵感，不证明UA-IFRMN、RelicWeave的性能、SOTA或新颖性。来源入口：SARe https://arxiv.org/abs/2603.21611v2；GARF https://openaccess.thecvf.com/content/ICCV2025/papers/Li_GARF_Learning_Generalizable_3D_Reassembly_for_Real-World_Fractures_ICCV_2025_paper.pdf；TORA https://arxiv.org/abs/2604.04050；MV-RoMa https://arxiv.org/abs/2603.27542；Coconut https://arxiv.org/abs/2412.06769v4。","primary-source corrections"),
 ("用户接受/驳回某成员后生成新的revision","结果页还应能请求补采/重拍、标记证据不足、显示预算耗尽并STOP；每次revision均保留理由与来源。Level 3未通过独立资格门前，所有成员输出保持研究模式候选，不得显示为已完成修复或已认证的器物成员集合。","D6.5 action and claim boundary"),
 ]
 patchlog=[add_clarification(ub,a,t,l) for a,t,l in patches]

 rows=[r for r in ub.xpath(".//w:tr",namespaces=NS) if "TRELLIS.2" in rowtext(r)]
 if len(rows)!=1: raise RuntimeError(f"TRELLIS.2 row matches {len(rows)}")
 row=rows[0]; old_row=rowtext(row)
 av=[p for p in row.xpath(".//w:p",namespaces=NS) if "能产生复杂拓扑和高多样性的长尾资产，并包含 PBR 表达。" in ptext(p)]
 rs=[p for p in row.xpath(".//w:p",namespaces=NS) if "结果不保证物理可用、尺度/壁厚/拓扑/封闭性需后处理，算力较高。" in ptext(p)]
 if len(av)!=1 or len(rs)!=1: raise RuntimeError(f"TRELLIS.2 text matches advantages={len(av)} restrictions={len(rs)}")
 add_break(av[0],"能产生复杂拓扑"); add_break(av[0],"和高多样性的长尾资产，"); add_break(rs[0],"结果不保证物理可用、")
 if rowtext(row)!=old_row: raise RuntimeError("TRELLIS.2 text changed")

 fonts=patch_fonts(ur)
 heads=diff["new_heading_ids_and_titles"]
 if len(heads)!=33: raise RuntimeError(f"new heading count {len(heads)}")
 old_ids=ids(ur)
 if len(old_ids)!=len(set(old_ids)): raise RuntimeError("duplicate old bookmark ids")
 next_id=max(old_ids,default=-1); oldnames={n for _,n in bms(ur)}; newnames=set(); targets=[]
 for i,rec in enumerate(heads,1):
  title=rec["heading"]; h=[p for p in paras(ub) if ptext(p)==title]
  if len(h)!=1: raise RuntimeError(f"heading count {len(h)}: {title}")
  label=title.split(None,1)[0]; safe=re.sub("[^A-Za-z0-9_]","_",label); name="RW147_"+safe
  if name in oldnames or name in newnames: raise RuntimeError("bookmark name collision "+name)
  add_bookmark(h[0],next_id+i,name); newnames.add(name); targets.append((label,name))
 nav_after=exact_para(ub,summary_text,"current p5 summary after insertion")
 add_nav(ub,nav_after,targets)
 darkpatch=patch_dark_headers(ur)

 outtext=[ptext(p) for p in paras(ub)]
 cursor=0
 for s in outtext:
  if cursor<len(source_user) and s==source_user[cursor]: cursor+=1
 if cursor!=len(source_user): raise RuntimeError(f"user text sequence retained {cursor}/{len(source_user)}")
 curbm=bms(cr); userbm=bms(read_doc(USER)[0]); outbm=bms(ur)
 if len(curbm)!=520 or len(userbm)!=520 or curbm!=userbm: raise RuntimeError("source bookmark identity mismatch")
 if len(outbm)!=553 or len(outbm-userbm)!=33 or not userbm.issubset(outbm): raise RuntimeError("bookmark preservation/addition mismatch")
 names=[n for _,n in outbm]
 if len(names)!=len(set(names)): raise RuntimeError("duplicate bookmark names")
 oldlinks=links(read_doc(USER)[0]); newlinks=links(ur)
 if len(newlinks)!=len(oldlinks)+33: raise RuntimeError("internal link count mismatch")
 if any(x not in set(names) for x in newlinks): raise RuntimeError("orphan internal hyperlink")
 user_br=len(read_doc(USER)[0].xpath(".//w:br",namespaces=NS))
 out_br=len(ur.xpath(".//w:br",namespaces=NS))
 if out_br-user_br!=3: raise RuntimeError(f"manual w:br count delta {out_br-user_br}")

 newxml=xmlbytes(ur)
 with zipfile.ZipFile(OUT,"w") as z:
  for name,(info,data) in cp.items(): z.writestr(info,newxml if name==DOC else data)
 rr,rparts=read_doc(OUT); rb=body(rr)
 readtext=[ptext(p) for p in paras(rb)]
 if readtext!=outtext: raise RuntimeError("readback text mismatch")
 statcounts=[sum(ptext(p)==s["text"] for p in paras(rb)) for s in statuses]
 if statcounts!=[1]*7: raise RuntimeError(f"protected status counts {statcounts}")
 if sum(ptext(p)==summary_text for p in paras(rb))!=1: raise RuntimeError("p5 summary count")
 unchanged=sum(1 for n in cp if n!=DOC and rparts[n][1]==cp[n][1])
 if set(rparts)!=set(cp) or len(rparts)!=23 or unchanged!=22: raise RuntimeError("package-base preservation failure")
 if rparts["word/_rels/document.xml.rels"][1]!=cp["word/_rels/document.xml.rels"][1] or rparts["_rels/.rels"][1]!=cp["_rels/.rels"][1]: raise RuntimeError("relationship bytes changed")
 if len(rr.xpath(".//w:br",namespaces=NS))-user_br!=3: raise RuntimeError("readback manual line break count")

 report={
  "candidate":str(OUT),"candidate_bytes":OUT.stat().st_size,"candidate_sha256":fhash(OUT)[1],
  "input_hashes":{p.name:{"bytes":fhash(p)[0],"sha256":fhash(p)[1]} for p in (CURRENT,USER)},
  "package":{"base":CURRENT.name,"parts":len(rparts),"unchanged_current_non_document_parts":unchanged,"document_relationships_unchanged":True,"package_relationships_unchanged":True},
  "paragraphs":{"user_source":len(source_user),"candidate":len(readtext),"all_user_paragraphs_preserved_in_order":True},
  "protected_current_state":{"seven_status_paragraphs_exact_once":statcounts,"current_p5_summary_exact_once":True,"protected_count":8},
  "bookmarks":{"source_current":len(curbm),"source_user":len(userbm),"candidate":len(outbm),"new_heading_bookmarks":len(outbm-userbm),"old_id_name_identities_preserved":True,"unique_names":True},
  "navigation":{"old_internal_links":len(oldlinks),"new_heading_links":33,"candidate_internal_links":len(newlinks),"orphan_links":0},
  "manual_breaks":{"new_w_br":3,"trellis_row_text_unchanged":True},
  "font":{"eastAsia_Droid_Sans_Fallback_replaced":fonts,"target":"Noto Sans SC"},
  "dark_header_text_patches":darkpatch,"applied_clarifications":patchlog,"protected_status_anchors":inserted_status,
  "layout_review":"pending main-agent promotion/render gate"
 }
 (TMP/"fresh_merge_SOURCECHECK.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
 md=[
 "# V1.47 merged candidate static check","",
 f"- Candidate: {OUT}",
 f"- SHA-256: {report['candidate_sha256']} ({report['candidate_bytes']} bytes)",
 f"- Package: current closeout base, 23 parts; all 22 non-document parts and both relationship files preserved byte-for-byte.",
 f"- Paragraphs: all {len(source_user)} user paragraphs retained in order; candidate has {len(readtext)}.",
 "- Protected closeout: all seven exact status paragraphs plus the complete current p5 summary are present once.",
 f"- Bookmarks: preserved all {len(userbm)} existing identities and added 33 unique bookmarks for new headings.",
 f"- Navigation: preserved {len(oldlinks)} existing internal links and added 33; no orphan targets.",
 "- TRELLIS.2: exactly three manual line breaks; concatenated cell text is unchanged.",
 f"- CJK font: replaced {fonts} East Asian Droid Sans Fallback mappings with Noto Sans SC.",
 f"- Approved narrow clarifications recorded: {len(patchlog)}.",
 "- Layout rendering/visual inspection remains pending the main-agent gate."
 ]
 (TMP/"fresh_merge_SOURCECHECK.md").write_text("\n".join(md)+"\n",encoding="utf-8")
 changelog=[
 "# Fresh V1.47 merge changelog","",
 "Built a separate candidate from the current closeout ZIP package. Replaced only word/document.xml with the user V1.47 body, then restored the eight protected current-state paragraphs and applied the approved narrow wording clarifications.",
 "",
 "Preserved all 23 package parts, current ancillary parts, styles/header/footer, relationship files, and existing bookmark identities/internal links. Added compact internal links and bookmarks for 33 new headings, three TRELLIS.2 cell line breaks, CJK font correction, and contrast fixes for dark header rows.",
 "",
 "No source DOCX was edited. No experiments or new performance numbers were run. Visual rendering awaits the main-agent gate.",
 "",
 "See fresh_merge_SOURCECHECK.json for hashes, counts, anchors, and patch text."
 ]
 (TMP/"fresh_merge_CHANGELOG.md").write_text("\n".join(changelog)+"\n",encoding="utf-8")
 print(json.dumps({"candidate":str(OUT),"sha256":report["candidate_sha256"],"bytes":report["candidate_bytes"],"protected":report["protected_current_state"],"bookmarks":report["bookmarks"],"navigation":report["navigation"],"manual_breaks":report["manual_breaks"],"clarifications":len(patchlog),"status":"ok"},ensure_ascii=False))

if __name__=="__main__": main()
