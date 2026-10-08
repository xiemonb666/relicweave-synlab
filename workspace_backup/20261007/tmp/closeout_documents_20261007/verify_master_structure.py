from pathlib import Path
from zipfile import ZipFile
from lxml import etree
import hashlib, json
from copy import deepcopy
root=Path(r'C:\Users\xiemo\Desktop\ShardForge')
src=root/'RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx'
out=root/'RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx'
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'; M='http://schemas.openxmlformats.org/officeDocument/2006/math'
OLD_EAST_ASIA='Droid Sans Fallback'; NEW_EAST_ASIA='Noto Sans SC'
parser=etree.XMLParser(resolve_entities=False,no_network=True,remove_blank_text=False)
with ZipFile(src) as z0, ZipFile(out) as z1:
    assert z0.testzip() is None and z1.testzip() is None
    names0=set(z0.namelist()); names1=set(z1.namelist()); assert names0==names1
    x0=etree.fromstring(z0.read('word/document.xml'),parser); x1=etree.fromstring(z1.read('word/document.xml'),parser)
    b0=x0.find('.//{%s}body'%W); b1=x1.find('.//{%s}body'%W)
    p0=[x for x in b0 if x.tag=='{%s}p'%W]; p1=[x for x in b1 if x.tag=='{%s}p'%W]
    anchors=[407,409,1311,2052,2097,2223,739]
    def outidx(i): return i+sum(1 for a in anchors if a<i)
    texts={1:'V1.47 A12／VesselForge／PG-Frag 收口版 2026年10月7日',5:'V1.47（2026年10月7日）为 A12、VesselForge 与 PG-Frag 的实现收口和证据归位版：维持三项目的独立边界，补入本轮实现状态、诊断证据及资格缺口。PG-Frag 当前仅有 virgin elastic 固定裂面 bridge 与未形成断开的开口历史 toy；12 状态中 step_index=0..7 尚非全点损伤（step_index=7 的 D 范围为 2/3–1），只有 step_index=8..11 全点 D=1，但 bulk 仍承载。moving-front 单次运行因审计字段错配在 wrench、KKT、G 之前停止。VesselForge 证据限于解析族、几何候选、条件证明、理想曲线距离和来源审阅；A12 计数仍以软件 QA 与未校准数据为主。本次未新增模型成绩或完整物理合格包；历史指标、FAIL、STOP、NOT_ESTABLISHED 判决和既有导航继续保留。'}
    def text(p): return ''.join(p.xpath('.//w:t/text()',namespaces={'w':W}))
    def normalize_font(node):
        if node is None: return b''
        cloned=deepcopy(node)
        for rf in cloned.xpath('.//w:rFonts[@w:eastAsia=$font]',namespaces={'w':W},font=NEW_EAST_ASIA):
            rf.set('{%s}eastAsia'%W,OLD_EAST_ASIA)
        return etree.tostring(cloned,method='c14n')
    def c14n(x): return normalize_font(x)
    def normalize_table(node):
        cloned=deepcopy(node)
        for rf in cloned.xpath('.//w:rFonts[@w:eastAsia=$font]',namespaces={'w':W},font=NEW_EAST_ASIA):
            rf.set('{%s}eastAsia'%W,OLD_EAST_ASIA)
        rows=cloned.findall('./w:tr',{'w':W})
        if rows:
            cells=rows[0].findall('./w:tc',{'w':W})
            header=[''.join(c.xpath('.//w:t/text()',namespaces={'w':W})) for c in cells]
            if header==['功能域','责任项目 / 默认接口','详细实施位置']:
                for run in rows[0].xpath('.//w:r[.//w:t]',namespaces={'w':W}):
                    rpr=run.find('./w:rPr',{'w':W})
                    if rpr is None: continue
                    color=rpr.find('./w:color',{'w':W})
                    if color is not None and color.get('{%s}val'%W)=='FFFFFF':
                        rpr.remove(color)
                        if len(rpr)==0: run.remove(rpr)
        return etree.tostring(cloned,method='c14n')
    failures=[]
    for i,p in enumerate(p0):
        q=p1[outidx(i)]
        if i in texts:
            if text(q)!=texts[i]: failures.append(f'text mismatch {i}')
            ppr=p.find('{%s}pPr'%W); qpr=q.find('{%s}pPr'%W)
            if (c14n(ppr) if ppr is not None else b'')!=(c14n(qpr) if qpr is not None else b''): failures.append(f'pPr changed {i}')
            orig_rprs=[c14n(x) for x in p.findall('w:r/w:rPr',{'w':W})]
            new_rprs=[c14n(x) for x in q.findall('w:r/w:rPr',{'w':W})]
            if orig_rprs and not set(orig_rprs).intersection(new_rprs): failures.append(f'rPr not preserved {i}')
        elif c14n(p)!=c14n(q): failures.append(f'untouched paragraph changed {i}')
    old_tables=x0.findall('.//w:body/w:tbl',{'w':W}); new_tables=x1.findall('.//w:body/w:tbl',{'w':W})
    if len(old_tables)!=176 or len(new_tables)!=176: failures.append('table count mismatch')
    for i,(old_table,new_table) in enumerate(zip(old_tables,new_tables),1):
        if normalize_table(old_table)!=normalize_table(new_table): failures.append(f'table content/structure changed {i}')
    inserted=[p for p in p1 if text(p).startswith(('A12.19 当前状态','A12.20 当前实施','G0 当前状态','G31.1 V1.47','VesselForge 当前状态','PG-Frag 当前状态','V1.47（2026-10-07）收口记录'))]
    def count(root,tag): return len(root.findall('.//{%s}%s'%(W,tag)))
    invariants={k:(count(x0,k),count(x1,k)) for k in ['tbl','bookmarkStart','bookmarkEnd','hyperlink']}
    omml=(len(x0.findall('.//{%s}oMath'%M))+len(x0.findall('.//{%s}oMathPara'%M)),len(x1.findall('.//{%s}oMath'%M))+len(x1.findall('.//{%s}oMathPara'%M)))
    changed=[]
    for n in names0:
        if z0.read(n)!=z1.read(n): changed.append(n)
    font_counts={}
    for n in names1:
        if not n.endswith('.xml'): continue
        root=etree.fromstring(z1.read(n),parser)
        remaining=len(root.xpath('.//w:rFonts[@w:eastAsia=$font]',namespaces={'w':W},font=OLD_EAST_ASIA))
        mapped=len(root.xpath('.//w:rFonts[@w:eastAsia=$font]',namespaces={'w':W},font=NEW_EAST_ASIA))
        if remaining: failures.append(f'unmapped East Asian font references in {n}: {remaining}')
        if mapped: font_counts[n]=mapped
    def texts(xml_root): return ''.join(xml_root.xpath('.//w:t/text()',namespaces={'w':W}))
    header=etree.fromstring(z1.read('word/header2.xml'),parser)
    footer=etree.fromstring(z1.read('word/footer2.xml'),parser)
    if 'RelicWeave  V1.47  完整项目方案' not in texts(header): failures.append('active header2 version text mismatch')
    if not texts(footer).startswith('2026年10月7日'): failures.append('active footer2 date mismatch')
    print('source_bytes',src.stat().st_size,'source_sha256',hashlib.sha256(src.read_bytes()).hexdigest())
    print('output_bytes',out.stat().st_size,'output_sha256',hashlib.sha256(out.read_bytes()).hexdigest())
    print('paragraphs',len(p0),len(p1),'inserted',len(inserted),'tables_bookmarks_links',invariants,'OMML',omml)
    print('changed_zip_parts',changed)
    print('eastAsia_font_refs_after_mapping',font_counts)
    print('tables_normalized_equal',len(old_tables),all(normalize_table(a)==normalize_table(b) for a,b in zip(old_tables,new_tables)))
    print('failures',failures)
    if failures or len(p1)!=2350 or len(inserted)!=7 or invariants['tbl'][0]!=invariants['tbl'][1] or invariants['bookmarkStart'][0]!=invariants['bookmarkStart'][1] or invariants['hyperlink'][0]!=invariants['hyperlink'][1] or omml[0]!=omml[1]: raise SystemExit(1)
