param([switch]$Restart)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$serviceRoot = Join-Path $projectRoot 'pickmate'
$pythonExe = Join-Path $serviceRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Install the Python dependencies in pickmate/.venv first.' }
$logRoot = Join-Path $serviceRoot '.cache'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

if ($Restart) {
    $processes = @(Get-CimInstance Win32_Process)
    $launchers = @($processes | Where-Object {
        $_.ExecutablePath -eq $pythonExe -and
        $_.CommandLine -match '-m (uvicorn counselor.app:app|counselor.worker)'
    })
    $stopIds = [System.Collections.Generic.HashSet[int]]::new()
    foreach ($launcher in $launchers) { [void]$stopIds.Add($launcher.ProcessId) }
    do {
        $added = $false
        foreach ($process in $processes) {
            if ($stopIds.Contains($process.ParentProcessId) -and $stopIds.Add($process.ProcessId)) { $added = $true }
        }
    } while ($added)
    foreach ($processIdToStop in $stopIds) { Stop-Process -Id $processIdToStop -Force -ErrorAction SilentlyContinue }
}

if (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) {
    throw 'Port 8000 is occupied. Use -Restart to restart this project''s services.'
}
$logStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $serviceRoot 'backend'
    $apiProcess = Start-Process -FilePath $pythonExe -ArgumentList @('-m','uvicorn','counselor.app:app','--app-dir','backend','--host','127.0.0.1','--port','8000') -WorkingDirectory $serviceRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot "counselor-api-$logStamp.out.log") -RedirectStandardError (Join-Path $logRoot "counselor-api-$logStamp.err.log") -PassThru
    $workerProcess = Start-Process -FilePath $pythonExe -ArgumentList @('-m','counselor.worker','start') -WorkingDirectory $serviceRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot "counselor-worker-$logStamp.out.log") -RedirectStandardError (Join-Path $logRoot "counselor-worker-$logStamp.err.log") -PassThru
} finally { $env:PYTHONPATH = $oldPythonPath }

if (-not (Get-NetTCPConnection -State Listen -LocalPort 5173 -ErrorAction SilentlyContinue)) {
    $nodeExe = (Get-Command node.exe).Source
    $viteScript = Join-Path $serviceRoot 'web\node_modules\vite\bin\vite.js'
    Start-Process -FilePath $nodeExe -ArgumentList @($viteScript,'--host','0.0.0.0','--port','5173','--strictPort') -WorkingDirectory (Join-Path $serviceRoot 'web') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot "counselor-web-$logStamp.out.log") -RedirectStandardError (Join-Path $logRoot "counselor-web-$logStamp.err.log") | Out-Null
}
Write-Output "Heard started: API launcher $($apiProcess.Id), voice launcher $($workerProcess.Id)."
Write-Output 'Open http://localhost:5173. Conversation uses the configured Vertex or Groq provider; voice uses LiveKit, Deepgram, and Rime.'
