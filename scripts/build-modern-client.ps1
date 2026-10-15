param([string]$CacheDirectory = (Join-Path $PSScriptRoot '..\build\godot-4.7.2'))
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$cache = [IO.Path]::GetFullPath($CacheDirectory)
$project = Join-Path $repo 'client\modern'
$output = Join-Path $repo 'build\modern-client'
New-Item -ItemType Directory -Force -Path $cache,$output | Out-Null

$files = @{
    'Godot_v4.7.2-stable_win64.exe.zip' = '83decd58fdf67b9d657958a1ae6bf1929c20785315a81effe245874cdc57acb709bf868e00778a96984338c1b29dafdb453c6847747694621c6ecf5da2259993'
    'Godot_v4.7.2-stable_export_templates.tpz' = 'ca4d71c4d7b81dfc15d1a98baa07534aa95b03fdda78a0075b06672e1648d2e5f40980c9adc28d23e1b92e732ee7bf3461997aa804af74ec2fcd7a93ccb84079'
}
foreach($name in $files.Keys) {
    $archive = Join-Path $cache $name
    if(!(Test-Path -LiteralPath $archive)) {
        Invoke-WebRequest -Uri "https://github.com/godotengine/godot-builds/releases/download/4.7.2-stable/$name" -OutFile $archive
    }
    if((Get-FileHash -LiteralPath $archive -Algorithm SHA512).Hash -ne $files[$name]) { throw "Checksum mismatch: $name" }
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$editorZip = [IO.Compression.ZipFile]::OpenRead((Join-Path $cache 'Godot_v4.7.2-stable_win64.exe.zip'))
try {
    foreach($name in @('Godot_v4.7.2-stable_win64.exe','Godot_v4.7.2-stable_win64_console.exe')) {
        $entry = $editorZip.GetEntry($name)
        if(!$entry) { throw "Missing official engine: $name" }
        $stream = $entry.Open()
        $hasher = [Security.Cryptography.SHA256]::Create()
        try { $expected = [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-','') }
        finally { $stream.Dispose(); $hasher.Dispose() }
        $path = Join-Path $cache $name
        # Reuse identical binaries, including an engine running a test window.
        if(!(Test-Path -LiteralPath $path) -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $expected) {
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,$path,$true)
        }
    }
} finally { $editorZip.Dispose() }
$template = Join-Path $env:APPDATA 'Godot\export_templates\4.7.2.stable'
New-Item -ItemType Directory -Force -Path $template | Out-Null
$zip = [IO.Compression.ZipFile]::OpenRead((Join-Path $cache 'Godot_v4.7.2-stable_export_templates.tpz'))
try {
    foreach($name in @('windows_release_x86_64.exe','windows_release_x86_64_console.exe','version.txt')) {
        $entry = $zip.GetEntry("templates/$name")
        if(!$entry) { throw "Missing official export template: $name" }
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,(Join-Path $template $name),$true)
    }
} finally { $zip.Dispose() }
$engine = Join-Path $cache 'Godot_v4.7.2-stable_win64_console.exe'
python (Join-Path $repo 'scripts\check-modern-client.py') --godot $engine --output (Join-Path $output 'checks.json')
if($LASTEXITCODE -ne 0) { throw 'Modern-client checks failed.' }
$log = & $engine --headless --path $project --export-release 'Windows Desktop' (Join-Path $output 'WulframRevival.exe') 2>&1
$log | Write-Output
if($LASTEXITCODE -ne 0 -or ($log -join "`n") -match '(SCRIPT ERROR:|ERROR:)') { throw 'Modern-client export failed.' }
$revision = git -C $repo rev-parse HEAD
$dirty = [bool](git -C $repo status --porcelain)
$manifest = [ordered]@{schema=1; version='0.1.6-dev'; source=$revision; dirty=$dirty; engine='4.7.2-stable'; channel='development-preview'; files=@()}
foreach($name in @('WulframRevival.exe','WulframRevival.pck')) {
    $path = Join-Path $output $name
    $manifest.files += @{name=$name;sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant();bytes=(Get-Item -LiteralPath $path).Length}
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $output 'BUILD.json') -Encoding utf8
Copy-Item -LiteralPath (Join-Path $project 'README.md') -Destination (Join-Path $output 'README.md')
Copy-Item -LiteralPath (Join-Path $project 'ORIGINAL_FORMATS.md') -Destination (Join-Path $output 'ORIGINAL_FORMATS.md')
Copy-Item -LiteralPath (Join-Path $project 'COMBAT_AUDIO.md') -Destination (Join-Path $output 'COMBAT_AUDIO.md')
Copy-Item -LiteralPath (Join-Path $repo 'LICENSE') -Destination (Join-Path $output 'LICENSE')
Copy-Item -LiteralPath (Join-Path $repo 'NOTICE') -Destination (Join-Path $output 'NOTICE')
Write-Output "MODERN_CLIENT_EXPORT=$output"
