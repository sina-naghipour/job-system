# scripts/demo_phase3_1.ps1
# Phase 3.1 demo: priority scheduling.
#
# Assumes Server and Agent are running.

$ErrorActionPreference = "Stop"

$apiBase = "http://localhost:8000"
$agentId = "agent-1"


function Submit-Job {
    param(
        [string]$Image,
        [string[]]$Command,
        [int]$TimeoutMs,
        [string]$IdempotencyKey,
        [int]$Priority
    )
    $body = @{
        agentId        = $agentId
        image          = $Image
        command        = $Command
        timeoutMs      = $TimeoutMs
        idempotencyKey = $IdempotencyKey
        priority       = $Priority
    } | ConvertTo-Json

    Invoke-RestMethod -Uri "$apiBase/jobs" -Method Post -Body $body -ContentType "application/json"
}


function Get-Job {
    param([string]$JobId)
    Invoke-RestMethod -Uri "$apiBase/jobs/$JobId"
}


Write-Host ""
Write-Host "=== Phase 3.1 Demo: Priority ===" -ForegroundColor Cyan
Write-Host ""

# First, occupy the agent with a slow batch Job so a queue builds up behind it.
Write-Host "[1/2] Occupy the agent with a slow batch Job" -ForegroundColor Yellow

$blocker = Submit-Job `
    -Image "alpine:latest" `
    -Command @("sleep", "8") `
    -TimeoutMs 30000 `
    -IdempotencyKey "p3-blocker-$(Get-Random)" `
    -Priority 2

Write-Host "    blocker: $($blocker.jobId) (priority 2, batch)"
Start-Sleep -Seconds 1
Write-Host ""

# Now submit three jobs. Batch first, then normal, then interactive.
# Without priority, they would run in submission order.
Write-Host "[2/2] Submit three jobs in the wrong order for FIFO" -ForegroundColor Yellow

$batch = Submit-Job `
    -Image "alpine:latest" `
    -Command @("echo", "batch") `
    -TimeoutMs 30000 `
    -IdempotencyKey "p3-batch-$(Get-Random)" `
    -Priority 2

$normal = Submit-Job `
    -Image "alpine:latest" `
    -Command @("echo", "normal") `
    -TimeoutMs 30000 `
    -IdempotencyKey "p3-normal-$(Get-Random)" `
    -Priority 1

$interactive = Submit-Job `
    -Image "alpine:latest" `
    -Command @("echo", "interactive") `
    -TimeoutMs 30000 `
    -IdempotencyKey "p3-interactive-$(Get-Random)" `
    -Priority 0

Write-Host "    batch:       $($batch.jobId)      (priority 2)"
Write-Host "    normal:      $($normal.jobId)     (priority 1)"
Write-Host "    interactive: $($interactive.jobId) (priority 0)"
Write-Host ""
Write-Host "    Expected completion order:" -ForegroundColor Yellow
Write-Host "      1. blocker     (already running, finishes first)"
Write-Host "      2. interactive (priority 0)"
Write-Host "      3. normal      (priority 1)"
Write-Host "      4. batch       (priority 2)"
Write-Host ""

$jobs = @($blocker, $interactive, $normal, $batch)
$finishedOrder = @()
$deadline = (Get-Date).AddSeconds(30)

while ((Get-Date) -lt $deadline -and $finishedOrder.Count -lt $jobs.Count) {
    foreach ($j in $jobs) {
        if ($finishedOrder -contains $j.jobId) { continue }
        $job = Get-Job -JobId $j.jobId
        if ($job.state -in @("SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED")) {
            $finishedOrder += $j.jobId
            Write-Host "    finished: $($j.jobId) (priority $($job.priority))"
        }
    }
    Start-Sleep -Milliseconds 500
}

Write-Host ""

if ($finishedOrder.Count -lt 4) {
    Write-Host "  FAIL: only $($finishedOrder.Count) of 4 jobs finished" -ForegroundColor Red
    exit 1
}

if ($finishedOrder[0] -eq $blocker.jobId -and
    $finishedOrder[1] -eq $interactive.jobId -and
    $finishedOrder[2] -eq $normal.jobId -and
    $finishedOrder[3] -eq $batch.jobId) {
    Write-Host "  OK: blocker finished first, then priority order respected" -ForegroundColor Green
} else {
    Write-Host "  FAIL: completion order was $($finishedOrder -join ' -> ')" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Demo complete ===" -ForegroundColor Cyan
Write-Host ""