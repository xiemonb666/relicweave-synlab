from pypdf import PdfReader
pdf='tmp/closeout_documents_20261007/reference_render/RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.pdf'
r=PdfReader(pdf)
for i,p in enumerate(r.pages):
 t=p.extract_text() or ''
 if '本表覆盖此前章节' in t or ('最新冻结' in t and '为准' in t):
  print('page',i+1,repr(t[:1200]))
