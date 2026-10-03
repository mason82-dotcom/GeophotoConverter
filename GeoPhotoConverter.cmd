@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\GeoPhotoConverter.ps1" %*
exit /b %ERRORLEVEL%
