# Reliable keep-awake for long unattended work (no dependence on a live process).
# Disables the display-off and sleep timeouts on the ACTIVE power scheme by editing
# powercfg directly, saving the originals so they can be restored exactly.
#
#   Enable :  powershell -ExecutionPolicy Bypass -File scripts\keepawake.ps1 -On
#   Restore:  powershell -ExecutionPolicy Bypass -File scripts\keepawake.ps1 -Restore
#   Status :  powershell -ExecutionPolicy Bypass -File scripts\keepawake.ps1 -Status
#
# Why powercfg (not SetThreadExecutionState): a background/non-interactive process
# does not reliably hold ES_DISPLAY_REQUIRED for the interactive session, so the
# screen still slept. A scheme timeout of 0 (=never) is enforced by the OS itself and
# needs no running process. Language-independent (reads hex indices, not localized text).
param([switch]$On, [switch]$Restore, [switch]$Status)

$ErrorActionPreference = "Stop"
$stateDir = Join-Path (Split-Path -Parent $PSScriptRoot) ".keepawake"
$stateFile = Join-Path $stateDir "original.json"

# The last two hex values in a `powercfg /q ... SETTING` block are always the
# AC then DC current index (after min/max/increment) -> language independent.
function Get-Idx($sub, $set) {
  $q = (powercfg /q SCHEME_CURRENT $sub $set) -join "`n"
  $m = [regex]::Matches($q, '0x[0-9a-fA-F]{8}')
  return @([Convert]::ToInt32($m[$m.Count - 2].Value, 16),
           [Convert]::ToInt32($m[$m.Count - 1].Value, 16))
}
function Set-Idx($sub, $set, $ac, $dc) {
  powercfg /setacvalueindex SCHEME_CURRENT $sub $set $ac | Out-Null
  powercfg /setdcvalueindex SCHEME_CURRENT $sub $set $dc | Out-Null
}

if ($Status) {
  $v = Get-Idx SUB_VIDEO VIDEOIDLE; $s = Get-Idx SUB_SLEEP STANDBYIDLE
  "display-off  AC/DC (sec): $($v[0]) / $($v[1])   (0 = never)"
  "sleep        AC/DC (sec): $($s[0]) / $($s[1])"
  if (Test-Path $stateFile) { "keep-awake is ON (saved originals exist)" } else { "keep-awake is OFF" }
  return
}

if ($On) {
  if (-not (Test-Path $stateFile)) {
    $v = Get-Idx SUB_VIDEO VIDEOIDLE; $s = Get-Idx SUB_SLEEP STANDBYIDLE
    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
    @{ video_ac = $v[0]; video_dc = $v[1]; sleep_ac = $s[0]; sleep_dc = $s[1] } |
      ConvertTo-Json | Set-Content $stateFile -Encoding utf8
    "saved originals: display $($v[0])/$($v[1])s  sleep $($s[0])/$($s[1])s"
  } else { "originals already saved (keep-awake was already on)" }
  Set-Idx SUB_VIDEO VIDEOIDLE 0 0
  Set-Idx SUB_SLEEP STANDBYIDLE 0 0
  powercfg /setactive SCHEME_CURRENT | Out-Null
  "keep-awake ON: display + sleep set to NEVER (AC & DC)."
  return
}

if ($Restore) {
  if (-not (Test-Path $stateFile)) { "no saved state; nothing to restore."; return }
  $o = Get-Content $stateFile -Raw | ConvertFrom-Json
  Set-Idx SUB_VIDEO VIDEOIDLE $o.video_ac $o.video_dc
  Set-Idx SUB_SLEEP STANDBYIDLE $o.sleep_ac $o.sleep_dc
  powercfg /setactive SCHEME_CURRENT | Out-Null
  Remove-Item $stateFile -Force
  "restored: display $($o.video_ac)/$($o.video_dc)s  sleep $($o.sleep_ac)/$($o.sleep_dc)s"
  return
}

"Specify -On, -Restore, or -Status."
