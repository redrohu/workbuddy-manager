# Clean build artifacts and temporary test files (conservative).
#
# Default is a DRY RUN: it only lists what would be removed.
# Add -Apply to actually delete.
#
#   powershell -ExecutionPolicy Bypass -File dev\clean-build-artifacts.ps1
#   powershell -ExecutionPolicy Bypass -File dev\clean-build-artifacts.ps1 -Apply
#
# NOT touched: .venv, web\node_modules, data\, .env, upstream\, .tools\,
#              dev\ screenshots / fixture data, source files.
# Note: removing web\out means start.cmd has no frontend until you run
#       `npm run build:export` again (packaging rebuilds it anyway).

param([switch]$Apply)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Never descend into these
$skipDirs = @('.git', '.venv', 'venv', 'node_modules', 'data', 'upstream', '.tools', '.runtime')
# Directory names removed wherever they appear
$junkDirNames = @('__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache')

$targets = New-Object System.Collections.Generic.List[string]

function Add-IfExists([string]$rel) {
    $p = Join-Path $root $rel
    if (Test-Path -LiteralPath $p) { $targets.Add($p) }
}

# Fixed build outputs
Add-IfExists 'web\.next'
Add-IfExists 'web\out'
Add-IfExists 'web\next-env.d.ts'
Add-IfExists 'server\tests\_dt_tmp'
Add-IfExists 'windows\launcher\dist'
Add-IfExists 'windows\launcher\obj'

# Walk the tree, skipping heavy / sensitive directories
function Walk([string]$dir) {
    foreach ($item in Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue) {
        if ($item.PSIsContainer) {
            if ($skipDirs -contains $item.Name) { continue }
            if ($item.FullName -eq (Join-Path $root 'web\.next') -or
                $item.FullName -eq (Join-Path $root 'web\out')) { continue }
            if ($junkDirNames -contains $item.Name) { $targets.Add($item.FullName); continue }
            Walk $item.FullName
        } else {
            if ($item.Extension -in @('.pyc', '.pyo', '.tsbuildinfo', '.log')) { $targets.Add($item.FullName) }
        }
    }
}
Walk $root

# Root-level temp files covered by .gitignore (.sec*.py security probes, .*.png debug shots)
Get-ChildItem -LiteralPath $root -Force -File | Where-Object {
    $_.Name -like '.sec*.py' -or $_.Name -like '.*.png'
} | ForEach-Object { $targets.Add($_.FullName) }

# De-duplicate and drop files that sit inside an already-listed directory
$sorted = $targets | Sort-Object -Unique
$final = @()
foreach ($t in $sorted) {
    if (-not ($final | Where-Object { $t.StartsWith($_ + '\') })) { $final += $t }
}

if ($final.Count -eq 0) { Write-Host 'Nothing to clean.'; exit 0 }

$total = 0
foreach ($t in $final) {
    $size = (Get-ChildItem -LiteralPath $t -Recurse -Force -File -ErrorAction SilentlyContinue |
             Measure-Object Length -Sum).Sum
    if (-not $size) { $size = (Get-Item -LiteralPath $t -Force).Length }
    $total += [int64]$size
    '{0,10:N1} KB  {1}' -f ($size / 1KB), $t.Substring($root.Length + 1)
}
Write-Host ('{0} item(s), {1:N1} MB total' -f $final.Count, ($total / 1MB))

if (-not $Apply) {
    Write-Host 'Dry run only. Re-run with -Apply to delete.' -ForegroundColor Yellow
    exit 0
}

foreach ($t in $final) { Remove-Item -LiteralPath $t -Recurse -Force -ErrorAction Continue }
Write-Host 'Done.' -ForegroundColor Green
