# Run the functional survey one lineage per process.
#
# Why: on this host a Python process that builds several mothers in a row is killed without a
# traceback (exit -1/1).  One process per lineage keeps every run bounded, and the survey driver
# rewrites its JSON after every lineage, so a kill loses at most the lineage in flight.
#
# usage: pwsh -File data/a12_smoke/_tmp/run_census_loop.ps1 -Root <store> -Out <json> -Indices 51,30,5
param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$Out,
    [Parameter(Mandatory = $true)][string]$Indices,
    [string]$Config = "configs/a12/next_experiment.yaml",
    [string]$Label = "census"
)
$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\..\.."))
foreach ($index in ($Indices -split ",")) {
    $index = $index.Trim()
    if (-not $index) { continue }
    $stamp = Get-Date -Format "HH:mm:ss"
    Write-Output "[$stamp] index $index -> $Out"
    & .venv\Scripts\python.exe -X utf8 data\a12\reports\synthesis_functional_survey.py `
        --config $Config --root $Root --out $Out --indices $index --label $Label 2>&1 | Out-String -Width 400 | Write-Output
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] index $index exit=$LASTEXITCODE"
}
Write-Output "loop done for $Out"
