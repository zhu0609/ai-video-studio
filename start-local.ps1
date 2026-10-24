param(
    [ValidateRange(1, 65535)][int]$Port = 8000,
    [switch]$NoBrowser,
    [switch]$Background,
    [switch]$InstallDependencies
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$studioUrl = "http://127.0.0.1:$Port"

function Test-StudioReady {
    try {
        $health = Invoke-RestMethod -Uri "$studioUrl/api/health" -TimeoutSec 2 -ErrorAction Stop
        # Match the workbench health contract, not just any HTTP 200 page.
        return ($health.ok -eq $true -and $null -ne $health.providers -and
            $null -ne $health.execution_mode -and $null -ne $health.demo_notice)
    } catch {
        return $false
    }
}

function Open-StudioPage {
    if (-not $NoBrowser) {
        $browserInfo = New-Object System.Diagnostics.ProcessStartInfo
        $browserInfo.FileName = $studioUrl
        $browserInfo.UseShellExecute = $true
        [void][System.Diagnostics.Process]::Start($browserInfo)
    }
}

function Test-PortInUse {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.ConnectAsync('127.0.0.1', $Port)
        return ($pending.Wait(1500) -and $client.Connected)
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

# Reopening an existing workbench must not install dependencies or restart jobs.
if (Test-StudioReady) {
    Write-Host "AI 视频生成数据台已运行，正在打开：$studioUrl"
    Open-StudioPage
    return
}

# Prevent two simultaneous double-clicks from launching duplicate servers.
$pathHash = [System.Security.Cryptography.SHA256]::Create()
try {
    $rootBytes = [System.Text.Encoding]::UTF8.GetBytes("$PSScriptRoot|$Port".ToLowerInvariant())
    $lockId = [System.BitConverter]::ToString($pathHash.ComputeHash($rootBytes)).Replace('-', '')
} finally {
    $pathHash.Dispose()
}
$startupMutex = New-Object System.Threading.Mutex($false, "Local\FrameflowStart_$lockId")
$ownsLock = $false
try {
    try { $ownsLock = $startupMutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $ownsLock = $true }
    if (-not $ownsLock) {
        Write-Host '另一个启动窗口正在准备服务，请等待该窗口完成。'
        return
    }
    if (Test-StudioReady) {
        Write-Host "AI 视频生成数据台已运行：$studioUrl"
        Open-StudioPage
        return
    }
    if (Test-PortInUse) {
        throw "端口 $Port 已被其他服务占用或工作台仍在启动，请稍后重试。也可使用 -Port 8001。现有进程不会被停止。"
    }

    if (-not (Test-Path -LiteralPath '.env')) {
        Copy-Item -LiteralPath '.env.example' -Destination '.env'
    }
    $pythonExe = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw '需要 Python 3.11 或更高版本，请安装后重试。' }
    }
    & $pythonExe -c "import importlib.util, sys; sys.exit(any(importlib.util.find_spec(name) is None for name in ('fastapi', 'uvicorn', 'celery', 'httpx', 'PIL', 'imageio_ffmpeg', 'sqlalchemy', 'pydantic_settings', 'redis', 'psycopg')))"
    $needsDependencies = ($LASTEXITCODE -ne 0)
    if ($needsDependencies -or $InstallDependencies) {
        Write-Host '正在安装后端依赖，首次启动需要联网。'
        & $pythonExe -m pip install --disable-pip-version-check -q -r backend/requirements.lock
        if ($LASTEXITCODE -ne 0) { throw '后端依赖安装失败，请检查网络后重试。' }
    }
    if (-not (Test-Path -LiteralPath 'frontend/dist/index.html')) {
        Push-Location frontend
        try {
            if (Get-Command pnpm -ErrorAction SilentlyContinue) {
                pnpm install --frozen-lockfile
                if ($LASTEXITCODE -ne 0) { throw 'pnpm install 失败，请检查网络。' }
                pnpm build
            } else {
                npm install
                if ($LASTEXITCODE -ne 0) { throw 'npm install 失败，请先安装 Node.js 22 LTS 并检查网络。' }
                npm run build
            }
            if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
        } finally { Pop-Location }
    }

    $env:PYTHONPATH = Join-Path $PSScriptRoot 'backend'
    $env:PYTHONUTF8 = '1'
    $env:EXECUTION_MODE = 'local'
    if ($Background) {
        $logDirectory = Join-Path $PSScriptRoot 'work/logs'
        [void](New-Item -ItemType Directory -Path $logDirectory -Force)
        $logStamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
        $stdoutPath = Join-Path $logDirectory "server-$logStamp.stdout.log"
        $stderrPath = Join-Path $logDirectory "server-$logStamp.stderr.log"
        $server = Start-Process -FilePath $pythonExe -WorkingDirectory $PSScriptRoot `
            -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port", '--no-access-log') `
            -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
        $ready = $false
        $timer = [System.Diagnostics.Stopwatch]::StartNew()
        while ($timer.Elapsed.TotalSeconds -lt 45) {
            if (Test-StudioReady) { $ready = $true; break }
            $server.Refresh()
            if ($server.HasExited) {
                throw "服务未能启动，请查看日志：$stderrPath"
            }
            Start-Sleep -Milliseconds 400
        }
        if (-not $ready) {
            throw "服务尚未就绪，进程保留运行。请稍后打开 $studioUrl，或查看日志：$stderrPath"
        }
        Write-Host "AI 视频生成数据台已在后台启动：$studioUrl"
        Write-Host "服务进程：$($server.Id)；日志：$logDirectory"
        Open-StudioPage
    } else {
        Write-Host "AI 视频生成数据台：$studioUrl（在本窗口按 Ctrl+C 停止服务）"
        Open-StudioPage
        & $pythonExe -m uvicorn app.main:app --host 127.0.0.1 --port $Port
        if ($LASTEXITCODE -ne 0) { throw '服务已退出，请检查上方错误信息。' }
    }
} finally {
    if ($ownsLock) { $startupMutex.ReleaseMutex() }
    $startupMutex.Dispose()
}
