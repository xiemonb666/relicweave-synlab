from __future__ import annotations
import argparse, hashlib, json, os
from pathlib import Path

def digest(p: Path):
    h=hashlib.sha256(); n=0
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):
            n+=len(b); h.update(b)
    return n,h.hexdigest()

def main():
    ap=argparse.ArgumentParser(description='Read-only source/destination/hash/scope verifier for a backup manifest')
    ap.add_argument('manifest',type=Path)
    ns=ap.parse_args()
    m=json.loads(ns.manifest.read_text(encoding='utf-8'))
    root=Path(m['workspace_root']).resolve()
    rows=m.get('files',m.get('candidate_actions',[]))
    failures=[]; checked=0; total=0; seen=set()
    for i,row in enumerate(rows):
        src=Path(row.get('source_absolute',''))
        expected=row.get('sha256'); n_expected=row.get('bytes')
        if not src.is_absolute(): src=(root/src).resolve()
        try:
            src_res=src.resolve(strict=True)
            n,h=digest(src_res)
            checked+=1; total+=n
            if n!=n_expected or h!=expected:
                failures.append({'index':i,'kind':'source_pin_mismatch','path':str(src_res)})
        except Exception as e:
            failures.append({'index':i,'kind':'source_unavailable','path':str(src),'error_type':type(e).__name__})
        repo_name=row.get('destination_repo') or row.get('repo')
        rel=row.get('destination_repo_relative')
        if rel and repo_name in m.get('repositories',{}):
            repo_root=Path(m['repositories'][repo_name]['repo_root']).resolve()
            target=(repo_root/Path(rel)).resolve()
            try: target.relative_to(repo_root)
            except Exception: failures.append({'index':i,'kind':'destination_escape','path':str(target)})
            key=(repo_name,target.as_posix().lower())
            if key in seen: failures.append({'index':i,'kind':'duplicate_destination','path':str(target)})
            seen.add(key)
    print(json.dumps({'manifest':str(ns.manifest.resolve()),'rows':len(rows),'sources_checked':checked,'source_bytes_checked':total,'failures':failures},ensure_ascii=True))
    return 1 if failures else 0
if __name__=='__main__':
    raise SystemExit(main())