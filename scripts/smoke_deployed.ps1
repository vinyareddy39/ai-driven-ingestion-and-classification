param(
    [string]$BackendUrl = "http://localhost:8000",
    [string]$AdminToken = ""
)

$ErrorActionPreference = "Stop"
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "ECM Document Pipeline: Live Deployment Smoke Verification" -ForegroundColor Cyan
Write-Host "Target URL: $BackendUrl" -ForegroundColor Cyan
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

# 1. Check Unauthenticated Rejection (Expect 401)
Run-Check "Reject Unauthenticated Request with 401" {
    $resp = curl.exe -s -o /dev/null -w "%{http_code}" "$BackendUrl/api/v1/documents"
    if ($resp -ne "401") {
        throw "Expected 401 Unauthorized, received HTTP $resp"
    }
}

# 2. Check CORS Preflight OPTIONS
Run-Check "CORS Preflight OPTIONS Returns 200 with Allow-Origin" {
    $headers = curl.exe -s -I -X OPTIONS "$BackendUrl/api/v1/system/info" -H "Origin: https://app.vercel.app" -H "Access-Control-Request-Method: GET"
    if ($headers -notmatch "200 OK|204 No Content") {
        throw "Expected 200 OK or 204 No Content on OPTIONS, headers: $headers"
    }
}

# 3. Authenticated System Info
if ($AdminToken -ne "") {
    Run-Check "Authenticated System Info with Bearer Token" {
        $infoJson = curl.exe -s -H "Authorization: Bearer $AdminToken" "$BackendUrl/api/v1/system/info"
        if ($infoJson -notmatch '"version"') {
            throw "Invalid system info response: $infoJson"
        }
    }
}

# 4. User Registration and JWT Auth Flow
$testEmail = "smoke_test_$(Get-Random)@ecm.local"
$testPass = "SmokeTest12345!"

Run-Check "User Registration Flow" {
    $body = @{
        email = $testEmail
        password = $testPass
        full_name = "Smoke Test User"
        role = "patient"
    } | ConvertTo-Json

    $resp = curl.exe -s -X POST "$BackendUrl/api/v1/auth/register" -H "Content-Type: application/json" -d $body
    if ($resp -notmatch '"user_id"') {
        throw "Registration failed: $resp"
    }
}

$jwtToken = ""
Run-Check "User Login and JWT Generation" {
    $loginBody = @{
        email = $testEmail
        password = $testPass
    } | ConvertTo-Json

    $loginResp = curl.exe -s -X POST "$BackendUrl/api/v1/auth/login" -H "Content-Type: application/json" -d $loginBody
    if ($loginResp -notmatch '"access_token"') {
        throw "Login failed: $loginResp"
    }
    $loginData = $loginResp | ConvertFrom-Json
    $script:jwtToken = $loginData.access_token
}

Write-Host "==========================================================" -ForegroundColor Cyan
if ($allPassed) {
    Write-Host "All deployment smoke checks PASSED successfully!" -ForegroundColor Green
    exit 0
} else {
    Write-Host "One or more deployment smoke checks FAILED." -ForegroundColor Red
    exit 1
}
