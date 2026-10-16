from pypdf import PdfReader
p='tmp/closeout_documents_20261007/reference_render/RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.pdf'
r=PdfReader(p)
print('pages',len(r.pages))
t=r.pages[102].extract_text()
print(t)
