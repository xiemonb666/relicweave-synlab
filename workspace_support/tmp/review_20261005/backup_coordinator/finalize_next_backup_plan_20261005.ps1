$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath('C:\Users\xiemo\Desktop\ShardForge')
$coord = [IO.Path]::GetFullPath((Join-Path $root 'tmp\review_20261005\backup_coordinator'))
$inputPath = Join-Path $coord 'next_backup_candidates_20261005_v2.json'
$outputPath = Join-Path $coord 'next_backup_candidates_20261005_final.json'
if (Test-Path -LiteralPath $outputPath) { throw 'Final plan path already exists; refusing overwrite.' }
$plan = Get-Content -LiteralPath $inputPath -Raw | ConvertFrom-Json
$byteChecks = New-Object 'System.Collections.Generic.List[object]'
foreach ($item in $plan.candidate_items) {
  $repoFull = Join-Path $root $item.repo
  $sourceFull = [IO.Path]::GetFullPath((Join-Path $root ($item.source_path.Replace('/', '\'))))
  $info = Get-Item -LiteralPath $sourceFull
  $sha = (Get-FileHash -LiteralPath $sourceFull -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($info.Length -ne $item.source_bytes -or $sha -ne $item.source_sha256) { throw ('Candidate source changed after manifest generation: ' + $item.source_path) }
  $rawBlob = (& git -C $repoFull -c core.autocrlf=false hash-object --no-filters -- $sourceFull 2>$null | Out-String).Trim()
  $same = ($rawBlob -eq $item.predicted_git_blob_oid_no_write)
  Add-Member -InputObject $item -NotePropertyName git_raw_blob_oid_no_filters -NotePropertyValue $rawBlob -Force
  Add-Member -InputObject $item -NotePropertyName git_path_clean_preserves_raw_bytes -NotePropertyValue $same -Force
  $byteChecks.Add([PSCustomObject]@{repo=$item.repo;destination_path=$item.destination_path;raw_blob_oid=$rawBlob;path_blob_oid=$item.predicted_git_blob_oid_no_write;raw_bytes_preserved=$same})
}
$plan | Add-Member -NotePropertyName attribute_rules -NotePropertyValue @(
  [PSCustomObject]@{repo='pgfrag';path='/docs/evidence/20261005/**';rule='-text';existing=$true;planned_change='none'},
  [PSCustomObject]@{repo='vesselforge';path='/docs/evidence/20261005/**';rule='-text';existing=$true;planned_change='none'},
  [PSCustomObject]@{repo='relicweave-synlab';path='/docs/a12/evidence/20261005/**';rule='-text';existing=$true;planned_change='none'}
) -Force
$plan | Add-Member -NotePropertyName git_byte_preservation_check -NotePropertyValue ([PSCustomObject]@{
  command='git -c core.autocrlf=false hash-object --path=<destination> <source> compared with --no-filters hash-object';
  candidate_count=$byteChecks.Count
  matching_raw_payload_count=@($byteChecks | Where-Object { $_.raw_bytes_preserved }).Count
  mismatches=@($byteChecks | Where-Object { -not $_.raw_bytes_preserved })
  no_object_writes_performed=$true
}) -Force
$plan | Add-Member -NotePropertyName explicit_scope_exclusions -NotePropertyValue @(
  'PG active free-fracture pilot, volume ingress, native initial-bond policy, other visibility bridge files, and all unnamed run scratch.',
  'VF global-mesh work, native CAD adapter, CAD/OCC/STEP outputs, ornament refinement, unrelated coupled-design artifacts, and active writers.',
  'Syn active heightgraph extensions beyond the two accepted source files, chain/certifier in progress, and unrelated A12 material.',
  'The external DOCX and all temporary/runtime/cache/private or unreviewed files.'
) -Force
$plan | Add-Member -NotePropertyName intended_future_git_flow -NotePropertyValue 'After root approves the exact manifest, rehash only approved entries, copy only approved evidence files to the listed docs targets, stage exact paths per repo, verify index blob payloads, then make separate commits and non-force pushes.' -Force
$json = $plan | ConvertTo-Json -Depth 14
[IO.File]::WriteAllText($outputPath, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
$outInfo = Get-Item -LiteralPath $outputPath
$outSHA = (Get-FileHash -LiteralPath $outputPath -Algorithm SHA256).Hash.ToLowerInvariant()
[PSCustomObject]@{
  path='tmp/review_20261005/backup_coordinator/next_backup_candidates_20261005_final.json'
  bytes=$outInfo.Length
  sha256=$outSHA
  candidate_count=$plan.candidate_items.Count
  pin_failures=@($plan.freeze_pin_checks | Where-Object { -not $_.match }).Count
  raw_git_blob_mismatches=@($byteChecks | Where-Object { -not $_.raw_bytes_preserved }).Count
  destination_conflicts=@($plan.candidate_items | Where-Object { $_.destination_exists -and -not $_.destination_matches_source }).Count
  attribute_rules=$plan.attribute_rules
  repo_summaries=$plan.repo_summaries
} | ConvertTo-Json -Depth 8
