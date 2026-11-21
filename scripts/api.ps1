<#
.SYNOPSIS
Thin wrapper over the revel8 target API for Windows PowerShell.

.EXAMPLE
$env:REVEL8_API_KEY="your-key-here"
.\scripts\api.ps1 scenarios
.\scripts\api.ps1 new practice
.\scripts\api.ps1 send <sid> julius email "Subject" "Body text"
.\scripts\api.ps1 events <sid>

# Override sender identity:
$env:FROM_NAME="Lena Hofer"; $env:FROM_ADDR="lena.hofer@eventcrew-muc.de"; .\scripts\api.ps1 send ...
#>

param(
    [Parameter(Position = 0)]
    [string]$Command = "help",

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"

$ErrorActionPreference = "Stop"

# Auto-load .env from the same folder as api.ps1 (or one folder up)
foreach ($envFile in @("$PSScriptRoot\.env", "$PSScriptRoot\..\.env")) {
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^\s*([^#=]+?)\s*=\s*(.*?)\s*$') {
                $val = $matches[2] -replace '^[''"]|[''"]$', ''
                [Environment]::SetEnvironmentVariable($matches[1], $val, 'Process')
            }
        }
        break
    }
}

$BASE = if ($env:REVEL8_API_BASE) { $env:REVEL8_API_BASE } else { "https://target-api.apps.01.cf.eu01.stackit.cloud/v1" }
$KEY = $env:REVEL8_API_KEY
$FROM_NAME = if ($env:FROM_NAME) { $env:FROM_NAME } else { "Lena Hofer" }
$FROM_ADDR = if ($env:FROM_ADDR) { $env:FROM_ADDR } else { "lena.hofer@eventcrew-muc.de" }

function Show-Usage {
    Write-Host @"
Usage:
  `$env:REVEL8_API_KEY="..."
  .\scripts\api.ps1 scenarios
  .\scripts\api.ps1 channels
  .\scripts\api.ps1 sessions
  .\scripts\api.ps1 new [practice]
  .\scripts\api.ps1 session <sid>
  .\scripts\api.ps1 events <sid>
  .\scripts\api.ps1 end <sid>
  .\scripts\api.ps1 send <sid> <to> <channel> <subject> <body>
  .\scripts\api.ps1 page <sid> <url> <title> <field1> [field2 ...]
  .\scripts\api.ps1 raw <METHOD> <path> [json-body]
"@
}

if ($Command -in @("help", "-h", "--help")) {
    Show-Usage
    exit 0
}

if ([string]::IsNullOrWhiteSpace($KEY)) {
    Write-Error 'REVEL8_API_KEY is not set. Run: $env:REVEL8_API_KEY="your-key"'
    exit 1
}

function Invoke-ApiReq {
    param(
        [string]$Method,
        [string]$Path,
        [string]$Body = $null
    )

    $headers = @{
        "Authorization"   = "Bearer $KEY"
        "Content-Type"    = "application/json"
        "Idempotency-Key" = [guid]::NewGuid().ToString()
    }

    $params = @{
        Uri             = "$BASE$Path"
        Method          = $Method
        Headers         = $headers
        TimeoutSec      = 150
        UseBasicParsing = $true
    }

    if (-not [string]::IsNullOrEmpty($Body)) {
        $params["Body"] = [System.Text.Encoding]::UTF8.GetBytes($Body)
    }

    try {
        $resp = Invoke-WebRequest @params
        try {
            $resp.Content | ConvertFrom-Json | ConvertTo-Json -Depth 10
        } catch {
            $resp.Content
        }
    } catch {
        Write-Error $_.Exception.Message
        if ($_.ErrorDetails.Message) {
            Write-Host $_.ErrorDetails.Message
        }
    }
}

switch ($Command) {
    "scenarios" { Invoke-ApiReq "GET" "/scenarios" }
    "channels"  { Invoke-ApiReq "GET" "/channels" }
    "sessions"  { Invoke-ApiReq "GET" "/sessions" }

    "new" {
        $scenario = if ($RemainingArgs.Count -ge 1) { $RemainingArgs[0] } else { "practice" }
        $payload = @{ scenario_id = $scenario } | ConvertTo-Json -Compress
        Invoke-ApiReq "POST" "/sessions" $payload
    }

    "session" { Invoke-ApiReq "GET" "/sessions/$($RemainingArgs[0])" }
    "events"  { Invoke-ApiReq "GET" "/sessions/$($RemainingArgs[0])/events" }
    "end"     { Invoke-ApiReq "POST" "/sessions/$($RemainingArgs[0])/end" }

    "send" {
        $sid     = $RemainingArgs[0]
        $to      = $RemainingArgs[1]
        $channel = $RemainingArgs[2]
        $subject = if ($RemainingArgs.Count -ge 4) { $RemainingArgs[3] } else { "" }
        $body    = if ($RemainingArgs.Count -ge 5) { $RemainingArgs[4] } else { "" }

        $obj = [ordered]@{
            to      = $to
            channel = $channel
            from    = [ordered]@{
                name    = $FROM_NAME
                address = $FROM_ADDR
            }
            body    = $body
        }
        if ($subject -ne "") {
            $obj["subject"] = $subject
        }

        $payload = $obj | ConvertTo-Json -Depth 5 -Compress
        Invoke-ApiReq "POST" "/sessions/$sid/messages" $payload
    }

    "page" {
        $sid    = $RemainingArgs[0]
        $url    = $RemainingArgs[1]
        $title  = $RemainingArgs[2]
        $fields = @()
        if ($RemainingArgs.Count -gt 3) {
            $fields = $RemainingArgs[3..($RemainingArgs.Count - 1)]
        }

        $payload = [ordered]@{
            url    = $url
            title  = $title
            fields = $fields
        } | ConvertTo-Json -Depth 5 -Compress

        Invoke-ApiReq "POST" "/sessions/$sid/pages" $payload
    }

    "raw" {
        $method = $RemainingArgs[0]
        $path   = $RemainingArgs[1]
        $body   = if ($RemainingArgs.Count -ge 3) { $RemainingArgs[2] } else { $null }
        Invoke-ApiReq $method $path $body
    }

    default { Show-Usage }
}