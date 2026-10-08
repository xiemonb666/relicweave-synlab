$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath('C:\Users\xiemo\Desktop\ShardForge')
$coord = [IO.Path]::GetFullPath((Join-Path $root 'tmp\review_20261005\backup_coordinator'))
$planRel = 'tmp/review_20261005/backup_coordinator/next_backup_candidates_20261005_final.json'
$planPath = Join-Path $root ($planRel.Replace('/', '\'))
$expectedPlanSHA = '5404c9e1ae3b2eb12427954d8693e0819dfd57208d5a68c302632cd3e3bc8c59'
$branchName = 'backup/forge-work-20261003'
$aggregatePath = Join-Path $coord 'next_backup_execution_receipt_20261005.json'
$preflightPath = Join-Path $coord 'next_backup_preflight_receipt_20261005.json'
if (Test-Path -LiteralPath $aggregatePath) { throw 'Aggregate receipt exists; refusing duplicate execution.' }
if (Test-Path -LiteralPath $preflightPath) { throw 'Preflight receipt exists; refusing duplicate execution.' }

$planSHA = (Get-FileHash -LiteralPath $planPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($planSHA -ne $expectedPlanSHA) { throw 'Approved candidate plan SHA-256 does not match.' }
$plan = Get-Content -LiteralPath $planPath -Raw | ConvertFrom-Json
if ($plan.status -ne 'awaiting_root_exact_list_approval' -or $plan.git_actions_performed -ne $false -or $plan.candidate_items.Count -ne 70) { throw 'Approved plan schema/status/count mismatch.' }

$repoIdentity = @{
  'pgfrag' = [PSCustomObject]@{name='PGFrag Maintainer';email='pgfrag@local';subject='backup: preserve coupon diagnostics and native transport';body='Preserve frozen baseline/dt-half coupon runs and point-state archives, independent arithmetic review, and accepted native-mask transport evidence (11 distinct focused testcases). These diagnostics do not establish timestep convergence, physics/fracture qualification, or native application.'}
  'vesselforge' = [PSCustomObject]@{name='A12 SynLab';email='synlab@local';subject='backup: preserve single-inner fairing math diagnostic';body='Preserve the frozen single-inner-span pure-math inputs, required coupled-v2 parent dependencies, and diagnostic/plot evidence. This does not establish CAD/OCC/STEP validation, whole-section self-intersection, or global normal-wall qualification.'}
  'relicweave-synlab' = [PSCustomObject]@{name='A12 SynLab';email='synlab@local';subject='backup: preserve heightgraph certificate focused review';body='Preserve the accepted heightgraph certificate source/test and 12 focused test/review evidence. Broader geometry, physics, observation, and label qualification remain unverified.'}
}
$expectedCounts = @{'pgfrag'=41;'vesselforge'=19;'relicweave-synlab'=10}
$preflightRepos = New-Object 'System.Collections.Generic.List[object]'
$preflightItems = New-Object 'System.Collections.Generic.List[object]'
$preflightErrors = New-Object 'System.Collections.Generic.List[string]'

function Invoke-GitCapture([string]$repoFull, [string[]]$GitArguments) {
  $rawOutput = & git -C $repoFull @GitArguments 2>&1
  $rc = $LASTEXITCODE
  $cleanOutput = @($rawOutput | ForEach-Object { $_.ToString() })
  $safeOutput = @($cleanOutput | ForEach-Object { $_ -replace 'https?://[^/@\s:]+:[^/@\s]+@', 'https://[redacted]@' })
  [PSCustomObject]@{argv=(@('git','-C',$repoFull) + $GitArguments);exit_code=$rc;output=$safeOutput}
}

function Get-RemoteBranchHead([string]$repoFull, [string]$branch) {
  $query = Invoke-GitCapture $repoFull @('ls-remote','--heads','origin',$branch)
  if ($query.exit_code -ne 0) { return [PSCustomObject]@{head=$null;exit_code=$query.exit_code;argv=$query.argv} }
  $head = $null
  foreach ($line in $query.output) {
    $m = [regex]::Match($line, '^([0-9a-f]{40,64})\s+refs/heads/' + [regex]::Escape($branch) + '$')
    if ($m.Success) { $head = $m.Groups[1].Value }
  }
  [PSCustomObject]@{head=$head;exit_code=$query.exit_code;argv=$query.argv}
}

function Get-BlobContentDigest([string]$repoFull, [string]$objectId) {
  $psi = [Diagnostics.ProcessStartInfo]::new()
  $psi.FileName = 'git'
  $psi.UseShellExecute = $false
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  foreach ($arg in @('-C',$repoFull,'cat-file','blob',$objectId)) { $psi.ArgumentList.Add($arg) }
  $proc = [Diagnostics.Process]::new()
  $proc.StartInfo = $psi
  [void]$proc.Start()
  $digest = [Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
  $buffer = New-Object byte[] (1024 * 1024)
  [long]$count = 0
  $stream = $proc.StandardOutput.BaseStream
  while (($n = $stream.Read($buffer,0,$buffer.Length)) -gt 0) {
    $digest.AppendData($buffer,0,$n)
    $count += $n
  }
  $stderr = $proc.StandardError.ReadToEnd()
  $proc.WaitForExit()
  $sha = [Convert]::ToHexString($digest.GetHashAndReset()).ToLowerInvariant()
  $digest.Dispose()
  [PSCustomObject]@{argv=@('git','-C',$repoFull,'cat-file','blob',$objectId);exit_code=$proc.ExitCode;bytes=$count;sha256=$sha;stderr=$stderr}
}

function Get-CurrentHead([string]$repoFull) {
  $r = Invoke-GitCapture $repoFull @('rev-parse','HEAD')
  if ($r.exit_code -ne 0 -or $r.output.Count -eq 0) { return $null }
  return $r.output[0].Trim()
}

function Get-CurrentBranch([string]$repoFull) {
  $r = Invoke-GitCapture $repoFull @('branch','--show-current')
  if ($r.exit_code -ne 0 -or $r.output.Count -eq 0) { return $null }
  return $r.output[0].Trim()
}

function Get-StagedPaths([string]$repoFull) {
  $r = Invoke-GitCapture $repoFull @('diff','--cached','--name-only')
  if ($r.exit_code -ne 0) { throw ('Could not inspect index: ' + $repoFull) }
  @($r.output | Where-Object { $_ -ne '' } | Sort-Object -Unique)
}

function Save-Json([string]$path, $value) {
  $json = $value | ConvertTo-Json -Depth 16
  [IO.File]::WriteAllText($path, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
}

# Global preflight: verify all three local/remote heads, clean indexes, frozen pins and every exact input before copying anything.
foreach ($repoHead in $plan.repo_heads) {
  $repo = $repoHead.repo
  $repoFull = Join-Path $root $repo
  $localHead = Get-CurrentHead $repoFull
  $branch = Get-CurrentBranch $repoFull
  $remote = Get-RemoteBranchHead $repoFull $branchName
  $staged = Get-StagedPaths $repoFull
  $expectedIdentity = $repoIdentity[$repo]
  $lastIdentityResult = Invoke-GitCapture $repoFull @('log','-1','--format=%an%x09%ae%x09%cn%x09%ce')
  $lastIdentity = if ($lastIdentityResult.output.Count -gt 0) { $lastIdentityResult.output[0].Trim() } else { '' }
  $expectedIdentityLine = ($expectedIdentity.name + "`t" + $expectedIdentity.email + "`t" + $expectedIdentity.name + "`t" + $expectedIdentity.email)
  $repoCheck = [PSCustomObject]@{
    repo=$repo
    branch=$branch
    expected_branch=$branchName
    local_head=$localHead
    expected_local_head=$repoHead.head
    remote_head=$remote.head
    expected_remote_head=$repoHead.remote_backup_branch_head
    remote_query_argv=$remote.argv
    remote_query_exit_code=$remote.exit_code
    staged_paths=$staged
    latest_commit_identity=$lastIdentity
    approved_per_call_identity=($expectedIdentity.name + ' <' + $expectedIdentity.email + '>')
    latest_identity_matches_approved=($lastIdentity -eq $expectedIdentityLine)
  }
  $preflightRepos.Add($repoCheck)
  if ($branch -ne $branchName) { $preflightErrors.Add($repo + ': current branch changed') }
  if ($localHead -ne $repoHead.head) { $preflightErrors.Add($repo + ': local HEAD changed') }
  if ($remote.exit_code -ne 0 -or $remote.head -ne $repoHead.remote_backup_branch_head -or $remote.head -ne $localHead) { $preflightErrors.Add($repo + ': remote branch head changed or could not be verified') }
  if ($staged.Count -ne 0) { $preflightErrors.Add($repo + ': index is not clean; refusing to mix staged paths') }
  if (-not $repoCheck.latest_identity_matches_approved) { $preflightErrors.Add($repo + ': existing maintainer identity differs from authorized per-call identity') }
  $itemsForRepo = @($plan.candidate_items | Where-Object { $_.repo -eq $repo })
  if ($itemsForRepo.Count -ne $expectedCounts[$repo]) { $preflightErrors.Add($repo + ': approved candidate count changed') }
}

foreach ($item in $plan.candidate_items) {
  $repoFull = Join-Path $root $item.repo
  $sourceFull = [IO.Path]::GetFullPath((Join-Path $root ($item.source_path.Replace('/', '\'))))
  $sourceExists = Test-Path -LiteralPath $sourceFull -PathType Leaf
  if (-not $sourceExists) {
    $preflightErrors.Add($item.repo + ': missing source ' + $item.source_path)
    continue
  }
  $sourceInfo = Get-Item -LiteralPath $sourceFull
  $sourceSHA = (Get-FileHash -LiteralPath $sourceFull -Algorithm SHA256).Hash.ToLowerInvariant()
  $sourceMatch = ($sourceInfo.Length -eq $item.source_bytes -and $sourceSHA -eq $item.source_sha256)
  if (-not $sourceMatch) { $preflightErrors.Add($item.repo + ': source byte/SHA changed ' + $item.source_path) }
  $destinationFull = [IO.Path]::GetFullPath((Join-Path $repoFull ($item.destination_path.Replace('/', '\'))))
  $destinationExists = Test-Path -LiteralPath $destinationFull -PathType Leaf
  $destinationSHA = $null
  $destinationBytes = $null
  if ($destinationExists) {
    $destinationInfo = Get-Item -LiteralPath $destinationFull
    $destinationBytes = $destinationInfo.Length
    $destinationSHA = (Get-FileHash -LiteralPath $destinationFull -Algorithm SHA256).Hash.ToLowerInvariant()
  }
  if ($item.operation -eq 'track_exact_existing_path') {
    if (-not $destinationExists -or $destinationBytes -ne $item.source_bytes -or $destinationSHA -ne $item.source_sha256) { $preflightErrors.Add($item.repo + ': in-place target drift ' + $item.destination_path) }
  } elseif ($item.operation -eq 'copy_exact_to_docs_evidence') {
    if ($destinationExists -and ($destinationBytes -ne $item.source_bytes -or $destinationSHA -ne $item.source_sha256)) { $preflightErrors.Add($item.repo + ': conflicting existing copy target ' + $item.destination_path) }
    $attr = Invoke-GitCapture $repoFull @('check-attr','--all','--',$item.destination_path)
    $attrText = $attr.output -join "`n"
    if ($attr.exit_code -ne 0 -or $attrText -notmatch 'text: unset') { $preflightErrors.Add($item.repo + ': docs evidence target is not covered by existing -text rule ' + $item.destination_path) }
  } else {
    $preflightErrors.Add($item.repo + ': unrecognized operation for ' + $item.destination_path)
  }
  $pathBlob = Invoke-GitCapture $repoFull @('-c','core.autocrlf=false','hash-object',('--path=' + $item.destination_path),'--',$sourceFull)
  if ($pathBlob.exit_code -ne 0 -or $pathBlob.output.Count -eq 0 -or $pathBlob.output[0].Trim() -ne $item.predicted_git_blob_oid_no_write) { $preflightErrors.Add($item.repo + ': predicted path blob differs from approved plan for ' + $item.destination_path) }
  $ignored = Invoke-GitCapture $repoFull @('check-ignore','-q','--',$item.destination_path)
  $item | Add-Member -NotePropertyName ignored_at_execution_preflight -NotePropertyValue ($ignored.exit_code -eq 0) -Force
  $preflightItems.Add([PSCustomObject]@{
    repo=$item.repo
    source_path=$item.source_path
    destination_path=$item.destination_path
    bytes=$sourceInfo.Length
    sha256=$sourceSHA
    source_match=$sourceMatch
    destination_exists=$destinationExists
    destination_matches_source=($destinationExists -and $destinationBytes -eq $item.source_bytes -and $destinationSHA -eq $item.source_sha256)
    path_blob_oid=$item.predicted_git_blob_oid_no_write
    ignored=$item.ignored_at_execution_preflight
  })
}

$preflight = [ordered]@{}
$preflight['schema'] = 'luna-backup-execution-preflight.v1'
$preflight['created_utc'] = [DateTime]::UtcNow.ToString('o')
$preflight['plan_path'] = $planRel
$preflight['plan_sha256'] = $planSHA
$preflight['status'] = if ($preflightErrors.Count -eq 0) { 'passed' } else { 'failed_no_repo_writes' }
$preflight['repo_checks'] = $preflightRepos.ToArray()
$preflight['item_checks'] = $preflightItems.ToArray()
$preflight['errors'] = $preflightErrors.ToArray()
Save-Json $preflightPath $preflight
if ($preflightErrors.Count -ne 0) {
  Get-Content -LiteralPath $preflightPath -Raw
  exit 2
}

$repoReceipts = New-Object 'System.Collections.Generic.List[object]'
foreach ($repoSummary in $plan.repo_summaries) {
  $repo = $repoSummary.repo
  $repoFull = Join-Path $root $repo
  $identity = $repoIdentity[$repo]
  $repoItems = @($plan.candidate_items | Where-Object { $_.repo -eq $repo } | Sort-Object destination_path)
  $copyResults = New-Object 'System.Collections.Generic.List[object]'
  $stageBlobChecks = New-Object 'System.Collections.Generic.List[object]'
  $commitBlobChecks = New-Object 'System.Collections.Generic.List[object]'
  $commands = New-Object 'System.Collections.Generic.List[object]'
  $receiptPath = Join-Path $coord ($repo.Replace('-','_') + '_exact_backup_receipt_20261005.json')
  if (Test-Path -LiteralPath $receiptPath) { throw ('Repository receipt already exists; refusing duplicate run for ' + $repo) }
  $receipt = [ordered]@{}
  $receipt['schema'] = 'luna-exact-backup-execution-receipt.v1'
  $receipt['created_utc'] = [DateTime]::UtcNow.ToString('o')
  $receipt['repository'] = $repo
  $receipt['plan_sha256'] = $planSHA
  $receipt['branch'] = $branchName
  $receipt['parent_head_expected'] = ($plan.repo_heads | Where-Object { $_.repo -eq $repo }).head
  $receipt['approved_identity_used_per_call'] = ($identity.name + ' <' + $identity.email + '>')
  $receipt['candidate_path_count'] = $repoItems.Count
  $receipt['candidate_paths'] = @($repoItems.destination_path)
  $receipt['status'] = 'in_progress'
  $receipt['copy_results'] = @()
  $receipt['commands'] = @()
  $receipt['stage_blob_checks'] = @()
  $receipt['commit_blob_checks'] = @()
  $receipt['failure'] = $null
  try {
    foreach ($item in ($repoItems | Where-Object { $_.operation -eq 'copy_exact_to_docs_evidence' })) {
      $sourceFull = [IO.Path]::GetFullPath((Join-Path $root ($item.source_path.Replace('/', '\'))))
      $destinationFull = [IO.Path]::GetFullPath((Join-Path $repoFull ($item.destination_path.Replace('/', '\'))))
      $sourceInfo = Get-Item -LiteralPath $sourceFull
      $sourceSHA = (Get-FileHash -LiteralPath $sourceFull -Algorithm SHA256).Hash.ToLowerInvariant()
      if ($sourceInfo.Length -ne $item.source_bytes -or $sourceSHA -ne $item.source_sha256) { throw ('Copy source changed immediately before copy: ' + $item.source_path) }
      $alreadyThere = Test-Path -LiteralPath $destinationFull -PathType Leaf
      if (-not $alreadyThere) {
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destinationFull)) | Out-Null
        [IO.File]::Copy($sourceFull,$destinationFull,$false)
      }
      $destInfo = Get-Item -LiteralPath $destinationFull
      $destSHA = (Get-FileHash -LiteralPath $destinationFull -Algorithm SHA256).Hash.ToLowerInvariant()
      if ($destInfo.Length -ne $item.source_bytes -or $destSHA -ne $item.source_sha256) { throw ('Copied evidence byte/SHA mismatch: ' + $item.destination_path) }
      $copyResults.Add([PSCustomObject]@{source_path=$item.source_path;destination_path=$item.destination_path;bytes=$destInfo.Length;sha256=$destSHA;already_present_same_bytes=$alreadyThere;match=$true})
      $receipt['copy_results'] = $copyResults.ToArray()
      Save-Json $receiptPath $receipt
    }

    $stagedBefore = Get-StagedPaths $repoFull
    if ($stagedBefore.Count -ne 0) { throw 'Index changed after global preflight; refusing to mix staged paths.' }
    $destPaths = @($repoItems.destination_path | Sort-Object -Unique)
    if ($destPaths.Count -ne $repoItems.Count) { throw 'Duplicate destination path in approved repository list.' }
    $forcePaths = @($repoItems | Where-Object { $_.ignored_at_execution_preflight } | ForEach-Object { $_.destination_path } | Sort-Object -Unique)
    $normalPaths = @($destPaths | Where-Object { $forcePaths -notcontains $_ })
    if ($normalPaths.Count -gt 0) {
      $stageArgs = @('-c','core.autocrlf=false','add','--') + $normalPaths
      $stageResult = Invoke-GitCapture $repoFull $stageArgs
      $commands.Add($stageResult)
      if ($stageResult.exit_code -ne 0) { throw 'Exact git add failed for non-ignored approved paths.' }
    }
    if ($forcePaths.Count -gt 0) {
      $forceStageArgs = @('-c','core.autocrlf=false','add','-f','--') + $forcePaths
      $stageResult = Invoke-GitCapture $repoFull $forceStageArgs
      $commands.Add($stageResult)
      if ($stageResult.exit_code -ne 0) { throw 'Exact git add -f failed for explicitly approved ignored paths.' }
    }
    $actualStaged = Get-StagedPaths $repoFull
    if (($actualStaged -join "`n") -ne ($destPaths -join "`n")) { throw 'Staged path set differs from exact approved path list; refusing commit.' }
    $receipt['stage_command_argv'] = @($commands | ForEach-Object { $_.argv })
    $receipt['stage_exit_codes'] = @($commands | ForEach-Object { $_.exit_code })
    $receipt['staged_path_count'] = $actualStaged.Count
    $receipt['staged_paths'] = $actualStaged
    Save-Json $receiptPath $receipt

    foreach ($item in $repoItems) {
      $ls = Invoke-GitCapture $repoFull @('ls-files','-s','--',$item.destination_path)
      if ($ls.exit_code -ne 0 -or $ls.output.Count -ne 1) { throw ('Cannot resolve exact index object: ' + $item.destination_path) }
      $match = [regex]::Match($ls.output[0], '^\d+\s+([0-9a-f]{40,64})\s+0\t')
      if (-not $match.Success) { throw ('Unexpected index entry for ' + $item.destination_path) }
      $oid = $match.Groups[1].Value
      if ($oid -ne $item.predicted_git_blob_oid_no_write) { throw ('Index blob OID differs from reviewed path blob: ' + $item.destination_path) }
      $digest = Get-BlobContentDigest $repoFull $oid
      $ok = ($digest.exit_code -eq 0 -and $digest.bytes -eq $item.source_bytes -and $digest.sha256 -eq $item.source_sha256)
      $stageBlobChecks.Add([PSCustomObject]@{path=$item.destination_path;object_id=$oid;bytes=$digest.bytes;sha256=$digest.sha256;expected_bytes=$item.source_bytes;expected_sha256=$item.source_sha256;content_match=$ok;cat_file_argv=$digest.argv;cat_file_exit_code=$digest.exit_code})
      if (-not $ok) { throw ('Index blob bytes/SHA differ from source: ' + $item.destination_path) }
    }
    $receipt['stage_blob_checks'] = $stageBlobChecks.ToArray()
    Save-Json $receiptPath $receipt

    $preCommitHead = Get-CurrentHead $repoFull
    if ($preCommitHead -ne $receipt['parent_head_expected']) { throw 'Local HEAD changed after preflight; refusing commit.' }
    $commitArgs = @('-c','core.autocrlf=false','-c',('user.name=' + $identity.name),'-c',('user.email=' + $identity.email),'commit','-m',$identity.subject,'-m',$identity.body)
    $commitResult = Invoke-GitCapture $repoFull $commitArgs
    $commands.Add($commitResult)
    $receipt['commit_command_argv'] = $commitResult.argv
    $receipt['commit_exit_code'] = $commitResult.exit_code
    $receipt['commit_output'] = $commitResult.output
    if ($commitResult.exit_code -ne 0) { throw 'Git commit failed; exact approved paths remain staged.' }
    $commit = Get-CurrentHead $repoFull
    $receipt['commit'] = $commit
    $receipt['commit_parent'] = (Invoke-GitCapture $repoFull @('rev-parse','HEAD^')).output[0].Trim()
    if ($receipt['commit_parent'] -ne $preCommitHead) { throw 'Commit parent is not the verified pre-commit HEAD.' }
    $changedResult = Invoke-GitCapture $repoFull @('diff-tree','--no-commit-id','--name-only','-r',$commit)
    if ($changedResult.exit_code -ne 0) { throw 'Could not verify commit path list.' }
    $changed = @($changedResult.output | Where-Object { $_ -ne '' } | Sort-Object -Unique)
    if (($changed -join "`n") -ne ($destPaths -join "`n")) { throw 'Commit tree changed paths differ from exact approved path list; commit retained, push withheld.' }
    $receipt['changed_path_count'] = $changed.Count
    $receipt['changed_paths'] = $changed
    $receipt['commit_tree_path_check'] = 'exact_match'
    foreach ($item in $repoItems) {
      $objectResult = Invoke-GitCapture $repoFull @('rev-parse',($commit + ':' + $item.destination_path))
      if ($objectResult.exit_code -ne 0 -or $objectResult.output.Count -eq 0) { throw ('Could not resolve committed object: ' + $item.destination_path) }
      $oid = $objectResult.output[0].Trim()
      $digest = Get-BlobContentDigest $repoFull $oid
      $ok = ($digest.exit_code -eq 0 -and $digest.bytes -eq $item.source_bytes -and $digest.sha256 -eq $item.source_sha256)
      $commitBlobChecks.Add([PSCustomObject]@{path=$item.destination_path;object_id=$oid;bytes=$digest.bytes;sha256=$digest.sha256;expected_bytes=$item.source_bytes;expected_sha256=$item.source_sha256;content_match=$ok;cat_file_argv=$digest.argv;cat_file_exit_code=$digest.exit_code})
      if (-not $ok) { throw ('Committed Git blob bytes/SHA differ from reviewed source: ' + $item.destination_path) }
    }
    $receipt['commit_blob_checks'] = $commitBlobChecks.ToArray()
    $receipt['commit_blob_match_count'] = @($commitBlobChecks | Where-Object { $_.content_match }).Count
    $receipt['commit_tree_verified'] = $true
    Save-Json $receiptPath $receipt

    $remainingStaged = Get-StagedPaths $repoFull
    if ($remainingStaged.Count -ne 0) { throw 'Index is unexpectedly nonempty after commit; push withheld.' }
    $prePushRemote = Get-RemoteBranchHead $repoFull $branchName
    $receipt['remote_head_before_push'] = $prePushRemote.head
    $receipt['remote_query_before_push_argv'] = $prePushRemote.argv
    $receipt['remote_query_before_push_exit_code'] = $prePushRemote.exit_code
    if ($prePushRemote.exit_code -ne 0 -or ($prePushRemote.head -ne $preCommitHead -and $prePushRemote.head -ne $commit)) {
      $receipt['status'] = 'committed_push_withheld_remote_moved'
      $receipt['push_exit_code'] = $null
      $receipt['failure'] = 'Remote head changed after preflight; local commit retained and no push attempted.'
    } elseif ($prePushRemote.head -eq $commit) {
      $receipt['status'] = 'commit_already_remote_verified'
      $receipt['push_exit_code'] = 0
      $receipt['push_argv'] = @()
    } else {
      $pushResult = Invoke-GitCapture $repoFull @('-c','core.autocrlf=false','push','origin',('HEAD:refs/heads/' + $branchName))
      $commands.Add($pushResult)
      $receipt['push_argv'] = $pushResult.argv
      $receipt['push_exit_code'] = $pushResult.exit_code
      $receipt['push_output'] = $pushResult.output
      $remoteAfter = Get-RemoteBranchHead $repoFull $branchName
      $receipt['remote_head_after_push'] = $remoteAfter.head
      $receipt['remote_query_after_push_argv'] = $remoteAfter.argv
      $receipt['remote_query_after_push_exit_code'] = $remoteAfter.exit_code
      if ($pushResult.exit_code -eq 0 -and $remoteAfter.exit_code -eq 0 -and $remoteAfter.head -eq $commit) {
        $receipt['status'] = 'pushed_and_remote_head_verified'
      } else {
        $receipt['status'] = 'commit_retained_push_failed_or_unverified'
        $receipt['failure'] = 'Push failed or remote HEAD did not verify to the new commit; local commit is retained.'
      }
    }
    $receipt['commands'] = $commands.ToArray()
    $receipt['local_head_after'] = Get-CurrentHead $repoFull
    $receipt['branch_after'] = Get-CurrentBranch $repoFull
    $receipt['remaining_staged_paths'] = Get-StagedPaths $repoFull
    $receipt['exact_path_status_after'] = (Invoke-GitCapture $repoFull (@('status','--porcelain=v1','--untracked-files=all','--') + $destPaths)).output
    $receipt['finished_utc'] = [DateTime]::UtcNow.ToString('o')
  } catch {
    $receipt['status'] = if ($null -ne $receipt['commit']) { 'commit_retained_after_execution_failure' } else { 'execution_failed_no_commit' }
    $receipt['failure'] = $_.Exception.Message
    $receipt['commands'] = $commands.ToArray()
    $receipt['copy_results'] = $copyResults.ToArray()
    $receipt['stage_blob_checks'] = $stageBlobChecks.ToArray()
    $receipt['commit_blob_checks'] = $commitBlobChecks.ToArray()
    $receipt['local_head_after'] = Get-CurrentHead $repoFull
    $receipt['branch_after'] = Get-CurrentBranch $repoFull
    $receipt['remaining_staged_paths'] = Get-StagedPaths $repoFull
    $receipt['finished_utc'] = [DateTime]::UtcNow.ToString('o')
  }
  Save-Json $receiptPath $receipt
  $receiptHash = (Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
  $repoReceipts.Add([PSCustomObject]@{repository=$repo;receipt_path=('tmp/review_20261005/backup_coordinator/' + [IO.Path]::GetFileName($receiptPath));receipt_sha256=$receiptHash;receipt_bytes=(Get-Item -LiteralPath $receiptPath).Length;receipt=$receipt})
}

$overallSuccess = @($repoReceipts | Where-Object { $_.receipt.status -ne 'pushed_and_remote_head_verified' -and $_.receipt.status -ne 'commit_already_remote_verified' }).Count -eq 0
$aggregate = [ordered]@{}
$aggregate['schema'] = 'luna-exact-backup-batch-receipt.v1'
$aggregate['created_utc'] = [DateTime]::UtcNow.ToString('o')
$aggregate['plan_path'] = $planRel
$aggregate['plan_sha256'] = $planSHA
$aggregate['preflight_receipt_path'] = 'tmp/review_20261005/backup_coordinator/next_backup_preflight_receipt_20261005.json'
$aggregate['status'] = if ($overallSuccess) { 'all_three_repositories_pushed_and_verified' } else { 'partial_or_failed_review_receipts' }
$aggregate['git_force_used'] = $false
$aggregate['git_config_changed'] = $false
$aggregate['repository_receipts'] = $repoReceipts.ToArray()
$aggregate['total_candidate_paths'] = @($repoReceipts | Measure-Object -Property { $_.receipt.candidate_path_count } -Sum).Sum
$aggregate['total_committed_blob_matches'] = @($repoReceipts | ForEach-Object { $_.receipt.commit_blob_match_count } | Measure-Object -Sum).Sum
Save-Json $aggregatePath $aggregate
[PSCustomObject]@{aggregate_path='tmp/review_20261005/backup_coordinator/next_backup_execution_receipt_20261005.json';aggregate_sha256=(Get-FileHash -LiteralPath $aggregatePath -Algorithm SHA256).Hash.ToLowerInvariant();aggregate_bytes=(Get-Item -LiteralPath $aggregatePath).Length;status=$aggregate.status;repo_statuses=@($repoReceipts | ForEach-Object {[PSCustomObject]@{repo=$_.repository;status=$_.receipt.status;commit=$_.receipt.commit;push_rc=$_.receipt.push_exit_code;remote_after=$_.receipt.remote_head_after_push;receipt=$_.receipt_path}})} | ConvertTo-Json -Depth 8
