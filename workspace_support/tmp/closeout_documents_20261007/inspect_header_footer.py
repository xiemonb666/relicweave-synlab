from zipfile import ZipFile
from lxml import etree
p='RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx'
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'; NS={'w':W}
with ZipFile(p) as z:
 for name in z.namelist():
  if name.startswith('word/header') or name.startswith('word/footer'):
   root=etree.fromstring(z.read(name)); pars=[]
   for para in root.findall('.//w:p',NS): pars.append(''.join(para.xpath('.//w:t/text()',namespaces=NS)))
   print(name,repr(pars))
