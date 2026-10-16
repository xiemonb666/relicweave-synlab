from zipfile import ZipFile
from lxml import etree
from pathlib import Path
p=Path('RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx')
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'; NS={'w':W}
with ZipFile(p) as z: root=etree.fromstring(z.read('word/document.xml'))
body=root.find('.//{%s}body'%W)
def tx(p): return ''.join(p.xpath('.//w:t/text()',namespaces=NS))
def props(p):
 pp=p.find('{%s}pPr'%W); out={}
 if pp is not None:
  for tag in ['pStyle','jc','spacing','ind','snapToGrid','contextualSpacing','keepNext','keepLines','autoSpaceDE','autoSpaceDN','widowControl']:
   x=pp.find('{%s}%s'%(W,tag))
   if x is not None: out[tag]={etree.QName(k).localname:v for k,v in x.attrib.items()}
 return out
for bi,block in enumerate(body):
 typ=etree.QName(block).localname
 ps=block.findall('.//{%s}p'%W) if typ=='tbl' else ([block] if typ=='p' else [])
 for pi,p in enumerate(ps):
  t=tx(p)
  if any(k in t for k in ['最新','当前结论','下一动作','当前结','结论']):
   print('\nBLOCK',bi,typ,'P_IN_BLOCK',pi,'TEXT',repr(t))
   print('PPR',props(p))
   if typ=='tbl':
    print('tblgrid',[c.get('{%s}w'%W) for c in block.findall('w:tblGrid/w:gridCol',NS)])
   for ri,r in enumerate(p.findall('w:r',NS)):
    rt=''.join(r.xpath('.//w:t/text()',namespaces=NS))
    rpr=r.find('w:rPr',NS); fmt={}
    if rpr is not None:
     for el in rpr:
      fmt[etree.QName(el).localname]={etree.QName(k).localname:v for k,v in el.attrib.items()}
    print(' RUN',ri,repr(rt),fmt)
