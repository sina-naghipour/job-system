# scripts/demo.ps1
# End-to-end demo for Phase 1.
# Assumes Server and Agent are already running.
# Submits three jobs: happy path, idempotency, failure path.

$ErrorActionPreference = "Stop"

$apiBase = "http://localhost:8000"
$agentId = "agent-1"

function Submit-Job {
    param(
        [string]$Image,
        [string[]]$Command,
        [int]$TimeoutMs = 30000,
        [string]$IdempotencyKey,
        [hashtable]$Metadata = @{}
    )
    $body = @{
        agentId        = $agentId
        image          = $Image
        command        = $Command
        timeoutMs      = $TimeoutMs
        idempotencyKey = $IdempotencyKey
        metadata       = $Metadata
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
            Write-Host "  state: $($job.state)"
            $lastState = $job.state
        }
        if ($job.state -in @("SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED")) {
            return $job
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Timed out waiting for job $JobId"
}

function Show-Result {
    param([string]$JobId)
    $result = Invoke-RestMethod -Uri "$apiBase/jobs/$JobId/result"
    Write-Host ""
    Write-Host "  state:    $($result.state)"
    Write-Host "  exitCode: $($result.exitCode)"
    Write-Host "  error:    $($result.error)"
    Write-Host "  stdout:   $($result.stdout.Trim())"
    if ($result.stderr) {
        Write-Host "  stderr:   $($result.stderr.Trim())"
    }
    Write-Host ""
}

Write-Host ""
Write-Host "=== Phase 1 Demo ===" -ForegroundColor Cyan
Write-Host ""

# --- 1. Happy path ---
Write-Host "[1/3] Happy path" -ForegroundColor Yellow
$job = Submit-Job `
    -Image "alpine:latest" `
    -Command @("sh", "-c", "echo 'Hello from the container' && sleep 2 && echo 'Done'") `
    -IdempotencyKey "demo-happy-$(Get-Random)"
Write-Host "  submitted: $($job.jobId)"
Wait-ForJob -JobId $job.jobId | Out-Null
Show-Result -JobId $job.jobId

# --- 2. Idempotency ---
Write-Host "[2/3] Idempotency" -ForegroundColor Yellow
$key = "demo-idem-$(Get-Random)"
$first = Submit-Job -Image "alpine:latest" -Command @("echo", "once") -IdempotencyKey $key
$second = Submit-Job -Image "alpine:latest" -Command @("echo", "once") -IdempotencyKey $key
Write-Host "  first:  $($first.jobId)"
Write-Host "  second: $($second.jobId)"
if ($first.jobId -eq $second.jobId) {
    Write-Host "  OK: same jobId returned, no duplicate created" -ForegroundColor Green
} else {
    Write-Host "  FAIL: expected same jobId" -ForegroundColor Red
}
Wait-ForJob -JobId $first.jobId | Out-Null
Show-Result -JobId $first.jobId

# --- 3. Failure path ---
Write-Host "[3/3] Failure path" -ForegroundColor Yellow
$fail = Submit-Job `
    -Image "alpine:latest" `
    -Command @("sh", "-c", "echo 'about to fail' && exit 42") `
    -IdempotencyKey "demo-fail-$(Get-Random)"
Write-Host "  submitted: $($fail.jobId)"
Wait-ForJob -JobId $fail.jobId | Out-Null
Show-Result -JobId $fail.jobId

Write-Host "=== Demo complete ===" -ForegroundColor Cyan
Write-Host ""