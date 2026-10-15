<#
.SYNOPSIS
    TradeSathi AI - Automated Disaster Recovery Verification Runner
    Milestone 2F Operational Hardening

.DESCRIPTION
    Runs automated disaster-recovery drill checks against an isolated restored instance,
    records results, and produces timestamped Markdown and JSON reports in reports/recovery/.
    Refuses unsafe paths resolving to the live database or storage.

.PARAMETER BackupPath
    Path to verified backup snapshot folder.

.PARAMETER RestoredDbPath
    Path to isolated restored SQLite database.

.PARAMETER RestoredStorageDir
    Path to isolated restored document storage directory.

.PARAMETER RecoveryUrl
    Base URL of isolated test server (default http://127.0.0.1:8001).

.PARAMETER OutputDir
    Directory for generated reports (default reports/recovery).

.PARAMETER RunRegressionSuite
    Optional switch to also execute the codebase test suites (backend pytest, frontend vitest, frontend build).
#>

[CmdletBinding()]
param (
    [Parameter(Mandatory = $false)]
    [string]$BackupPath = "backend\backups\backup_20261013_131946_d599fd",

    [Parameter(Mandatory = $false)]
    [string]$RestoredDbPath = "C:\Users\RAHUL\AppData\Local\Temp\tradesathi-restore-test-20261013-190724\tradesathi-test.db",

    [Parameter(Mandatory = $false)]
    [string]$RestoredStorageDir = "C:\Users\RAHUL\AppData\Local\Temp\tradesathi-restore-test-20261013-190724\documents",

    [Parameter(Mandatory = $false)]
    [string]$RecoveryUrl = "http://127.0.0.1:8001",

    [Parameter(Mandatory = $false)]
    [string]$OutputDir = "reports\recovery",

    [Parameter(Mandatory = $false)]
    [switch]$RunRegressionSuite
)

$ErrorActionPreference = "Stop"

# Determine repository root
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " TradeSathi AI - Disaster Recovery Verification Runner" -ForegroundColor Cyan
Write-Host " Project Root : $ProjectRoot"
Write-Host " Recovery URL : $RecoveryUrl"
Write-Host "================================================================================" -ForegroundColor Cyan

# 1. Critical Safety Boundary Checks
$LiveDb = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot "backend\tradesathi.db"))
$LiveStorage = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot "backend\storage\documents"))

$TargetDb = [System.IO.Path]::GetFullPath($RestoredDbPath)
$TargetStorage = [System.IO.Path]::GetFullPath($RestoredStorageDir)

Write-Host "[SAFETY CHECK] Validating destination isolation boundaries..." -ForegroundColor Yellow

if ($TargetDb -ieq $LiveDb) {
    Write-Error "CRITICAL SAFETY VIOLATION: Restored database path matches LIVE database ($LiveDb). Aborting immediately."
    exit 1
}

if ($TargetStorage -ieq $LiveStorage) {
    Write-Error "CRITICAL SAFETY VIOLATION: Restored storage path matches LIVE storage ($LiveStorage). Aborting immediately."
    exit 1
}

if ((Split-Path -Parent $TargetDb) -ieq (Split-Path -Parent $LiveDb) -and (Split-Path -Leaf $TargetDb) -ieq (Split-Path -Leaf $LiveDb)) {
    Write-Error "CRITICAL SAFETY VIOLATION: Restored database conflicts with live database in same directory ($TargetDb). Aborting."
    exit 1
}

Write-Host "[SAFETY CHECK] PASS: Target paths verified isolated from live database and storage." -ForegroundColor Green

# 2. Check Recovery Server Reachability Probe
Write-Host "[PROBE] Checking reachability of recovery API: $RecoveryUrl/api/health"
try {
    $HealthResponse = Invoke-RestMethod -Uri "$RecoveryUrl/api/health" -Method Get -TimeoutSec 3 -ErrorAction Stop
    $ApiStatus = $HealthResponse.status
    Write-Host "[PROBE] Recovery endpoint is online (status: $ApiStatus)." -ForegroundColor Green
}
catch {
    Write-Warning "Recovery endpoint at $RecoveryUrl did not respond to health probe. API verification checks will report BLOCKED."
}

# 3. Construct arguments for Python verification engine
$PyArgs = @(
    "-m", "backend.app.recovery_verifier",
    "--backup-path", $BackupPath,
    "--restored-db", $RestoredDbPath,
    "--restored-storage", $RestoredStorageDir,
    "--recovery-url", $RecoveryUrl,
    "--output-dir", $OutputDir
)

if ($RunRegressionSuite) {
    $PyArgs += "--run-regression-suite"
}

# 4. Execute verification runner
Write-Host "[EXECUTION] Launching automated disaster recovery verification..." -ForegroundColor Yellow
$Start = Get-Date

Push-Location $ProjectRoot
try {
    & python @PyArgs
    $PyExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

$ElapsedSec = [math]::Round(((Get-Date) - $Start).TotalSeconds, 2)
Write-Host "Execution completed in $ElapsedSec seconds." -ForegroundColor Cyan

# 5. Return appropriate exit code
if ($PyExitCode -ne 0) {
    Write-Host "[RESULT] Recovery verification completed with errors or blocked checks." -ForegroundColor Red
    exit $PyExitCode
} else {
    Write-Host "[RESULT] Recovery verification completed successfully." -ForegroundColor Green
    exit 0
}
