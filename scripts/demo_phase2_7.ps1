# scripts/demo_phase2_7.ps1
# Phase 2.7 demo: agent reconcile.
#
# Assumes:
#   - Server is running in Terminal 1
#   - Agent is running in Terminal 2
#   - This script runs in Terminal 3

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


function Wait-ForState {
    param([string]$JobId, [string]$State, [int]$TimeoutSeconds = 30)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $j = Get-Job -JobId $JobId
        if ($j.state -eq $State) {
            return $j
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Timed out waiting for job $JobId to reach $State"
}


Write-Host ""
Write-Host "=== Phase 2.7 Demo: Agent Reconcile ===" -ForegroundColor Cyan
Write-Host ""

# --- Step 1 ---
Write-Host "[1/5] Submit a long-running job (sleeps 30 seconds)" -ForegroundColor Yellow
Write-Host ""

$job = Submit-Job `
    -Image "alpine:latest" `
    -Command @("sh", "-c", "echo start && sleep 30 && echo done") `
    -TimeoutMs 120000 `
    -IdempotencyKey "demo-reconcile-$(Get-Random)"

Write-Host "    submitted: $($job.jobId)"
$null = Wait-ForState -JobId $job.jobId -State "RUNNING"
Write-Host "    state: RUNNING"
Write-Host ""

# --- Step 2 ---
Write-Host "[2/5] Kill the agent" -ForegroundColor Yellow
Write-Host ""
Write-Host "    Go to Terminal 2 (the Agent) and press Ctrl+C."
Write-Host "    Do NOT restart it yet."
Write-Host ""
$null = Read-Host "    Press ENTER once the agent has stopped"
Write-Host ""

# --- Step 3 ---
Write-Host "[3/5] Verify the job is still RUNNING on the server" -ForegroundColor Yellow
Write-Host ""

Start-Sleep -Seconds 3
$j = Get-Job -JobId $job.jobId
Write-Host "    state: $($j.state)"

if ($j.state -ne "RUNNING") {
    Write-Host "  FAIL: expected RUNNING, got $($j.state)" -ForegroundColor Red
    exit 1
}

Write-Host "  OK: job is stuck in RUNNING; container is still alive in Docker" -ForegroundColor Green
Write-Host ""
Write-Host "    Check Docker Desktop. The container should still be running."
Write-Host ""

# --- Step 4 ---
Write-Host "[4/5] Restart the agent" -ForegroundColor Yellow
Write-Host ""
Write-Host "    Go to Terminal 2 and run:"
Write-Host "      `$env:AGENT_ID = `"agent-1`""
Write-Host "      python -m packages.agent.main"
Write-Host ""
Write-Host "    Watch Terminal 2 for:"
Write-Host "      'Reconcile: found 1 managed container(s)'"
Write-Host "      'Reconcile: job ... still running; reattaching'"
Write-Host ""
$null = Read-Host "    Press ENTER once the agent has registered"
Write-Host ""

# --- Step 5 ---
Write-Host "[5/5] Wait for the container to exit and the result to arrive" -ForegroundColor Yellow
Write-Host ""

$deadline = (Get-Date).AddSeconds(60)
$lastState = ""
while ((Get-Date) -lt $deadline) {
    $j = Get-Job -JobId $job.jobId
    if ($j.state -ne $lastState) {
        Write-Host "    state: $($j.state) exitCode=$($j.exitCode)"
        $lastState = $j.state
    }
    if ($j.state -in @("SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED")) {
        break
    }
    Start-Sleep -Milliseconds 500
}

$final = Get-Job -JobId $job.jobId
Write-Host ""

if ($final.state -eq "SUCCEEDED") {
    Write-Host "  OK: job completed after agent restart via reconcile" -ForegroundColor Green
} else {
    Write-Host "  FAIL: expected SUCCEEDED, got $($final.state)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Demo complete ===" -ForegroundColor Cyan
Write-Host ""