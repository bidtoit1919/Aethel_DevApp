@echo off
rem Run the Windows edition's tests (MSYS2 UCRT64 Python). Set AETHEL_MSYS2 if MSYS2 is not in C:\msys64.
if "%AETHEL_MSYS2%"=="" set "AETHEL_MSYS2=C:\msys64"
set "PATH=%AETHEL_MSYS2%\ucrt64\bin;%PATH%"
set "PYTHONPATH=%~dp0..\src;%LOCALAPPDATA%\Aethel\site"
cd /d "%~dp0.."
python -m unittest discover -s tests -v
