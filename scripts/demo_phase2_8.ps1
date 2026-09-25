# scripts/demo_phase2_8.ps1
# Phase 2.8 demo: structured logging, correlation IDs, and event history.
#
# Assumes:
#   - Server is running in Terminal 1 and its log is being captured
#   - Agent is running in Terminal 2 and its log is being captured
#   - This script runs in Terminal 3
#
# The demo prints the JSON event history for a Job and instructs you to
# search Terminal 1 and Terminal 2 logs by correlation_id.

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
    while ((Get-Date) -lt $deadline) {
        $j = Invoke-RestMethod -Uri "$apiBase/jobs/$JobId"
        if ($j.state -in @("SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED")) {
            return $j
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Timed out waiting for job $JobId"
}


Write-Host ""
Write-Host "=== Phase 2.8 Demo: Structured Logging and Events ===" -ForegroundColor Cyan
Write-Host ""

# --- Step 1: submit a job ---
Write-Host "[1/4] Submit a job" -ForegroundColor Yellow
Write-Host ""

$cmd = 'echo line one && echo line two && exit 0'

$job = Submit-Job `
    -Image "alpine:latest" `
    -Command @("sh", "-c", $cmd) `
    -TimeoutMs 30000 `
    -IdempotencyKey "demo-logs-$(Get-Random)"

Write-Host "    jobId: $($job.jobId)"

$final = Wait-ForJob -JobId $job.jobId
Write-Host "    final state: $($final.state)"

$full = Invoke-RestMethod -Uri "$apiBase/jobs/$($job.jobId)"
$correlationId = $full.correlationId

Write-Host "    correlationId: $correlationId"
Write-Host ""

# --- Step 2: fetch event history ---
Write-Host "[2/4] Event history (GET /jobs/{id}/events)" -ForegroundColor Yellow
Write-Host ""

$events = Invoke-RestMethod -Uri "$apiBase/jobs/$($job.jobId)/events"
foreach ($e in $events.events) {
    $payload = if ($e.payload) { ($e.payload | ConvertTo-Json -Compress) } else { "{}" }
    Write-Host "  $($e.createdAt)  $($e.eventType)  $payload"
}
Write-Host ""

# --- Step 3: fetch final log ---
Write-Host "[3/4] Final log (GET /jobs/{id}/logs)" -ForegroundColor Yellow
Write-Host ""

$logs = Invoke-RestMethod -Uri "$apiBase/jobs/$($job.jobId)/logs"
$logs.TrimEnd() -split "`n" | ForEach-Object { Write-Host "  $_" }
Write-Host ""

# --- Step 4: trace correlation ---
Write-Host "[4/4] Trace across components" -ForegroundColor Yellow
Write-Host ""
Write-Host "    Every Server and Agent log line about this job carries the field:"
Write-Host "      `"correlation_id`": `"$correlationId`"" -ForegroundColor Cyan
Write-Host ""
Write-Host "    To see the full trace:"
Write-Host ""
Write-Host "      In Terminal 1 (Server):" -ForegroundColor DarkGray
Write-Host "        Select-String -Path server.log -Pattern `"$correlationId`""
Write-Host ""
Write-Host "      In Terminal 2 (Agent):" -ForegroundColor DarkGray
Write-Host "        Select-String -Path agent.log -Pattern `"$correlationId`""
Write-Host ""
Write-Host "    Or just scroll each terminal and look for lines containing that string."
Write-Host ""

Write-Host "=== Demo complete ===" -ForegroundColor Cyan
Write-Host ""