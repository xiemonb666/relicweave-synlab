from zipfile import ZipFile
from lxml import etree
p='RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx'
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'; R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'; NS={'w':W}
with ZipFile(p) as z:
 doc=etree.fromstring(z.read('word/document.xml')); rels=etree.fromstring(z.read('word/_rels/document.xml.rels'))
 rm={e.get('Id'):e.get('Target') for e in rels}
 body=doc.find('.//{%s}body'%W); i=0
 for p0 in body:
  s=p0.find('w:pPr/w:sectPr',NS) if etree.QName(p0).localname=='p' else None
  if s is None and etree.QName(p0).localname=='sectPr': s=p0
  if s is not None:
   print('SECTION',i)
   for e in s:
    if etree.QName(e).localname in ('headerReference','footerReference'):
     rid=e.get('{%s}id'%R); typ=e.get('{%s}type'%W); print(' ',etree.QName(e).localname,typ,rid,rm.get(rid))
   i+=1
