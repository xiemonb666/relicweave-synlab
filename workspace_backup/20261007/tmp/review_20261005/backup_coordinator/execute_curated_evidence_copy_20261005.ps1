$ErrorActionPreference='Stop'
$root=(Resolve-Path '.').Path
$work=Join-Path $root 'tmp/review_20261005/backup_coordinator'
$manifestPath=Join-Path $work 'curated_evidence_copy_plan_20261005.json'
$expectedManifestSha='fb2eff29c6205f728331132ffd7ec5c795049b8a35f944209c19c31f99431558'
$manifest=Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
function Get-FileSha([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower() }
function Get-ByteSha([byte[]]$Bytes) { $sha=[Security.Cryptography.SHA256]::Create(); try { ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-','').ToLower() } finally { $sha.Dispose() } }
function Invoke-Git([string]$RepoPath,[string[]]$GitArgs) { $out=& git -C $RepoPath @GitArgs 2>&1; if($LASTEXITCODE -ne 0){throw "git failed ($LASTEXITCODE): $($GitArgs -join ' '): $($out -join ' ')" }; return $out }
if ((Get-FileSha $manifestPath) -ne $expectedManifestSha) { throw 'Curated copy plan SHA mismatch; aborting.' }
$repoNames=@('pgfrag','vesselforge','relicweave-synlab')
$expectedHeads=@{pgfrag='bf15835cac97a2ba032ec1872c57e6e60cb1e977'; vesselforge='8da9b538e2588fe51418588cb6301c258cd5363f'; 'relicweave-synlab'='b1099e4c714baff56083570883b44fee45e110f9'}
$allCopies=@()
foreach($item in $manifest.items) {
  $src=Join-Path $root ($item.source_path -replace '/','\')
  $dst=Join-Path $root ($item.proposed_destination -replace '/','\')
  $bytes=(Get-Item -LiteralPath $src).Length
  $sha=Get-FileSha $src
  if ($bytes -ne [int64]$item.bytes -or $sha -ne $item.sha256.ToLower()) { throw "Approved plan source changed: $($item.source_path)" }
  if (Test-Path -LiteralPath $dst) { throw "Copy destination already exists; refusing overwrite: $($item.proposed_destination)" }
  $allCopies += [pscustomobject]@{repo=$item.repo; source_path=$item.source_path; destination=$item.proposed_destination; bytes=[int64]$bytes; sha256=$sha; category=$item.category; status=$item.source_status; notes=$item.notes}
}
$codeSpecs=@(
  [pscustomobject]@{path='synlab/qa/forge_chain_audit.py'; bytes=73028; sha256='3f84f824ca2dbc908303ae3c2b14f3ac3e1d8c88349238adf59ed747be48b5d7'; category='report_only_source'},
  [pscustomobject]@{path='tests/a12/qa/test_forge_chain_source_dispatch_20261005.py'; bytes=11038; sha256='4df2391f107616b38854cbedc13b18c6e864ff3a4d0eeb1cc5ef102021f716e4'; category='focused_tests'},
  [pscustomobject]@{path='docs/a12/chain_source_reader_dispatch_20261005.md'; bytes=3830; sha256='2480962d753b90700382e1477926271a69c63e6b94fffc07a0c90a50ea1eba58'; category='report_only_design'}
)
foreach($spec in $codeSpecs) {
  $src=Join-Path (Join-Path $root 'relicweave-synlab') ($spec.path -replace '/','\')
  $bytes=(Get-Item -LiteralPath $src).Length
  $sha=Get-FileSha $src
  if ($bytes -ne [int64]$spec.bytes -or $sha -ne $spec.sha256) { throw "Approved Syn source changed: $($spec.path)" }
}
$chainDir=Join-Path $root 'relicweave-synlab/tmp/review_20261005/chain_contract_review'
$chainSpecs=@(
  [pscustomobject]@{name='focused_pytest_20261005_receipt.json'; bytes=757; sha256='a0216bf2c468b916318ecf45c9b426b28d1d630bde3438847fc2034acced8858'; category='focused_pytest_receipt'},
  [pscustomobject]@{name='focused_pytest_20261005.junit.xml'; bytes=4128; sha256='bdba8730d155c6e120e613a0518ef6e8038e8b99b0ac4a8cf7dc7baba38077dc'; category='focused_junit'},
  [pscustomobject]@{name='focused_pytest_20261005.stdout.txt'; bytes=81; sha256='0861033bdc2d6203bd8178972703a811b101e61fc065ed32dfd1a4824ab482f0'; category='focused_stdout'},
  [pscustomobject]@{name='pretest_sha256_20261005.json'; bytes=3652; sha256='0507950d3150fd572fde67ccfb5002ca247dc9bc608ad02d7db574665714b643'; category='pretest_snapshot'},
  [pscustomobject]@{name='posttest_sha256_20261005.json'; bytes=3652; sha256='5566964f51ab0ce82d3c347eb33f393fd05804047b02150a92ed5acae3f5c159'; category='posttest_snapshot'}
)
$chainCopies=@()
foreach($spec in $chainSpecs) {
  $src=Join-Path $chainDir $spec.name
  $bytes=(Get-Item -LiteralPath $src).Length
  $sha=Get-FileSha $src
  if ($bytes -ne [int64]$spec.bytes -or $sha -ne $spec.sha256) { throw "Frozen Syn chain evidence changed: $($spec.name)" }
  $destRel="relicweave-synlab/docs/a12/evidence/20261005/chain_source_dispatch/$($spec.name)"
  $dst=Join-Path $root ($destRel -replace '/','\')
  if (Test-Path -LiteralPath $dst) { throw "Chain evidence destination exists; refusing overwrite: $destRel" }
  $chainCopies += [pscustomobject]@{repo='relicweave-synlab'; source_path="relicweave-synlab/tmp/review_20261005/chain_contract_review/$($spec.name)"; destination=$destRel; bytes=[int64]$bytes; sha256=$sha; category=$spec.category; status='root-reviewed; frozen source snapshot'; notes='Report-only source-dispatch validation evidence; not full-chain qualification.'}
}
$allCopies += $chainCopies
$attrsSpecs=@{
  pgfrag=[pscustomobject]@{repoPath=(Join-Path $root 'pgfrag'); repo='pgfrag'; rule='/docs/evidence/20261005/** -text'; indexRel='docs/evidence/20261005/backup_evidence_index_20261005.json'}
  vesselforge=[pscustomobject]@{repoPath=(Join-Path $root 'vesselforge'); repo='vesselforge'; rule='/docs/evidence/20261005/** -text'; indexRel='docs/evidence/20261005/backup_evidence_index_20261005.json'}
  'relicweave-synlab'=[pscustomobject]@{repoPath=(Join-Path $root 'relicweave-synlab'); repo='relicweave-synlab'; rule='/docs/a12/evidence/20261005/** -text'; indexRel='docs/a12/evidence/20261005/backup_evidence_index_20261005.json'}
}
$attrsBefore=@{}
$headsBefore=@{}
foreach($repo in $repoNames) {
  $rp=Join-Path $root $repo
  $branch=((Invoke-Git $rp @('branch','--show-current')) | Select-Object -Last 1).Trim()
  $head=((Invoke-Git $rp @('rev-parse','HEAD')) | Select-Object -Last 1).Trim()
  $remote=((Invoke-Git $rp @('ls-remote','--heads','origin','backup/forge-work-20261003')) | Select-Object -Last 1).Trim()
  $remoteHead=($remote -split '\s+')[0]
  if ($branch -ne 'backup/forge-work-20261003' -or $head -ne $expectedHeads[$repo] -or $remoteHead -ne $expectedHeads[$repo]) { throw "Branch/head changed for $repo; refusing to proceed." }
  $headsBefore[$repo]=$head
  $attrPath=Join-Path $rp '.gitattributes'
  $old=[IO.File]::ReadAllBytes($attrPath)
  $oldText=[Text.Encoding]::UTF8.GetString($old)
  $rule=$attrsSpecs[$repo].rule
  if ($oldText.Contains($rule)) { throw "Exact attributes rule already exists in $repo; refusing duplicate append." }
  $attrsBefore[$repo]=[pscustomobject]@{path=$attrPath; bytes=$old; size=$old.Length; sha256=(Get-ByteSha $old); rule=$rule}
  $indexPath=Join-Path $rp ($attrsSpecs[$repo].indexRel -replace '/','\')
  if (Test-Path -LiteralPath $indexPath) { throw "Index destination exists; refusing overwrite: $($attrsSpecs[$repo].indexRel)" }
}
foreach($copy in $allCopies) {
  $src=Join-Path $root ($copy.source_path -replace '/','\')
  $dst=Join-Path $root ($copy.destination -replace '/','\')
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
  [IO.File]::Copy($src,$dst,$false)
}
$attrAfter=@{}
foreach($repo in $repoNames) {
  $a=$attrsBefore[$repo]
  [byte[]]$old=$a.bytes
  $needsLf=($old.Length -gt 0 -and $old[$old.Length-1] -ne 10)
  $ruleBytes=[Text.Encoding]::ASCII.GetBytes($a.rule + [char]10)
  [byte[]]$prefixBytes=@()
  if($needsLf){[byte[]]$prefixBytes=@(10)}
  $combined=[byte[]]::new($old.Length+$prefixBytes.Length+$ruleBytes.Length)
  [Array]::Copy($old,0,$combined,0,$old.Length)
  if($prefixBytes.Length -gt 0){[Array]::Copy($prefixBytes,0,$combined,$old.Length,$prefixBytes.Length)}
  [Array]::Copy($ruleBytes,0,$combined,$old.Length+$prefixBytes.Length,$ruleBytes.Length)
  [IO.File]::WriteAllBytes($a.path,$combined)
  $check=[IO.File]::ReadAllBytes($a.path)
  $oldPrefix=[byte[]]::new($old.Length)
  [Array]::Copy($check,0,$oldPrefix,0,$old.Length)
  if((Get-ByteSha $oldPrefix) -ne $a.sha256){throw "Prior .gitattributes bytes changed in $repo."}
  $tailStart=$old.Length+$prefixBytes.Length
  $tail=[Text.Encoding]::ASCII.GetString($check,$tailStart,$ruleBytes.Length)
  if($tail -cne ($a.rule + [char]10)){throw "Attributes rule append mismatch in $repo."}
  $attrAfter[$repo]=[pscustomobject]@{path='.gitattributes'; old_bytes=$old.Length; old_sha256=$a.sha256; bytes=$check.Length; sha256=(Get-ByteSha $check); appended_rule=$a.rule}
}
foreach($copy in $allCopies) {
  $src=Join-Path $root ($copy.source_path -replace '/','\')
  $dst=Join-Path $root ($copy.destination -replace '/','\')
  $dstBytes=(Get-Item -LiteralPath $dst).Length
  $dstSha=Get-FileSha $dst
  if($dstBytes -ne [int64]$copy.bytes -or $dstSha -ne $copy.sha256 -or $dstSha -ne (Get-FileSha $src)){throw "Copied target mismatch: $($copy.destination)"}
}
$indexResults=@()
foreach($repo in $repoNames) {
  $entries=@()
  foreach($e in @($allCopies | Where-Object { $_.repo -eq $repo })) {
    $entries += [ordered]@{source_path=$e.source_path; destination=$e.destination; bytes=[int64]$e.bytes; sha256=$e.sha256; category=$e.category; source_status=$e.status; notes=$e.notes}
  }
  if($repo -eq 'relicweave-synlab') {
    foreach($spec in $codeSpecs) {
      $entries += [ordered]@{source_path="relicweave-synlab/$($spec.path)"; destination="relicweave-synlab/$($spec.path)"; bytes=[int64]$spec.bytes; sha256=$spec.sha256; category=$spec.category; source_status='root-reviewed; frozen source'; notes='Report-only source-dispatch audit; no whole-chain/physics qualification.'}
    }
  }
  $known=@($manifest.known_results_and_limits | Where-Object { $_.repo -eq $repo })
  $extraLimits=@()
  if($repo -eq 'relicweave-synlab') {
    $extraLimits=@(
      'Chain source-dispatch focused suite: 25 passed, 0 failed/errors/skipped; report-only source wiring, not full-chain qualification.',
      'Whole-chain state remains 30 gaps and 0 qualified; the main repository is unchanged.',
      'Document render review remains FAILED with clipping/overlap; source attribution remains UNKNOWN. The DOCX draft is withheld.'
    )
  }
  $idx=[ordered]@{
    schema='shardforge.backup-evidence-index.v1'
    repository=$repo
    branch='backup/forge-work-20261003'
    source_snapshot_commit=$headsBefore[$repo]
    remote_head_before=$headsBefore[$repo]
    copy_plan_sha256=$expectedManifestSha
    created_utc=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    entries=$entries
    attributes=$attrAfter[$repo]
    known_results_and_limits=$known
    additional_limits=$extraLimits
    note='Evidence copies are byte-identical to their pinned tmp sources; raw large/native data and active writer files are excluded.'
  }
  $json=ConvertTo-Json -InputObject $idx -Depth 16
  $indexPath=Join-Path (Join-Path $root $repo) ($attrsSpecs[$repo].indexRel -replace '/','\')
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $indexPath) | Out-Null
  [IO.File]::WriteAllText($indexPath,$json+[char]10,[Text.UTF8Encoding]::new($false))
  $indexResults += [pscustomobject]@{repo=$repo; path=$attrsSpecs[$repo].indexRel; bytes=(Get-Item -LiteralPath $indexPath).Length; sha256=(Get-FileSha $indexPath); listedEntries=$entries.Count; knownResultRows=$known.Count; additionalLimitRows=$extraLimits.Count}
}
[pscustomobject]@{
 manifest_sha256=$expectedManifestSha
 copy_count=$allCopies.Count
 copy_bytes=($allCopies | Measure-Object -Property bytes -Sum).Sum
 copy_verification='all source and target byte counts/SHA-256 match'
 copies_by_repo=($allCopies | Group-Object repo | ForEach-Object { [pscustomobject]@{repo=$_.Name; count=$_.Count; bytes=($_.Group | Measure-Object -Property bytes -Sum).Sum} })
 attributes=$attrAfter
 approved_syn_sources=$codeSpecs
 chain_evidence=$chainCopies
 indexes=$indexResults
 heads_before=$headsBefore
} | ConvertTo-Json -Depth 8