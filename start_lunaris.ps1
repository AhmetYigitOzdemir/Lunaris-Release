# Starts the Lunaris API (if it is not already running), builds the 3D viewer,
# and opens the viewer in the default browser.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$apiUrl = "http://127.0.0.1:8000"

$listening = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if (-not $listening) {
    Write-Host "Starting the Lunaris API..."
    Start-Process -FilePath "python" `
        -ArgumentList @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $PSScriptRoot `
        -WindowStyle Minimized
} else {
    Write-Host "The Lunaris API is already running on port 8000."
}

Write-Host "Waiting for the API to become ready..."
$ready = $false
for ($i = 0; $i -lt 120; $i++) {
    try {
        $health = Invoke-RestMethod -Uri "$apiUrl/health" -TimeoutSec 2
        if ($health.ready) {
            $ready = $true
            break
        }
    } catch {
        # The server is still starting.
    }
    Start-Sleep -Milliseconds 500
}

if (-not $ready) {
    throw "The Lunaris API did not become ready. Install the dependencies with: pip install -r requirements.txt"
}

Write-Host "Building the interactive 3D viewer..."
python south_pole_3d.py --api-base http://127.0.0.1:8000
if ($LASTEXITCODE -ne 0) {
    throw "The viewer could not be generated. Check that data\ldem_80s_40m_float.img is present."
}

Write-Host ""
Write-Host "Lunaris is running."
Write-Host "  Viewer  : $PSScriptRoot\outputs\south_pole_3d.html"
Write-Host "  Horizon : $PSScriptRoot\outputs\horizon_analysis.html"
Write-Host "  API docs: $apiUrl/docs"
Write-Host ""
Write-Host "Close the minimized 'python' API window to stop the server."
Read-Host "Press Enter to close this window"
