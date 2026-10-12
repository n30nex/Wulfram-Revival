param(
    [Parameter(Mandatory = $true)][string]$ClientDir,
    [ValidateSet('modern', 'classic')][string]$Preset = 'modern'
)
$ErrorActionPreference = 'Stop'
$ClientDir = [IO.Path]::GetFullPath($ClientDir)
$game = Join-Path $ClientDir 'wulfram2.exe'
if (-not (Test-Path -LiteralPath $game -PathType Leaf)) { throw 'Choose the extracted Wulfram client folder.' }
if (Get-Process wulfram2 -ErrorAction SilentlyContinue | Where-Object Path -EQ $game) { throw 'Close this client before changing its controls.' }
$profiles = Join-Path $ClientDir 'canadaverse\controls'
$classic = Join-Path $profiles 'classic'
$modern = Join-Path $profiles 'modern'
[IO.Directory]::CreateDirectory($classic) | Out-Null
[IO.Directory]::CreateDirectory($modern) | Out-Null
$movement = @'

axis_key "movement" "w" "moving_forward" absolute 1.0
axis_key "movement" "s" "moving_forward" absolute -1.0
axis_key "movement" "a" "moving_sideways" absolute -1.0
axis_key "movement" "d" "moving_sideways" absolute 1.0
axis_key "movement" "q" "turning" absolute -0.6
axis_key "movement" "e" "turning" absolute 0.6
action_key "movement" " " "jumpjet"
'@
foreach ($name in 'keymap', 'keymap_tank', 'keymap_scout') {
    $target = Join-Path $ClientDir ('data\' + $name)
    $original = Join-Path $classic $name
    if (-not (Test-Path -LiteralPath $original)) { Copy-Item -LiteralPath $target -Destination $original }
    $lines = [IO.File]::ReadAllLines($original) | Where-Object {
        $_ -notmatch '^(?:axis_key|weapon_key|action_key)\s+"[^"]*"\s+"(?:w|a|s|d|q|e| )"\s'
    }
    $bindings = if ($name -eq 'keymap') { 'axis_key "movement" "shift-q" "upward_thrust" relative 0.5' } else { $movement }
    $text = ($lines -join "`r`n") + "`r`n" + ($bindings -replace "`r?`n", "`r`n") + "`r`n"
    [IO.File]::WriteAllText((Join-Path $modern $name), $text, [Text.UTF8Encoding]::new($false))
    $selected = Join-Path (Join-Path $profiles $Preset) $name
    if ((Get-FileHash -LiteralPath $target).Hash -ne (Get-FileHash -LiteralPath $selected).Hash) {
        $backup = $target + '.pre-canadaverse-controls-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff')
        Copy-Item -LiteralPath $target -Destination $backup
        Copy-Item -LiteralPath $selected -Destination $target -Force
    }
}
Write-Output "Applied $Preset controls. The classic profile is preserved in canadaverse\controls\classic."
