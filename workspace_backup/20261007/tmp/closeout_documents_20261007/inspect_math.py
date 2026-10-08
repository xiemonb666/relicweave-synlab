from zipfile import ZipFile
from pathlib import Path
for x in ['RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx','RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx']:
 with ZipFile(x) as z:
  print(x)
  for n in z.namelist():
   b=z.read(n)
   if b'oMath' in b or b'm:' in b and b'officeDocument/2006/math' in b:
    print(n,'oMath',b.count(b'oMath'),'namespace',b.count(b'officeDocument/2006/math'))
