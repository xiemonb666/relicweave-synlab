from pypdf import PdfReader
r=PdfReader('tmp/closeout_documents_20261007/reference_render/RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.pdf')
for i in range(97,106):
 t=r.pages[i].extract_text() or ''
 print('\n---PAGE',i+1,'---\n',t[:1600])
