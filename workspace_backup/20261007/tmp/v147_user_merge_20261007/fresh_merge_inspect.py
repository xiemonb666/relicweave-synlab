import json,zipfile,hashlib
from pathlib import Path
from lxml import etree
base=Path('tmp/v147_user_merge_20261007')
doc=base/'fresh_merge_final_candidate.docx'
check=base/'fresh_merge_FINAL_SOURCECHECK.json'
data=json.loads(check.read_text(encoding='utf-8'))
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'; N={'w':W}
root=etree.fromstring(zipfile.ZipFile(doc).read('word/document.xml'))
body=root.xpath('.//w:body',namespaces=N)[0]
paras=body.xpath('.//w:p',namespaces=N)
texts=[''.join(t.text or '' for t in p.xpath('.//w:t',namespaces=N)) for p in paras]
for patch in data['patches']:
    hits=[i for i,t in enumerate(texts) if t==patch['new']]
    if len(hits)!=1: raise RuntimeError(f"new text match {len(hits)} for {patch['label']}")
    patch['paragraph_index']=hits[0]
indices=[p['paragraph_index'] for p in data['patches']]
if len(set(indices))!=8 or set(indices)!=set(data['text_integrity']['changed_paragraph_indices']):
    raise RuntimeError('patchlist indices do not match changed slots')
data['text_integrity']['changed_paragraphs_by_label']=[{'paragraph_index':p['paragraph_index'],'label':p['label']} for p in data['patches']]
check.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# Final planning-text patch list','',
       'These are the only eight paragraph text changes from fresh_merge_candidate.docx to fresh_merge_final_candidate.docx. They are confined to planning/specification sections; no protected closeout/status or historical paragraph changed.','']
for i,p in enumerate(data['patches'],1):
    lines += [f"## {i}. {p['label']}","",f"Paragraph index: {p['paragraph_index']}","","Old text:","",p['old'],"","New text:","",p['new'],""]
(base/'fresh_merge_FINAL_PATCHLIST.md').write_text('\n'.join(lines),encoding='utf-8')
chg=base/'fresh_merge_FINAL_CHANGELOG.md'
existing=chg.read_text(encoding='utf-8').rstrip()
existing += ("\n\nTemporary-helper note: fresh_merge_inspect.py was overwritten during this turn's extraction checks. Its prior byte count and hash were not snapshotted, so they are unknown; the helper was not reconstructed. This does not affect the candidate or source DOCX files.\n")
chg.write_text(existing,encoding='utf-8')
print(json.dumps({'candidate_sha256':hashlib.sha256(doc.read_bytes()).hexdigest(),'candidate_bytes':doc.stat().st_size,'patch_indices':indices,'helper_prior_size_hash':'unknown; overwritten; not reconstructed'},ensure_ascii=False))
