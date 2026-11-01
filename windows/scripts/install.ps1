<#
.SYNOPSIS
    Install Aethel for Windows for the current user.

.DESCRIPTION
    1. Makes sure MSYS2 is installed (offers to install it with winget).
    2. Installs GTK 4, libadwaita, Python, PyGObject and pywinpty from MSYS2's
       UCRT64 packages.
    3. Installs pyte (the terminal emulator Aethel draws agents with) into
       %LOCALAPPDATA%\Aethel\site.
    4. Checks that everything imports, then adds "Aethel" to the Start menu.

    Run it from this checkout:
        powershell -ExecutionPolicy Bypass -File windows\scripts\install.ps1

.PARAMETER Msys2
    Where MSYS2 is or should be installed. Default: C:\msys64.

.PARAMETER Uninstall
    Remove the Start-menu shortcut and %LOCALAPPDATA%\Aethel\site. Projects
    and the ledger (%LOCALAPPDATA%\Aethel\aethel.db) are kept.
#>
param(
    [string]$Msys2 = "C:\msys64",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$Edition = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$State = Join-Path $env:LOCALAPPDATA "Aethel"
$Site = Join-Path $State "site"
$Shortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "Aethel.lnk"
$Ucrt = Join-Path $Msys2 "ucrt64\bin"
$Python = Join-Path $Ucrt "python.exe"
$Pythonw = Join-Path $Ucrt "pythonw.exe"
$Bash = Join-Path $Msys2 "usr\bin\bash.exe"

function Step($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }

if ($Uninstall) {
    Step "Removing Aethel's shortcut and packages"
    if (Test-Path $Shortcut) { Remove-Item $Shortcut }
    if (Test-Path $Site) { Remove-Item $Site -Recurse -Force }
    Write-Host "Done. Your projects and ledger in $State are kept; delete that folder to remove them too."
    exit 0
}

Step "MSYS2"
if (-not (Test-Path $Bash)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "MSYS2 is not installed and winget is not available."
        Write-Host "Install MSYS2 from https://www.msys2.org to $Msys2, then run this script again."
        exit 1
    }
    $answer = Read-Host "MSYS2 (which provides GTK 4 for Windows) is not installed. Install it with winget now? [y/N]"
    if ($answer -notmatch '^[Yy]') { Write-Host "Stopped. Nothing was changed."; exit 1 }
    winget install --id MSYS2.MSYS2 -e --source winget --location $Msys2
    if (-not (Test-Path $Bash)) {
        Write-Host "MSYS2 did not appear in $Msys2. If it went elsewhere, run: install.ps1 -Msys2 <folder>"
        exit 1
    }
}
Write-Host "Using MSYS2 in $Msys2"

Step "GTK 4, libadwaita, Python and PyGObject (MSYS2 UCRT64 packages)"
$packages = @(
    "mingw-w64-ucrt-x86_64-gtk4",
    "mingw-w64-ucrt-x86_64-libadwaita",
    "mingw-w64-ucrt-x86_64-adwaita-icon-theme",
    "mingw-w64-ucrt-x86_64-python",
    "mingw-w64-ucrt-x86_64-python-gobject",
    "mingw-w64-ucrt-x86_64-python-pip"
)
& $Bash -lc "pacman -S --needed --noconfirm $($packages -join ' ')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "pacman failed. Open 'MSYS2 UCRT64' from the Start menu, run 'pacman -Syu' (twice if it asks to restart), then run this script again."
    exit 1
}

Step "pywinpty (ConPTY, for agents inside the window)"
& $Bash -lc "pacman -S --needed --noconfirm mingw-w64-ucrt-x86_64-python-pywinpty"
if ($LASTEXITCODE -ne 0) {
    Write-Host "The MSYS2 pywinpty package could not be installed. Aethel still runs; agents then open in console windows." -ForegroundColor Yellow
}

Step "pyte (terminal emulator) into $Site"
New-Item -ItemType Directory -Force -Path $Site | Out-Null
& $Python -m pip install --upgrade --target $Site --break-system-packages --disable-pip-version-check "pyte>=0.8.2"
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip could not install pyte. Aethel still runs; agents then open in console windows." -ForegroundColor Yellow
}

Step "Checking that Aethel can start"
$env:PATH = "$Ucrt;$env:PATH"
$env:PYTHONPATH = "$(Join-Path $Edition 'src');$Site"
& $Python -c @"
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gtk
from aethel.views import console
print('GTK', Gtk.get_major_version(), Gtk.get_minor_version(), '/ libadwaita', Adw.get_major_version(), Adw.get_minor_version())
print('Agents inside the window:', 'yes' if console.AVAILABLE else 'no (they open in console windows)')
"@
if ($LASTEXITCODE -ne 0) {
    Write-Host "Aethel could not import GTK. See the message above." -ForegroundColor Red
    exit 1
}

Step "Start-menu shortcut"
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($Shortcut)
$link.TargetPath = $Pythonw
$link.Arguments = "`"$(Join-Path $Edition 'aethel.pyw')`""
$link.WorkingDirectory = $Edition
$link.Description = "Aethel: projects, models and coding agents in one window"
$link.Save()
Write-Host "Added $Shortcut"

Write-Host ""
Write-Host "Aethel is installed. Start it from the Start menu, or run windows\run.cmd to see its messages." -ForegroundColor Green
Write-Host "Start-up errors are written to $(Join-Path $State 'aethel.log')."
