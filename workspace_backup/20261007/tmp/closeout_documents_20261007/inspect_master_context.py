from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
DOC = Path(r'C:\Users\xiemo\Desktop\ShardForge\RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx')
NS = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
with ZipFile(DOC) as z:
    root=ET.fromstring(z.read('word/document.xml'))
body=root.find('w:body',NS)
paras=[]
for x in list(body):
    if x.tag.rsplit('}',1)[-1]=='p':
        tx=''.join(t.text or '' for t in x.findall('.//w:t',NS))
        st=x.find('w:pPr/w:pStyle',NS)
        paras.append((st.get('{%s}val'%NS['w']) if st is not None else '',tx))
for i,(st,tx) in enumerate(paras):
    if i<12 or 405<=i<=412 or 730<=i<=745 or 1307<=i<=1314 or 2048<=i<=2058 or 2093<=i<=2102 or 2219<=i<=2228:
        print(f'[{i}] ({st}) {tx}')
