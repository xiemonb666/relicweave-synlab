from __future__ import annotations
import os, sys, re, json, hashlib, subprocess, time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(r'C:\Users\xiemo\Desktop\ShardForge').resolve()
OUT = ROOT / 'tmp' / 'backup_coordinator' / 'closeout_20261007'
OUT.mkdir(parents=True, exist_ok=True)
REPOS = {
    'pgfrag': ROOT / 'pgfrag',
    'vesselforge': ROOT / 'vesselforge',
    'relicweave-synlab': ROOT / 'relicweave-synlab',
}
BRANCH_EXPECTED = 'backup/forge-work-20261003'
SKIP_DIRS = {
    '.git', '.venv', 'venv', 'env', '__pycache__', '.pytest_cache', '.mypy_cache',
    '.ruff_cache', '.cache', 'cache', '.tox', '.nox', 'node_modules', 'build', 'dist',
    'target', 'site-packages', 'relicweave_synlab.egg-info', '.next', '.nuxt', 'coverage',
}
SKIP_SUBTREES = {
    'third_party/akantu-runtime', 'third_party/blender-5.2.2-windows-x64',
    'third_party/doc-render-runtime', 'third_party/pgfrag-geometry-runtime',
    'third_party/pgfrag-runtime', 'third_party/vesselforge-runtime',
}
CODE_EXTS = {
    '.py','.pyi','.pyx','.pxd','.jl','.r','.rmd','.m','.sh','.bash','.zsh','.ps1','.psm1',
    '.bat','.cmd','.js','.mjs','.cjs','.ts','.tsx','.jsx','.html','.css','.scss','.sass',
    '.c','.h','.cc','.cpp','.cxx','.hpp','.hxx','.rs','.go','.java','.kt','.kts','.cs',
    '.php','.sql','.lua','.pl','.rb','.swift','.scala','.ex','.exs','.erl','.hrl','.f','.f90',
    '.f95','.for','.cob','.cbl','.groovy','.gradle','.vue','.svelte','.astro','.ipynb','.svg',
}
CONFIG_EXTS = {'.toml','.ini','.cfg','.conf','.properties','.xml','.yml','.yaml','.lock'}
DOC_EXTS = {'.md','.rst','.adoc'}
SOURCE_NAMES = {
    'dockerfile','makefile','justfile','procfile','gemfile','rakefile','cmakelists.txt',
    '.editorconfig','.gitattributes','.gitignore','.dockerignore','.npmrc','.nvmrc',
    '.pre-commit-config.yaml','requirements.txt','requirements.lock.txt','constraints.txt',
    'manifest.toml','project.toml','pyproject.toml','cargo.toml','cargo.lock','go.mod','go.sum',
    'package.json','package-lock.json','pnpm-lock.yaml','yarn.lock','poetry.lock','pipfile','pipfile.lock',
    'license','license.txt','copying','copying.txt','notice','notice.txt','authors','contributors',
    'security.md','code_of_conduct.md','contributing.md','changelog.md','readme','readme.md',
    'agents.md','citation.cff','tox.ini','setup.cfg','setup.py','setup.py.snapshot',
}
LICENSE_PREFIXES = ('license','licence','copying','notice','authors','contributors','third_party_notices')
SECRET_PATH_RE = re.compile(r'(^|[/\\])(?:\.env(?:\..*)?|credentials?(?:\.[^/\\]+)?|secrets?(?:\.[^/\\]+)?|id_(?:rsa|ed25519)|.*\.(?:pem|p12|pfx|key|keystore))(?:$|[/\\])', re.I)
SECRET_TOKEN_RE = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|\b(?:gh[pousr]_[A-Za-z0-9_]{25,}|github_pat_[A-Za-z0-9_]{25,}|AKIA[0-9A-Z]{16}|sk_live_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_\-]{30,})\b')

# Exact source roots with current stable/closed review artifacts; output evidence is kept
# distinguishable from general source inventory. Existing 40-entry proposal is read-only.
CLOSED_REVIEW_ROOTS = [
    'pgfrag/tmp/review_20261007/mixed93_opening_history_independent',
    'pgfrag/tmp/review_20261007/mixed93_opening_history_saved_visual',
    'pgfrag/tmp/review_20261007/mixed93_mechanics_objectivity_independent',
    'pgfrag/tmp/review_20261007/mixed93_moving_front_reanalysis_20261007',
]
CURATED_IMAGE_RELS = {
    'pgfrag/tmp/review_20261007/mixed93_opening_history_saved_visual/run01/opening_history_saved_diagnostic.png',
}
# Previously selected bounded replay datasets; add only when not already tracked/represented.
SELECTED_DATA_RELS = {
    'pgfrag/tmp/review_20261007/mixed93_moving_front_reanalysis_20261007/run01/failure_arrays.npz',
    'pgfrag/tmp/review_20261006/tip_aligned_quadrature_study_20261006/run01/arrays.npz',
    'pgfrag/tmp/review_20261006/mixed93_cached_lefm_solve_20261006/run01/arrays.npz',
}


def run_git(repo: Path, *args, timeout=15):
    try:
        cp = subprocess.run(['git','-C',str(repo),*args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout, check=False)
        return cp.returncode, cp.stdout, cp.stderr
    except subprocess.TimeoutExpired as e:
        return 124, e.stdout or b'', e.stderr or b''

def decode_z(data: bytes):
    return [x.decode('utf-8','surrogateescape') for x in data.split(b'\0') if x]

def sha256_file(path: Path):
    h = hashlib.sha256(); n = 0
    with path.open('rb') as f:
        while True:
            b=f.read(1024*1024)
            if not b: break
            n += len(b); h.update(b)
    return n, h.hexdigest()

def is_secret_path(rel: str):
    norm = rel.replace('\\','/')
    base = norm.rsplit('/',1)[-1].lower()
    if SECRET_PATH_RE.search('/'+norm+'/'): return True
    if base in {'.npmrc','.pypirc','.netrc','credentials.json','service-account.json'}: return True
    return False

def likely_secret_bytes(path: Path):
    # Return a boolean only; matched content is never serialized or printed.
    try:
        if path.stat().st_size > 8*1024*1024: return False
        data = path.read_bytes()
    except Exception:
        return False
    return bool(SECRET_TOKEN_RE.search(data))

def is_snapshot_name(name: str):
    s=name.lower()
    return any(f'.{ext}.' in s and any(t in s for t in ('snapshot','pre_','pre-','frozen','freeze','backup')) for ext in ('py','jl','js','ts','rs','c','h','cpp','md'))

def is_generated_path(rel: str):
    p=rel.replace('\\','/').lower().split('/')
    if any(x in p for x in ('outputs','output','pytest-tmp','pytest_tmp','artifacts_cache','generated_data','generated-datasets')):
        return True
    if any(x in p for x in ('reports','report_exports','a12_exports')):
        return True
    return False

def under_any(rel: str, roots):
    q=rel.replace('\\','/').lower()
    return any(q == r.lower() or q.startswith(r.lower().rstrip('/')+'/') for r in roots)

def is_candidate(rel: str, size: int, repo_rel: str|None, external: bool):
    norm=rel.replace('\\','/')
    p=norm.lower().split('/')
    name=p[-1]
    ext=Path(name).suffix.lower()
    if name in SOURCE_NAMES or name.startswith(LICENSE_PREFIXES): return ('authored_docs_or_config','include')
    if ext in CODE_EXTS or is_snapshot_name(name): return ('source_code_or_snapshot','include')
    if ext in CONFIG_EXTS:
        # YAML in data/reports is usually generated metadata; preserve only source config/schema/fixture.
        if ext in {'.yaml','.yml'} and ('data' in p or 'report' in p or 'metadata' in p) and not any(x in p for x in ('config','configs','schema','schemas','fixtures','tests')):
            return ('generated_metadata_yaml','exclude')
        if is_generated_path(norm): return ('generated_configlike_output','exclude')
        return ('project_configuration','include')
    if ext in DOC_EXTS:
        if is_generated_path(norm): return ('generated_report_document','exclude')
        return ('authored_documentation','include')
    if ext == '.txt':
        if name.endswith('.log') or name.startswith(('stdout','stderr','run_','pytest_')): return ('runtime_text_output','exclude')
        if name in SOURCE_NAMES or any(s in p for s in ('docs','experiments','examples','tests','schemas','src','synlab','tools','scripts')):
            return ('text_document_or_dependency_file','include')
        if under_any(norm,CLOSED_REVIEW_ROOTS): return ('closed_review_record','include')
        return ('unclassified_text_output','exclude')
    if ext == '.json':
        if is_generated_path(norm): return ('generated_json_dataset_or_report','exclude')
        if any(s in p for s in ('tests','fixtures','schemas','configs','.github','examples')):
            return ('fixture_or_configuration_json','include')
        base=name.lower()
        if any(k in base for k in ('source_pin','source_freeze','manifest','case','schema','contract','design','readme','lock','license','license','index')):
            return ('source_metadata_json','include')
        if under_any(norm,CLOSED_REVIEW_ROOTS): return ('closed_review_record','include')
        return ('unclassified_json_output','exclude')
    if ext == '.jsonl':
        if any(s in p for s in ('tests','fixtures','schemas','configs')): return ('fixture_or_configuration_jsonl','include')
        return ('generated_jsonl_data','exclude')
    if ext in {'.csv','.tsv','.npy','.npz','.parquet','.arrow','.feather','.h5','.hdf5','.mat'}:
        if norm in SELECTED_DATA_RELS: return ('selected_bounded_replay_data','include')
        if any(s in p for s in ('tests','fixtures','schemas')) and size <= 1024*1024: return ('small_test_fixture_data','include')
        return ('generated_numeric_dataset','exclude')
    if ext in {'.png','.jpg','.jpeg','.webp','.gif','.bmp','.tif','.tiff'}:
        if norm in CURATED_IMAGE_RELS: return ('closed_review_figure','include')
        if under_any(norm,CLOSED_REVIEW_ROOTS) and ext == '.png' and size <= 5*1024*1024: return ('closed_review_figure','include')
        return ('image_or_generated_figure','exclude')
    return ('not_in_source_scope','exclude')

def path_in_skipped_subtree(repo_name, rel):
    q=rel.replace('\\','/').lower()
    if repo_name=='relicweave-synlab' and q.startswith('third_party/'):
        return any(q == s or q.startswith(s+'/') for s in SKIP_SUBTREES)
    return False

repos_state={}
repo_sets={}
for name, repo in REPOS.items():
    rc, out, err = run_git(repo,'rev-parse','--show-toplevel')
    top=out.decode('utf-8','replace').strip() if rc==0 else None
    rc_b, b, _=run_git(repo,'branch','--show-current')
    branch=b.decode('utf-8','replace').strip() if rc_b==0 else None
    rc_h, h, _=run_git(repo,'rev-parse','HEAD')
    head=h.decode('ascii','replace').strip() if rc_h==0 else None
    rc_p, p, _=run_git(repo,'rev-parse','HEAD^')
    parent=p.decode('ascii','replace').strip() if rc_p==0 else None
    rc_tr, tr, _=run_git(repo,'ls-files','-z')
    tracked=set(decode_z(tr)) if rc_tr==0 else set()
    rc_u, u, _=run_git(repo,'ls-files','--others','--exclude-standard','-z')
    untracked=set(decode_z(u)) if rc_u==0 else set()
    rc_i, ig, _=run_git(repo,'ls-files','--others','--ignored','--exclude-standard','-z')
    ignored=set(decode_z(ig)) if rc_i==0 else set()
    rc_s, st, _=run_git(repo,'status','--porcelain=v1','--untracked-files=no')
    tracked_status=st.decode('utf-8','replace').splitlines() if rc_s==0 else ['status_error']
    rc_c, cached, _=run_git(repo,'diff','--cached','--name-only','-z')
    staged=decode_z(cached) if rc_c==0 else ['status_error']
    rc_r, url, _=run_git(repo,'remote','get-url','origin')
    remote=url.decode('utf-8','replace').strip() if rc_r==0 else None
    # Strip URL user-info defensively before serializing.
    if remote and '://' in remote and '@' in remote.split('://',1)[1]:
        remote=remote.split('://',1)[0]+'://[redacted]@'+remote.split('://',1)[1].split('@',1)[1]
    elif remote and '@' in remote and '://' not in remote:
        remote='[redacted]@'+remote.split('@',1)[1]
    rc_lr, lr, lre=run_git(repo,'ls-remote','--heads','origin',BRANCH_EXPECTED,timeout=12)
    remote_head=None
    if rc_lr==0:
        for line in lr.decode('ascii','replace').splitlines():
            if line.endswith('\trefs/heads/'+BRANCH_EXPECTED): remote_head=line.split('\t',1)[0]
    repos_state[name]={
        'repo_root':str(repo),'git_toplevel':top,'branch':branch,'head':head,'parent':parent,
        'expected_branch':BRANCH_EXPECTED,'branch_matches':branch==BRANCH_EXPECTED,
        'origin_sanitized':remote,'remote_ls_remote_rc':rc_lr,'remote_head':remote_head,
        'remote_matches_head':bool(remote_head and remote_head==head),
        'tracked_count':len(tracked),'untracked_nonignored_count':len(untracked),
        'ignored_untracked_count':len(ignored),'tracked_status_lines':tracked_status,
        'staged_paths':staged,'tracked_index_clean':not tracked_status and not staged,
    }
    repo_sets[name]=(tracked,untracked,ignored)

entries=[]
large_files=[]
excluded_subtrees=[]
credential_paths=[]
scan_errors=[]

# Existing v1 manifest selection is preserved as an explicit curated scope; read-only.
v1_path=ROOT/'tmp'/'backup_coordinator'/'new_milestone_closed_backup_plan_20261007.json'
v1_selected=set()
if v1_path.exists():
    try:
        v1=json.loads(v1_path.read_text(encoding='utf-8'))
        for f in v1.get('files',[]):
            sr=f.get('source_relative') or f.get('source_workspace_relative') or f.get('source_relpath')
            if sr: v1_selected.add(str(sr).replace('\\','/'))
    except Exception as e:
        scan_errors.append({'path':str(v1_path),'error_type':type(e).__name__})

# Collect all files in each repository, including ignored files, except explicit generated/runtime dirs.
for repo_name, repo in REPOS.items():
    tracked, untracked, ignored=repo_sets[repo_name]
    for dirpath, dirnames, filenames in os.walk(repo, topdown=True, followlinks=False):
        d=Path(dirpath)
        rel_dir=d.relative_to(repo).as_posix()
        keep=[]
        for dn in dirnames:
            if dn.lower() in SKIP_DIRS:
                excluded_subtrees.append({'repo':repo_name,'path':(Path(rel_dir)/dn).as_posix(),'reason':'build_cache_or_environment'})
                continue
            child_rel=(Path(rel_dir)/dn).as_posix() if rel_dir!='.' else dn
            if path_in_skipped_subtree(repo_name,child_rel):
                excluded_subtrees.append({'repo':repo_name,'path':child_rel,'reason':'vendored_runtime_or_installer'})
                continue
            if repo_name=='relicweave-synlab' and child_rel.replace('\\','/').lower()=='workspace_backup/20261007':
                # The root-outside source mirror destination is planned, not part of the source inventory.
                excluded_subtrees.append({'repo':repo_name,'path':child_rel,'reason':'planned_workspace_backup_destination'})
                continue
            keep.append(dn)
        dirnames[:]=keep
        for fn in filenames:
            f=d/fn
            try:
                rel=f.relative_to(repo).as_posix()
                if f.is_symlink():
                    entries.append({'repo':repo_name,'source_absolute':str(f),'source_repo_relative':rel,'destination_repo_relative':rel,'operation':'exclude','classification':'symlink_not_followed','git_status':'tracked' if rel in tracked else ('ignored_untracked' if rel in ignored else 'untracked'),'bytes':None,'sha256':None,'review_state':'excluded'})
                    continue
                size=f.stat().st_size
            except Exception as e:
                scan_errors.append({'repo':repo_name,'path':str(f),'error_type':type(e).__name__}); continue
            if size > 50*1024*1024:
                large_files.append({'repo':repo_name,'path':rel,'bytes':size,'flag':'over_50MiB','classification':'not_hashed'} )
            if is_secret_path(rel):
                credential_paths.append({'repo':repo_name,'path':rel,'status':'path_matches_credential_or_key_name','bytes':size})
                entries.append({'repo':repo_name,'source_absolute':str(f),'source_repo_relative':rel,'destination_repo_relative':None,'operation':'exclude','classification':'credential_path_excluded','git_status':'tracked' if rel in tracked else ('ignored_untracked' if rel in ignored else 'untracked'),'bytes':size,'sha256':None,'review_state':'excluded_no_content_read'})
                continue
            cls, incl=is_candidate(rel,size,rel,False)
            if cls=='selected_bounded_replay_data' and rel in tracked:
                cls='selected_bounded_replay_data_already_tracked_or_duplicate_candidate'
            if incl!='include':
                # Keep a summary entry for non-source files and generated data only when >50 MiB or source-like extension.
                ext=Path(fn).suffix.lower()
                if size>50*1024*1024 or ext in CODE_EXTS or is_snapshot_name(fn) or ext in {'.json','.yaml','.yml','.csv','.npz','.npy','.png','.jpg','.md','.txt'}:
                    entries.append({'repo':repo_name,'source_absolute':str(f),'source_repo_relative':rel,'destination_repo_relative':None,'operation':'exclude','classification':cls,'git_status':'tracked' if rel in tracked else ('ignored_untracked' if rel in ignored else 'untracked'),'bytes':size,'sha256':None,'review_state':'excluded_generated_or_non_source'})
                continue
            if size > 50*1024*1024:
                entries.append({'repo':repo_name,'source_absolute':str(f),'source_repo_relative':rel,'destination_repo_relative':None,'operation':'exclude','classification':'source_over_50MiB_requires_review','git_status':'tracked' if rel in tracked else ('ignored_untracked' if rel in ignored else 'untracked'),'bytes':size,'sha256':None,'review_state':'hold_large_file'})
                continue
            if likely_secret_bytes(f):
                credential_paths.append({'repo':repo_name,'path':rel,'status':'high_confidence_secret_token_pattern_detected','bytes':size})
                entries.append({'repo':repo_name,'source_absolute':str(f),'source_repo_relative':rel,'destination_repo_relative':None,'operation':'exclude','classification':'credential_content_pattern_excluded','git_status':'tracked' if rel in tracked else ('ignored_untracked' if rel in ignored else 'untracked'),'bytes':size,'sha256':None,'review_state':'excluded_content_never_recorded'})
                continue
            try: actual_size, digest=sha256_file(f)
            except Exception as e:
                scan_errors.append({'repo':repo_name,'path':rel,'error_type':type(e).__name__}); continue
            status='tracked' if rel in tracked else ('ignored_untracked' if rel in ignored else 'untracked')
            if status=='tracked': op='already_on_branch'
            else: op='stage_existing_exact_force' if status=='ignored_untracked' else 'stage_existing_exact'
            if under_any(rel,CLOSED_REVIEW_ROOTS): review='closed_review_candidate_root_review_pending'
            elif rel in v1_selected: review='preserved_prior_v1_candidate'
            elif repo_name=='pgfrag' and rel.startswith('experiments/mixed93_mechanics_objectivity_20261007/'):
                review='source_freeze_status_root_review_pending'
            else: review='general_source_inventory_root_scope_review_pending'
            entries.append({'repo':repo_name,'source_absolute':str(f),'source_repo_relative':rel,'destination_repo_relative':rel,'operation':op,'classification':cls,'git_status':status,'bytes':actual_size,'sha256':digest,'review_state':review})

# Root-workspace files outside the three existing repos are mapped into SynLab, preserving their relative path.
repo_abs=[p.resolve() for p in REPOS.values()]
for dirpath, dirnames, filenames in os.walk(ROOT, topdown=True, followlinks=False):
    d=Path(dirpath)
    rel_dir=d.relative_to(ROOT).as_posix()
    if rel_dir=='.':
        pass
    keep=[]
    for dn in dirnames:
        child=(Path(rel_dir)/dn).as_posix() if rel_dir!='.' else dn
        resolved=(d/dn).resolve()
        if any(resolved==rp for rp in repo_abs): continue
        if dn.lower() in SKIP_DIRS or dn.lower()=='.git':
            excluded_subtrees.append({'repo':'workspace_root_external','path':child,'reason':'build_cache_or_environment'}); continue
        if child.replace('\\','/').lower()=='tmp/backup_coordinator':
            excluded_subtrees.append({'repo':'workspace_root_external','path':child,'reason':'backup_coordinator_working_area'}); continue
        if child.replace('\\','/').lower().startswith('tmp/backup_coordinator/'):
            continue
        if child.replace('\\','/').lower().startswith(('pgfrag/','vesselforge/','relicweave-synlab/')): continue
        keep.append(dn)
    dirnames[:]=keep
    for fn in filenames:
        f=d/fn
        try:
            rel=f.relative_to(ROOT).as_posix()
            if f.is_symlink():
                entries.append({'repo':'workspace_root_external','source_absolute':str(f),'source_workspace_relative':rel,'destination_repo':'relicweave-synlab','destination_repo_relative':f'workspace_backup/20261007/{rel}','operation':'exclude','classification':'symlink_not_followed','git_status':'outside_repo','bytes':None,'sha256':None,'review_state':'excluded'}); continue
            size=f.stat().st_size
        except Exception as e:
            scan_errors.append({'repo':'workspace_root_external','path':str(f),'error_type':type(e).__name__}); continue
        if size>50*1024*1024:
            large_files.append({'repo':'workspace_root_external','path':rel,'bytes':size,'flag':'over_50MiB','classification':'not_hashed'})
        if is_secret_path(rel):
            credential_paths.append({'repo':'workspace_root_external','path':rel,'status':'path_matches_credential_or_key_name','bytes':size})
            entries.append({'repo':'workspace_root_external','source_absolute':str(f),'source_workspace_relative':rel,'destination_repo':'relicweave-synlab','destination_repo_relative':None,'operation':'exclude','classification':'credential_path_excluded','git_status':'outside_repo','bytes':size,'sha256':None,'review_state':'excluded_no_content_read'}); continue
        cls,incl=is_candidate(rel,size,None,True)
        if incl!='include':
            ext=Path(fn).suffix.lower()
            if size>50*1024*1024 or ext in CODE_EXTS or is_snapshot_name(fn) or ext in {'.json','.yaml','.yml','.csv','.npz','.npy','.png','.jpg','.md','.txt'}:
                entries.append({'repo':'workspace_root_external','source_absolute':str(f),'source_workspace_relative':rel,'destination_repo':'relicweave-synlab','destination_repo_relative':None,'operation':'exclude','classification':cls,'git_status':'outside_repo','bytes':size,'sha256':None,'review_state':'excluded_generated_or_non_source'})
            continue
        if size>50*1024*1024:
            entries.append({'repo':'workspace_root_external','source_absolute':str(f),'source_workspace_relative':rel,'destination_repo':'relicweave-synlab','destination_repo_relative':None,'operation':'exclude','classification':'source_over_50MiB_requires_review','git_status':'outside_repo','bytes':size,'sha256':None,'review_state':'hold_large_file'}); continue
        if likely_secret_bytes(f):
            credential_paths.append({'repo':'workspace_root_external','path':rel,'status':'high_confidence_secret_token_pattern_detected','bytes':size})
            entries.append({'repo':'workspace_root_external','source_absolute':str(f),'source_workspace_relative':rel,'destination_repo':'relicweave-synlab','destination_repo_relative':None,'operation':'exclude','classification':'credential_content_pattern_excluded','git_status':'outside_repo','bytes':size,'sha256':None,'review_state':'excluded_content_never_recorded'}); continue
        try: actual_size,digest=sha256_file(f)
        except Exception as e:
            scan_errors.append({'repo':'workspace_root_external','path':rel,'error_type':type(e).__name__}); continue
        dest=f'workspace_backup/20261007/{rel}'
        target=REPOS['relicweave-synlab']/Path(dest)
        if target.exists():
            try: ts,th=sha256_file(target)
            except Exception: ts,th=None,None
            if ts==actual_size and th==digest: op='destination_already_same_bytes_stage_exact'
            else: op='blocked_destination_collision'
            collision={'exists':True,'bytes':ts,'sha256':th,'matches':ts==actual_size and th==digest}
        else:
            op='copy_then_stage_exact_force' if not dest else 'copy_then_stage_exact'
            collision={'exists':False,'bytes':None,'sha256':None,'matches':None}
        # The destination may be ignored; query only this path, do not write.
        rc_ci, ci, _=run_git(REPOS['relicweave-synlab'],'check-ignore','-q','--',dest)
        if rc_ci==0 and op=='copy_then_stage_exact': op='copy_then_stage_exact_force'
        entries.append({'repo':'workspace_root_external','source_absolute':str(f),'source_workspace_relative':rel,'destination_repo':'relicweave-synlab','destination_repo_relative':dest,'operation':op,'classification':cls,'git_status':'outside_repo','bytes':actual_size,'sha256':digest,'destination_preflight':collision,'review_state':'root_external_code_mapped_pending_root_review'})

# Reconcile duplicate destinations and summarize exact operations.
dest_counts={}
for e in entries:
    dest=e.get('destination_repo_relative')
    target_repo=e.get('destination_repo') or e.get('repo')
    if dest and target_repo:
        key=(target_repo,dest.replace('\\','/').lower())
        dest_counts[key]=dest_counts.get(key,0)+1
for e in entries:
    dest=e.get('destination_repo_relative'); target_repo=e.get('destination_repo') or e.get('repo')
    if dest and dest_counts.get((target_repo,dest.replace('\\','/').lower()),0)>1:
        e['review_state']='blocked_duplicate_destination'
        e['operation']='blocked_duplicate_destination'

ops=['stage_existing_exact','stage_existing_exact_force','copy_then_stage_exact','copy_then_stage_exact_force','destination_already_same_bytes_stage_exact']
repo_summary={}
for name in ('pgfrag','vesselforge','relicweave-synlab','workspace_root_external'):
    items=[e for e in entries if e.get('repo')==name]
    candidate=[e for e in items if e.get('operation') in ops]
    tracked=[e for e in items if e.get('operation')=='already_on_branch']
    repo_summary[name]={
        'inventory_entries':len(items),'candidate_stage_or_copy_entries':len(candidate),
        'already_on_branch_entries':len(tracked),
        'candidate_bytes':sum(e.get('bytes') or 0 for e in candidate),
        'candidate_by_operation':{op:sum(1 for e in candidate if e['operation']==op) for op in ops},
        'candidate_by_classification':{},
        'candidate_by_git_status':{},
    }
    for e in candidate:
        c=e.get('classification','unknown'); s=e.get('git_status','unknown')
        repo_summary[name]['candidate_by_classification'][c]=repo_summary[name]['candidate_by_classification'].get(c,0)+1
        repo_summary[name]['candidate_by_git_status'][s]=repo_summary[name]['candidate_by_git_status'].get(s,0)+1

candidate_entries=[e for e in entries if e.get('operation') in ops]
# Candidate destination uniqueness and in-workspace safety flags.
manifest={
    'schema':'codex_full_code_backup_inventory_v1',
    'mode':'PREPARE_ONLY_NO_COPY_NO_GIT_MUTATION',
    'created_utc':datetime.now(timezone.utc).isoformat(),
    'workspace_root':str(ROOT),
    'scope_note':'Candidate inventory covers tracked/untracked/ignored source, tests, project config, docs/licenses, selected closed-review evidence, and root-external authored source. Generated datasets and runtimes are excluded; unreviewed/mutable candidates remain pending root review.',
    'repositories':repos_state,
    'summary':{
        'entry_count':len(entries),'candidate_entry_count':len(candidate_entries),
        'candidate_bytes':sum(e.get('bytes') or 0 for e in candidate_entries),
        'per_repo':repo_summary,
        'large_files_over_50MiB_count':len(large_files),
        'credential_paths_status_only_count':len(credential_paths),
        'excluded_subtree_count':len(excluded_subtrees),
        'scan_error_count':len(scan_errors),
        'duplicate_destination_count':sum(1 for v in dest_counts.values() if v>1),
        'source_hashes_recorded':sum(1 for e in entries if e.get('sha256')),
    },
    'large_files_over_50MiB':large_files,
    'credential_path_status_only':credential_paths,
    'excluded_subtrees':excluded_subtrees,
    'scan_errors':scan_errors,
    'entries':entries,
    'root_review_required':True,
    'exclusions':{
        'directories':['.git','.venv','venv','node_modules','build','dist','target','pytest/cache dirs','known third_party runtime/installers'],
        'content':['credentials/private keys detected by path or high-confidence token pattern (only path/status recorded)','generated numeric datasets and report exports except explicitly selected bounded replay/closed-review figures','binary installers/runtime payloads','large source-like files >50 MiB held for review'],
        'mutable_or_unreviewed':'source inventory can contain files that are not frozen; any copy/stage manifest must filter by fresh exact SHA and root acceptance/freeze evidence.'
    }
}
(OUT/'inventory.json').write_text(json.dumps(manifest,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
# A separate explicit allowlist contains only candidate actions, with source/destination identity and hashes.
stage_manifest={
    'schema':'codex_exact_source_stage_manifest_v1','mode':'PREPARE_ONLY_NOT_AUTHORIZED_FOR_COPY_OR_GIT',
    'inventory_path':str(OUT/'inventory.json'),'inventory_sha256':hashlib.sha256((OUT/'inventory.json').read_bytes()).hexdigest(),
    'workspace_root':str(ROOT),'branch':BRANCH_EXPECTED,'repositories':repos_state,
    'files':candidate_entries,
    'summary':{
        'file_count':len(candidate_entries),'total_bytes':sum(e.get('bytes') or 0 for e in candidate_entries),
        'per_repo':repo_summary,'no_copy_stage_commit_push_performed':True,
        'all_targets_unique':not any(v>1 for v in dest_counts.values()),
        'all_repo_destinations_within_repo':True,
        'all_external_targets_under_a12_workspace_backup':all(e.get('destination_repo_relative','').startswith('workspace_backup/20261007/') for e in candidate_entries if e.get('repo')=='workspace_root_external'),
    }
}
(OUT/'explicit_stage_manifest.json').write_text(json.dumps(stage_manifest,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
# Small human review notes.
lines=[
'# Full-source backup inventory (prepare only)','',
'No files were copied and no Git index, commit, branch, remote, or persistent configuration was changed. This directory contains an inventory and an exact candidate manifest for root review; the manifest is not execution authorization.','',
'## Snapshot',
'- Workspace: `'+str(ROOT)+'`',
'- Repositories: '+', '.join(f"{n} {repos_state[n]['head']} ({repos_state[n]['branch']})" for n in REPOS),
'- Candidate stage/copy files: '+str(len(candidate_entries))+'; bytes: '+str(sum(e.get('bytes') or 0 for e in candidate_entries)),
'- >50 MiB file flags: '+str(len(large_files))+'; credential-name/token status paths: '+str(len(credential_paths))+'; scan errors: '+str(len(scan_errors)),
'- Prior closed-artifact v1 remains unchanged at `tmp/backup_coordinator/new_milestone_closed_backup_plan_20261007.json`.',
'',
'## Review rules',
'- `already_on_branch` entries are present at the checked HEAD and are not staged by this plan.',
'- `stage_existing_exact*` means source is already in a repository; ignored paths require exact-path force-add if root later authorizes it.',
'- `copy_then_stage_exact*` maps workspace-external authored files to `relicweave-synlab/workspace_backup/20261007/<original-relative-path>`.',
'- The inventory can contain mutable or unreviewed files. Any execution plan must be re-frozen and root-approved by exact hashes; no physics or quality claims are implied.',
'- Large-file and credential reports include only paths/status/byte counts, never credential values.',
'',
'Files: `inventory.json` (coverage and exclusions), `explicit_stage_manifest.json` (candidate exact path/hash allowlist).'
]
(OUT/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'out':str(OUT),'inventory_entries':len(entries),'candidate_count':len(candidate_entries),'candidate_bytes':sum(e.get('bytes') or 0 for e in candidate_entries),'summary':repo_summary,'large_files':len(large_files),'credential_status_paths':len(credential_paths),'excluded_subtrees':len(excluded_subtrees),'scan_errors':scan_errors,'inventory_sha256':hashlib.sha256((OUT/'inventory.json').read_bytes()).hexdigest(),'stage_manifest_sha256':hashlib.sha256((OUT/'explicit_stage_manifest.json').read_bytes()).hexdigest()},ensure_ascii=True))