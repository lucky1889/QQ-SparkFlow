# QQ SparkFlow local Windows deploy script (requires Docker Desktop + WSL2)
# Usage (from repo root): powershell -ExecutionPolicy Bypass -File .\deploy\install-local.ps1
$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PkgRoot = Join-Path $RepoRoot 'QQSparkFlow'
$EnvFile = Join-Path $RepoRoot '.env'
$OverrideFile = Join-Path $RepoRoot 'docker-compose.override.yml'

$QQ_ACCOUNT_COUNT = if ($env:QQ_ACCOUNT_COUNT) { [int]$env:QQ_ACCOUNT_COUNT } else { 1 }
$WEB_PORT = if ($env:WEB_PORT) { $env:WEB_PORT } else { '8787' }
$DEFAULT_SEND_TIME = if ($env:DEFAULT_SEND_TIME) { $env:DEFAULT_SEND_TIME } else { '10:00' }
$ONEBOT_ACCESS_TOKEN = if ($env:ONEBOT_ACCESS_TOKEN) { $env:ONEBOT_ACCESS_TOKEN } else { '' }

function New-RandomHex([int]$length) {
    $bytes = New-Object byte[] ($length)
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    -join ($bytes | ForEach-Object { '{0:x2}' -f $_ })
}

function Set-EnvValue([string]$file, [string]$key, [string]$value) {
    if (Test-Path -LiteralPath $file) {
        $lines = Get-Content -LiteralPath $file -Encoding UTF8
        $found = $false
        $lines = $lines | ForEach-Object {
            if ($_ -match "^$([regex]::Escape($key))=") { $found = $true; "$key=$value" } else { $_ }
        }
        if (-not $found) { $lines += "$key=$value" }
        Set-Content -LiteralPath $file -Value $lines -Encoding UTF8
    } else {
        Set-Content -LiteralPath $file -Value "$key=$value" -Encoding UTF8
    }
}

Write-Host '[install-local] checking Docker...'
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) { throw 'docker not found. Install Docker Desktop and make sure it is running.' }
docker version --format '{{.Server.Os}} {{.Server.Version}}' | Out-Host

if (-not (Test-Path -LiteralPath $EnvFile)) {
    Copy-Item -LiteralPath (Join-Path $RepoRoot '.env.example') -Destination $EnvFile
}
if (-not $ONEBOT_ACCESS_TOKEN) {
    $ONEBOT_ACCESS_TOKEN = New-RandomHex 24
}
Set-EnvValue $EnvFile 'WEB_PORT' $WEB_PORT
Set-EnvValue $EnvFile 'QQ_ACCOUNT_COUNT' "$QQ_ACCOUNT_COUNT"
Set-EnvValue $EnvFile 'DEFAULT_SEND_TIME' $DEFAULT_SEND_TIME
Set-EnvValue $EnvFile 'ONEBOT_ACCESS_TOKEN' $ONEBOT_ACCESS_TOKEN
Set-EnvValue $EnvFile 'SPARKFLOW_SESSION_COOKIE_SECURE' '0'
Set-EnvValue $EnvFile 'PIP_INDEX_URL' 'https://pypi.tuna.tsinghua.edu.cn/simple'
Set-EnvValue $EnvFile 'PIP_TRUSTED_HOST' 'pypi.tuna.tsinghua.edu.cn'
Set-EnvValue $EnvFile 'APT_MIRROR' 'mirrors.tuna.tsinghua.edu.cn'

Write-Host "[install-local] generating napcat services 1..$QQ_ACCOUNT_COUNT"
$template = Get-Content -LiteralPath (Join-Path $RepoRoot 'deploy\compose-napcat.template.yml') -Raw
$sb = New-Object System.Text.StringBuilder
for ($i = 1; $i -le $QQ_ACCOUNT_COUNT; $i++) {
    $webuiPort = 6098 + $i
    $block = $template.Replace('${I}', "$i").Replace('${WEBUI_PORT}', "$webuiPort")
    [void]$sb.AppendLine($block)
}
Set-Content -LiteralPath $OverrideFile -Value $sb.ToString() -Encoding UTF8

Write-Host '[install-local] running setup_napcat.py'
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) { throw 'python not found. Install Python 3.' }
& $py.Source (Join-Path $PkgRoot 'scripts\setup_napcat.py') --count $QQ_ACCOUNT_COUNT --token $ONEBOT_ACCESS_TOKEN --state-dir (Join-Path $RepoRoot 'state') --users-data (Join-Path $PkgRoot 'usersData.json')

Write-Host '[install-local] writing default cron'
$cronDir = Join-Path $RepoRoot 'state\cron'
New-Item -ItemType Directory -Force -Path $cronDir | Out-Null
$parts = $DEFAULT_SEND_TIME -split ':'
$hour = [int]$parts[0]; $minute = [int]$parts[1]
$total = $hour * 60 + $minute + 40
$fh = [int](($total / 60) % 24); $fm = $total % 60
$cron = @(
    '# QQ SparkFlow daily send'
    "$fm $fh * * * cd /app && env SPARKFLOW_MANUAL_RUN=1 SPARKFLOW_MANUAL_UNSENT_ONLY=1 PYTHONUNBUFFERED=1 python main.py --doTask >> /app/logs/app.log 2>&1"
    "$minute $hour * * * cd /app && python main.py --doTask >> /app/logs/app.log 2>&1"
) -join "`n"
Set-Content -LiteralPath (Join-Path $cronDir 'root') -Value $cron -Encoding UTF8

Write-Host '[install-local] building and starting containers'
Push-Location $RepoRoot
try {
    docker compose up -d --build
} finally {
    Pop-Location
}

Write-Host ''
Write-Host 'QQ SparkFlow is running locally.'
Write-Host "Web UI: http://localhost:$WEB_PORT  (first open: create admin account)"
for ($i = 1; $i -le $QQ_ACCOUNT_COUNT; $i++) {
    $webuiPort = 6098 + $i
    Write-Host "Account $i NapCat WebUI: http://127.0.0.1:$webuiPort/webui (scan to login QQ)"
}
Write-Host 'After scanning, go back to Web UI -> account management -> add friend QQ numbers.'

