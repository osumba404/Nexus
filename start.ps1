# ─────────────────────────────────────────────────────────────────────────────
# Epicenter Nexus — Windows startup script
# Starts 3 Waitress worker processes behind a shared Nginx reverse proxy.
#
# Usage:
#   .\start.ps1              # production (3 workers × 8 threads)
#   .\start.ps1 -Workers 5 -Threads 12
#   .\start.ps1 -Dev         # single-process Django dev server
# ─────────────────────────────────────────────────────────────────────────────
param(
    [switch]$Dev,
    [int]$Workers = 3,
    [int]$Threads = 8,
    [int]$Port    = 8001
)

$Root  = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv  = Join-Path $Root "venv\Scripts\Activate.ps1"
$Manage = Join-Path $Root "manage.py"
$Serve  = Join-Path $Root "serve.py"

# Activate virtual environment
if (Test-Path $Venv) {
    & $Venv
} else {
    Write-Warning "Virtual environment not found at $Venv — using system Python."
}

Set-Location $Root

if ($Dev) {
    Write-Host "[Nexus] Starting development server…" -ForegroundColor Cyan
    python $Manage runserver 8080
    exit
}

# Run migrations
Write-Host "[Nexus] Applying database migrations…" -ForegroundColor Cyan
python $Manage migrate --noinput
if ($LASTEXITCODE -ne 0) {
    Write-Error "Migration failed. Aborting."
    exit 1
}

Write-Host "[Nexus] Starting $Workers Waitress workers on ports $Port–$($Port + $Workers - 1)…" -ForegroundColor Green
python $Serve --workers $Workers --threads $Threads --port $Port
