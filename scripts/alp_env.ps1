# ALP environment bootstrap — run before any python command in this repo.
$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = @(
    $root,
    (Join-Path $root 'policy-engine'),
    (Join-Path $root 'capability-engine'),
    (Join-Path $root 'verification-engine'),
    (Join-Path $root 'compatibility'),
    (Join-Path $root 'vendor-adapters'),
    $env:PYTHONPATH
) -join ';'
Write-Host "ALP PYTHONPATH set: $env:PYTHONPATH"