# scripts/demo_phase3_routing.ps1
# Phase 3 demo: two-agent routing.
#
# Assumes:
#   - Server is running on http://localhost:8000
#   - Two agents are connected: "agent-1" and "agent-2"
#     (start them with: docker compose up)
#
# Scenarios:
#   1. Job for agent-1 runs on agent-1, not agent-2
#   2. Job for agent-2 runs on agent-2, not agent-1
#   3. A Job for an agent that never connected stays PENDING

$ErrorActionPreference = "Stop"

$apiBase = "http://localhost:8000"


function Submit-Job {
    param(
        [string]$AgentId,
        [string]$Image,
        [string[]]$Command,
        [int]$TimeoutMs = 30000
    )
    $body = @{
        agentId        = $AgentId
        image          = $Image
        command        = $Command
        timeoutMs      = $TimeoutMs
        idempotencyKey = "demo-routing-$(Get-Random)"
    } | ConvertTo-Json

    Invoke-RestMethod -Uri "$apiBase/jobs" -Method Post -Body $body -ContentType "application/json"
}


function Get-Job {
    param([string]$JobId)
    Invoke-RestMethod -Uri "$apiBase/jobs/$JobId"
}


function Wait-ForJob {
    param(
        [string]$JobId,
        [int]$TimeoutSeconds = 30
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastState = ""
    while ((Get-Date) -lt $deadline) {
        $job = Get-Job -JobId $JobId
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


function Assert-Agent {
    param(
        [string]$JobId,
        [string]$ExpectedAgent
    )
    $job = Get-Job -JobId $JobId
    if ($job.agentId -ne $ExpectedAgent) {
        throw "Job $JobId expected agent $ExpectedAgent but is on $($job.agentId)"
    }
    Write-Host "  OK: job $JobId ran on $ExpectedAgent" -ForegroundColor Green
}


Write-Host ""
Write-Host "=== Phase 3 Demo: Two-Agent Routing ===" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# Scenario 1 — a Job submitted for agent-1 must run on agent-1
# ---------------------------------------------------------------------------

Write-Host "[1/3] Submit a Job for agent-1" -ForegroundColor Yellow

$job1 = Submit-Job `
    -AgentId "agent-1" `
    -Image "alpine:latest" `
    -Command @("echo", "I am agent-1")

Write-Host "    submitted: $($job1.jobId)"
$final1 = Wait-ForJob -JobId $job1.jobId

if ($final1.state -ne "SUCCEEDED") {
    Write-Host "  FAIL: expected SUCCEEDED, got $($final1.state)" -ForegroundColor Red
    exit 1
}
Assert-Agent -JobId $job1.jobId -ExpectedAgent "agent-1"
Write-Host ""


# ---------------------------------------------------------------------------
# Scenario 2 — a Job submitted for agent-2 must run on agent-2
# ---------------------------------------------------------------------------

Write-Host "[2/3] Submit a Job for agent-2" -ForegroundColor Yellow

$job2 = Submit-Job `
    -AgentId "agent-2" `
    -Image "alpine:latest" `
    -Command @("echo", "I am agent-2")

Write-Host "    submitted: $($job2.jobId)"
$final2 = Wait-ForJob -JobId $job2.jobId

if ($final2.state -ne "SUCCEEDED") {
    Write-Host "  FAIL: expected SUCCEEDED, got $($final2.state)" -ForegroundColor Red
    exit 1
}
Assert-Agent -JobId $job2.jobId -ExpectedAgent "agent-2"
Write-Host ""


# ---------------------------------------------------------------------------
# Scenario 3 — a Job for an agent that never connected stays PENDING
# ---------------------------------------------------------------------------

Write-Host "[3/3] Submit a Job for agent-99 (never connected)" -ForegroundColor Yellow

$job3 = Submit-Job `
    -AgentId "agent-99" `
    -Image "alpine:latest" `
    -Command @("echo", "nobody will run this")

Write-Host "    submitted: $($job3.jobId)"
Start-Sleep -Seconds 3

$pending = Get-Job -JobId $job3.jobId
Write-Host "    state: $($pending.state)"

if ($pending.state -ne "PENDING") {
    Write-Host "  FAIL: expected PENDING, got $($pending.state)" -ForegroundColor Red
    exit 1
}

Write-Host "  OK: job is queued, waiting for an agent that never arrives" -ForegroundColor Green
Write-Host ""

Write-Host "=== Demo complete ===" -ForegroundColor Cyan
Write-Host ""