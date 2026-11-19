#!/usr/bin/env bash
set -euo pipefail

# Build the audio formats used by NCM Converter, natively on macOS or for
# Windows from Ubuntu with the MinGW toolchain.
if [[ $# -ne 2 ]]; then
    echo "Usage: bash build-ffmpeg.sh <source-archives> <output-binary>" >&2
    exit 2
fi

sources=$(cd "$1" && pwd -P)
mkdir -p "$(dirname "$2")"
output="$(cd "$(dirname "$2")" && pwd -P)/$(basename "$2")"
checksums="$(cd "$(dirname "$0")" && pwd -P)/ffmpeg-source-sha256.txt"
workdir=$(mktemp -d)
trap 'rm -rf -- "$workdir"' EXIT
prefix="$workdir/prefix"
library_config=(--prefix="$prefix" --enable-static --disable-shared)
ldflags="-L$prefix/lib"
platform=$(uname -s)

case "$platform" in
    Darwin)
        (cd "$sources" && shasum -a 256 --check "$checksums")
        binary=ffmpeg
        jobs=${JOBS:-$(sysctl -n hw.logicalcpu)}
        export MACOSX_DEPLOYMENT_TARGET=${MACOSX_DEPLOYMENT_TARGET:-11.0}
        ffmpeg_config=(--cc=clang --cxx=clang++ --disable-x86asm)
        ;;
    Linux)
        (cd "$sources" && sha256sum --check "$checksums")
        host=x86_64-w64-mingw32
        binary=ffmpeg.exe
        jobs=${JOBS:-$(nproc)}
        library_config+=(--host="$host")
        ffmpeg_config=(--enable-cross-compile --arch=x86_64 --target-os=mingw32 --cross-prefix="$host-")
        ldflags="-static $ldflags"
        ;;
    *)
        echo "Build FFmpeg from macOS or Ubuntu/WSL." >&2
        exit 2
        ;;
esac

cd "$workdir"

for archive in libogg-1.3.6.tar.gz libvorbis-1.3.7.tar.gz lame_3.100.orig.tar.gz ffmpeg-7.1.5.tar.xz; do
    tar -xf "$sources/$archive"
done

if [[ "$platform" == Darwin ]]; then
    # The older releases predate Apple Silicon. Use the newer GNU host
    # detection scripts distributed with libogg before running configure.
    for library in libvorbis-1.3.7 lame-3.100; do
        for script in config.guess config.sub; do
            find "$library" -name "$script" -exec cp "libogg-1.3.6/$script" '{}' \;
        done
    done
fi

export PKG_CONFIG_LIBDIR="$prefix/lib/pkgconfig"
export CPPFLAGS="-I$prefix/include"
export LDFLAGS="-L$prefix/lib"

build_static_library() {
    (
        cd "$1"
        shift
        if ! ./configure "${library_config[@]}" "$@"; then
            tail -n 100 config.log >&2
            exit 1
        fi
        make -j"$jobs"
        make install
    )
}
build_static_library libogg-1.3.6
build_static_library libvorbis-1.3.7 --with-ogg="$prefix" --disable-oggtest
build_static_library lame-3.100 --disable-frontend --disable-decoder

cd ffmpeg-7.1.5
if ! ./configure \
    "${ffmpeg_config[@]}" \
    --disable-everything --disable-autodetect --disable-network --disable-doc --disable-debug \
    --disable-ffplay --disable-ffprobe --disable-avdevice --enable-ffmpeg \
    --enable-static --disable-shared --enable-gpl --enable-version3 \
    --pkg-config=pkg-config --pkg-config-flags=--static \
    --extra-cflags="-I$prefix/include" --extra-ldflags="$ldflags" \
    --enable-libmp3lame --enable-libvorbis \
    --enable-protocol=file,pipe \
    --enable-demuxer=flac,mp3,wav,aiff,ogg,mov --enable-parser=flac,mpegaudio,aac,vorbis \
    --enable-decoder=flac,mp3,mp3float,aac,vorbis,pcm_s16le,pcm_s24le,pcm_s32le,pcm_s16be,pcm_s24be,pcm_s32be \
    --enable-muxer=flac,mp3,wav,aiff,ogg,ipod,hash \
    --enable-encoder=flac,libmp3lame,libvorbis,aac,pcm_s16le,pcm_s24le,pcm_s32le,pcm_s16be,pcm_s24be,pcm_s32be,pcm_f32le \
    --enable-filter=abuffer,abuffersink,aformat,anull,aresample,atrim; then
    tail -n 100 ffbuild/config.log >&2
    exit 1
fi
make -j"$jobs" "$binary"
install -m755 "$binary" "$output"
