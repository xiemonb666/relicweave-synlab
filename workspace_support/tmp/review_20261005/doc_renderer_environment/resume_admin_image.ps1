$ErrorActionPreference = 'Stop'
$workspace = 'C:\Users\xiemo\Desktop\ShardForge'
$receiptDir = Join-Path $workspace 'tmp\review_20261005\doc_renderer_environment'
$downloadDir = Join-Path $receiptDir 'download'
$scratch = Join-Path $receiptDir 'scratch'
$runtimeRoot = Join-Path $workspace 'third_party\doc-render-runtime'
$targetDir = Join-Path $runtimeRoot 'LibreOffice-26.8.0'
$msiName = 'LibreOffice_26.8.0_Win_x86-64.msi'
$msi = Join-Path $downloadDir $msiName
$msiUrl = 'https://download.documentfoundation.org/libreoffice/stable/26.8.0/win/x86_64/' + $msiName
$expectedBytes = 374906880L
$expectedSha = '4aa6c6e1895f4055104effcb556bd3362d20c6ad707c149543304f395ef9db95'
$receipt = Join-Path $receiptDir 'verified_setup_receipt.txt'
$shaPath = Join-Path $downloadDir ($msiName + '.sha256')
$ascPath = Join-Path $downloadDir ($msiName + '.asc')
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
$env:TEMP = $scratch
$env:TMP = $scratch
$env:TMPDIR = $scratch
function Record([string]$line) {
  Add-Content -LiteralPath $receipt -Value ((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ssZ') + ' ' + $line) -Encoding UTF8
}
Set-Content -LiteralPath $receipt -Value 'LibreOffice isolated renderer setup receipt (verification + admin image)' -Encoding UTF8
try {
  if (-not (Test-Path -LiteralPath $msi -PathType Leaf)) {
    throw 'Previously downloaded MSI is missing; do not redownload automatically.'
  }
  Record ('requested_source=' + $msiUrl)
  Record 'download_source_note=Downloaded once from official download.documentfoundation.org URL; PowerShell Invoke-WebRequest -OutFile returned no response object, so no redirect URI was exposed.'
  $actualBytes = (Get-Item -LiteralPath $msi).Length
  Record ('bytes=' + $actualBytes)
  if ($actualBytes -ne $expectedBytes) {
    throw ('Exact size mismatch: expected ' + $expectedBytes + ', got ' + $actualBytes)
  }
  $actualSha = (Get-FileHash -LiteralPath $msi -Algorithm SHA256).Hash.ToLowerInvariant()
  Record ('sha256=' + $actualSha)
  if ($actualSha -ne $expectedSha) {
    throw ('SHA-256 mismatch: expected ' + $expectedSha + ', got ' + $actualSha)
  }
  Invoke-WebRequest -Uri ($msiUrl + '.sha256') -OutFile $shaPath -TimeoutSec 60 -UseBasicParsing | Out-Null
  Invoke-WebRequest -Uri ($msiUrl + '.asc') -OutFile $ascPath -TimeoutSec 60 -UseBasicParsing | Out-Null
  $sidecarText = Get-Content -LiteralPath $shaPath -Raw
  Record ('official_sha256_sidecar=' + (($sidecarText -replace '\s+', ' ').Trim()))
  if ($sidecarText -notmatch $expectedSha) {
    throw 'Official SHA-256 sidecar did not contain the expected digest.'
  }
  Record ('official_pgp_signature_sidecar=' + $ascPath)
  $auth = Get-AuthenticodeSignature -LiteralPath $msi
  $subject = if ($auth.SignerCertificate) { $auth.SignerCertificate.Subject } else { 'none' }
  $thumb = if ($auth.SignerCertificate) { $auth.SignerCertificate.Thumbprint } else { 'none' }
  $issuer = if ($auth.SignerCertificate) { $auth.SignerCertificate.Issuer } else { 'none' }
  Record ('authenticode_status=' + $auth.Status + ';subject=' + $subject + ';thumbprint=' + $thumb + ';issuer=' + $issuer + ';message=' + $auth.StatusMessage)
  if ($auth.Status -ne 'Valid') {
    throw ('Authenticode status not Valid: ' + $auth.Status + '; ' + $auth.StatusMessage)
  }
  New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
  $msiLog = Join-Path $receiptDir 'msiexec_admin_image.log'
  $args = '/a "' + $msi + '" /qn /norestart /l*v "' + $msiLog + '" TARGETDIR="' + $targetDir + '"'
  Record ('admin_image_target=' + $targetDir)
  Record ('msiexec_mode=administrative_image_only;command=msiexec.exe ' + $args)
  $installer = Join-Path $env:SystemRoot 'System32\msiexec.exe'
  $proc = Start-Process -FilePath $installer -ArgumentList $args -Wait -PassThru -WindowStyle Hidden
  Record ('msiexec_exit_code=' + $proc.ExitCode + ';log=' + $msiLog)
  if ($proc.ExitCode -ne 0) {
    throw ('msiexec administrative image failed with exit code ' + $proc.ExitCode)
  }
  $soffice = Join-Path $targetDir 'program\soffice.exe'
  if (-not (Test-Path -LiteralPath $soffice -PathType Leaf)) {
    throw ('Expected program executable missing after admin image: ' + $soffice)
  }
  Record ('soffice_path=' + $soffice)
  Record 'RESULT=ADMIN_IMAGE_CREATED;version_probe_pending'
} catch {
  Record ('RESULT=STOPPED;error=' + $_.Exception.Message)
  exit 20
}
