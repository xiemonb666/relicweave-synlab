from pathlib import Path
import hashlib,json,zipfile,xml.etree.ElementTree as ET
ROOT=Path(r'C:\Users\xiemo\Desktop\ShardForge')
BASE=ROOT/'RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx'
DONOR=ROOT/'RelicWeave_V1.47.docx'
V146=ROOT/'RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx'
OUT=ROOT/'tmp/v147_user_merge_20261007/merge_preflight.json'
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}; W='{'+NS['w']+'}'
def sha(b): return hashlib.sha256(b).hexdigest()
def part_map(path):
    with zipfile.ZipFile(path,'r') as z: return {n:sha(z.read(n)) for n in z.namelist()}
def body_report(path):
    with zipfile.ZipFile(path,'r') as z: root=ET.fromstring(z.read('word/document.xml'))
    body=root.find('w:body',NS); blocks=[]
    for i,e in enumerate(list(body)):
        text=''.join(t.text or '' for t in e.findall('.//w:t',NS))
        style=e.find('w:pPr/w:pStyle',NS) if e.tag==W+'p' else None
        blocks.append({'index':i,'kind':e.tag.split('}')[-1], 'paragraph_style':style.get(W+'val') if style is not None else None,'text':text,'text_sha256':sha(text.encode('utf-8')),'text_chars':len(text),'bookmark_ids':[x.get(W+'id') for x in e.findall('.//w:bookmarkStart',NS)],'bookmark_names':[x.get(W+'name') for x in e.findall('.//w:bookmarkStart',NS)],'hyperlink_count':len(e.findall('.//w:hyperlink',NS))})
    return {'direct_body_child_count':len(blocks),'paragraph_count':sum(b['kind']=='p' for b in blocks),'table_count':sum(b['kind']=='tbl' for b in blocks),'blocks':blocks}
assert BASE.exists() and DONOR.exists() and V146.exists()
base_parts=part_map(BASE); donor_parts=part_map(DONOR); v146_parts=part_map(V146)
with zipfile.ZipFile(BASE,'r') as z: base_rel=z.read('word/_rels/document.xml.rels')
with zipfile.ZipFile(DONOR,'r') as z: donor_rel=z.read('word/_rels/document.xml.rels')
report={'purpose':'Read-only merge preflight; creates no DOCX.','inputs':{},'package_part_changes':{},'relationship_comparison':{'base_sha256':sha(base_rel),'donor_sha256':sha(donor_rel),'byte_equal':base_rel==donor_rel},'body_blocks':{'base':body_report(BASE),'donor':body_report(DONOR),'v146':body_report(V146)}}
for label,path,parts in [('base',BASE,base_parts),('donor',DONOR,donor_parts),('v146',V146,v146_parts)]:
    report['inputs'][label]={'path':str(path),'bytes':path.stat().st_size,'sha256':sha(path.read_bytes()),'part_count':len(parts)}
common=set(base_parts)&set(donor_parts)
report['package_part_changes']={'base_only':sorted(set(base_parts)-set(donor_parts)),'donor_only':sorted(set(donor_parts)-set(base_parts)),'changed_common_parts':sorted(n for n in common if base_parts[n]!=donor_parts[n]),'same_common_part_count':sum(base_parts[n]==donor_parts[n] for n in common)}
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('preflight_json='+str(OUT))
print('preflight_bytes='+str(OUT.stat().st_size)+' sha256='+sha(OUT.read_bytes()))
for label in ['base','donor','v146']:
    d=report['inputs'][label]; b=report['body_blocks'][label]
    print(label+'|'+str(d['bytes'])+'|'+d['sha256']+'|parts='+str(d['part_count'])+'|body='+str(b['direct_body_child_count'])+'|paras='+str(b['paragraph_count'])+'|tables='+str(b['table_count']))
print('rels_byte_equal='+str(report['relationship_comparison']['byte_equal']))
print('changed_common_parts='+','.join(report['package_part_changes']['changed_common_parts']))
