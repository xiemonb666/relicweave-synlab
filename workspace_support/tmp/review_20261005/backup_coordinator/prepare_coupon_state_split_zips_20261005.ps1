$ErrorActionPreference = 'Stop'
$root = 'C:\Users\xiemo\Desktop\ShardForge'
$coord = [IO.Path]::GetFullPath((Join-Path $root 'tmp\review_20261005\backup_coordinator'))
Add-Type -AssemblyName System.IO.Compression

function Write-Receipt($path, $value) {
  $json = $value | ConvertTo-Json -Depth 8
  [IO.File]::WriteAllText($path, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
}

function Remove-OwnInvalidArchive($path) {
  $full = [IO.Path]::GetFullPath($path)
  if (-not $full.StartsWith($coord + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Refusing cleanup outside coordinator directory.' }
  if (Test-Path -LiteralPath $full -PathType Leaf) { [IO.File]::Delete($full) }
}

function New-VerifiedArchive($name, $item) {
  $archivePath = Join-Path $coord $name
  $receiptPath = [IO.Path]::ChangeExtension($archivePath, '.receipt.json')
  if (Test-Path -LiteralPath $archivePath) { throw ('Archive path already exists: ' + $name) }
  if (Test-Path -LiteralPath $receiptPath) { throw ('Receipt path already exists: ' + [IO.Path]::GetFileName($receiptPath)) }
  $clock = [Diagnostics.Stopwatch]::StartNew()
  $receipt = [ordered]@{
    created_utc = [DateTime]::UtcNow.ToString('o')
    purpose = 'single-case lossless ZIP preparation only; no repository copy or Git action'
    status = 'in_progress'
    archive_path = ('tmp/review_20261005/backup_coordinator/' + $name)
    compression = 'System.IO.Compression.ZipArchive CompressionLevel.Optimal (DEFLATE)'
    cap_bytes_exclusive = 52428800
    source_path = $item.Path
    expected_source_bytes = $item.Bytes
    expected_source_sha256 = $item.SHA
  }
  $created = $false
  $fs = $null
  $zip = $null
  try {
    $sourcePath = Join-Path $root ($item.Path.Replace('/', '\'))
    $sourceInfo = Get-Item -LiteralPath $sourcePath
    $sourceSHAInitial = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($sourceInfo.Length -ne $item.Bytes -or $sourceSHAInitial -ne $item.SHA) { throw 'Source preflight byte/SHA pin mismatch.' }
    $fs = [IO.File]::Open($archivePath, [IO.FileMode]::CreateNew, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $created = $true
    $zip = [IO.Compression.ZipArchive]::new($fs, [IO.Compression.ZipArchiveMode]::Create, $true)
    $entry = $zip.CreateEntry($item.Path, [IO.Compression.CompressionLevel]::Optimal)
    $input = [IO.File]::OpenRead($sourcePath)
    $output = $entry.Open()
    $sha = [Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
    $buffer = New-Object byte[] (1024 * 1024)
    [long]$count = 0
    try {
      while (($n = $input.Read($buffer, 0, $buffer.Length)) -gt 0) {
        if ($clock.Elapsed.TotalSeconds -ge 120) { throw 'Per-archive 120-second bound reached while writing.' }
        $output.Write($buffer, 0, $n)
        $sha.AppendData($buffer, 0, $n)
        $count += $n
      }
    } finally {
      $output.Dispose()
      $input.Dispose()
    }
    $sourceSHAStream = [Convert]::ToHexString($sha.GetHashAndReset()).ToLowerInvariant()
    $sha.Dispose()
    if ($count -ne $item.Bytes -or $sourceSHAStream -ne $item.SHA) { throw 'Source changed or source-stream hash mismatch during archive.' }
    $zip.Dispose()
    $fs.Dispose()
    $zip = $null
    $fs = $null
    $archiveInfo = Get-Item -LiteralPath $archivePath
    $archiveSHA = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $receipt.source_sha256_during_archive = $sourceSHAStream
    $receipt.source_bytes_during_archive = $count
    $receipt.archive_bytes = $archiveInfo.Length
    $receipt.archive_sha256 = $archiveSHA
    if ($archiveInfo.Length -ge 52428800) { throw ('Single-case archive exceeded strict 50 MiB cap: ' + $archiveInfo.Length) }
    $readFs = [IO.File]::OpenRead($archivePath)
    try {
      $readZip = [IO.Compression.ZipArchive]::new($readFs, [IO.Compression.ZipArchiveMode]::Read, $false)
      try {
        $zentry = $readZip.GetEntry($item.Path)
        if ($null -eq $zentry) { throw 'Expected ZIP entry missing during readback.' }
        $entryStream = $zentry.Open()
        $readSHA = [Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
        [long]$readCount = 0
        try {
          while (($rn = $entryStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            if ($clock.Elapsed.TotalSeconds -ge 120) { throw 'Per-archive 120-second bound reached during streaming readback.' }
            $readSHA.AppendData($buffer, 0, $rn)
            $readCount += $rn
          }
        } finally {
          $entryStream.Dispose()
        }
        $readSHA256 = [Convert]::ToHexString($readSHA.GetHashAndReset()).ToLowerInvariant()
        $readSHA.Dispose()
        if ($readCount -ne $item.Bytes -or $readSHA256 -ne $item.SHA -or $zentry.Length -ne $item.Bytes) { throw 'Streaming ZIP readback failed source byte/SHA equality.' }
        $receipt.readback = [ordered]@{entry_path=$item.Path; uncompressed_bytes=$readCount; uncompressed_sha256=$readSHA256; compressed_entry_bytes=$zentry.CompressedLength; match=$true}
      } finally {
        $readZip.Dispose()
      }
    } finally {
      $readFs.Dispose()
    }
    $receipt.elapsed_seconds = [Math]::Round($clock.Elapsed.TotalSeconds, 3)
    $receipt.status = 'verified_lossless_under_cap'
    Write-Receipt $receiptPath $receipt
  } catch {
    if ($null -ne $zip) { $zip.Dispose() }
    if ($null -ne $fs) { $fs.Dispose() }
    $receipt.elapsed_seconds = [Math]::Round($clock.Elapsed.TotalSeconds, 3)
    $receipt.status = 'failed'
    $receipt.failure = $_.Exception.Message
    if ($created -and (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
      $bad = Get-Item -LiteralPath $archivePath
      $receipt.archive_bytes = $bad.Length
      $receipt.archive_sha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
      Remove-OwnInvalidArchive $archivePath
      $receipt.invalid_archive_deleted = $true
    }
    Write-Receipt $receiptPath $receipt
  }
  Get-Content -LiteralPath $receiptPath -Raw
}

$specs = @(
  [PSCustomObject]@{Name='native_coupon_point_state_baseline_20261005.zip'; Path='pgfrag/experiments/free_evolution_coupon_20261005/run_attempt_01/results/point_state_history.f64le'; Bytes=37044000L; SHA='0f436e4d8cabd29f3f634334e2d1e00e920be098cafaea8a1e0a9df2b221be77'},
  [PSCustomObject]@{Name='native_coupon_point_state_dt_half_20261005.zip'; Path='pgfrag/experiments/free_evolution_coupon_dt_half_20261005/run_attempt_01/results/point_state_history.f64le'; Bytes=73332000L; SHA='674a8b00ba433bdca840384a6e6cd9437fe78fbbdfeabc0293151322170e367c'}
)
foreach ($spec in $specs) { New-VerifiedArchive $spec.Name $spec }
