# scripts/demo_phase2_3.ps1
# Phase 2.3 demo: live log streaming over SSE.
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


Write-Host ""
Write-Host "=== Phase 2.3 Demo: Live Log Streaming ===" -ForegroundColor Cyan
Write-Host ""

$cmd = 'for i in 1 2 3 4 5; do echo "tick $i"; sleep 1; done'

Write-Host "[1/1] Submitting a job that prints once per second" -ForegroundColor Yellow

$job = Submit-Job `
    -Image "alpine:latest" `
    -Command @("sh", "-c", $cmd) `
    -TimeoutMs 30000 `
    -IdempotencyKey "demo-logs-$(Get-Random)"

Write-Host "    submitted: $($job.jobId)"
Write-Host ""
Write-Host "    streaming logs (each line should appear once per second):" -ForegroundColor Yellow
Write-Host ""

# curl.exe streams the SSE response line by line. It is built into Windows 10+.
& curl.exe --no-buffer -s -N "$apiBase/jobs/$($job.jobId)/logs/live"

Write-Host ""
Write-Host "=== Demo complete ===" -ForegroundColor Cyan
Write-Host ""