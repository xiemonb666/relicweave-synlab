param(
  [Parameter(Mandatory = $true)]
  [string]$InputDocx,
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^[0-9a-fA-F]{64}$')]
  [string]$ExpectedSha256
)
$ErrorActionPreference = 'Stop'
$workspace = 'C:\Users\xiemo\Desktop\ShardForge'
$receiptDir = Join-Path $workspace 'tmp\review_20261005\doc_renderer_environment'
$outputDir = Join-Path $workspace 'tmp\review_20261005\doc_render_updated'
$scratch = Join-Path $receiptDir 'scratch'
$programDir = Join-Path $workspace 'third_party\doc-render-runtime\LibreOffice-26.8.0\program'
$popplerBin = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin'
$pythonExe = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$renderer = Join-Path $env:USERPROFILE '.codex\plugins\cache\openai-primary-runtime\documents\26.909.12148\skills\documents\render_docx.py'
if (-not (Test-Path -LiteralPath $InputDocx -PathType Leaf)) {
  throw ('Updated DOCX not found: ' + $InputDocx)
}
if (-not (Test-Path -LiteralPath $programDir -PathType Container) -or
    -not (Test-Path -LiteralPath $popplerBin -PathType Container) -or
    -not (Test-Path -LiteralPath $pythonExe -PathType Leaf) -or
    -not (Test-Path -LiteralPath $renderer -PathType Leaf)) {
  throw 'Bundled Python, canonical renderer, isolated LibreOffice, or bundled Poppler path is missing.'
}
$resolvedInput = (Resolve-Path -LiteralPath $InputDocx).Path
$sha = [System.Security.Cryptography.SHA256]::Create()
$inputStream = [System.IO.File]::OpenRead($resolvedInput)
try {
  $inputHash = [BitConverter]::ToString($sha.ComputeHash($inputStream)).Replace('-', '').ToLowerInvariant()
} finally {
  $inputStream.Dispose()
  $sha.Dispose()
}
if ($inputHash -ne $ExpectedSha256.ToLowerInvariant()) {
  throw ('Input SHA-256 did not match the authorized final SHA; expected=' + $ExpectedSha256.ToLowerInvariant() + ';actual=' + $inputHash)
}
if (Test-Path -LiteralPath $outputDir -PathType Container) {
  $oldItems = @(Get-ChildItem -LiteralPath $outputDir -Force -ErrorAction SilentlyContinue)
  if ($oldItems.Count -gt 0) {
    throw ('Output directory is not empty; refusing to mix a new render: ' + $outputDir)
  }
} else {
  New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
}
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
$env:TEMP = $scratch
$env:TMP = $scratch
$env:TMPDIR = $scratch
$env:XDG_CONFIG_HOME = Join-Path $scratch 'xdg_config'
$env:XDG_CACHE_HOME = Join-Path $scratch 'xdg_cache'
$env:APPDATA = Join-Path $scratch 'appdata'
$env:LOCALAPPDATA = Join-Path $scratch 'localappdata'
$env:PATH = $programDir + ';' + $popplerBin + ';' + (Join-Path $env:SystemRoot 'System32')
New-Item -ItemType Directory -Force -Path $env:XDG_CONFIG_HOME,$env:XDG_CACHE_HOME,$env:APPDATA,$env:LOCALAPPDATA | Out-Null
$logPath = Join-Path $receiptDir 'updated_render_verbose.log'
$receiptPath = Join-Path $receiptDir 'updated_render_receipt.txt'
Set-Content -LiteralPath $receiptPath -Value 'Updated DOCX canonical render receipt' -Encoding UTF8
Add-Content -LiteralPath $receiptPath -Value ('input=' + $resolvedInput + ';sha256=' + $inputHash + ';expected_sha256=' + $ExpectedSha256.ToLowerInvariant()) -Encoding UTF8
Add-Content -LiteralPath $receiptPath -Value ('output=' + $outputDir + ';path=' + $env:PATH + ';scratch=' + $scratch) -Encoding UTF8
Add-Content -LiteralPath $receiptPath -Value 'unique_UserInstallation=canonical_render_docx.py_temp_profile;HOME=not_overridden_by_runner' -Encoding UTF8
Add-Content -LiteralPath $receiptPath -Value ('started_utc=' + (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ssZ')) -Encoding UTF8
& $pythonExe $renderer $resolvedInput --output_dir $outputDir --emit_pdf --verbose *> $logPath
$renderExit = $LASTEXITCODE
Add-Content -LiteralPath $receiptPath -Value ('renderer_exit_code=' + $renderExit + ';verbose_log=' + $logPath) -Encoding UTF8
if ($renderExit -ne 0) {
  Add-Content -LiteralPath $receiptPath -Value ('RESULT=FAILED;finished_utc=' + (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ssZ')) -Encoding UTF8
  exit $renderExit
}
$pages = @(Get-ChildItem -LiteralPath $outputDir -Filter 'page-*.png' -File)
$pdfPath = Join-Path $outputDir (([System.IO.Path]::GetFileNameWithoutExtension($resolvedInput)) + '.pdf')
$pdfBytes = if (Test-Path -LiteralPath $pdfPath -PathType Leaf) { (Get-Item -LiteralPath $pdfPath).Length } else { 0 }
$finished = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ssZ')
Add-Content -LiteralPath $receiptPath -Value ('page_png_count=' + $pages.Count + ';pdf=' + $pdfPath + ';pdf_bytes=' + $pdfBytes + ';finished_utc=' + $finished) -Encoding UTF8
if ($pages.Count -lt 1 -or $pdfBytes -lt 1) {
  Add-Content -LiteralPath $receiptPath -Value 'RESULT=INCOMPLETE;expected PNG pages and nonempty PDF'
  exit 21
}
Add-Content -LiteralPath $receiptPath -Value 'RESULT=SUCCESS'
