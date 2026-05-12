@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: 杀掉可能占用的旧进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000') do (
    taskkill /f /pid %%a >nul 2>nul
)
timeout /t 1 /nobreak >nul

python 手机预览.py

pause
