from pathlib import Path
from zipfile import ZipFile
from lxml import etree
p=Path('RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx')
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'; NS={'w':W}
with ZipFile(p) as z: root=etree.fromstring(z.read('word/document.xml'))
body=root.find('.//{%s}body'%W)
paras=[x for x in body if x.tag=='{%s}p'%W]
for i,x in enumerate(paras):
 t=''.join(x.xpath('.//w:t/text()',namespaces=NS))
 if any(q in t for q in ['V1.47 A12／','V1.47（2026年10月7日）','A12.19 当前状态','A12.20 当前实施','G0 当前状态','G31.1 V1.47','VesselForge 当前状态','PG-Frag 当前状态','V1.47（2026-10-07）收口记录']):
  print(i,t)
pdf=Path('tmp/closeout_documents_20261007/master_v147_render/RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.pdf')
try:
 import fitz
 d=fitz.open(pdf)
 print('pdf_page_count',len(d))
 for i,page in enumerate(d):
  t=page.get_text()
  if any(q in t for q in ['A12.19 当前状态','A12.20 当前实施','G0 当前状态','G31.1 V1.47','VesselForge 当前状态','PG-Frag 当前状态','收口记录']): print('modified_text_page',i+1,' '.join(t[:100].split()))
except Exception as e: print('fitz_unavailable',repr(e))
