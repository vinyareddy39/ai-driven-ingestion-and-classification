# scripts/smoke_deployed.ps1
# Automated post-deployment smoke test for live production environments.
# Takes BACKEND_URL and AUTH_TOKEN from environment variables or command-line parameters.

param(
    [string]$BackendUrl = $(if ($env:BACKEND_URL) { $env:BACKEND_URL } else { "http://127.0.0.1:8000" }),
    [string]$AuthToken = $(if ($env:AUTH_TOKEN) { $env:AUTH_TOKEN } else { "" })
)

$ErrorActionPreference = "Stop"
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "ECM Document Pipeline: Live Deployment Smoke Verification" -ForegroundColor Cyan
Write-Host "Backend URL: $BackendUrl" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$allPassed = $true

function Run-Check([string]$name, [scriptblock]$action) {
    Write-Host -NoNewline "[CHECK] $name... "
    try {
        & $action
        Write-Host "PASS" -ForegroundColor Green
    }
    catch {
        Write-Host "FAIL: $_" -ForegroundColor Red
        $script:allPassed = $false
    }
}

# 1. Health and Readiness Probe
Run-Check "Readiness Probe /health/ready" {
    $code = curl.exe -s -o /dev/null -w "%{http_code}" "$BackendUrl/health/ready"
    if ($code -ne "200") {
        throw "Readiness check failed with HTTP code $code"
    }
}

# 2. Auth Matrix: Reject Unauthenticated Request (Expect 401)
Run-Check "Reject Unauthenticated Access with 401" {
    $code = curl.exe -s -o /dev/null -w "%{http_code}" "$BackendUrl/api/v1/documents"
    if ($code -ne "401") {
        throw "Expected 401 Unauthorized, received HTTP code $code"
    }
}

# 3. CORS Preflight Check for Vercel Origin
Run-Check "CORS Preflight (OPTIONS /api/v1/system/info)" {
    $headers = curl.exe -s -I -X OPTIONS "$BackendUrl/api/v1/system/info" `
        -H "Origin: https://app.vercel.app" `
        -H "Access-Control-Request-Method: GET"
    if ($headers -notmatch "200 OK|204 No Content") {
        throw "Expected 200/204 on OPTIONS, got: $headers"
    }
}

# Resolve active token
$activeToken = $AuthToken
if (-not $activeToken) {
    # Attempt to obtain a token via demo or auth endpoint if running in test environment
    try {
        $loginJson = curl.exe -s -X POST "$BackendUrl/api/v1/auth/login" `
            -H "Content-Type: application/json" `
            -d '{"email":"admin@enterprise.local","password":"TemporaryAdminPassword123!"}'
        if ($loginJson -match '"access_token"') {
            $parsed = $loginJson | ConvertFrom-Json
            $activeToken = $parsed.access_token
        }
    } catch {}
}

if ($activeToken) {
    $authHeader = "Authorization: Bearer $activeToken"

    # 4. System Info & Engine Verification
    Run-Check "System Info & Engine Verification (/api/v1/system/info)" {
        $info = curl.exe -s -H $authHeader "$BackendUrl/api/v1/system/info"
        if ($info -notmatch '"version"' -or $info -notmatch '"engines"') {
            throw "System info missing required engines or version field: $info"
        }
    }

    # 5. Create Batch
    $batchId = ""
    Run-Check "Create Batch (/api/v1/batches)" {
        $batchResp = curl.exe -s -X POST "$BackendUrl/api/v1/batches" `
            -H $authHeader `
            -H "Content-Type: application/json" `
            -d '{"name": "Smoke Test Upload Batch"}'
        if ($batchResp -match '"batch_id"') {
            $bData = $batchResp | ConvertFrom-Json
            $script:batchId = $bData.batch_id
        } else {
            throw "Batch creation failed: $batchResp"
        }
    }

    # 6. Multipart Upload Initiation
    $uploadId = ""
    $partUrl = ""
    Run-Check "Multipart Upload Init (/api/v1/uploads/init)" {
        $initPayload = @{
            file_name = "smoke_synthetic_document.pdf"
            file_size = 1024
            mime_type = "application/pdf"
            batch_id = $script:batchId
        } | ConvertTo-Json

        $initResp = curl.exe -s -X POST "$BackendUrl/api/v1/uploads/init" `
            -H $authHeader `
            -H "Content-Type: application/json" `
            -d $initPayload

        if ($initResp -match '"upload_id"') {
            $initData = $initResp | ConvertFrom-Json
            $script:uploadId = $initData.upload_id
            $script:partUrl = $initData.parts[0].url
        } else {
            throw "Multipart init failed: $initResp"
        }
    }

    # 7. Upload Synthetic Part & Complete
    Run-Check "Upload Part & Complete Multipart" {
        $syntheticPdf = "%PDF-1.4`n% Smoke Test Synthetic PDF Document`n1 0 obj<<>>endobj`ntrailer<<>>`n%%EOF"
        $etag = "fake-etag-smoke-001"

        if ($script:partUrl -match "^/api/") {
            # Local route part upload
            $partResp = curl.exe -s -X PUT "$BackendUrl$($script:partUrl)" `
                -H $authHeader `
                -H "Content-Type: application/octet-stream" `
                -d $syntheticPdf
            if ($partResp -match '"etag"') {
                $etag = ($partResp | ConvertFrom-Json).etag
            }
        }

        $completePayload = @{
            parts = @(
                @{
                    part_number = 1
                    etag = $etag
                }
            )
        } | ConvertTo-Json

        $completeResp = curl.exe -s -X POST "$BackendUrl/api/v1/uploads/$($script:uploadId)/complete" `
            -H $authHeader `
            -H "Content-Type: application/json" `
            -d $completePayload

        if ($completeResp -notmatch '"COMPLETED"') {
            throw "Multipart complete failed: $completeResp"
        }
    }

    # 8. Query Batch Results
    Run-Check "Batch Results Status & Aggregation (/api/v1/batches/{id})" {
        $bStatus = curl.exe -s -H $authHeader "$BackendUrl/api/v1/batches/$($script:batchId)"
        if ($bStatus -notmatch '"batch_id"') {
            throw "Failed to fetch batch status: $bStatus"
        }
    }
} else {
    Write-Host "[NOTE] AUTH_TOKEN not provided; authenticated multipart and batch checks skipped." -ForegroundColor Yellow
}

Write-Host "==========================================================" -ForegroundColor Cyan
if ($allPassed) {
    Write-Host "Post-deployment smoke verification completed successfully." -ForegroundColor Green
    exit 0
} else {
    Write-Host "One or more deployment smoke checks FAILED." -ForegroundColor Red
    exit 1
}
