param(
    [ValidateSet('claude', 'ollama')]
    [string]$Provider = 'claude'
)

$ProxyDir   = "$env:USERPROFILE\pluely-proxy"
$PluelyExe  = "$env:LOCALAPPDATA\Pluely\pluely.exe"
$SttPy      = "$ProxyDir\whisper-venv\Scripts\python.exe"
$ProxyPort  = 8765
$SttPort    = 8766
$LogFile    = "$ProxyDir\memora-launcher.log"

function Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Out-File -FilePath $LogFile -Append -Encoding utf8
}

function Test-PortListening($port) {
    $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

# Start a console app with no window, stdout/stderr redirected to a log file.
function Start-Hidden($commandLine, $logPath) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $env:ComSpec
    $psi.Arguments = "/c $commandLine > `"$logPath`" 2>&1"
    $psi.WorkingDirectory = $ProxyDir
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    [void][System.Diagnostics.Process]::Start($psi)
}

function Stop-PortOwners($port) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object {
            Log "Stopping PID $_ (port $port)"
            Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
        }
}

Log "=== Launch (provider: $Provider) ==="

# Restart Memora cleanly; give a previous watchdog time to tear down its servers.
taskkill /F /IM pluely.exe 2>$null | Out-Null
Start-Sleep -Seconds 2

& node "$ProxyDir\level-tools\select-provider.mjs" $Provider *>> $LogFile

if ($Provider -eq 'claude' -and -not (Test-PortListening $ProxyPort)) {
    Log "Starting proxy on port $ProxyPort"
    Start-Hidden "python proxy.py --project `"$ProxyDir`" --port $ProxyPort" "$ProxyDir\proxy-server.log"
}

if (-not (Test-PortListening $SttPort)) {
    Log "Starting STT server on port $SttPort"
    Start-Hidden "`"$SttPy`" stt-server.py --port $SttPort" "$ProxyDir\stt-server.log"
}

$pluely = Start-Process -FilePath $PluelyExe -PassThru
Log "Memora started (PID $($pluely.Id)), watchdog waiting"

$pluely.WaitForExit()
Log "Memora exited, shutting down servers"

Stop-PortOwners $ProxyPort
Stop-PortOwners $SttPort
Log "=== Done ==="
