param([int]$IntervalMinutes = 15, [int]$MaxIterations = 96)
# Periodic checkpoint loop: commits only compile-clean snapshots and pushes to origin/main.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$log = Join-Path $root "data/a12/reports/git_commit_log.txt"
$py  = Join-Path $root ".venv/Scripts/python.exe"
$env:GIT_TERMINAL_PROMPT = "0"
for ($i = 1; $i -le $MaxIterations; $i++) {
  $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  $dirty = (git status --porcelain | Measure-Object -Line).Lines
  if ($dirty -gt 0) {
    $bad = 0
    git status --porcelain | ForEach-Object {
      $f = $_.Substring(3).Trim()
      if ($f -like "*.py" -and (Test-Path $f)) { & $py -m py_compile $f 2>$null; if ($LASTEXITCODE -ne 0) { $script:bad++ } }
    }
    if ($bad -eq 0) {
      git add -A 2>&1 | Out-Null
      git -c user.email="synlab@local" -c user.name="A12 SynLab" commit -q -m "auto: periodic checkpoint $stamp ($dirty paths)"
      $push = (git push origin main 2>&1 | Select-Object -Last 1)
      Add-Content $log "$stamp | committed $dirty paths | $push"
    } else {
      Add-Content $log "$stamp | SKIPPED: $bad python file(s) fail py_compile (mid-edit snapshot)"
    }
  } else {
    Add-Content $log "$stamp | no changes"
  }
  Start-Sleep -Seconds ($IntervalMinutes * 60)
}
