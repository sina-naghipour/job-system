# scripts/demo_phase2_2.ps1
# Phase 2.2 demo: timeout enforcement and user cancellation.
#
# Assumes:
#   - Server is running on http://localhost:8000
#   - Agent "agent-1" is connected to ws://localhost:8080
#
# Scenarios:
#   1. Job exceeds timeoutMs -> TIMED_OUT
#   2. User cancels a running Job -> CANCELLED
#   3. Cancel on a terminal Job -> 409 Conflict

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
    param(
        [string]$JobId,
        [int]$TimeoutSeconds = 30
    )
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


function Assert-Job-State {
    param(
        [string]$JobId,
        [string]$Expected
    )
    $job = Invoke-RestMethod -Uri "$apiBase/jobs/$JobId"
    if ($job.state -ne $Expected) {
        throw "Job $JobId expected $Expected but is $($job.state)"
    }
    Write-Host "  OK: job $JobId is $Expected" -ForegroundColor Green
}


# ---------------------------------------------------------------------------
# Scenario 1 — timeout
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "=== Phase 2.2 Demo ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "[1/3] Timeout: job sleeps 60s, timeout is 3s" -ForegroundColor Yellow

$job1 = Submit-Job `
    -Image "alpine:latest" `
    -Command @("sleep", "60") `
    -TimeoutMs 3000 `
    -IdempotencyKey "demo-timeout-$(Get-Random)"

Write-Host "    submitted: $($job1.jobId)"
$null = Wait-ForJob -JobId $job1.jobId
Assert-Job-State -JobId $job1.jobId -Expected "TIMED_OUT"

$result1 = Invoke-RestMethod -Uri "$apiBase/jobs/$($job1.jobId)/result"
Write-Host "    exitCode: $($result1.exitCode)"
Write-Host ""


# ---------------------------------------------------------------------------
# Scenario 2 — user cancellation
# ---------------------------------------------------------------------------

Write-Host "[2/3] Cancel: job sleeps 60s, cancelled after 2s" -ForegroundColor Yellow

$job2 = Submit-Job `
    -Image "alpine:latest" `
    -Command @("sleep", "60") `
    -TimeoutMs 60000 `
    -IdempotencyKey "demo-cancel-$(Get-Random)"

Write-Host "    submitted: $($job2.jobId)"
Start-Sleep -Seconds 2

$cancel = Invoke-RestMethod -Uri "$apiBase/jobs/$($job2.jobId)/cancel" -Method Post
Write-Host "    cancel response: state=$($cancel.state)"

$null = Wait-ForJob -JobId $job2.jobId
Assert-Job-State -JobId $job2.jobId -Expected "CANCELLED"
Write-Host ""


# ---------------------------------------------------------------------------
# Scenario 3 — cancel on a terminal job
# ---------------------------------------------------------------------------

Write-Host "[3/3] Cancel on a terminal job returns 409" -ForegroundColor Yellow

try {
    Invoke-RestMethod -Uri "$apiBase/jobs/$($job2.jobId)/cancel" -Method Post
    Write-Host "  FAIL: expected 409, got success" -ForegroundColor Red
    exit 1
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 409) {
        Write-Host "  OK: got 409 Conflict as expected" -ForegroundColor Green
    } else {
        Write-Host "  FAIL: expected 409, got $code" -ForegroundColor Red
        exit 1
    }
}
Write-Host ""


Write-Host "=== Demo complete ===" -ForegroundColor Cyan
Write-Host ""