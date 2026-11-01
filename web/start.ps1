# ============================================
# AI 图像篡改检测系统 - 一键启动器
# ============================================
# 使用方法：
#   1. 确保虚拟环境（项目根目录 .venv）已创建并安装依赖
#   2. 在 PowerShell 中运行: .\start.ps1
#   3. 自动启动后端（FastAPI @ 8000）+ 前端（React+Vite @ 5173）
#   4. 手动访问 http://localhost:5173（若浏览器未自动打开）
#   5. 按 Ctrl+C 停止所有服务（自动结束进程树）
# ============================================

Write-Host "╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║           AI 检测系统 - 一键启动器           ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# 脚本所在目录（web/）
$ROOT = $PSScriptRoot
Set-Location $ROOT

# 端口探测函数：先试 IPv4 再试 IPv6（Vite 默认只监听 IPv6 的 ::1，PowerShell 默认 IPv4 套接字连不上）
function Test-PortOpen($Port) {
    $candidates = @(
        @{ Family = [System.Net.Sockets.AddressFamily]::InterNetwork;   Host = [System.Net.IPAddress]::Loopback },
        @{ Family = [System.Net.Sockets.AddressFamily]::InterNetworkV6; Host = [System.Net.IPAddress]::IPv6Loopback }
    )
    foreach ($cfg in $candidates) {
        $tcp = New-Object System.Net.Sockets.TcpClient -ArgumentList $cfg.Family
        try {
            $async = $tcp.BeginConnect($cfg.Host, $Port, $null, $null)
            $ok = $async.AsyncWaitHandle.WaitOne(1500)
            if ($ok) { $tcp.EndConnect($async); return $true }
        } catch {
            # 该地址族连接失败，尝试下一个
        } finally {
            $tcp.Close()
        }
    }
    return $false
}

# 释放被占用的端口：结束占用端口的旧进程（防止上次异常退出残留导致本次绑定失败/误判）
function Stop-PortOwner($Port) {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { return }
    foreach ($ownerId in ($conns | Select-Object -ExpandProperty OwningProcess -Unique)) {
        $proc = Get-Process -Id $ownerId -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "  ⚠ 端口 $Port 被 $($proc.ProcessName) (PID $ownerId) 占用，结束旧进程..." -ForegroundColor Yellow
            & taskkill /PID $ownerId /T /F 2>$null | Out-Null
        }
    }
    Start-Sleep -Milliseconds 800
}

$backendProc = $null
$frontendProc = $null

try {
    # ─── 1. 启动后端 ───
    Write-Host "[1/2] 启动后端 (FastAPI @ 8000)..." -ForegroundColor Yellow
    Stop-PortOwner 8000

    # 虚拟环境在项目根目录（web 上一级）的 .venv 中
    $pythonPath = "$ROOT\..\.venv\Scripts\python.exe"
    if (-not (Test-Path $pythonPath)) {
        Write-Host "✕ 找不到后端虚拟环境: $pythonPath" -ForegroundColor Red
        Write-Host "  请先执行: cd $ROOT\..; python -m venv .venv; .\.venv\Scripts\Activate.ps1; 然后安装后端所需依赖" -ForegroundColor Yellow
        exit 1
    }

    # -u 无缓冲输出，让日志实时显示
    $backendProc = Start-Process -FilePath $pythonPath `
        -ArgumentList "-u", "app.py" `
        -WorkingDirectory "$ROOT" -NoNewWindow -PassThru

    # 等待后端就绪（最多 30 秒，TCP 端口探测，兼容 IPv4/IPv6）
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if ($backendProc.HasExited) {
            Write-Host "  ✕ 后端进程启动失败已退出（请查看上方日志）" -ForegroundColor Red
            break
        }
        if (Test-PortOpen 8000) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        Write-Host "⚠ 后端启动超时或进程退出，仍继续启动前端（请查看上方日志）" -ForegroundColor Yellow
    } else {
        Write-Host "  ✓ 后端已启动: http://localhost:8000" -ForegroundColor Green
    }

    # ─── 2. 启动前端 ───
    Write-Host "[2/2] 启动前端 (React + Vite @ 5173)..." -ForegroundColor Yellow
    Stop-PortOwner 5173

    # 前端依赖未安装时自动安装
    if (-not (Test-Path "$ROOT\frontend\node_modules")) {
        Write-Host "  检测到前端依赖未安装，正在执行 npm install ..." -ForegroundColor Yellow
        Start-Process -FilePath "npm.cmd" -ArgumentList "install" `
            -WorkingDirectory "$ROOT\frontend" -NoNewWindow -Wait
    }

    $npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
    if (-not $npmCmd) {
        Write-Host "✕ 找不到 npm.cmd，请确认 Node.js 已安装" -ForegroundColor Red
        exit 1
    }

    $frontendProc = Start-Process -FilePath $npmCmd `
        -ArgumentList "run", "dev" `
        -WorkingDirectory "$ROOT\frontend" -NoNewWindow -PassThru

    # 等待前端端口开放（最多 30 秒）
    $frontReady = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-PortOpen 5173) {
            $frontReady = $true
            break
        }
    }
    if (-not $frontReady) {
        Write-Host "⚠ 前端启动超时或进程退出，请查看上方日志" -ForegroundColor Yellow
    } else {
        Write-Host "  ✓ 前端已启动: http://localhost:5173" -ForegroundColor Green
    }
    Write-Host ""
    Write-Host "══════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  在浏览器中打开: http://localhost:5173" -ForegroundColor White
    Write-Host "  按 Ctrl+C 停止所有服务" -ForegroundColor White
    Write-Host "══════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  若浏览器未打开，请手动访问: http://localhost:5173" -ForegroundColor DarkGray

    # 等待用户按 Ctrl+C（或任一服务进程退出）
    Write-Host ""
    Write-Host "（后端/前端日志输出在上方，按 Ctrl+C 停止）" -ForegroundColor DarkGray
    while ($true) {
        Start-Sleep -Seconds 1
        if ($backendProc.HasExited) {
            Write-Host "⚠ 后端进程已退出" -ForegroundColor Red
            break
        }
        if ($frontendProc.HasExited) {
            Write-Host "⚠ 前端进程已退出" -ForegroundColor Red
            break
        }
    }
} finally {
    Write-Host "正在停止服务..." -ForegroundColor Yellow
    # 用 taskkill /T 结束整个进程树（可杀 uvicorn 的 watcher/worker 和 vite 子进程）
    if ($backendProc -and -not $backendProc.HasExited) {
        & taskkill /PID $backendProc.Id /T /F 2>$null | Out-Null
    }
    if ($frontendProc -and -not $frontendProc.HasExited) {
        & taskkill /PID $frontendProc.Id /T /F 2>$null | Out-Null
    }
    Start-Sleep -Milliseconds 500
    Write-Host "已停止" -ForegroundColor Green
}
