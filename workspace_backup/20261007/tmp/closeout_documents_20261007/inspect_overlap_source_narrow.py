from zipfile import ZipFile
from lxml import etree
p='RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx'
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'; NS={'w':W}
with ZipFile(p) as z: root=etree.fromstring(z.read('word/document.xml'))
body=root.find('.//{%s}body'%W)
def tx(x): return ''.join(x.xpath('.//w:t/text()',namespaces=NS))
def pp(x):
 ppr=x.find('{%s}pPr'%W); a={}
 if ppr is not None:
  for tag in ['pStyle','spacing','ind','jc','snapToGrid','contextualSpacing','keepNext','keepLines']:
   q=ppr.find('{%s}%s'%(W,tag))
   if q is not None: a[tag]={etree.QName(k).localname:v for k,v in q.attrib.items()}
 return a
for i,x in enumerate(body):
 if etree.QName(x).localname=='p':
  t=tx(x)
  if '最新' in t and ('为准' in t or '最新状态' in t or '最新结果' in t):
   print('\nTOP P',i,repr(t)); print('PPR',pp(x))
   for ri,r in enumerate(x.findall('w:r',NS)):
    rt=''.join(r.xpath('.//w:t/text()',namespaces=NS)); rpr=r.find('w:rPr',NS); f={}
    if rpr is not None:
     for e in rpr: f[etree.QName(e).localname]={etree.QName(k).localname:v for k,v in e.attrib.items()}
    print('R',ri,repr(rt),f)
 if etree.QName(x).localname=='tbl' and ('当前结论' in tx(x) or '当前准确结论' in tx(x)):
  print('\nTABLE',i,'grid',[c.get('{%s}w'%W) for c in x.findall('w:tblGrid/w:gridCol',NS)])
  for ri,row in enumerate(x.findall('w:tr',NS)):
   cs=row.findall('w:tc',NS)
   print(' ROW',ri,'cells=',len(cs))
   for ci,cell in enumerate(cs):
    print('  CELL',ci,'w',cell.find('w:tcPr/w:tcW',NS).attrib if cell.find('w:tcPr/w:tcW',NS) is not None else None,'text=',repr(tx(cell)))
    for para in cell.findall('w:p',NS):
     pt=tx(para)
     if '当前结论' in pt or '当前准确结论' in pt:
      print('   HEADER PPR',pp(para))
      for ri,r in enumerate(para.findall('w:r',NS)):
       rt=''.join(r.xpath('.//w:t/text()',namespaces=NS)); rpr=r.find('w:rPr',NS); f={}
       if rpr is not None:
        for e in rpr: f[etree.QName(e).localname]={etree.QName(k).localname:v for k,v in e.attrib.items()}
       print('   RUN',ri,repr(rt),f)
