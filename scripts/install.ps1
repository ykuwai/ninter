# Install (or uninstall) all built Ninter fonts for the current user.
#   Install:    powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#   Uninstall:  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Uninstall
# Per-user install (no admin needed): copies to %LOCALAPPDATA%\Microsoft\Windows\Fonts
# and registers each face in HKCU so Word/PowerPoint see them and Ctrl+I / Ctrl+B link.
param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $root "build"
$fontDir = Join-Path $env:LOCALAPPDATA "Microsoft\Windows\Fonts"
$regKey = "HKCU:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"

# Map PostScript-ish file stem -> the name Windows shows in the registry value.
function Get-FaceName([string]$stem) {
  # stem like "Ninter-SemiBoldItalic" -> "Ninter SemiBold Italic"
  $s = $stem -replace '^Ninter-', ''
  # -creplace = case-SENSITIVE (plain -replace is case-insensitive in PowerShell,
  # which would match every letter pair and mangle the name).
  $s = $s -creplace '([a-z])([A-Z])', '$1 $2'   # split camelCase
  return "Ninter $s"
}

$fonts = Get-ChildItem -Path $buildDir -Filter "Ninter-*.ttf" -ErrorAction SilentlyContinue
if (-not $fonts) { Write-Host "No built fonts in $buildDir. Run: python build.py" -ForegroundColor Yellow; exit 1 }

if (-not (Test-Path $fontDir)) { New-Item -ItemType Directory -Path $fontDir -Force | Out-Null }

foreach ($f in $fonts) {
  $dest = Join-Path $fontDir $f.Name
  $face = Get-FaceName ([IO.Path]::GetFileNameWithoutExtension($f.Name))
  $regName = "$face (TrueType)"
  if ($Uninstall) {
    if (Test-Path $dest) { Remove-Item $dest -Force -ErrorAction SilentlyContinue }
    if (Get-ItemProperty -Path $regKey -Name $regName -ErrorAction SilentlyContinue) {
      Remove-ItemProperty -Path $regKey -Name $regName -Force -ErrorAction SilentlyContinue
    }
    Write-Host "removed  $face"
  } else {
    Copy-Item $f.FullName $dest -Force
    New-ItemProperty -Path $regKey -Name $regName -Value $dest -PropertyType String -Force | Out-Null
    Write-Host "installed $face"
  }
}

if ($Uninstall) {
  Write-Host "`nUninstalled Ninter. Restart apps to refresh." -ForegroundColor Cyan
} else {
  Write-Host "`nInstalled Ninter (per-user). Restart Word/PowerPoint, pick 'Ninter'." -ForegroundColor Cyan
  Write-Host "Ctrl+I -> Japanese italic (gentle slant), Ctrl+B -> Bold." -ForegroundColor Cyan
}
