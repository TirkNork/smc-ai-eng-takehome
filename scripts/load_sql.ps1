$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

$pgUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "postgres" }
$pgDb   = if ($env:POSTGRES_DB)   { $env:POSTGRES_DB }   else { "findb" }

do {
    docker compose exec postgres pg_isready -U $pgUser -d $pgDb *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "waiting for postgres..."
        Start-Sleep -Seconds 1
    }
} while ($LASTEXITCODE -ne 0)

Get-Content data/financial_data.sql -Raw | docker compose exec -T postgres psql -U $pgUser -d $pgDb
Write-Host "loaded financial_data.sql"
