@echo off
chcp 65001 >nul
cd /d "%~dp0.."

where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "run_gui.pyw"
  exit /b
)

where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw "run_gui.pyw"
  exit /b
)

where python >nul 2>nul
if %errorlevel%==0 (
  start "" python "run_gui.pyw"
  exit /b
)

echo 未找到 Python，请先安装 Python 3.11+ 并加入 PATH。
pause
