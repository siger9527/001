@echo off
setlocal
cd /d "%~dp0"
title Local IPTV Review Workbench
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10+ was not found. Install Python and enable "Add Python to PATH".
  pause
  exit /b 1
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo WARNING: FFmpeg was not found in PATH. The dashboard can import and review lists,
  echo but visual frame analysis requires FFmpeg.
  echo.
)
echo Starting local IPTV review workbench...
echo Dashboard: http://127.0.0.1:8765/
echo Stop with Ctrl+C in this window.
python local_iptv_server.py
if errorlevel 1 (
  echo.
  echo The server exited with an error. Review the message above.
  pause
)
endlocal
