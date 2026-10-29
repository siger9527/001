@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python 3.10+ was not found. Install Python and enable PATH.
  pause
  exit /b 1
)
echo Starting batch visual review. Keep Ollama running and ensure FFmpeg is on PATH.
echo AI results are advisory; this process never approves or rejects channels.
python batch_review.py
set "RESULT=%ERRORLEVEL%"
echo.
echo Batch process exit code: %RESULT%
echo Report: %CD%\batch-review-report.csv
pause
exit /b %RESULT%
