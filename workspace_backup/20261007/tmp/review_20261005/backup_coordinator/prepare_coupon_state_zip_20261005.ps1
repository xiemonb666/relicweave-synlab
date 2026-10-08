$ErrorActionPreference = 'Stop'
$root = 'C:\Users\xiemo\Desktop\ShardForge'
$coord = Join-Path $root 'tmp\review_20261005\backup_coordinator'
$archivePath = Join-Path $coord 'native_coupon_point_state_baseline_dt_half_20261005.zip'
$receiptPath = Join-Path $coord 'native_coupon_point_state_zip_receipt_20261005.json'
if (Test-Path -LiteralPath $archivePath) { throw 'Archive path already exists; refusing overwrite.' }
if (Test-Path -LiteralPath $receiptPath) { throw 'Receipt path already exists; refusing overwrite.' }
$items = @(
  [PSCustomObject]@{Path='pgfrag/experiments/free_evolution_coupon_20261005/run_attempt_01/results/point_state_history.f64le'; ExpectedBytes=37044000L; ExpectedSHA='0f436e4d8cabd29f3f634334e2d1e00e920be098cafaea8a1e0a9df2b221be77'},
  [PSCustomObject]@{Path='pgfrag/experiments/free_evolution_coupon_dt_half_20261005/run_attempt_01/results/point_state_history.f64le'; ExpectedBytes=73332000L; ExpectedSHA='674a8b00ba433bdca840384a6e6cd9437fe78fbbdfeabc0293151322170e367c'}
)
$started = [DateTime]::UtcNow
$sw = [Diagnostics.Stopwatch]::StartNew()
$receipt = [ordered]@{
  created_utc = $started.ToString('o')
  purpose = 'bounded lossless ZIP preparation only; no repository copy or Git action'
  status = 'in_progress'
  archive_path = 'tmp/review_20261005/backup_coordinator/native_coupon_point_state_baseline_dt_half_20261005.zip'
  compression = 'System.IO.Compression.ZipArchive CompressionLevel.Optimal (DEFLATE)'
  cap_bytes_exclusive = 52428800
  entries = @()
}
$zip = $null
$fs = $null
try {
  Add-Type -AssemblyName System.IO.Compression
  $fs = [IO.File]::Open($archivePath, [IO.FileMode]::CreateNew, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
  $zip = [IO.Compression.ZipArchive]::new($fs, [IO.Compression.ZipArchiveMode]::Create, $true)
  $buffer = New-Object byte[] (1024 * 1024)
  foreach ($item in $items) {
    if ($sw.Elapsed.TotalSeconds -ge 120) { throw '120-second bound reached before all entries were written.' }
    $sourcePath = Join-Path $root ($item.Path.Replace('/', '\'))
    $info = Get-Item -LiteralPath $sourcePath
    if ($info.Length -ne $item.ExpectedBytes) { throw ('Source byte count mismatch for ' + $item.Path) }
    $source = [IO.File]::OpenRead($sourcePath)
    try {
      $entry = $zip.CreateEntry($item.Path, [IO.Compression.CompressionLevel]::Optimal)
      $dst = $entry.Open()
      $sha = [Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
      [long]$count = 0
      try {
        while (($n = $source.Read($buffer, 0, $buffer.Length)) -gt 0) {
          if ($sw.Elapsed.TotalSeconds -ge 120) { throw '120-second bound reached while writing archive.' }
          $dst.Write($buffer, 0, $n)
          $sha.AppendData($buffer, 0, $n)
          $count += $n
        }
      } finally {
        $dst.Dispose()
      }
      $sourceSHA = [Convert]::ToHexString($sha.GetHashAndReset()).ToLowerInvariant()
      $sha.Dispose()
      if ($count -ne $item.ExpectedBytes -or $sourceSHA -ne $item.ExpectedSHA) { throw ('Source changed or hash mismatch while archiving ' + $item.Path) }
      $receipt.entries += [ordered]@{path=$item.Path; source_bytes=$count; source_sha256=$sourceSHA; compressed_entry_bytes=$entry.CompressedLength}
    } finally {
      $source.Dispose()
    }
  }
  $zip.Dispose()
  $fs.Dispose()
  $zip = $null
  $fs = $null
  $archiveInfo = Get-Item -LiteralPath $archivePath
  $archiveSHA = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
  $receipt.archive_bytes = $archiveInfo.Length
  $receipt.archive_sha256 = $archiveSHA
  if ($archiveInfo.Length -ge 52428800) { throw ('Archive exceeded strict 50 MiB cap: ' + $archiveInfo.Length) }
  $readFs = [IO.File]::OpenRead($archivePath)
  try {
    $readZip = [IO.Compression.ZipArchive]::new($readFs, [IO.Compression.ZipArchiveMode]::Read, $false)
    try {
      $verified = @()
      foreach ($item in $items) {
        if ($sw.Elapsed.TotalSeconds -ge 120) { throw '120-second bound reached during archive readback.' }
        $zentry = $readZip.GetEntry($item.Path)
        if ($null -eq $zentry) { throw ('Missing ZIP entry: ' + $item.Path) }
        $ins = $zentry.Open()
        $sha2 = [Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
        [long]$count2 = 0
        try {
          while (($n2 = $ins.Read($buffer, 0, $buffer.Length)) -gt 0) {
            if ($sw.Elapsed.TotalSeconds -ge 120) { throw '120-second bound reached while streaming ZIP entry readback.' }
            $sha2.AppendData($buffer, 0, $n2)
            $count2 += $n2
          }
        } finally {
          $ins.Dispose()
        }
        $readSHA = [Convert]::ToHexString($sha2.GetHashAndReset()).ToLowerInvariant()
        $sha2.Dispose()
        if ($count2 -ne $item.ExpectedBytes -or $readSHA -ne $item.ExpectedSHA -or $zentry.Length -ne $item.ExpectedBytes) { throw ('ZIP entry readback mismatch: ' + $item.Path) }
        $verified += [ordered]@{path=$item.Path; uncompressed_bytes=$count2; uncompressed_sha256=$readSHA; zip_entry_length=$zentry.Length; compressed_length=$zentry.CompressedLength; readback_match=$true}
      }
      $receipt.readback_entries = $verified
    } finally {
      $readZip.Dispose()
    }
  } finally {
    $readFs.Dispose()
  }
  $receipt.elapsed_seconds = [Math]::Round($sw.Elapsed.TotalSeconds, 3)
  $receipt.status = 'verified_lossless_under_cap'
} catch {
  if ($null -ne $zip) { $zip.Dispose() }
  if ($null -ne $fs) { $fs.Dispose() }
  $receipt.status = 'failed'
  $receipt.elapsed_seconds = [Math]::Round($sw.Elapsed.TotalSeconds, 3)
  $receipt.failure = $_.Exception.Message
}
$json = $receipt | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($receiptPath, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
Get-Content -LiteralPath $receiptPath -Raw
if ($receipt.status -ne 'verified_lossless_under_cap') { exit 2 }
