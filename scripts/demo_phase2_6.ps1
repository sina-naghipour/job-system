# scripts/demo_phase2_6.ps1
# Phase 2.6 demo: heartbeat and offline detection.
#
# Assumes:
#   - Server is running in Terminal 1
#   - Real Agent is running in Terminal 2
#   - This script runs in Terminal 3
#
# The script is interactive: it asks you to stop and restart the Agent
# at the right moments, and queries the Server between steps.

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


function Get-Job {
    param([string]$JobId)
    Invoke-RestMethod -Uri "$apiBase/jobs/$JobId"
}


function Wait-ForJob {
    param([string]$JobId, [int]$TimeoutSeconds = 60)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastState = ""
    while ((Get-Date) -lt $deadline) {
        $j = Get-Job -JobId $JobId
        if ($j.state -ne $lastState) {
            Write-Host "    state: $($j.state) attempts=$($j.dispatchAttempts)"
            $lastState = $j.state
        }
        if ($j.state -in @("SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED")) {
            return $j
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Timed out waiting for job $JobId"
}


Write-Host ""
Write-Host "=== Phase 2.6 Demo: Heartbeat and Reconnect ===" -ForegroundColor Cyan
Write-Host ""

# --- Step 1: Confirm baseline ---
Write-Host "[1/4] Confirm the agent is online and jobs run" -ForegroundColor Yellow
Write-Host ""

$job1 = Submit-Job `
    -Image "alpine:latest" `
    -Command @("echo", "baseline") `
    -TimeoutMs 30000 `
    -IdempotencyKey "demo-hb-1-$(Get-Random)"

Write-Host "    submitted: $($job1.jobId)"
$null = Wait-ForJob -JobId $job1.jobId
Write-Host ""
Write-Host "  OK: agent is online and processed a job" -ForegroundColor Green
Write-Host ""

# --- Step 2: Kill the agent ---
Write-Host "[2/4] Kill the agent" -ForegroundColor Yellow
Write-Host ""
Write-Host "    Go to Terminal 2 (the Agent)."
Write-Host "    Press Ctrl+C to stop the Agent."
Write-Host "    Do NOT restart it yet."
Write-Host ""
$null = Read-Host "    Press ENTER once the agent has stopped"

Write-Host ""
Write-Host "    Waiting 35 seconds for the server to detect missed heartbeats..."
Write-Host "    (heartbeat interval = 10s, missed beats before offline = 3)"
Write-Host ""

for ($i = 35; $i -gt 0; $i -= 5) {
    Write-Host "    ... $i seconds"
    Start-Sleep -Seconds 5
}

Write-Host ""
Write-Host "    Check Terminal 1 (Server). You should see:"
Write-Host "      'Agent agent-1 missed 3 heartbeats; marking offline'"
Write-Host ""

# --- Step 3: Submit a job while the agent is offline ---
Write-Host "[3/4] Submit a job while the agent is offline" -ForegroundColor Yellow
Write-Host ""

$job2 = Submit-Job `
    -Image "alpine:latest" `
    -Command @("echo", "queued while offline") `
    -TimeoutMs 30000 `
    -IdempotencyKey "demo-hb-2-$(Get-Random)"

Write-Host "    submitted: $($job2.jobId)"
Start-Sleep -Seconds 3

$j2 = Get-Job -JobId $job2.jobId
Write-Host "    current state: $($j2.state) attempts=$($j2.dispatchAttempts)"

if ($j2.state -ne "PENDING") {
    Write-Host "  FAIL: expected PENDING, got $($j2.state)" -ForegroundColor Red
    exit 1
}

Write-Host "  OK: job is queued, waiting for an online agent" -ForegroundColor Green
Write-Host ""

# --- Step 4: Restart the agent, watch the job complete ---
Write-Host "[4/4] Restart the agent" -ForegroundColor Yellow
Write-Host ""
Write-Host "    Go to Terminal 2 and start the Agent again:"
Write-Host "      `$env:AGENT_ID = `"agent-1`""
Write-Host "      python -m packages.agent.main"
Write-Host ""
$null = Read-Host "    Press ENTER once the agent is registered"

Write-Host ""
Write-Host "    Waiting for the queued job to complete..."
Write-Host ""

$final = Wait-ForJob -JobId $job2.jobId -TimeoutSeconds 30
Write-Host ""

if ($final.state -eq "SUCCEEDED") {
    Write-Host "  OK: queued job ran after the agent came back" -ForegroundColor Green
} else {
    Write-Host "  FAIL: expected SUCCEEDED, got $($final.state)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Demo complete ===" -ForegroundColor Cyan
Write-Host ""