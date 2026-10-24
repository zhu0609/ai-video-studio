$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
docker compose up --build -d
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose failed. Ensure Docker Desktop is running.' }
Write-Host 'Open http://127.0.0.1:8000 . Stop with: docker compose down'
