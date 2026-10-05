# SonicVision Launcher for Windows PowerShell
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "       Launching SonicVision AI          " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# 1. Start Backend in a separate window
Write-Host "[1/2] Starting Backend (port 8000)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\backend'; .\venv\Scripts\uvicorn.exe server:app --reload --port 8000"

# 2. Start Frontend in a separate window
Write-Host "[2/2] Starting Frontend (port 3000)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\frontend'; yarn start"

Write-Host ""
Write-Host "Both servers launched! Your browser will open http://localhost:3000 shortly." -ForegroundColor Green
