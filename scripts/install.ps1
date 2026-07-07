# Install (or uninstall) all built Ninter fonts for the current user.
#   Install:    powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#   Uninstall:  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Uninstall
#
# Per-user install (no admin needed): copies to %LOCALAPPDATA%\Microsoft\Windows\Fonts
# and registers each face in HKCU so Word/PowerPoint see them and Ctrl+I / Ctrl+B link.
#
# Updating is lock-safe: Windows keeps a handle on an installed font for the whole
# logon session, so overwriting the same filename fails ("being used by another
# process"). We instead write each build to a *content-hashed* filename and re-point
# the registry, so a rebuild always installs cleanly without logging off.
param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $root "build"
$fontDir = Join-Path $env:LOCALAPPDATA "Microsoft\Windows\Fonts"
$regKey = "HKCU:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"

# "Ninter-SemiBoldItalic" -> "Ninter SemiBold Italic"  (-creplace = case-SENSITIVE;
# plain -replace is case-insensitive and would mangle the name to "S em iB ol d").
function Get-FaceName([string]$stem) {
  $s = $stem -replace '^Ninter-', ''
  $s = $s -creplace '([a-z])([A-Z])', '$1 $2'
  return "Ninter $s"
}

function Broadcast-FontChange {
  Add-Type @"
using System;using System.Runtime.InteropServices;
public static class NinterFC {
  [DllImport("user32.dll")] public static extern IntPtr SendMessageTimeout(
    IntPtr hWnd,uint Msg,IntPtr wParam,IntPtr lParam,uint flags,uint timeout,out IntPtr result);
}
"@ -ErrorAction SilentlyContinue
  $r = [IntPtr]::Zero
  [NinterFC]::SendMessageTimeout([IntPtr]0xffff, 0x1D, [IntPtr]::Zero, [IntPtr]::Zero, 2, 1000, [ref]$r) | Out-Null
}

$fonts = Get-ChildItem -Path $buildDir -Filter "Ninter-*.ttf" -ErrorAction SilentlyContinue
if (-not $fonts) { Write-Host "No built fonts in $buildDir. Run: python build.py" -ForegroundColor Yellow; exit 1 }
if (-not (Test-Path $fontDir)) { New-Item -ItemType Directory -Path $fontDir -Force | Out-Null }

if ($Uninstall) {
  foreach ($f in $fonts) {
    $regName = "$(Get-FaceName $f.BaseName) (TrueType)"
    if (Get-ItemProperty -Path $regKey -Name $regName -ErrorAction SilentlyContinue) {
      Remove-ItemProperty -Path $regKey -Name $regName -Force -ErrorAction SilentlyContinue
    }
    # remove every physical file for this face (hashed or not); locked ones are skipped
    Get-ChildItem $fontDir -Filter "$($f.BaseName)*.ttf" -ErrorAction SilentlyContinue |
      ForEach-Object { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue }
    Write-Host "removed  $(Get-FaceName $f.BaseName)"
  }
  Broadcast-FontChange
  Write-Host "`nUninstalled Ninter. Any file still locked by this session is cleared at next logon." -ForegroundColor Cyan
  return
}

$updated = 0; $same = 0
foreach ($f in $fonts) {
  $face = Get-FaceName $f.BaseName
  $regName = "$face (TrueType)"
  $hash = (Get-FileHash $f.FullName -Algorithm SHA1).Hash.Substring(0, 8).ToLower()
  $destName = "$($f.BaseName).$hash.ttf"          # e.g. Ninter-Black.1a2b3c4d.ttf
  $dest = Join-Path $fontDir $destName

  $cur = (Get-ItemProperty -Path $regKey -Name $regName -ErrorAction SilentlyContinue).$regName
  if ($cur -eq $dest -and (Test-Path $dest)) { $same++; continue }   # already current

  Copy-Item $f.FullName $dest -Force              # new name -> never locked
  New-ItemProperty -Path $regKey -Name $regName -Value $dest -PropertyType String -Force | Out-Null
  # sweep older copies of THIS face (the "." after basename avoids matching *Italic)
  Get-ChildItem $fontDir -Filter "$($f.BaseName).*.ttf" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -ne $dest } |
    ForEach-Object { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue }
  # also try to remove a legacy non-hashed file from older installer versions
  Remove-Item (Join-Path $fontDir "$($f.BaseName).ttf") -Force -ErrorAction SilentlyContinue
  Write-Host "installed $face"
  $updated++
}

Broadcast-FontChange
Write-Host "`nNinter: $updated updated, $same already current." -ForegroundColor Cyan
Write-Host "Restart Word/PowerPoint if open, then pick 'Ninter'. Ctrl+I = Japanese italic, Ctrl+B = Bold." -ForegroundColor Cyan
