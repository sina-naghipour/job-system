# scripts/demo_phase3_1_starvation.ps1
# Phase 3.1 demo: starvation.
#
# Shows that a low-priority Job can starve when higher-priority Jobs
# keep arriving at a rate faster than the Agent can drain them.
# Aging (v0.3.3) will fix this.
#
# Assumes Server and Agent are running.

$ErrorActionPreference = "Stop"

$apiBase = "http://localhost:8000"
$agentId = "agent-1"

$floodSeconds = 30
$interactiveDurationSeconds = 2
$submissionIntervalMs = 200


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
Write-Host "=== Phase 3.1 Demo: Starvation ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Interactive Jobs run for $interactiveDurationSeconds second(s) each."
Write-Host "  New interactive Jobs are submitted every $submissionIntervalMs ms."
Write-Host "  The queue grows faster than the Agent drains it."
Write-Host ""

# Step 1: flood the queue with interactive Jobs FIRST.
# The Agent will be busy with interactive work the entire time.
Write-Host "[1/3] Flood the queue with interactive Jobs for $floodSeconds seconds" -ForegroundColor Yellow
Write-Host ""

$interactiveIds = @()
$floodDeadline = (Get-Date).AddSeconds($floodSeconds)
$interactiveCommand = @("sh", "-c", "sleep $interactiveDurationSeconds")

while ((Get-Date) -lt $floodDeadline) {
    $job = Submit-Job `
        -Image "alpine:latest" `
        -Command $interactiveCommand `
        -TimeoutMs 30000 `
        -IdempotencyKey "starve-interactive-$(Get-Random)" `
        -Priority 0
    $interactiveIds += $job.jobId
    Start-Sleep -Milliseconds $submissionIntervalMs
}

Write-Host "    submitted $($interactiveIds.Count) interactive Jobs"
Write-Host ""

# Step 2: submit a batch Job. It enters PENDING at priority 2,
# behind every interactive Job still in the queue.
Write-Host "[2/3] Submit a batch Job (priority 2) while the queue is full" -ForegroundColor Yellow

$batch = Submit-Job `
    -Image "alpine:latest" `
    -Command @("echo", "batch") `
    -TimeoutMs 30000 `
    -IdempotencyKey "starve-batch-$(Get-Random)" `
    -Priority 2

Write-Host "    batch: $($batch.jobId)"
Write-Host ""

# Step 3: wait a few more seconds, then check.
Write-Host "[3/3] Wait 10 seconds and check the batch Job" -ForegroundColor Yellow
Write-Host ""

Start-Sleep -Seconds 10

$batchJob = Get-Job -JobId $batch.jobId
Write-Host "    batch state: $($batchJob.state)"

$pendingInteractive = 0
foreach ($id in $interactiveIds) {
    $state = (Get-Job -JobId $id).state
    if ($state -eq "PENDING" -or $state -eq "DISPATCHED" -or $state -eq "RUNNING") {
        $pendingInteractive++
    }
}

Write-Host "    interactive still not finished: $pendingInteractive of $($interactiveIds.Count)"
Write-Host ""

if ($batchJob.state -eq "PENDING") {
    Write-Host "  STARVED: the batch Job never ran." -ForegroundColor Magenta
    Write-Host "  High-priority Jobs kept arriving faster than the Agent could finish them." -ForegroundColor Magenta
    Write-Host "  Aging (v0.3.3) will prevent this." -ForegroundColor Magenta
} elseif ($batchJob.state -eq "DISPATCHED" -or $batchJob.state -eq "RUNNING") {
    Write-Host "  NOT YET STARVED: the batch Job is now running." -ForegroundColor Yellow
    Write-Host "  It waited a long time but eventually got picked." -ForegroundColor Yellow
} else {
    Write-Host "  DID NOT STARVE: the batch Job finished." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Demo complete ===" -ForegroundColor Cyan
Write-Host ""