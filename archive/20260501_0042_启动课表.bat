@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo       课程表 - 启动服务
echo ========================================
echo.

:: 检查 python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未找到 python
    pause
    exit /b 1
)

:: 杀掉可能占用的旧进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000') do (
    taskkill /f /pid %%a >nul 2>nul
)
timeout /t 1 /nobreak >nul

echo 服务启动中...
echo.
echo 请在浏览器地址栏输入：http://localhost:8000
echo.
echo 导入或更新课表后，关闭此窗口，
echo 然后双击「查看课表.bat」即可离线查看。
echo ========================================
echo.

python -m uvicorn main:app --host 0.0.0.0 --port 8000

:: 服务关闭后，自动生成离线文件
echo.
echo 正在生成离线课表文件...
python export_html.py
python export_mobile.py
echo.
echo 已生成：
echo   「我的课表.html」- 电脑双击查看
echo   「课表-手机版.html」- 发送到手机查看
timeout /t 3 /nobreak >nul
