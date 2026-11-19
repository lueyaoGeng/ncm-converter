#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
if [[ "$(uname -s)" != Darwin ]]; then
    echo "Run this build on macOS." >&2
    exit 2
fi
if [[ ! -x vendor/ffmpeg ]]; then
    echo "Build vendor/ffmpeg using build-ffmpeg.sh first." >&2
    exit 2
fi
python=${PYTHON:-python3}
arch=$("$python" -c 'import platform; print(platform.machine())')
native_arch=$(uname -m)
if [[ "$arch" != "$native_arch" ]]; then
    echo "The Python interpreter must run on this Mac's native architecture." >&2
    exit 2
fi

"$python" -m PyInstaller --onedir --windowed --noconfirm --noupx \
    --name NCMConverter --target-arch "$arch" \
    --osx-bundle-identifier io.github.lueyaogeng.ncmconverter \
    --exclude-module numpy --add-binary 'vendor/ffmpeg:vendor' \
    --add-data 'LICENSE:.' --add-data 'THIRD_PARTY_NOTICES.txt:.' \
    --add-data 'licenses:licenses' converter.py

app=dist/NCMConverter.app
codesign --verify --deep --strict "$app"
lipo "$app/Contents/MacOS/NCMConverter" -verify_arch "$arch"
ditto -c -k --sequesterRsrc --keepParent "$app" "dist/NCMConverter-macos-$arch.zip"
