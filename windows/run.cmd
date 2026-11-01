@echo off
rem Run Aethel for Windows from this checkout, with a console for messages.
rem Uses MSYS2 UCRT64 (see scripts\install.ps1). Set AETHEL_MSYS2 if MSYS2 is not in C:\msys64.
if "%AETHEL_MSYS2%"=="" set "AETHEL_MSYS2=C:\msys64"
set "PATH=%AETHEL_MSYS2%\ucrt64\bin;%PATH%"
set "PYTHONPATH=%~dp0src;%LOCALAPPDATA%\Aethel\site"
python -m aethel %*
