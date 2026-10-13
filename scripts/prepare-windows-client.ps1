param(
    [string]$ClientDir = (Join-Path $PSScriptRoot '..\..\client-windows'),
    [Parameter(Mandatory = $true)][string]$CompatibilityDll,
    [switch]$CheckOnly,
    [switch]$SelfTest
)
$ErrorActionPreference = 'Stop'
$ClientDir = [IO.Path]::GetFullPath($ClientDir)
$CompatibilityDll = [IO.Path]::GetFullPath($CompatibilityDll)
$exeHash = '94990864AB1DB2DDBE2652CFDBCA726356B19DD3FB7597945E297A43973D99D4'
$shapesHash = '8EBE6D994D8F824F9D3D8102F321A9AE9DAE5B815494BC647711E6132229C394'
$shimHash = '477B8938034987DB335998CD3C2BFA2F2BD32A005D5E2114256E12528A0A34AA'

if ($SelfTest) {
    $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $fixture = Join-Path $temporaryRoot ('wulfram-client-check-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path (Join-Path $fixture 'data') | Out-Null
    try {
        foreach ($name in @('wulfram2.exe', 'w2reg.dll', 'ddraw.dll', 'dinput.dll', 'dxwrapper.dll', 'dxwrapper.ini', 'DDrawCompat.ini', 'data\shapes.zip', 'data\shapes2.zip')) {
            Copy-Item -LiteralPath (Join-Path $ClientDir $name) -Destination (Join-Path $fixture $name)
        }
        [IO.File]::WriteAllText((Join-Path $fixture 'wulfram2_player_config'), "display_system `"unspecified`"`r`ncustom_preference keep_me`r`n")
        & $PSCommandPath -ClientDir $fixture -CompatibilityDll $CompatibilityDll
        & $PSCommandPath -ClientDir $fixture -CompatibilityDll $CompatibilityDll -CheckOnly
        $before = @(Get-ChildItem -LiteralPath $fixture -Recurse -Filter '*.pre-canadaverse-*').Count
        & $PSCommandPath -ClientDir $fixture -CompatibilityDll $CompatibilityDll
        if (@(Get-ChildItem -LiteralPath $fixture -Recurse -Filter '*.pre-canadaverse-*').Count -ne $before) { throw 'Preparation is not idempotent.' }
        if (-not ([IO.File]::ReadAllText((Join-Path $fixture 'wulfram2_player_config')).Contains('custom_preference keep_me'))) { throw 'An unrelated preference changed.' }
        $rejected = $false
        try { & $PSCommandPath -ClientDir $fixture -CompatibilityDll (Join-Path $fixture 'wulfram2.exe') -CheckOnly } catch { $rejected = $true }
        if (-not $rejected) { throw 'An invalid compatibility DLL was accepted.' }
        Write-Output 'PASS: actual assets prepared, backups preserved, preferences retained, repeat run unchanged, invalid DLL rejected.'
    } finally {
        if ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($fixture)) -ne $temporaryRoot.TrimEnd('\')) { throw 'Unexpected temporary fixture path.' }
        Remove-Item -LiteralPath $fixture -Recurse -Force
    }
    return
}

function Assert-Hash([string]$Path, [string]$Expected, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -or (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Expected) {
        throw "Unrecognized $Label. See REVIVAL.md for the tested versions and hashes."
    }
}
function Set-Setting([string]$Text, [string]$Name, [string]$Value, [string]$Separator) {
    $pattern = '(?m)^' + [regex]::Escape($Name) + '[ \t]+[^\r\n]*'
    $replacement = $Name + $Separator + $Value
    if ([regex]::IsMatch($Text, $pattern)) { return [regex]::Replace($Text, $pattern, $replacement) }
    $newline = if ($Text.Contains("`r`n") -or $Text.Length -eq 0) { "`r`n" } else { "`n" }
    if ($Text.Length -gt 0 -and -not $Text.EndsWith("`n")) { $Text += $newline }
    return $Text + $replacement + $newline
}

$game = Join-Path $ClientDir 'wulfram2.exe'
Assert-Hash $game $exeHash 'Wulfram II executable'
Assert-Hash $CompatibilityDll $shimHash 'release compatibility DLL (the preserved Debug DLL is unsupported)'
$shapes = Join-Path $ClientDir 'data\shapes2.zip'
Assert-Hash $shapes $shapesHash 'shapes2.zip archive'
foreach ($name in @('ddraw.dll', 'dinput.dll', 'dxwrapper.dll', 'dxwrapper.ini')) {
    if (-not (Test-Path -LiteralPath (Join-Path $ClientDir $name) -PathType Leaf)) { throw "Missing compatibility component: $name" }
}
$wrapper = [IO.File]::ReadAllText((Join-Path $ClientDir 'dxwrapper.ini'))
if ($wrapper -notmatch '(?im)^LoadCustomDllPath\s*=\s*w2reg\.dll\s*$') { throw 'dxwrapper.ini must load w2reg.dll; use the preserved client compatibility profile.' }
$override = Join-Path $ClientDir '_override_args'
if ((Test-Path -LiteralPath $override) -and ([IO.File]::ReadAllText($override) -match '(?m)(^|\s)-(windowed|allow_windowed)(\s|$)')) { throw 'Remove -windowed and -allow_windowed from _override_args before preparing this client.' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($shapes)
try {
    foreach ($name in @('gun_turret_1', 'gun_turret_2', 'scout_1', 'scout_2', 'gun_turret_1_s', 'gun_turret_2_s', 'scout_1_s', 'scout_2_s')) {
        if ($null -eq $archive.GetEntry($name)) { throw "Required model missing: $name" }
    }
} finally { $archive.Dispose() }

$copies = @{'data\shapes.zip' = $shapes; 'w2reg.dll' = $CompatibilityDll}
$textFiles = @{}
foreach ($name in @('wulfram2_player_config', 'DDrawCompat.ini', 'DDrawCompat-wulfram2.ini')) {
    $path = Join-Path $ClientDir $name
    $textFiles[$name] = if (Test-Path -LiteralPath $path) { [IO.File]::ReadAllText($path) }
        elseif ($name -eq 'wulfram2_player_config') { ":/`r`n" } else { '' }
}
$textFiles['wulfram2_player_config'] = Set-Setting $textFiles['wulfram2_player_config'] 'display_system' '"D3D Alpha (supporters only)"' ' '
foreach ($setting in @{AltTabFix='keepvidmem'; DepthFormat='32'; ResolutionScale='display(1)'; ResolutionScaleFilter='point'; SpriteAltPixelCenter='off'; ThreadPriorityBoost='on'; VertexBufferMemoryType='sysmem'; VSync='off'; DpiAwareness='permonitorv2'; FullscreenMode='borderless'; DisplayResolution='desktop'; DisplayAspectRatio='app'}.GetEnumerator()) {
    $textFiles['DDrawCompat.ini'] = Set-Setting $textFiles['DDrawCompat.ini'] $setting.Key $setting.Value ' = '
}
foreach ($setting in @{ResolutionScale='display(1)'; DisplayAspectRatio='app'; DisplayResolution='desktop'; FullscreenMode='borderless'; DpiAwareness='permonitorv2'; SupportedResolutions='native, 640x480, 720x540, 800x600, 864x540, 960x540, 1024x768, 1280x540, 1290x540, 1296x540, 1920x540'; TextureFilter='af16x'; Antialiasing='msaa4x(0)'; SpriteDetection='point'; SpriteFilter='point'}.GetEnumerator()) {
    $textFiles['DDrawCompat-wulfram2.ini'] = Set-Setting $textFiles['DDrawCompat-wulfram2.ini'] $setting.Key $setting.Value ' = '
}
if (-not (Test-Path -LiteralPath (Join-Path $ClientDir 'do_not_update'))) { $textFiles['do_not_update'] = "Retired original updater disabled for the preserved client.`r`n" }
$changes = @()
foreach ($name in $copies.Keys) {
    $path = Join-Path $ClientDir $name
    if (-not (Test-Path -LiteralPath $path) -or (Get-FileHash -LiteralPath $path).Hash -ne (Get-FileHash -LiteralPath $copies[$name]).Hash) { $changes += $name }
}
foreach ($name in $textFiles.Keys) {
    $path = Join-Path $ClientDir $name
    if (-not (Test-Path -LiteralPath $path) -or [IO.File]::ReadAllText($path) -cne $textFiles[$name]) { $changes += $name }
}
if ($CheckOnly) {
    if ($changes.Count) { throw ('Client preparation required: ' + ($changes -join ', ')) }
    Write-Output 'Windows client preparation verified.'
    return
}
if (Get-Process -Name wulfram2 -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $game }) { throw 'Close this Wulfram II client before changing its files.' }
$backupSuffix = '.pre-canadaverse-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 6)
foreach ($name in $changes) {
    $path = Join-Path $ClientDir $name
    if (Test-Path -LiteralPath $path) { Copy-Item -LiteralPath $path -Destination ($path + $backupSuffix) }
    if ($copies.ContainsKey($name)) { Copy-Item -LiteralPath $copies[$name] -Destination $path -Force }
    else { [IO.File]::WriteAllText($path, $textFiles[$name], [Text.UTF8Encoding]::new($false)) }
}
Write-Output ("Windows client prepared; {0} files changed. Existing files have adjacent .pre-canadaverse-* backups." -f $changes.Count)
