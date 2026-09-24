@echo off
REM Deckhand one-click launcher; scripts\start.ps1 does the work in a hidden window and explains any failure.
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0scripts\start.ps1" %*
exit /b %errorlevel%
