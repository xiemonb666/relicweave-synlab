import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from pypdf import PdfReader
import pdfplumber
pdf=Path(sys.argv[1]); out=Path(sys.argv[2])
reader=PdfReader(str(pdf))
embedded_by_page=defaultdict(set)
for pn,page in enumerate(reader.pages,1):
    res=page.get('/Resources')
    if res is None: continue
    fonts=res.get_object().get('/Font')
    if fonts is None: continue
    for ref in fonts.get_object().values():
        f=ref.get_object(); objs=[f]
        descendants=f.get('/DescendantFonts')
        if descendants: objs.extend(x.get_object() for x in descendants.get_object())
        for obj in objs:
            name=str(obj.get('/BaseFont','')).lstrip('/')
            name=re.sub(r'^[A-Z]{6}\+','',name)
            desc=obj.get('/FontDescriptor'); embedded=False
            if desc:
                d=desc.get_object()
                embedded=any(d.get(k) is not None for k in ('/FontFile','/FontFile2','/FontFile3'))
            if name: embedded_by_page[pn].add((name,embedded))
face_pages=defaultdict(set); char_counts=Counter(); char_pages=defaultdict(set)
with pdfplumber.open(str(pdf)) as doc:
    page_count=len(doc.pages)
    for pn,page in enumerate(doc.pages,1):
        for c in page.chars:
            name=c['fontname']
            char_counts[name]+=1; char_pages[name].add(pn)
            if name: face_pages[name].add(pn)
embedded_faces=sorted({n for vals in embedded_by_page.values() for n,e in vals if e})
char_face_rows=[]
for name,count in sorted(char_counts.items()):
    char_face_rows.append({'fontname':name,'characters':count,'pages':len(char_pages[name])})
norm=lambda s: re.sub(r'[^a-z0-9]','',s.lower())
result={
 'pdf':str(pdf.resolve()),
 'pdf_page_count':page_count,
 'embedded_font_faces':embedded_faces,
 'char_font_usage':char_face_rows,
 'liberation_sans_embedded':any('liberationsans' in norm(x) for x in embedded_faces),
 'droid_sans_fallback_embedded':any('droidsansfallback' in norm(x) for x in embedded_faces),
 'liberation_sans_used_by_chars':any('liberationsans' in norm(x) for x in char_counts),
 'droid_sans_fallback_used_by_chars':any('droidsansfallback' in norm(x) for x in char_counts),
}
result['both_expected_fonts_used_and_embedded']=all(result[k] for k in ('liberation_sans_embedded','droid_sans_fallback_embedded','liberation_sans_used_by_chars','droid_sans_fallback_used_by_chars'))
out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(0 if result['both_expected_fonts_used_and_embedded'] else 32)
