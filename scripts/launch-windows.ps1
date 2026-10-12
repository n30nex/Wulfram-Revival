param(
    [string]$ClientDir = (Join-Path $PSScriptRoot '..\..\client-windows'),
    [string]$Server = 'wulfram.canadaverse.org',
    [switch]$Windowed
)
$ErrorActionPreference = 'Stop'
$ClientDir = [IO.Path]::GetFullPath($ClientDir)
$game = Join-Path $ClientDir 'wulfram2.exe'
if ((Get-FileHash -LiteralPath $game -Algorithm SHA256).Hash -ne '94990864AB1DB2DDBE2652CFDBCA726356B19DD3FB7597945E297A43973D99D4') {
    throw 'Unrecognized original Wulfram II client build.'
}
if ($Server -notmatch '^[A-Za-z0-9.-]+$') { throw 'Supply an IP address or hostname.' }
foreach ($name in 'ddraw.dll', 'dinput.dll', 'dxwrapper.dll', 'w2reg.dll', 'do_not_update') {
    if (-not (Test-Path -LiteralPath (Join-Path $ClientDir $name) -PathType Leaf)) {
        throw "Missing Windows compatibility file: $name"
    }
}
$gameArguments = @('-root', '-server', $Server)
if ($Windowed) { $gameArguments += @('-windowed', '-allow_windowed') }
# This is the interactive game window, not a background helper.
Start-Process -FilePath $game -ArgumentList $gameArguments -WorkingDirectory $ClientDir
