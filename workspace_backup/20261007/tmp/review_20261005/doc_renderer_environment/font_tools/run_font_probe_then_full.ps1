$ErrorActionPreference = 'Stop'
$workspace = 'C:\Users\xiemo\Desktop\ShardForge'
$envRoot = Join-Path $workspace 'tmp\review_20261005\doc_renderer_environment\font_runtime'
$fontDir = Join-Path $envRoot 'fonts'
$probeDocx = Join-Path $envRoot 'font_probe_input.docx'
$sourceDocx = Join-Path $workspace 'RelicWeave_V1.46_Implementation_Update_20261005.docx'
$probeOutput = Join-Path $envRoot 'probe_render'
$fullOutput = Join-Path $workspace 'tmp\review_20261005\doc_render_fontfixed_01'
$probeScratch = Join-Path $envRoot 'scratch_probe'
$fullScratch = Join-Path $envRoot 'scratch_full'
$pythonExe = 'C:\Users\xiemo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$renderer = 'C:\Users\xiemo\.codex\plugins\cache\openai-primary-runtime\documents\26.909.12148\skills\documents\render_docx.py'
$verifyProbe = Join-Path $envRoot 'verify_pdf_font_probe.py'
$inspectFull = Join-Path $envRoot 'inspect_full_pdf_fonts.py'
$programDir = Join-Path $workspace 'third_party\doc-render-runtime\LibreOffice-26.8.0\program'
$popplerBin = 'C:\Users\xiemo\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin'
$receipt = Join-Path $envRoot 'fontfixed_render_receipt.txt'
$runLog = Join-Path $envRoot 'fontfixed_render_progress.log'
$expectedDocxSha = '85f3bb0e6115e208ce51c666d77ee756a4e2b74d67e8d039283574bb6764b531'
$expectedProbeSha = '345ecf37519aa0525f087076fd4cebb8e4f3758cb490930ec83ebf1338bb49d3'
$fontAssets = @(
  @{ Name='LiberationSans-Regular.ttf'; Sha='76d04c18ea243f426b7de1f3ad208e927008f961dc5945e5aad352d0dfde8ee8' },
  @{ Name='LiberationSans-Bold.ttf'; Sha='788abee4c806d660e8aee46689dd8540cd4bb98da03dcc9d171ce3efd99a9173' },
  @{ Name='LiberationSans-Italic.ttf'; Sha='e5bae5c4cde31f22142753855f4f8fb86da6ff39955ed3c0a11248b0d16948b0' },
  @{ Name='LiberationSans-BoldItalic.ttf'; Sha='698da70fc191cc5f33ad4d6d3fe830fe4624b898ea2e3169955928b7c491f1ee' },
  @{ Name='DroidSansFallback.ttf'; Sha='21b96a0377f067833a93af3082eb28d4ffab7a8cd46bfd513286f1d64b7b0949' }
)
$loadedFonts = [System.Collections.Generic.List[string]]::new()
$scriptStatus = 0
$cleanupFailed = $false
Set-Content -LiteralPath $runLog -Value '' -Encoding UTF8

function Write-RunLog([string]$message) {
  $line = ((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ssZ') + ' ' + $message)
  Add-Content -LiteralPath $runLog -Value $line -Encoding UTF8
  [Console]::Out.WriteLine($line)
}
function Get-Sha256Lower([string]$path) {
  return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Send-FontChangeNotification {
  $result = [IntPtr]::Zero
  $sendResult = [TaskFontApi20261005]::SendMessageTimeout([IntPtr]::new(-1), 0x001D, [IntPtr]::Zero, [IntPtr]::Zero, 0x0002, 1000, [ref]$result)
  Write-RunLog ('WM_FONTCHANGE broadcast_return=' + $sendResult.ToInt64())
}
function Set-TaskChildEnvironment([string]$scratch) {
  foreach ($d in @($scratch,(Join-Path $scratch 'xdg_config'),(Join-Path $scratch 'xdg_cache'),(Join-Path $scratch 'appdata'),(Join-Path $scratch 'localappdata'))) {
    if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d | Out-Null }
  }
  $env:TEMP = $scratch
  $env:TMP = $scratch
  $env:TMPDIR = $scratch
  $env:XDG_CONFIG_HOME = Join-Path $scratch 'xdg_config'
  $env:XDG_CACHE_HOME = Join-Path $scratch 'xdg_cache'
  $env:APPDATA = Join-Path $scratch 'appdata'
  $env:LOCALAPPDATA = Join-Path $scratch 'localappdata'
  $env:PATH = $programDir + ';' + $popplerBin + ';' + (Join-Path $env:SystemRoot 'System32')
  Write-RunLog ('CHILD_ENV scratch=' + $scratch + ';HOME=unchanged;PATH=' + $env:PATH)
}
function Invoke-BoundedPython([string]$label,[string[]]$argumentValues,[int]$timeoutSeconds,[string]$stdoutPath,[string]$stderrPath) {
  $quoted = foreach ($value in $argumentValues) { '"' + $value.Replace('"','\"') + '"' }
  $argumentLine = [string]::Join(' ', [string[]]$quoted)
  $proc = Start-Process -FilePath $pythonExe -ArgumentList $argumentLine -WorkingDirectory $workspace -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
  Write-RunLog ('PROCESS_START label=' + $label + ';pid=' + $proc.Id + ';timeout_seconds=' + $timeoutSeconds)
  $timer = [Diagnostics.Stopwatch]::StartNew()
  $timedOut = $false
  while ($true) {
    $remainingMs = ($timeoutSeconds * 1000) - [int]$timer.ElapsedMilliseconds
    if ($remainingMs -le 0) { $timedOut = $true; break }
    $waitMs = [Math]::Min(30000, $remainingMs)
    if ($proc.WaitForExit($waitMs)) { break }
    Write-RunLog ('PROCESS_PROGRESS label=' + $label + ';pid=' + $proc.Id + ';elapsed_seconds=' + [int]$timer.Elapsed.TotalSeconds)
  }
  if ($timedOut) {
    Write-RunLog ('PROCESS_TIMEOUT label=' + $label + ';pid=' + $proc.Id + ';elapsed_seconds=' + [int]$timer.Elapsed.TotalSeconds + ';action=taskkill_exact_root_process_tree')
    & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $proc.Id /T /F | Out-Null
    [void]$proc.WaitForExit(10000)
    $proc.Dispose()
    throw ($label + ' timed out after ' + $timeoutSeconds + ' seconds; task process tree rooted at PID was terminated.')
  }
  $proc.WaitForExit()
  $proc.Refresh()
  $exitCode = $proc.ExitCode
  Write-RunLog ('PROCESS_EXIT label=' + $label + ';pid=' + $proc.Id + ';exit_code=' + $exitCode + ';stdout=' + $stdoutPath + ';stderr=' + $stderrPath)
  $proc.Dispose()
  return $exitCode
}
function Invoke-CanonicalRender([string]$label,[string]$inputDocx,[string]$expectedSha,[string]$outputDir,[string]$scratch) {
  if (-not (Test-Path -LiteralPath $inputDocx -PathType Leaf)) { throw ('Render input missing: ' + $inputDocx) }
  $actual = Get-Sha256Lower $inputDocx
  if ($actual -ne $expectedSha) { throw ($label + ' input SHA-256 mismatch; expected=' + $expectedSha + ';actual=' + $actual) }
  if (Test-Path -LiteralPath $outputDir -PathType Container) {
    $items = @(Get-ChildItem -LiteralPath $outputDir -Force)
    if ($items.Count -gt 0) { throw ('Refusing to mix output in nonempty directory: ' + $outputDir) }
  } else {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
  }
  Set-TaskChildEnvironment $scratch
  $stem = Join-Path $envRoot ($label + '_canonical')
  $stdoutPath = $stem + '.stdout.log'
  $stderrPath = $stem + '.stderr.log'
  $pythonArguments = @($renderer,$inputDocx,'--output_dir',$outputDir,'--emit_pdf','--verbose')
  $exitCode = Invoke-BoundedPython $label $pythonArguments 180 $stdoutPath $stderrPath
  if ($exitCode -ne 0) { throw ($label + ' canonical renderer returned exit code ' + $exitCode) }
  $pdfPath = Join-Path $outputDir ([IO.Path]::GetFileNameWithoutExtension($inputDocx) + '.pdf')
  $pngFiles = @(Get-ChildItem -LiteralPath $outputDir -File -Filter 'page-*.png')
  if (-not (Test-Path -LiteralPath $pdfPath -PathType Leaf)) { throw ($label + ' PDF was not produced: ' + $pdfPath) }
  $pdfBytes = (Get-Item -LiteralPath $pdfPath).Length
  if ($pdfBytes -lt 1 -or $pngFiles.Count -lt 1) { throw ($label + ' produced an empty PDF or no page PNGs.') }
  Write-RunLog ('CANONICAL_RESULT label=' + $label + ';exit=0;docx_sha256=' + $actual + ';pdf=' + $pdfPath + ';pdf_bytes=' + $pdfBytes + ';png_count=' + $pngFiles.Count)
  return @{ Pdf=$pdfPath; PngCount=$pngFiles.Count; PdfBytes=$pdfBytes; InputSha=$actual }
}

try {
  if (Test-Path -LiteralPath $receipt) { throw ('Refusing to overwrite prior font registration receipt: ' + $receipt) }
  if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf) -or -not (Test-Path -LiteralPath $renderer -PathType Leaf) -or -not (Test-Path -LiteralPath $programDir -PathType Container) -or -not (Test-Path -LiteralPath $popplerBin -PathType Container)) { throw 'Canonical renderer or bundled runtime path missing.' }
  if (-not (Test-Path -LiteralPath $probeDocx -PathType Leaf) -or -not (Test-Path -LiteralPath $sourceDocx -PathType Leaf)) { throw 'Probe or final source DOCX missing.' }
  $probeActual = Get-Sha256Lower $probeDocx
  $sourceActual = Get-Sha256Lower $sourceDocx
  if ($probeActual -ne $expectedProbeSha) { throw ('Probe DOCX SHA mismatch; expected=' + $expectedProbeSha + ';actual=' + $probeActual) }
  if ($sourceActual -ne $expectedDocxSha) { throw ('Final DOCX SHA mismatch; expected=' + $expectedDocxSha + ';actual=' + $sourceActual) }
  foreach ($font in $fontAssets) {
    $path = Join-Path $fontDir $font.Name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw ('Required task font missing: ' + $path) }
    $hash = Get-Sha256Lower $path
    if ($hash -ne $font.Sha) { throw ('Font SHA-256 mismatch; refusing registration: ' + $font.Name + ';actual=' + $hash) }
    Write-RunLog ('FONT_PRECHECK name=' + $font.Name + ';bytes=' + (Get-Item -LiteralPath $path).Length + ';sha256=' + $hash)
  }
  foreach ($dir in @($probeOutput,$fullOutput)) {
    if (Test-Path -LiteralPath $dir -PathType Container) {
      $items = @(Get-ChildItem -LiteralPath $dir -Force)
      if ($items.Count -gt 0) { throw ('Output path is not fresh; refusing to overwrite/mix: ' + $dir) }
    }
  }
  [void](New-Item -ItemType Directory -Force -Path $envRoot)
  Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class TaskFontApi20261005 {
  [DllImport("gdi32.dll", CharSet=CharSet.Unicode, SetLastError=true, EntryPoint="AddFontResourceExW")]
  public static extern int AddFontResourceEx(string fileName, uint flags, IntPtr reserved);
  [DllImport("gdi32.dll", CharSet=CharSet.Unicode, SetLastError=true, EntryPoint="RemoveFontResourceExW")]
  [return: MarshalAs(UnmanagedType.Bool)]
  public static extern bool RemoveFontResourceEx(string fileName, uint flags, IntPtr reserved);
  [DllImport("user32.dll", SetLastError=true, EntryPoint="SendMessageTimeoutW")]
  public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam, uint flags, uint timeout, out IntPtr result);
}
"@
  foreach ($font in $fontAssets) {
    $path = (Resolve-Path -LiteralPath (Join-Path $fontDir $font.Name)).Path
    $added = [TaskFontApi20261005]::AddFontResourceEx($path,0,[IntPtr]::Zero)
    if ($added -lt 1) { throw ('AddFontResourceEx failed for ' + $font.Name + ';win32=' + [Runtime.InteropServices.Marshal]::GetLastWin32Error()) }
    $loadedFonts.Add($path)
    Write-RunLog ('FONT_REGISTER flags=0;fonts_added=' + $added + ';path=' + $path)
  }
  Send-FontChangeNotification
  Add-Type -AssemblyName System.Drawing
  $gdiNames = @((New-Object System.Drawing.Text.InstalledFontCollection).Families | ForEach-Object { $_.Name })
  $gdiLib = $gdiNames -contains 'Liberation Sans'
  $gdiDroid = $gdiNames -contains 'Droid Sans Fallback'
  Write-RunLog ('GDI_FAMILY_PROBE liberation_sans=' + $gdiLib + ';droid_sans_fallback=' + $gdiDroid)

  Set-Content -LiteralPath $receipt -Value 'Task-local font registration and canonical renderer receipt' -Encoding UTF8
  Add-Content -LiteralPath $receipt -Value ('source_docx=' + $sourceDocx + ';sha256=' + $sourceActual + ';expected=' + $expectedDocxSha) -Encoding UTF8
  Add-Content -LiteralPath $receipt -Value ('probe_docx=' + $probeDocx + ';sha256=' + $probeActual + ';source_normal_fonts=ascii/hAnsi/cs Liberation Sans;eastAsia Droid Sans Fallback') -Encoding UTF8
  Add-Content -LiteralPath $receipt -Value ('font_registration=AddFontResourceExW flags=0;current_session_only;no_registry_write;WM_FONTCHANGE broadcast;fonts=' + ($fontAssets.Name -join ',')) -Encoding UTF8
  Add-Content -LiteralPath $receipt -Value ('gdi_family_probe=liberation_sans:' + $gdiLib + ',droid_sans_fallback:' + $gdiDroid) -Encoding UTF8
  Add-Content -LiteralPath $receipt -Value 'HOME=unchanged;system_PATH=unchanged;canonical_renderer_source=unmodified'
  Add-Content -LiteralPath $receipt -Value ('started_utc=' + (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ssZ')) -Encoding UTF8

  $probeRun = Invoke-CanonicalRender 'font_probe' $probeDocx $expectedProbeSha $probeOutput $probeScratch
  $probeReport = Join-Path $envRoot 'font_probe_pdf_diagnostics.json'
  $verifyOut = Join-Path $envRoot 'font_probe_verify.stdout.log'
  $verifyErr = Join-Path $envRoot 'font_probe_verify.stderr.log'
  Set-TaskChildEnvironment $probeScratch
  $verifyArgs = @($verifyProbe,'--pdf',$probeRun.Pdf,'--png-dir',$probeOutput,'--report',$probeReport)
  $verifyExit = Invoke-BoundedPython 'font_probe_pdf_verification' $verifyArgs 60 $verifyOut $verifyErr
  Add-Content -LiteralPath $receipt -Value ('probe_pdf=' + $probeRun.Pdf + ';pdf_bytes=' + $probeRun.PdfBytes + ';png_count=' + $probeRun.PngCount + ';verify_exit=' + $verifyExit + ';diagnostics=' + $probeReport) -Encoding UTF8
  if ($verifyExit -ne 0 -or -not (Test-Path -LiteralPath $probeReport -PathType Leaf)) { throw ('Probe font verification did not pass; verify_exit=' + $verifyExit + '; full book will not be rendered.') }
  $probeCheck = Get-Content -LiteralPath $probeReport -Raw | ConvertFrom-Json
  if (-not $probeCheck.visual_probe_gate_passed) { throw 'Probe PDF does not embed and use both requested font families on actual sample characters; full book will not be rendered.' }
  Add-Content -LiteralPath $receipt -Value ('PROBE_GATE=PASS;embedded_and_character_used=Liberation Sans+Droid Sans Fallback;pdf_pages=' + $probeCheck.page_count) -Encoding UTF8
  Write-RunLog ('PROBE_GATE=PASS;pdf=' + $probeRun.Pdf + ';png_count=' + $probeRun.PngCount + ';liberation=' + ($probeCheck.ascii_probe_fontnames -join ',') + ';droid=' + ($probeCheck.cjk_probe_fontnames -join ','))

  $fullRun = Invoke-CanonicalRender 'fontfixed_full_book' $sourceDocx $expectedDocxSha $fullOutput $fullScratch
  $fullPdfReport = Join-Path $envRoot 'fontfixed_full_pdf_font_inventory.json'
  $inspectOut = Join-Path $envRoot 'fontfixed_full_pdf_inspect.stdout.log'
  $inspectErr = Join-Path $envRoot 'fontfixed_full_pdf_inspect.stderr.log'
  Set-TaskChildEnvironment $fullScratch
  $inspectArgs = @($inspectFull,$fullRun.Pdf,$fullPdfReport)
  $inspectExit = Invoke-BoundedPython 'full_pdf_font_inventory' $inspectArgs 60 $inspectOut $inspectErr
  $fullCheck = $null
  if (Test-Path -LiteralPath $fullPdfReport -PathType Leaf) { $fullCheck = Get-Content -LiteralPath $fullPdfReport -Raw | ConvertFrom-Json }
  $sourceFinal = Get-Sha256Lower $sourceDocx
  Add-Content -LiteralPath $receipt -Value ('full_pdf=' + $fullRun.Pdf + ';pdf_bytes=' + $fullRun.PdfBytes + ';png_count=' + $fullRun.PngCount + ';source_sha256_after=' + $sourceFinal + ';font_inventory_exit=' + $inspectExit + ';font_inventory=' + $fullPdfReport) -Encoding UTF8
  if ($sourceFinal -ne $expectedDocxSha) { throw ('Source DOCX hash changed during task; after=' + $sourceFinal) }
  if ($null -ne $fullCheck) {
    Add-Content -LiteralPath $receipt -Value ('full_pdf_pages=' + $fullCheck.pdf_page_count + ';both_requested_fonts_used_and_embedded=' + $fullCheck.both_expected_fonts_used_and_embedded) -Encoding UTF8
    Write-RunLog ('FULL_FONT_CHECK pages=' + $fullCheck.pdf_page_count + ';liberation_embedded=' + $fullCheck.liberation_sans_embedded + ';droid_embedded=' + $fullCheck.droid_sans_fallback_embedded + ';liberation_chars=' + $fullCheck.liberation_sans_used_by_chars + ';droid_chars=' + $fullCheck.droid_sans_fallback_used_by_chars)
  }
  Add-Content -LiteralPath $receipt -Value ('FULL_RENDER=SUCCESS;finished_utc=' + (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ssZ')) -Encoding UTF8
  Write-RunLog ('FULL_RENDER=SUCCESS;pdf=' + $fullRun.Pdf + ';png_count=' + $fullRun.PngCount)
} catch {
  $scriptStatus = 1
  $message = $_.Exception.Message
  Write-RunLog ('TASK_ERROR=' + $message)
  if (Test-Path -LiteralPath $receipt -PathType Leaf) { Add-Content -LiteralPath $receipt -Value ('TASK_ERROR=' + $message) -Encoding UTF8 }
} finally {
  for ($i = $loadedFonts.Count - 1; $i -ge 0; $i--) {
    $path = $loadedFonts[$i]
    try {
      $removed = [TaskFontApi20261005]::RemoveFontResourceEx($path,0,[IntPtr]::Zero)
      Write-RunLog ('FONT_REMOVE flags=0;success=' + $removed + ';path=' + $path)
      if (-not $removed) { $cleanupFailed = $true }
    } catch {
      $cleanupFailed = $true
      Write-RunLog ('FONT_REMOVE_ERROR path=' + $path + ';message=' + $_.Exception.Message)
    }
  }
  if ($loadedFonts.Count -gt 0) {
    try { Send-FontChangeNotification } catch { $cleanupFailed = $true; Write-RunLog ('WM_FONTCHANGE_REMOVE_ERROR=' + $_.Exception.Message) }
  }
  Write-RunLog ('FONT_CLEANUP complete=' + (-not $cleanupFailed) + ';removed_count=' + $loadedFonts.Count)
  if (Test-Path -LiteralPath $receipt -PathType Leaf) { Add-Content -LiteralPath $receipt -Value ('font_cleanup_complete=' + (-not $cleanupFailed) + ';removed_count=' + $loadedFonts.Count + ';finished_utc=' + (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ssZ')) -Encoding UTF8 }
  if ($cleanupFailed) { $scriptStatus = 2 }
}
if ($scriptStatus -eq 0) { Write-RunLog 'RESULT=SUCCESS' } else { Write-RunLog ('RESULT=FAILED;status=' + $scriptStatus) }
exit $scriptStatus

