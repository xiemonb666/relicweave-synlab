$ErrorActionPreference = 'Stop'

$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$pythonPath = (Resolve-Path (Join-Path $workspaceRoot 'third_party\vesselforge-runtime\venv\Scripts\python.exe')).Path
$sourcePath = (Resolve-Path (Join-Path $workspaceRoot 'vesselforge\experiments\smooth_surface_route_20261004\route_source_draft.py')).Path
$casesPath = (Resolve-Path (Join-Path $workspaceRoot 'vesselforge\experiments\smooth_surface_route_20261004\fixed_cases.json')).Path
$outputPath = Join-Path $PSScriptRoot 'run_beaker'
$approvedSourceHash = '359DC041B521799C39A08ED1F2A680A192EECC234FD8E47845511CAE58048D8E'
$approvedCasesHash = '9AFDFC764C28FC73932598B38A1A36DB56642864F620B0C67E2382AD5DAEF74F'

if (Test-Path -LiteralPath $outputPath) {
    throw "Refusing to reuse existing output directory: $outputPath"
}
$sourceHashBefore = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash
$casesHashBefore = (Get-FileHash -Algorithm SHA256 -LiteralPath $casesPath).Hash
if ($sourceHashBefore -ne $approvedSourceHash) {
    throw "Frozen source hash mismatch; expected $approvedSourceHash, got $sourceHashBefore"
}
if ($casesHashBefore -ne $approvedCasesHash) {
    throw "Frozen fixed-case hash mismatch; expected $approvedCasesHash, got $casesHashBefore"
}

$pythonVersion = (& $pythonPath --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Could not read configured Python runtime version: $pythonVersion"
}

New-Item -ItemType Directory -Path $outputPath | Out-Null
$stdoutPath = Join-Path $outputPath 'stdout.txt'
$stderrPath = Join-Path $outputPath 'stderr.txt'
$metadataPath = Join-Path $outputPath 'run_metadata.json'
$over120Path = Join-Path $outputPath 'status_over_120s.json'
$argv = @('-B', $sourcePath, '--family', 'beaker', '--output', $outputPath, '--step-roundtrip')
if ($sourcePath -match '\s' -or $outputPath -match '\s') {
    throw 'This launcher uses a joined Windows argument string and requires paths without whitespace.'
}
$argumentLine = [string]::Join(' ', $argv)
$startedUtc = [DateTimeOffset]::UtcNow
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$process = $null
$timedOut = $false

try {
    $process = Start-Process -FilePath $pythonPath `
        -ArgumentList $argumentLine `
        -WorkingDirectory $workspaceRoot `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath
} catch {
    $stopwatch.Stop()
    $failure = [ordered]@{
        status = 'START_FAILED'
        executable = $pythonPath
        argv = $argv
        runtime_python_version = $pythonVersion
        started_utc = $startedUtc.ToString('o')
        ended_utc = [DateTimeOffset]::UtcNow.ToString('o')
        wall_time_seconds = $stopwatch.Elapsed.TotalSeconds
        source_sha256_before = $sourceHashBefore
        source_sha256_after = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash
        fixed_cases_sha256_before = $casesHashBefore
        fixed_cases_sha256_after = (Get-FileHash -Algorithm SHA256 -LiteralPath $casesPath).Hash
        exception = $_.Exception.ToString()
    }
    $failure | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $metadataPath -Encoding utf8
    throw
}

Write-Output "RUNNING process_id=$($process.Id) output=$outputPath"
$over120Recorded = $false
while (-not $process.HasExited) {
    $process.Refresh()
    if (-not $over120Recorded -and $stopwatch.Elapsed.TotalSeconds -ge 120.0) {
        $over120Recorded = $true
        $snapshot = [ordered]@{
            status = 'STILL_RUNNING_AT_120_SECONDS'
            process_id = $process.Id
            process_name = $process.ProcessName
            started_utc = $startedUtc.ToString('o')
            observed_utc = [DateTimeOffset]::UtcNow.ToString('o')
            wall_time_seconds = $stopwatch.Elapsed.TotalSeconds
            stdout_bytes = if (Test-Path -LiteralPath $stdoutPath) { (Get-Item -LiteralPath $stdoutPath).Length } else { 0 }
            stderr_bytes = if (Test-Path -LiteralPath $stderrPath) { (Get-Item -LiteralPath $stderrPath).Length } else { 0 }
        }
        $snapshot | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $over120Path -Encoding utf8
        Write-Output "STILL_RUNNING_AT_120_SECONDS process_id=$($process.Id)"
    }
    if ($stopwatch.Elapsed.TotalSeconds -ge 240.0) {
        $timedOut = $true
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit()
        break
    }
    Start-Sleep -Seconds 2
}

$process.Refresh()
if (-not $process.HasExited -and $timedOut) {
    $process.WaitForExit()
}
$stopwatch.Stop()
$sourceHashAfter = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash
$casesHashAfter = (Get-FileHash -Algorithm SHA256 -LiteralPath $casesPath).Hash
$exitCode = if ($process.HasExited) { $process.ExitCode } else { $null }
$metadata = [ordered]@{
    status = if ($timedOut) { 'TERMINATED_AT_240_SECONDS' } else { 'COMPLETED' }
    executable = $pythonPath
    runtime_python_version = $pythonVersion
    argv = $argv
    working_directory = $workspaceRoot
    process_id = $process.Id
    started_utc = $startedUtc.ToString('o')
    ended_utc = [DateTimeOffset]::UtcNow.ToString('o')
    wall_time_seconds = $stopwatch.Elapsed.TotalSeconds
    exit_code = $exitCode
    source_sha256_before = $sourceHashBefore
    source_sha256_after = $sourceHashAfter
    fixed_cases_sha256_before = $casesHashBefore
    fixed_cases_sha256_after = $casesHashAfter
    stdout_path = $stdoutPath
    stdout_sha256 = if (Test-Path -LiteralPath $stdoutPath) { (Get-FileHash -Algorithm SHA256 -LiteralPath $stdoutPath).Hash } else { $null }
    stderr_path = $stderrPath
    stderr_sha256 = if (Test-Path -LiteralPath $stderrPath) { (Get-FileHash -Algorithm SHA256 -LiteralPath $stderrPath).Hash } else { $null }
    over_120_status_path = if ($over120Recorded) { $over120Path } else { $null }
}
$metadata | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $metadataPath -Encoding utf8
Write-Output ("FINISHED status={0} exit_code={1} wall_time_seconds={2:N3} metadata={3}" -f $metadata.status, $exitCode, $stopwatch.Elapsed.TotalSeconds, $metadataPath)
if ($timedOut) {
    exit 124
}
if ($exitCode -ne 0) {
    exit $exitCode
}
