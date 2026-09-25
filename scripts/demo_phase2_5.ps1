# scripts/demo_phase2_5.ps1
# Phase 2.5 demo: ack-based delivery.
#
# Assumes:
#   - Server is running on http://localhost:8000
#   - A fake agent is running that registers as "agent-noack" and never acks
#     (see scripts/fake_agent_noack.py)

$ErrorActionPreference = "Stop"

$apiBase = "http://localhost:8000"
$agentId = "agent-noack"


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


function Get-Job {
    param([string]$JobId)
    Invoke-RestMethod -Uri "$apiBase/jobs/$JobId"
}


Write-Host ""
Write-Host "=== Phase 2.5 Demo: Ack-Based Delivery ===" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/1] Submit a job to an agent that never acks" -ForegroundColor Yellow

$job = Submit-Job `
    -Image "alpine:latest" `
    -Command @("echo", "this will never run") `
    -TimeoutMs 30000 `
    -IdempotencyKey "demo-noack-$(Get-Random)"

Write-Host "    submitted: $($job.jobId)"
Write-Host "    target:    $agentId"
Write-Host ""

Write-Host "    watching job state (ack timeout is 5s, max attempts is 3):" -ForegroundColor Yellow
Write-Host ""

$lastState = ""
$lastAttempts = -1
$deadline = (Get-Date).AddSeconds(45)

while ((Get-Date) -lt $deadline) {
    $j = Get-Job -JobId $job.jobId

    if ($j.state -ne $lastState -or $j.dispatchAttempts -ne $lastAttempts) {
        Write-Host "  state=$($j.state)  dispatchAttempts=$($j.dispatchAttempts)"
        $lastState = $j.state
        $lastAttempts = $j.dispatchAttempts
    }

    if ($j.state -in @("SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED")) {
        break
    }
    Start-Sleep -Milliseconds 500
}

$final = Get-Job -JobId $job.jobId
Write-Host ""
Write-Host "  final state: $($final.state)"
Write-Host "  attempts:    $($final.dispatchAttempts)"
if ($final.error) {
    Write-Host "  error:       $($final.error)"
}

if ($final.state -eq "FAILED" -and $final.dispatchAttempts -ge 3) {
    Write-Host ""
    Write-Host "  OK: job requeued, retried, and finally failed after max attempts" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "  FAIL: expected FAILED after 3 attempts" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Demo complete ===" -ForegroundColor Cyan
Write-Host ""