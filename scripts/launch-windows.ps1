param(
    [string]$ClientDir = (Join-Path $PSScriptRoot '..\..\client-windows'),
    [string]$Server = 'wulfram.canadaverse.org'
)
$ErrorActionPreference = 'Stop'
$ClientDir = [IO.Path]::GetFullPath($ClientDir)
$game = Join-Path $ClientDir 'wulfram2.exe'
if ($Server -notmatch '^[A-Za-z0-9.-]+$') { throw 'Supply an IP address or hostname.' }
& (Join-Path $PSScriptRoot 'prepare-windows-client.ps1') -ClientDir $ClientDir -CompatibilityDll (Join-Path $ClientDir 'w2reg.dll') -CheckOnly
$gameArguments = @('-root', '-server', $Server)
# This is the interactive game window, not a background helper.
Start-Process -FilePath $game -ArgumentList $gameArguments -WorkingDirectory $ClientDir
