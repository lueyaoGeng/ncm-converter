param([string]$Python = 'python')

$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    if (!(Test-Path -LiteralPath 'vendor\ffmpeg.exe' -PathType Leaf)) {
        throw 'Build vendor\ffmpeg.exe using build-ffmpeg.sh first.'
    }
    $options = @(
        '--onefile', '--windowed', '--noconfirm', '--noupx',
        '--name', 'NCMConverter', '--exclude-module', 'numpy',
        '--add-binary', 'vendor\ffmpeg.exe:vendor',
        '--add-data', 'LICENSE:.',
        '--add-data', 'THIRD_PARTY_NOTICES.txt:.',
        '--add-data', 'licenses:licenses',
        'converter.py'
    )
    & $Python -m PyInstaller @options
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
