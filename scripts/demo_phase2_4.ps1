# scripts/demo_phase2_4.ps1
# Phase 2.4 demo: durable final logs.
#
# Assumes:
#   - Server is running on http://localhost:8000
#   - Agent "agent-1" is connected

$ErrorActionPreference = "Stop"

$apiBase = "http://localhost:8000"
$agentId = "agent-1"


function Submit-Job {
    param(
        [string]$Image,
        [string[]]$Command,
        [int]$TimeoutMs,
        [string]$IdempotencyKey
    )
    $body = @{
        agentId        = $agentId
        image          = $Image
        command        = $Command
        timeoutMs      = $TimeoutMs
        idempotencyKey = $IdempotencyKey
    } | ConvertTo-Json

    Invoke-RestMethod -Uri "$apiBase/jobs" -Method Post -Body $body -ContentType "application/json"
}


function Wait-ForJob {
    param([string]$JobId, [int]$TimeoutSeconds = 30)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastState = ""
    while ((Get-Date) -lt $deadline) {
        $job = Invoke-RestMethod -Uri "$apiBase/jobs/$JobId"
        if ($job.state -ne $lastState) {
            Write-Host "    state: $($job.state)"
            $lastState = $job.state
        }
        if ($job.state -in @("SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED")) {
            return $job
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Timed out waiting for job $JobId"
}


function Fetch-Logs {
    param([string]$JobId)
    Invoke-RestMethod -Uri "$apiBase/jobs/$JobId/logs"
}


function Show-Log {
    param([string]$Text, [string]$Header)
    Write-Host "    --- $Header ---"
    $Text.TrimEnd() -split "`n" | ForEach-Object { Write-Host "    $_" }
    Write-Host "    ---"
    Write-Host ""
}


Write-Host ""
Write-Host "=== Phase 2.4 Demo: Durable Final Logs ===" -ForegroundColor Cyan
Write-Host ""

$cmd = 'for i in 1 2 3 4 5; do echo "line $i"; done'

Write-Host "[1/3] Submit a job that prints five lines" -ForegroundColor Yellow

$job = Submit-Job `
    -Image "alpine:latest" `
    -Command @("sh", "-c", $cmd) `
    -TimeoutMs 30000 `
    -IdempotencyKey "demo-logs-$(Get-Random)"

Write-Host "    submitted: $($job.jobId)"
$null = Wait-ForJob -JobId $job.jobId
Write-Host ""

Write-Host "[2/3] Fetch persisted log" -ForegroundColor Yellow
$logsBefore = Fetch-Logs -JobId $job.jobId
Show-Log -Text $logsBefore -Header "log content (before restart)"

Write-Host "[3/3] Durability check" -ForegroundColor Yellow
Write-Host "    Restart the Server (Ctrl+C in Terminal 1, then start it again)."
Write-Host "    Then press ENTER to fetch the log again."
$null = Read-Host
Write-Host ""

$logsAfter = Fetch-Logs -JobId $job.jobId
Show-Log -Text $logsAfter -Header "log content (after restart)"

if ($logsBefore -eq $logsAfter) {
    Write-Host "  OK: log survived Server restart" -ForegroundColor Green
} else {
    Write-Host "  FAIL: log changed after restart" -ForegroundColor Red
    Write-Host "    before: $logsBefore"
    Write-Host "    after:  $logsAfter"
    exit 1
}

Write-Host ""
Write-Host "=== Demo complete ===" -ForegroundColor Cyan
Write-Host ""