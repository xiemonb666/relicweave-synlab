from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree
import hashlib, shutil, tempfile, os

root = Path(r'C:\Users\xiemo\Desktop\ShardForge')
src = root / 'RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx'
out = root / 'RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx'
expected_src = '15978a3956fa33e8048cc54c1dad6878a7e19d9c71b84415dcaf8732f041a3b4'

def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()
if sha(src) != expected_src:
    raise SystemExit(f'Source SHA mismatch: {sha(src)}')
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
DC='http://purl.org/dc/elements/1.1/'
CP='http://schemas.openxmlformats.org/package/2006/metadata/core-properties'
XML='http://www.w3.org/XML/1998/namespace'
ns={'w':W}
OLD_EAST_ASIA='Droid Sans Fallback'
NEW_EAST_ASIA='Noto Sans SC'
parser=etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
with ZipFile(src,'r') as zin:
    entries=[(info,zin.read(info.filename)) for info in zin.infolist()]
xml_data=dict((info.filename,data) for info,data in entries)
doc=etree.fromstring(xml_data['word/document.xml'],parser)
body=doc.find('.//{%s}body'%W)
paras=[child for child in body if child.tag=='{%s}p'%W]
if len(paras)!=2343: raise SystemExit(f'Expected 2343 body paragraphs, got {len(paras)}')

def ptext(p): return ''.join(p.xpath('.//w:t/text()',namespaces=ns))
def replace_p_text(p,text):
    # These front-matter paragraphs contain only ordinary runs; retain pPr and first run formatting.
    if p.xpath('.//w:bookmarkStart|.//w:bookmarkEnd|.//w:hyperlink|.//w:drawing|.//w:object',namespaces=ns):
        raise SystemExit('Refusing to rewrite a paragraph containing a bookmark/link/drawing')
    ppr=p.find('{%s}pPr'%W)
    runs=p.findall('{%s}r'%W)
    rpr=None
    for run in runs:
        candidate=run.find('{%s}rPr'%W)
        if candidate is not None:
            rpr=etree.fromstring(etree.tostring(candidate))
            break
    for ch in list(p):
        if ch is not ppr: p.remove(ch)
    r=etree.SubElement(p,'{%s}r'%W)
    if rpr is not None: r.append(rpr)
    t=etree.SubElement(r,'{%s}t'%W)
    if text[:1].isspace() or text[-1:].isspace(): t.set('{%s}space'%XML,'preserve')
    t.text=text

def new_para(style_source, text):
    p=etree.Element('{%s}p'%W)
    ppr=style_source.find('{%s}pPr'%W)
    if ppr is not None: p.append(etree.fromstring(etree.tostring(ppr)))
    r=etree.SubElement(p,'{%s}r'%W)
    for run in style_source.findall('{%s}r'%W):
        rpr=run.find('{%s}rPr'%W)
        if rpr is not None:
            r.append(etree.fromstring(etree.tostring(rpr)))
            break
    t=etree.SubElement(r,'{%s}t'%W)
    t.text=text
    return p

# Update current front-matter version and current status without altering historic sections.
replace_p_text(paras[1], 'V1.47 A12／VesselForge／PG-Frag 收口版 2026年10月7日')
replace_p_text(paras[5], 'V1.47（2026年10月7日）为 A12、VesselForge 与 PG-Frag 的实现收口和证据归位版：维持三项目的独立边界，补入本轮实现状态、诊断证据及资格缺口。PG-Frag 当前仅有 virgin elastic 固定裂面 bridge 与未形成断开的开口历史 toy；12 状态中 step_index=0..7 尚非全点损伤（step_index=7 的 D 范围为 2/3–1），只有 step_index=8..11 全点 D=1，但 bulk 仍承载。moving-front 单次运行因审计字段错配在 wrench、KKT、G 之前停止。VesselForge 证据限于解析族、几何候选、条件证明、理想曲线距离和来源审阅；A12 计数仍以软件 QA 与未校准数据为主。本次未新增模型成绩或完整物理合格包；历史指标、FAIL、STOP、NOT_ESTABLISHED 判决和既有导航继续保留。')

# Existing paragraph indexes are captured before insertion, so anchor node identity remains stable.
anchors={i:paras[i] for i in [407,409,1311,2052,2097,2223,739]}
notes=[
 (407, 'A12.19 当前状态（2026-10-07）：本节所列 Release 能力仍是目标接口与验收清单，不代表已完成发布。当前 31 个退化轴、155 个档位/检查组合属于软件 QA；其中 9 个轴有测量记录、36 个非零级别，均来自 1 个母体且未校准。16 个纹样族 ID 尚无经历史样式验证的族，12 个材料 ID 尚无经物理校准的材料。端到端检索收益、真实迁移、真实样本需求下降和规模交付均未建立，完整物理合格包为 0。负责人给出的工程进度估计仍为 PG-Frag 25–35%、VesselForge 30–40%、A12 30–40%；这些比例是工程判断，不代表物理准确度或资格覆盖率。', 738),
 (409, 'A12.20 当前实施与资格边界（2026-10-07）：独立仓库、公共合同与可替换后端是架构边界；局部源代码接受或诊断 toy 不等于完整实现或项目资格。PG-Frag 的固定界面与开口控制仍未形成断口分离；moving-front 在合同字段错误处停止。VesselForge 尚无历史器型、生产几何、唇口或实体全局壁厚资格。A12 仍承担观测、权限、关系、训练与诊断编排，不复制两个子项目的内核。', 738),
 (1311, 'G0 当前状态（2026-10-07）：本规则已明确底层内核归属，但当前只是局部实现与来源证据归位，不表示端到端 Asset→Job/Result→Release 链路已完整验收。PG-Frag bridge/opening 是诊断 toy；moving-front 因审计字段错配停止。VesselForge native C4 仅完成 driver/runner 来源审阅，未运行 CAD 或 STEP，也没有实体级 wall/lip 结论。', 738),
 (2052, 'G31.1 V1.47 收口核对（2026-10-07）：本节列出的专项签收项目仍是待完成的资格门。当前 31 轴与 155 项 QA 记录没有替代逐档物理校准；16 个纹样族 ID 没有历史样式验证；原方案所列四个必做碎裂后端、完整三方发布谱系、真实检索对照和规模资源实测仍未整体签收。局部来源审阅、几何证明和诊断运行仅按各自范围记录，不晋级为完整程序或物理资格。', 738),
 (2097, 'VesselForge 当前状态（2026-10-07）：已有 bowl/beaker/jar 三个解析参数族、两个默认 CAD 实例，以及局部二维几何候选与理想曲线距离证据；仍有 0 个经历史参考验证的器型族、0 个经资格确认的生产实体和 0 个校准材料/真实纹样外观。最新 native C4 来源审阅为 SOURCE_ACCEPTED，仅接受源代码合同，CAD/STEP 未运行。', 738),
 (2223, 'PG-Frag 当前状态（2026-10-07）：固定裂面 virgin elastic bridge 与开口历史控制均为诊断 toy，未证明裂纹增长或碎片分离。12 状态轨迹中 step_index=0..7 均非全点损伤；step_index=6 的 D 范围为 0–1，step_index=7 为 2/3–1；仅 step_index=8..11（第 9–12 个状态）全点 D=1。bulk 仍承载，未形成 fragment disconnect。moving-front 唯一获准尝试因 schema 字段错配失败并按单次失败规则停止；没有 wrench、KKT、G 或 primary result。当前证据不构成材料校准、方向/网格偏差收敛、动态多接触或完整三维物理断裂资格。后续算法方向采用连续 MLS 与 support-topology-restricted H/front PU enrichment，停止将 Bool-only 作为主路线；这是基于有限裂片两侧可见支撑集突变和 ghost-jump 反例的工程路线修正，不是已证明的新颖性或物理资格。', 738),
 (739, 'V1.47（2026-10-07）收口记录：本次更新实施状态、证据边界与后续资格门，并在不改历史文字、数值或导航的前提下修复缺失的东亚字体映射、A12.17 第 39 表深色表头字色及活动版本页眉/日期页脚；未新增模型成绩或完整物理合格包。moving-front 单次运行因审计字段错配在 wrench/KKT/G 前停止，未重试；objectivity 与 native C4 均为经独立审阅接受的 SOURCE_ONLY；VesselForge 解析/几何证据和 A12 软件 QA 仍未达到生产或物理资格。V1.46 全文及导航保持原样，历史指标、FAIL、STOP 与 NOT_ESTABLISHED 判决不变。备份交付回执固定于 `relicweave-synlab/docs/handover/20261007/BACKUP_DELIVERY_RECEIPT.json`；该后置 sidecar 将记录最终三仓 HEAD 与文件清单，不写入本记录以避免循环引用。', 738),
]
# Use existing SYNBody style for inserted status paragraphs.
style_source=paras[738]
for idx,text,style_idx in notes:
    anchor=anchors[idx]
    p=new_para(style_source,text)
    body.insert(body.index(anchor)+1,p)

# Replace only the unavailable East Asian font name throughout package XML.
# ASCII/HAnsi fonts, run sizes, emphasis, spacing and paragraph/table geometry stay intact.
font_ref_counts={}
for part, raw in list(xml_data.items()):
    if not part.endswith('.xml'):
        continue
    part_root = doc if part == 'word/document.xml' else etree.fromstring(raw, parser)
    refs=part_root.xpath('.//w:rFonts[@w:eastAsia=$font]',namespaces=ns,font=OLD_EAST_ASIA)
    for ref in refs:
        ref.set('{%s}eastAsia'%W,NEW_EAST_ASIA)
    if refs:
        font_ref_counts[part]=len(refs)
    if part == 'word/header2.xml':
        paragraphs=part_root.findall('.//w:p',ns)
        matching=[p for p in paragraphs if ''.join(p.xpath('.//w:t/text()',namespaces=ns))=='RelicWeave  V1.46  完整项目方案']
        if len(matching)!=1: raise SystemExit(f'Expected one active header2 title, found {len(matching)}')
        nodes=matching[0].findall('.//w:t',ns)
        if len(nodes)!=1: raise SystemExit(f'Unexpected header title text-node layout: {len(nodes)}')
        nodes[0].text='RelicWeave  V1.47  完整项目方案'
        xml_data[part]=etree.tostring(part_root,xml_declaration=True,encoding='UTF-8',standalone=True)
    elif part == 'word/footer2.xml':
        paragraphs=part_root.findall('.//w:p',ns)
        matching=[p for p in paragraphs if ''.join(p.xpath('.//w:t/text()',namespaces=ns)).startswith('2026年10月5日')]
        if len(matching)!=1: raise SystemExit(f'Expected one active footer2 date, found {len(matching)}')
        nodes=matching[0].findall('.//w:t',ns)
        if not nodes or not (nodes[0].text or '').startswith('2026年10月5日'):
            raise SystemExit('Unexpected footer date text-node layout')
        nodes[0].text=nodes[0].text.replace('2026年10月5日','2026年10月7日',1)
        xml_data[part]=etree.tostring(part_root,xml_declaration=True,encoding='UTF-8',standalone=True)
    elif part != 'word/document.xml' and refs:
        xml_data[part]=etree.tostring(part_root,xml_declaration=True,encoding='UTF-8',standalone=True)

# A static scan of all 176 first-row headers found one dark-filled header with
# inherited dark text: A12.17's three-cell table header. Add explicit white
# text only to those existing text runs; preserve all row/cell geometry.
tables=body.findall('.//{%s}tbl'%W)
if len(tables)!=176: raise SystemExit(f'Expected 176 tables before contrast fix, got {len(tables)}')
contrast_table=tables[38]
first_row=contrast_table.find('{%s}tr'%W)
expected_header=['功能域','责任项目 / 默认接口','详细实施位置']
actual_header=[''.join(c.xpath('.//w:t/text()',namespaces=ns)) for c in first_row.findall('{%s}tc'%W)]
if actual_header!=expected_header: raise SystemExit(f'Unexpected table-39 header: {actual_header!r}')
for cell in first_row.findall('{%s}tc'%W):
    for run in cell.xpath('.//w:r[.//w:t]',namespaces=ns):
        rpr=run.find('{%s}rPr'%W)
        if rpr is None:
            rpr=etree.Element('{%s}rPr'%W)
            run.insert(0,rpr)
        color=rpr.find('{%s}color'%W)
        if color is None:
            color=etree.SubElement(rpr,'{%s}color'%W)
        color.set('{%s}val'%W,'FFFFFF')
        for attr in ('themeColor','themeTint','themeShade'):
            q='{%s}%s'%(W,attr)
            if q in color.attrib: del color.attrib[q]

# Update core title/subject metadata while preserving authors, timestamps and all other package parts.
core=etree.fromstring(xml_data['docProps/core.xml'],parser)
title=core.find('{%s}title'%DC)
if title is None: title=etree.SubElement(core,'{%s}title'%DC)
title.text='RelicWeave V1.47 A12 VesselForge PG-Frag Closeout'
subject=core.find('{%s}subject'%DC)
if subject is None: subject=etree.SubElement(core,'{%s}subject'%DC)
subject.text='2026-10-07 implementation status, evidence boundaries and qualification gates'
xml_data['word/document.xml']=etree.tostring(doc,xml_declaration=True,encoding='UTF-8',standalone=True)
xml_data['docProps/core.xml']=etree.tostring(core,xml_declaration=True,encoding='UTF-8',standalone=True)
# Write to a temp then atomically replace final artifact.
tmp=out.with_suffix('.docx.tmp')
with ZipFile(src,'r') as zin, ZipFile(tmp,'w',ZIP_DEFLATED) as zout:
    for info in zin.infolist():
        zout.writestr(info,xml_data[info.filename])
os.replace(tmp,out)
print(f'created={out}')
print(f'bytes={out.stat().st_size}')
print(f'sha256={sha(out)}')
print(f'original_sha256={sha(src)}')
print(f'eastAsia_font_refs_mapped={font_ref_counts}')
print(f'explicit_white_header_cells={len(expected_header)}')

