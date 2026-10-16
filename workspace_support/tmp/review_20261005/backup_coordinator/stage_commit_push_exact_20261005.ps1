param(
  [Parameter(Mandatory=$true)][string]$RepoName,
  [Parameter(Mandatory=$true)][string]$Subject,
  [Parameter(Mandatory=$true)][string]$Body
)
$ErrorActionPreference='Stop'
$root=(Resolve-Path '.').Path
$work=Join-Path $root 'tmp/review_20261005/backup_coordinator'
$manifestPath=Join-Path $work 'curated_evidence_copy_plan_20261005.json'
$expectedManifestSha='fb2eff29c6205f728331132ffd7ec5c795049b8a35f944209c19c31f99431558'
$manifest=Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
function Get-FileSha([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower() }
function Invoke-Git([string]$RepoPath,[string[]]$GitArgs) { $out=& git -C $RepoPath @GitArgs 2>&1; if($LASTEXITCODE -ne 0){throw "git failed ($LASTEXITCODE): $($GitArgs -join ' '): $($out -join ' ')" }; return $out }
if((Get-FileSha $manifestPath) -ne $expectedManifestSha){throw 'Copy-plan SHA mismatch.'}
if($RepoName -notin @('pgfrag','vesselforge','relicweave-synlab')){throw 'Unapproved repository.'}
$rp=Join-Path $root $RepoName
$expectedHeads=@{pgfrag='bf15835cac97a2ba032ec1872c57e6e60cb1e977'; vesselforge='8da9b538e2588fe51418588cb6301c258cd5363f'; 'relicweave-synlab'='b1099e4c714baff56083570883b44fee45e110f9'}
$parent=$expectedHeads[$RepoName]
$identityLine=((Invoke-Git $rp @('show','-s','--format=%an%x09%ae',$parent)) | Select-Object -Last 1).Trim()
$identityParts=$identityLine -split [char]9
if($identityParts.Count -ne 2){throw "Parent commit identity unavailable in $RepoName."}
$branch=((Invoke-Git $rp @('branch','--show-current')) | Select-Object -Last 1).Trim()
$head=((Invoke-Git $rp @('rev-parse','HEAD')) | Select-Object -Last 1).Trim()
$remote=((Invoke-Git $rp @('ls-remote','--heads','origin','backup/forge-work-20261003')) | Select-Object -Last 1).Trim()
$remoteHead=($remote -split '\s+')[0]
if($branch -ne 'backup/forge-work-20261003' -or $head -ne $parent -or $remoteHead -ne $parent){throw "Head/branch/remote changed for $RepoName; stop before staging."}
$stagedBefore=@(Invoke-Git $rp @('diff','--cached','--name-only') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$expectedEntries=@()
foreach($item in @($manifest.items | Where-Object { $_.repo -eq $RepoName })) {
  $rel=$item.proposed_destination.Substring($RepoName.Length+1)
  $file=Join-Path $rp ($rel -replace '/','\')
  $sha=Get-FileSha $file
  $bytes=(Get-Item -LiteralPath $file).Length
  if($sha -ne $item.sha256.ToLower() -or $bytes -ne [int64]$item.bytes){throw "Evidence file changed after copy: $rel"}
  $expectedEntries += [pscustomobject]@{path=$rel; bytes=[int64]$bytes; sha256=$sha; source_path=$item.source_path}
}
if($RepoName -eq 'relicweave-synlab') {
  $extra=@(
    [pscustomobject]@{path='synlab/qa/forge_chain_audit.py'; bytes=73028; sha256='3f84f824ca2dbc908303ae3c2b14f3ac3e1d8c88349238adf59ed747be48b5d7'},
    [pscustomobject]@{path='tests/a12/qa/test_forge_chain_source_dispatch_20261005.py'; bytes=11038; sha256='4df2391f107616b38854cbedc13b18c6e864ff3a4d0eeb1cc5ef102021f716e4'},
    [pscustomobject]@{path='docs/a12/chain_source_reader_dispatch_20261005.md'; bytes=3830; sha256='2480962d753b90700382e1477926271a69c63e6b94fffc07a0c90a50ea1eba58'},
    [pscustomobject]@{path='docs/a12/evidence/20261005/chain_source_dispatch/focused_pytest_20261005_receipt.json'; bytes=757; sha256='a0216bf2c468b916318ecf45c9b426b28d1d630bde3438847fc2034acced8858'},
    [pscustomobject]@{path='docs/a12/evidence/20261005/chain_source_dispatch/focused_pytest_20261005.junit.xml'; bytes=4128; sha256='bdba8730d155c6e120e613a0518ef6e8038e8b99b0ac4a8cf7dc7baba38077dc'},
    [pscustomobject]@{path='docs/a12/evidence/20261005/chain_source_dispatch/focused_pytest_20261005.stdout.txt'; bytes=81; sha256='0861033bdc2d6203bd8178972703a811b101e61fc065ed32dfd1a4824ab482f0'},
    [pscustomobject]@{path='docs/a12/evidence/20261005/chain_source_dispatch/pretest_sha256_20261005.json'; bytes=3652; sha256='0507950d3150fd572fde67ccfb5002ca247dc9bc608ad02d7db574665714b643'},
    [pscustomobject]@{path='docs/a12/evidence/20261005/chain_source_dispatch/posttest_sha256_20261005.json'; bytes=3652; sha256='5566964f51ab0ce82d3c347eb33f393fd05804047b02150a92ed5acae3f5c159'}
  )
  foreach($e in $extra){$file=Join-Path $rp ($e.path -replace '/','\'); $sha=Get-FileSha $file; $bytes=(Get-Item -LiteralPath $file).Length; if($sha -ne $e.sha256 -or $bytes -ne [int64]$e.bytes){throw "Approved Syn path changed: $($e.path)"}; $expectedEntries += [pscustomobject]@{path=$e.path; bytes=[int64]$bytes; sha256=$sha; source_path='root-approved frozen source'}}
}
$indexRel=if($RepoName -eq 'relicweave-synlab'){'docs/a12/evidence/20261005/backup_evidence_index_20261005.json'}else{'docs/evidence/20261005/backup_evidence_index_20261005.json'}
$indexFile=Join-Path $rp ($indexRel -replace '/','\')
$attrsFile=Join-Path $rp '.gitattributes'
foreach($rel in @($indexRel,'.gitattributes')) {
  $file=Join-Path $rp ($rel -replace '/','\')
  $expectedEntries += [pscustomobject]@{path=$rel; bytes=(Get-Item -LiteralPath $file).Length; sha256=(Get-FileSha $file); source_path='generated approved index or exact attributes append'}
}
$stagePaths=@($expectedEntries | ForEach-Object path | Sort-Object -Unique)
if($stagePaths.Count -ne $expectedEntries.Count){throw 'Duplicate paths in exact staging list.'}
if($stagedBefore.Count -gt 0){
  $stagedDifference=Compare-Object -ReferenceObject @($stagePaths | Sort-Object) -DifferenceObject @($stagedBefore | Sort-Object)
  if($stagedDifference){throw 'Pre-staged paths differ from approved exact set.'}
}
$ignoreOutput=& git -C $rp check-ignore -v -- $stagePaths 2>&1
$ignoreExit=$LASTEXITCODE
if($ignoreExit -eq 0){throw "One or more approved paths are ignored; no force-add authorized: $($ignoreOutput -join ' ')"}
if($ignoreExit -gt 1){throw "git check-ignore failed in ${RepoName}: $($ignoreOutput -join ' ')"}
$attrs=Invoke-Git $rp (@('check-attr','text','--') + $stagePaths) 
if($stagedBefore.Count -eq 0){
  $addOut=& git -c core.autocrlf=false -C $rp add -- $stagePaths 2>&1
  if($LASTEXITCODE -ne 0){throw "Exact git add failed in ${RepoName}: $($addOut -join ' ')"}
}
$staged=@(Invoke-Git $rp @('diff','--cached','--name-only') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$diff=Compare-Object -ReferenceObject @($stagePaths | Sort-Object) -DifferenceObject @($staged | Sort-Object)
if($diff){throw "Staged path set mismatch in ${RepoName}: $($diff | Out-String)"}
$nodeHelper=Join-Path $work 'verify_git_blob_bytes_20261005.cjs'
$nodeJson=& node $nodeHelper $rp 'INDEX' $stagePaths
if($LASTEXITCODE -ne 0){throw "Git index blob verification failed in $RepoName."}
$indexBlobs=[string]::Join([Environment]::NewLine,@($nodeJson)) | ConvertFrom-Json
foreach($expected in $expectedEntries) {
  $actual=$indexBlobs | Where-Object { $_.path -ceq $expected.path } | Select-Object -First 1
  if($null -eq $actual -or [int64]$actual.object_bytes -ne $expected.bytes -or $actual.object_sha256 -ne $expected.sha256 -or -not $actual.matches_worktree){throw "Staged Git object bytes mismatch: $($expected.path)"}
}
$commitArgs=@('-c','core.autocrlf=false','-c',('user.name='+$identityParts[0]),'-c',('user.email='+$identityParts[1]),'-C',$rp,'commit','-m',$Subject,'-m',$Body)
$commitOut=& git @commitArgs 2>&1
if($LASTEXITCODE -ne 0){throw "Commit failed in ${RepoName}: $($commitOut -join ' ')"}
$commit=((Invoke-Git $rp @('rev-parse','HEAD')) | Select-Object -Last 1).Trim()
$actualParent=((Invoke-Git $rp @('rev-parse','HEAD^')) | Select-Object -Last 1).Trim()
if($actualParent -ne $parent){throw "Unexpected commit parent in ${RepoName}: $actualParent"}
$commitBlobsJson=& node $nodeHelper $rp $commit $stagePaths
if($LASTEXITCODE -ne 0){throw "Committed Git blob verification failed in $RepoName."}
$commitBlobs=[string]::Join([Environment]::NewLine,@($commitBlobsJson)) | ConvertFrom-Json
foreach($expected in $expectedEntries) {
  $actual=$commitBlobs | Where-Object { $_.path -ceq $expected.path } | Select-Object -First 1
  if($null -eq $actual -or [int64]$actual.object_bytes -ne $expected.bytes -or $actual.object_sha256 -ne $expected.sha256){throw "Committed Git object bytes mismatch: $($expected.path)"}
}
$remoteBeforePush=((Invoke-Git $rp @('ls-remote','--heads','origin','backup/forge-work-20261003')) | Select-Object -Last 1).Trim()
if(($remoteBeforePush -split '\s+')[0] -ne $parent){throw "Remote head changed before push in $RepoName; commit kept local, no force push."}
$pushOut=& git -c core.autocrlf=false -C $rp push origin backup/forge-work-20261003 2>&1
if($LASTEXITCODE -ne 0){throw "Non-force push failed in ${RepoName}: $($pushOut -join ' ')"}
$remoteAfter=((Invoke-Git $rp @('ls-remote','--heads','origin','backup/forge-work-20261003')) | Select-Object -Last 1).Trim()
$remoteAfterHead=($remoteAfter -split '\s+')[0]
if($remoteAfterHead -ne $commit){throw "Post-push remote head does not match commit in ${RepoName}: $remoteAfterHead"}
$dirtyApproved=& git -C $rp status --porcelain -- $stagePaths 2>&1
if($LASTEXITCODE -ne 0 -or @($dirtyApproved).Count -gt 0){throw "Approved path set is not clean after push in $RepoName."}
$receipt=[ordered]@{
  schema='shardforge.git-backup-push-receipt.v1'
  repository=$RepoName
  branch='backup/forge-work-20261003'
  parent_commit=$parent
  commit=$commit
  commit_subject=$Subject
  remote_head_before=$parent
  remote_head_after=$remoteAfterHead
  copy_plan_sha256=$expectedManifestSha
  staged_path_count=$stagePaths.Count
  paths=$commitBlobs
  push_result=@($pushOut | ForEach-Object { "$_" })
  exact_approved_paths_clean_after_push=$true
}
$receiptPath=Join-Path $work ($RepoName+'_curated_evidence_push_receipt_20261005.json')
[IO.File]::WriteAllText($receiptPath,(ConvertTo-Json -InputObject $receipt -Depth 8)+[char]10,[Text.UTF8Encoding]::new($false))
[pscustomobject]@{repository=$RepoName; parent=$parent; commit=$commit; remote_head=$remoteAfterHead; staged_path_count=$stagePaths.Count; blob_count=$commitBlobs.Count; all_blobs_exact=$true; receipt_path=$receiptPath; receipt_sha256=(Get-FileSha $receiptPath); staged_paths=$stagePaths} | ConvertTo-Json -Depth 5