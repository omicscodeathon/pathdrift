$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:MPLBACKEND = "Agg"
Write-Host "Starting PathDrift backend from: $PSScriptRoot"
# Set WindowsSelectorEventLoopPolicy before uvicorn starts (required for asyncpg on Windows)
& "$PSScriptRoot\venv\Scripts\python.exe" -c "
import asyncio, sys, os
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
os.chdir(r'$PSScriptRoot')
import uvicorn
uvicorn.run('app.main:app', host='0.0.0.0', port=8000, reload=True, reload_delay=1.0)
"
