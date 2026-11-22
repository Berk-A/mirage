<##
.SYNOPSIS
Run one evaluation or practice pass end-to-end.

.EXAMPLE
.\scripts\eval.ps1
.\scripts\eval.ps1 --tries 3
.\scripts\eval.ps1 --scenario practice --targets julius
##>

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

# Load simple KEY=VALUE entries from the repository .env into this process.
$envFile = Join-Path $repoRoot ".env"
if (Test-Path -LiteralPath $envFile -PathType Leaf) {
    Get-Content -LiteralPath $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line -match "^\s*([^#=]+?)\s*=(.*?)\s*$") {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
                ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

$python = $env:PYTHON
if ([string]::IsNullOrWhiteSpace($python)) {
    $python = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        if (Get-Command python -ErrorAction SilentlyContinue) {
            $python = "python"
        } elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
            $python = "python3"
        } else {
            $python = "py"
        }
    }
}

& $python -m experiments.run_eval @args
exit $LASTEXITCODE
