$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath('C:\Users\xiemo\Desktop\ShardForge')
$coord = [IO.Path]::GetFullPath((Join-Path $root 'tmp\review_20261005\backup_coordinator'))
$outPath = Join-Path $coord 'next_backup_candidates_20261005_v2.json'
if (Test-Path -LiteralPath $outPath) { throw 'Plan path already exists; refusing overwrite.' }

$items = New-Object 'System.Collections.Generic.List[object]'
function Add-PlanItem($repo, $source, $destination, $group, $kind) {
  $items.Add([PSCustomObject]@{repo=$repo; source_path=$source; destination_path=$destination; group=$group; operation=$kind})
}

# PG coupon frozen inputs and the small, exact run outputs.
$couponCases = @('free_evolution_coupon_20261005','free_evolution_coupon_dt_half_20261005')
$couponSources = @('fixed_case.toml','run_free_evolution_coupon.jl','run_once.ps1','source_freeze.toml','SOURCE_REVIEW.md')
$couponResults = @('run_attempt_01/launcher_receipt.json','run_attempt_01/native_stderr.log','run_attempt_01/native_stdout.log','run_attempt_01/results/energy_reaction_history.csv','run_attempt_01/results/point_reference.csv','run_attempt_01/results/point_state_layout.toml','run_attempt_01/results/summary.toml')
foreach ($case in $couponCases) {
  foreach ($name in $couponSources) {
    $src = ('pgfrag/experiments/' + $case + '/' + $name)
    Add-PlanItem 'pgfrag' $src ($src.Substring('pgfrag/'.Length)) 'coupon_frozen_source' 'track_exact_existing_path'
  }
  foreach ($name in $couponResults) {
    $src = ('pgfrag/experiments/' + $case + '/' + $name)
    Add-PlanItem 'pgfrag' $src ($src.Substring('pgfrag/'.Length)) 'coupon_small_run_evidence' 'track_exact_existing_path'
  }
}

# Independent arithmetic/source review artifacts for the baseline coupon.
$reviewRoot = 'pgfrag/tmp/review_20261005/free_coupon_independent_review'
$reviewNames = @('independent_review.py','independent_review.md','REVIEW_METHOD.md','audit_output/independent_review.json','audit_output/coupon_diagnostics.png','audit_output/coupon_points_3d.png')
foreach ($name in $reviewNames) {
  Add-PlanItem 'pgfrag' ($reviewRoot + '/' + $name) ('docs/evidence/20261005/free_evolution_coupon_independent_review/' + $name) 'coupon_independent_review_evidence' 'copy_exact_to_docs_evidence'
}

# Accepted native transport source and its exact focused-test receipt.
$transportSourceRoot = 'pgfrag/experiments/material_visibility_native_bridge_20261005'
foreach ($name in @('native_mask_transport.py','test_native_mask_transport.py','TRANSPORT.md')) {
  $src = ($transportSourceRoot + '/' + $name)
  Add-PlanItem 'pgfrag' $src ($src.Substring('pgfrag/'.Length)) 'native_transport_accepted_source' 'track_exact_existing_path'
}
$transportEvidenceRoot = 'pgfrag/tmp/review_20261005/native_transport_tests'
foreach ($name in @('run_manifest.json','native_transport.junit.xml','native_transport.stdout.txt','native_transport.stderr.txt','distinct_testcase_ids.txt','exit_code.txt')) {
  Add-PlanItem 'pgfrag' ($transportEvidenceRoot + '/' + $name) ('docs/evidence/20261005/native_transport/' + $name) 'native_transport_11_testcase_evidence' 'copy_exact_to_docs_evidence'
}

# Independently verified lossless split archives for the two large point-state inputs.
Add-PlanItem 'pgfrag' 'tmp/review_20261005/backup_coordinator/native_coupon_point_state_baseline_20261005.zip' 'docs/evidence/20261005/free_evolution_coupon_native_states/native_coupon_point_state_baseline_20261005.zip' 'coupon_native_state_archive' 'copy_exact_to_docs_evidence'
Add-PlanItem 'pgfrag' 'tmp/review_20261005/backup_coordinator/native_coupon_point_state_dt_half_20261005.zip' 'docs/evidence/20261005/free_evolution_coupon_native_states/native_coupon_point_state_dt_half_20261005.zip' 'coupon_native_state_archive' 'copy_exact_to_docs_evidence'

# Accepted VF single-inner-span math experiment and the exact frozen v2 dependencies.
$vfNewRoot = 'vesselforge/experiments/smooth_surface_single_inner_fairing_20261005'
foreach ($name in @('single_inner_fairing_math.py','fixed_case_beaker_single_inner_fairing_v1.json','plot_single_inner_fairing_section.py','DESIGN_NOTE.md')) {
  $src = ($vfNewRoot + '/' + $name)
  Add-PlanItem 'vesselforge' $src ($src.Substring('vesselforge/'.Length)) 'single_inner_v3_accepted_source' 'track_exact_existing_path'
}
$vfParentRoot = 'vesselforge/experiments/smooth_surface_coupled_design_20261005'
foreach ($name in @('coupled_profile_math.py','fixed_case_beaker_coupled_v2.json')) {
  $src = ($vfParentRoot + '/' + $name)
  Add-PlanItem 'vesselforge' $src ($src.Substring('vesselforge/'.Length)) 'single_inner_v3_frozen_parent_dependency' 'track_exact_existing_path'
}
$vfEvidenceRoot = 'tmp/review_20261005/smooth_single_inner_fairing'
$vfEvidenceNames = @(
  'FROZEN_SHA256.txt',
  'REVIEW_AND_EXECUTION_BUDGET.md',
  'frozen_run/RESULTS.md',
  'frozen_run/RUN_OUTPUT_SHA256.txt',
  'frozen_run/math_diagnostics.json',
  'frozen_run/diagnostic_run_record.json',
  'frozen_run/diagnostic.stdout.txt',
  'frozen_run/diagnostic.stderr.txt',
  'frozen_run/plot_run_record.json',
  'frozen_run/plot.stdout.txt',
  'frozen_run/plot.stderr.txt',
  'frozen_run/plot/single_inner_fairing_profile_rz_arrays.json',
  'frozen_run/plot/single_inner_fairing_profile_rz.png'
)
foreach ($name in $vfEvidenceNames) {
  Add-PlanItem 'vesselforge' ($vfEvidenceRoot + '/' + $name) ('docs/evidence/20261005/single_inner_fairing_v3/' + [IO.Path]::GetFileName($name)) 'single_inner_v3_curated_run_evidence' 'copy_exact_to_docs_evidence'
}

# Accepted Syn heightgraph certificate source, focused test, and narrow review/test receipts.
$synSources = @(
  'relicweave-synlab/synlab/degrade/heightgraph_certificate.py',
  'relicweave-synlab/tests/a12/degrade/test_heightgraph_certificate_20261005.py'
)
foreach ($src in $synSources) { Add-PlanItem 'relicweave-synlab' $src ($src.Substring('relicweave-synlab/'.Length)) 'heightgraph_accepted_source' 'track_exact_existing_path' }
$synEvidenceRoot = 'relicweave-synlab/tmp/review_20261005/degradation_resume'
$synEvidenceNames = @(
  'focused_pytest_review2.junit.xml',
  'focused_pytest_review2.rc.txt',
  'focused_pytest_review2.stdout.txt',
  'focused_pytest_review2.stderr.txt',
  'report.md',
  'proposal.json',
  'source-review-plan.md',
  'source-freeze-review2.sha256'
)
foreach ($name in $synEvidenceNames) {
  Add-PlanItem 'relicweave-synlab' ($synEvidenceRoot + '/' + $name) ('docs/a12/evidence/20261005/heightgraph_certificate/' + $name) 'heightgraph_12_testcase_review_evidence' 'copy_exact_to_docs_evidence'
}

# Pins authored in the existing freeze/test manifests, used only for read-only validation.
$pinMap = @{}
$pinCheckList = New-Object 'System.Collections.Generic.List[object]'
foreach ($case in $couponCases) {
  $freezePath = Join-Path $root ('pgfrag/experiments/' + $case + '/source_freeze.toml')
  $freezeRaw = Get-Content -LiteralPath $freezePath -Raw
  $blocks = $freezeRaw -split '(?m)(?=^\[\[pins\]\])'
  foreach ($block in $blocks) {
    $mPath = [regex]::Match($block, '(?m)^path\s*=\s*"([^"]+)"\s*$')
    $mBytes = [regex]::Match($block, '(?m)^bytes\s*=\s*(\d+)\s*$')
    $mSha = [regex]::Match($block, '(?m)^sha256\s*=\s*"([0-9a-f]{64})"\s*$')
    if ($mPath.Success -and $mBytes.Success -and $mSha.Success -and $mPath.Groups[1].Value -match ('^pgfrag/experiments/' + [regex]::Escape($case) + '/')) {
      $pinMap[$mPath.Groups[1].Value] = [PSCustomObject]@{bytes=[long]$mBytes.Groups[1].Value;sha256=$mSha.Groups[1].Value;freeze_path=('pgfrag/experiments/' + $case + '/source_freeze.toml')}
    }
  }
}
$transportManifest = Get-Content -LiteralPath (Join-Path $root 'pgfrag/tmp/review_20261005/native_transport_tests/run_manifest.json') -Raw | ConvertFrom-Json
$pinMap['pgfrag/experiments/material_visibility_native_bridge_20261005/native_mask_transport.py'] = [PSCustomObject]@{bytes=$null;sha256=$transportManifest.pre_sha256.native_mask_transport_py;freeze_path='pgfrag/tmp/review_20261005/native_transport_tests/run_manifest.json'}
$pinMap['pgfrag/experiments/material_visibility_native_bridge_20261005/test_native_mask_transport.py'] = [PSCustomObject]@{bytes=$null;sha256=$transportManifest.pre_sha256.test_native_mask_transport_py;freeze_path='pgfrag/tmp/review_20261005/native_transport_tests/run_manifest.json'}
$pinMap['pgfrag/experiments/material_visibility_native_bridge_20261005/TRANSPORT.md'] = [PSCustomObject]@{bytes=$null;sha256=$transportManifest.pre_sha256.transport_md;freeze_path='pgfrag/tmp/review_20261005/native_transport_tests/run_manifest.json'}

$vfFreezePath = Join-Path $root 'tmp/review_20261005/smooth_single_inner_fairing/FROZEN_SHA256.txt'
foreach ($line in (Get-Content -LiteralPath $vfFreezePath)) {
  $m = [regex]::Match($line, '^([0-9a-f]{64})\s+(.+?)\s*$')
  if ($m.Success) { $pinMap[$m.Groups[2].Value] = [PSCustomObject]@{bytes=$null;sha256=$m.Groups[1].Value;freeze_path='tmp/review_20261005/smooth_single_inner_fairing/FROZEN_SHA256.txt'} }
}
$synFreezePath = Join-Path $root 'relicweave-synlab/tmp/review_20261005/degradation_resume/source-freeze-review2.sha256'
foreach ($line in (Get-Content -LiteralPath $synFreezePath)) {
  $m = [regex]::Match($line, '^([0-9a-f]{64})\s+(.+?)\s*$')
  if ($m.Success) { $pinMap[('relicweave-synlab/' + $m.Groups[2].Value)] = [PSCustomObject]@{bytes=$null;sha256=$m.Groups[1].Value;freeze_path='relicweave-synlab/tmp/review_20261005/degradation_resume/source-freeze-review2.sha256'} }
}

# Verify all candidate source bytes, determine destination state, attributes and no-write Git object IDs.
$repoNames = @('pgfrag','vesselforge','relicweave-synlab')
$repoStatus = @()
foreach ($repo in $repoNames) {
  $repoFull = Join-Path $root $repo
  $branch = (& git -C $repoFull branch --show-current 2>$null | Out-String).Trim()
  $head = (& git -C $repoFull rev-parse HEAD 2>$null | Out-String).Trim()
  $remoteLine = & git -C $repoFull ls-remote --heads origin backup/forge-work-20261003 2>$null
  $remoteHead = ''
  if ($remoteLine -match '^([0-9a-f]{40,64})\s+refs/heads/backup/forge-work-20261003$') { $remoteHead = $Matches[1] }
  $staged = @(& git -C $repoFull diff --cached --name-only 2>$null)
  $repoStatus += [PSCustomObject]@{repo=$repo;branch=$branch;head=$head;remote_backup_branch_head=$remoteHead;staged_paths_before_plan=$staged.Count}
}

$resultItems = New-Object 'System.Collections.Generic.List[object]'
foreach ($item in $items) {
  $repoFull = Join-Path $root $item.repo
  $sourceFull = [IO.Path]::GetFullPath((Join-Path $root ($item.source_path.Replace('/', '\'))))
  if (-not (Test-Path -LiteralPath $sourceFull -PathType Leaf)) { throw ('Candidate source missing: ' + $item.source_path) }
  $sourceInfo = Get-Item -LiteralPath $sourceFull
  $sourceSHA = (Get-FileHash -LiteralPath $sourceFull -Algorithm SHA256).Hash.ToLowerInvariant()
  $pin = $pinMap[$item.source_path]
  $pinMatch = $null
  $pinExpectedSHA = $null
  $pinExpectedBytes = $null
  $pinPath = $null
  if ($null -ne $pin) {
    $pinExpectedSHA = $pin.sha256
    $pinExpectedBytes = $pin.bytes
    $pinPath = $pin.freeze_path
    $pinMatch = ($sourceSHA -eq $pin.sha256 -and ($null -eq $pin.bytes -or $sourceInfo.Length -eq $pin.bytes))
    $pinCheckList.Add([PSCustomObject]@{source_path=$item.source_path;freeze_path=$pin.freeze_path;expected_bytes=$pin.bytes;actual_bytes=$sourceInfo.Length;expected_sha256=$pin.sha256;actual_sha256=$sourceSHA;match=$pinMatch})
  }
  $destFull = Join-Path $repoFull ($item.destination_path.Replace('/', '\'))
  $destExists = Test-Path -LiteralPath $destFull -PathType Leaf
  $destSHA = $null
  $destBytes = $null
  if ($destExists) {
    $destInfo = Get-Item -LiteralPath $destFull
    $destBytes = $destInfo.Length
    $destSHA = (Get-FileHash -LiteralPath $destFull -Algorithm SHA256).Hash.ToLowerInvariant()
  }
  $statusText = (& git -C $repoFull status --porcelain=v1 --untracked-files=all -- $item.destination_path 2>$null | Out-String).Trim()
  $trackedTest = & git -C $repoFull ls-files --error-unmatch -- $item.destination_path 2>$null
  $isTracked = ($LASTEXITCODE -eq 0)
  $attrText = (& git -C $repoFull check-attr --all -- $item.destination_path 2>$null | Out-String).Trim()
  $gitBlob = (& git -C $repoFull -c core.autocrlf=false hash-object ('--path=' + $item.destination_path) -- $sourceFull 2>$null | Out-String).Trim()
  $gitBlobExit = $LASTEXITCODE
  if ($gitBlobExit -ne 0) { $gitBlob = 'ERROR' }
  $resultItems.Add([PSCustomObject]@{
    repo=$item.repo
    group=$item.group
    operation=$item.operation
    source_path=$item.source_path
    destination_path=$item.destination_path
    source_bytes=$sourceInfo.Length
    source_sha256=$sourceSHA
    destination_exists=$destExists
    destination_bytes=$destBytes
    destination_sha256=$destSHA
    destination_matches_source=($destExists -and $destBytes -eq $sourceInfo.Length -and $destSHA -eq $sourceSHA)
    destination_tracked=$isTracked
    destination_git_status=$statusText
    destination_attributes=$attrText
    predicted_git_blob_oid_no_write=$gitBlob
    freeze_source_path=$pinPath
    freeze_expected_bytes=$pinExpectedBytes
    freeze_expected_sha256=$pinExpectedSHA
    freeze_pin_match=$pinMatch
  })
}

$couponFreezeStatus = @()
foreach ($case in $couponCases) {
  $freezePath = ('pgfrag/experiments/' + $case + '/source_freeze.toml')
  $raw = Get-Content -LiteralPath (Join-Path $root ($freezePath.Replace('/', '\'))) -Raw
  $runStatusMatch = [regex]::Match($raw, '(?m)^run_status\s*=\s*"([^"]+)"\s*$')
  $couponFreezeStatus += [PSCustomObject]@{freeze_path=$freezePath;freeze_status='FROZEN_SOURCE_ONLY';historical_run_status=$runStatusMatch.Groups[1].Value;note='Source freeze remains as historical pre-run record; run outputs are listed separately and the freeze is not edited.'}
}

$zipReceiptPaths = @(
  'tmp/review_20261005/backup_coordinator/native_coupon_point_state_baseline_20261005.receipt.json',
  'tmp/review_20261005/backup_coordinator/native_coupon_point_state_dt_half_20261005.receipt.json',
  'tmp/review_20261005/backup_coordinator/native_coupon_point_state_zip_receipt_20261005.json'
)
$zipReceipts = @()
foreach ($path in $zipReceiptPaths) {
  $full = Join-Path $root ($path.Replace('/', '\'))
  $value = Get-Content -LiteralPath $full -Raw | ConvertFrom-Json
  $zipReceipts += [PSCustomObject]@{receipt_path=$path;receipt_sha256=(Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant();receipt_bytes=(Get-Item -LiteralPath $full).Length;receipt=$value}
}

$excludedInputs = @(
  [PSCustomObject]@{path='pgfrag/experiments/free_evolution_coupon_20261005/run_attempt_01/results/point_state_history.f64le';bytes=37044000;sha256='0f436e4d8cabd29f3f634334e2d1e00e920be098cafaea8a1e0a9df2b221be77';handling='preserved inside baseline ZIP archive; do not stage as loose file'},
  [PSCustomObject]@{path='pgfrag/experiments/free_evolution_coupon_dt_half_20261005/run_attempt_01/results/point_state_history.f64le';bytes=73332000;sha256='674a8b00ba433bdca840384a6e6cd9437fe78fbbdfeabc0293151322170e367c';handling='preserved inside dt-half ZIP archive; do not stage as loose file'}
)

$repoSummary = @()
foreach ($repo in $repoNames) {
  $selected = @($resultItems | Where-Object { $_.repo -eq $repo })
  $inPlace = @($selected | Where-Object { $_.operation -eq 'track_exact_existing_path' })
  $copies = @($selected | Where-Object { $_.operation -eq 'copy_exact_to_docs_evidence' })
  $repoSummary += [PSCustomObject]@{repo=$repo;candidate_file_count=$selected.Count;in_place_source_count=$inPlace.Count;evidence_copy_count=$copies.Count;evidence_copy_targets_already_present_same_bytes=@($copies | Where-Object {$_.destination_matches_source}).Count;evidence_copy_targets_present_with_conflict=@($copies | Where-Object {$_.destination_exists -and -not $_.destination_matches_source}).Count;total_source_bytes=($selected | Measure-Object -Property source_bytes -Sum).Sum;freeze_pins_checked=@($pinCheckList | Where-Object { $_.source_path -like ($repo + '/*') }).Count}
}

$plan = [ordered]@{}
$plan['schema'] = 'luna-backup-candidate-plan.v1'
$plan['created_utc'] = [DateTime]::UtcNow.ToString('o')
$plan['status'] = 'awaiting_root_exact_list_approval'
$plan['git_actions_performed'] = $false
$plan['repo_heads'] = @($repoStatus)
$plan['repo_summaries'] = @($repoSummary)
$plan['candidate_items'] = $resultItems.ToArray()
$plan['freeze_pin_checks'] = $pinCheckList.ToArray()
$plan['coupon_source_freeze_status'] = @($couponFreezeStatus)
$plan['zip_preparation_receipts'] = @($zipReceipts)
$plan['raw_native_state_inputs_not_staged_loose'] = @($excludedInputs)
$plan['rules'] = @(
    'No stage, commit, push, branch move, config change, or source copy has been performed for this candidate plan.',
    'On later approval, use only the exact per-repository destination paths listed here; commit/push separately without force to backup/forge-work-20261003.',
    'Use per-call -c core.autocrlf=false; do not change local or global Git configuration.',
    'Current docs/evidence paths are expected to inherit the repository existing -text rule; no .gitattributes edit is proposed.',
    'Each source/destination byte count and SHA-256 is recorded; predicted Git blob IDs were computed read-only without -w.',
    'Do not stage any parent directory recursively; coupon run_attempt_01.claim and all unnamed experiment files remain excluded.',
    'Native transport reports 11 distinct focused testcases (JUnit tests attribute 20), serialization/declared-ledger only; native application remains unverified.',
    'Coupon outputs and ZIPs are diagnostic run evidence only; the timestep comparison is not convergence or physics/fracture qualification.',
    'Heightgraph evidence records 12 focused tests; broader geometry/physics/observation qualification remains unknown.',
    'Single-inner v3 is a pure mathematical section result; no CAD/OCC/STEP run, whole-section self-intersection proof, or global normal-wall qualification is claimed.'
  )
$json = $plan | ConvertTo-Json -Depth 12
[IO.File]::WriteAllText($outPath, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
Get-Content -LiteralPath $outPath -Raw
