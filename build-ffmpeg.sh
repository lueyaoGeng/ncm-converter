#!/usr/bin/env bash
set -euo pipefail

# Cross-compile only the audio formats used by NCM Converter.
# On Ubuntu: sudo apt-get install build-essential gcc-mingw-w64-x86-64-posix pkg-config nasm
if [[ $# -ne 2 ]]; then
    echo "Usage: bash build-ffmpeg.sh <source-archives> <target-ffmpeg.exe>" >&2
    exit 2
fi

sources=$(realpath "$1")
output=$(realpath -m "$2")
checksums=$(realpath "$(dirname "$0")/ffmpeg-source-sha256.txt")
(cd "$sources" && sha256sum --check "$checksums")
workdir=$(mktemp -d)
prefix="$workdir/prefix"
host=x86_64-w64-mingw32
jobs=${JOBS:-$(nproc)}
trap 'rm -rf -- "$workdir"' EXIT
cd "$workdir"

for archive in libogg-1.3.6.tar.gz libvorbis-1.3.7.tar.gz lame_3.100.orig.tar.gz ffmpeg-7.1.5.tar.xz; do
    tar -xf "$sources/$archive"
done

export PKG_CONFIG_LIBDIR="$prefix/lib/pkgconfig"
export CPPFLAGS="-I$prefix/include"
export LDFLAGS="-L$prefix/lib"

build_static_library() {
    (
        cd "$1"
        shift
        ./configure --host="$host" --prefix="$prefix" --enable-static --disable-shared "$@"
        make -j"$jobs"
        make install
    )
}
build_static_library libogg-1.3.6
build_static_library libvorbis-1.3.7 --with-ogg="$prefix" --disable-oggtest
build_static_library lame-3.100 --disable-frontend --disable-decoder

cd ffmpeg-7.1.5
if ! ./configure \
    --enable-cross-compile --arch=x86_64 --target-os=mingw32 --cross-prefix="$host-" \
    --disable-everything --disable-autodetect --disable-network --disable-doc --disable-debug \
    --disable-ffplay --disable-ffprobe --disable-avdevice --enable-ffmpeg \
    --enable-static --disable-shared --enable-gpl --enable-version3 \
    --pkg-config=pkg-config --pkg-config-flags=--static \
    --extra-cflags="-I$prefix/include" --extra-ldflags="-static -L$prefix/lib" \
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
make -j"$jobs" ffmpeg.exe
install -m755 ffmpeg.exe "$output"
