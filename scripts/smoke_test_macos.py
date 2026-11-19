"""Exercise the downloadable bundle with generated audio and artwork."""
import base64
import errno
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import wave
from unittest.mock import patch

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from converter import FORMATS, publish_file, read_tags


def create_source(path, payload, file_format, cover):
    key = b'NCM smoke test key'
    core = bytes.fromhex('687a4852416d736f356b496e62617857')
    meta = bytes.fromhex('2331346c6a6b5f215c5d2630553c2728')
    title = '示例曲目'
    metadata = {
        'musicName': title,
        'artist': [['测试艺人', 1], ['Guest Artist', 2]],
        'album': '测试专辑',
        'format': file_format,
    }
    encrypted_key = AES.new(core, AES.MODE_ECB).encrypt(pad(b'neteasecloudmusic' + key, 16))
    encoded_meta = b'music:' + json.dumps(metadata, ensure_ascii=False).encode('utf-8')
    encrypted_meta = AES.new(meta, AES.MODE_ECB).encrypt(pad(encoded_meta, 16))

    def sized(data):
        return struct.pack('<I', len(data)) + data

    box = list(range(256))
    j = 0
    for i in range(256):
        j = (j + box[i] + key[i % len(key)]) % 256
        box[i], box[j] = box[j], box[i]
    mask = bytearray()
    for i in range(256):
        j = (i + 1) % 256
        mask.append(box[(box[j] + box[(box[j] + j) % 256]) % 256])
    audio = bytes(byte ^ mask[i % 256] for i, byte in enumerate(payload.read_bytes()))
    header = b'CTENFDAM\0\0' + sized(bytes(byte ^ 0x64 for byte in encrypted_key))
    field = b"163 key(Don't modify):" + base64.b64encode(encrypted_meta)
    header += sized(bytes(byte ^ 0x63 for byte in field))
    header += b'\0' * 5 + struct.pack('<II', len(cover), len(cover))
    path.write_bytes(header + cover + audio)
    return metadata


def run(app, ffmpeg, temp):
    # Exclude Homebrew from the executable's search path, as on a clean Mac.
    env = dict(os.environ, PATH='/usr/bin:/bin:/usr/sbin:/sbin')
    with subprocess.Popen([str(app)], env=env) as gui:
        try:
            result = gui.wait(timeout=4)
        except subprocess.TimeoutExpired:
            print('GUI launched and stayed open')
        else:
            raise RuntimeError(f'GUI exited with code {result}')
        finally:
            if gui.poll() is None:
                gui.terminate()
                gui.wait(timeout=10)

    staged = temp / 'completed-audio'
    output = temp / 'reserved-output'
    staged.write_bytes(b'complete')
    with patch('converter.os.link', side_effect=OSError(errno.ENOTSUP, 'hard links unavailable')):
        publish_file(staged, output)
        assert output.read_bytes() == b'complete'
        staged.write_bytes(b'different')
        try:
            publish_file(staged, output)
        except FileExistsError:
            assert output.read_bytes() == b'complete'
        else:
            raise AssertionError('Replacement of an existing output should fail')

    wav = temp / 'tone.wav'
    with wave.open(str(wav), 'wb') as f:
        f.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
        samples = (int(math.sin(2 * math.pi * 440 * i / 44100) * 8000) for i in range(44100))
        f.writeframes(b''.join(struct.pack('<h', sample) for sample in samples))

    def decoded_hash(path):
        return subprocess.check_output([
            str(ffmpeg), '-v', 'error', '-nostdin', '-i', str(path),
            '-map', '0:a:0', '-c:a', 'pcm_f32le', '-f', 'hash', '-hash', 'sha256', '-',
        ], env=env)

    for original, codec, picture in [('flac', 'flac', 'png'), ('mp3', 'libmp3lame', 'jpg')]:
        payload = temp / f'tone.{original}'
        subprocess.run([
            str(ffmpeg), '-v', 'error', '-nostdin', '-i', str(wav), '-c:a', codec, str(payload),
        ], env=env, check=True)
        image = temp / f'cover.{picture}'
        Image.new('RGB', (32, 32), (40, 80, 120)).save(image)
        cover = image.read_bytes()
        source = temp / f'{original} 测试.ncm'
        meta = create_source(source, payload, original, cover)
        original_bytes = source.read_bytes()

        for mode in FORMATS:
            output_dir = temp / f'{original} 输出 {mode}'
            subprocess.run(
                [str(app), str(source), '-f', mode, '-o', str(output_dir)],
                env=env, check=True, timeout=40,
            )
            output, = output_dir.iterdir()
            expected_suffix = original if mode == '原格式' else mode.lower()
            assert output.suffix == f'.{expected_suffix}', output
            title, artist, album, images = read_tags(output)
            artists = [credit[0] for credit in meta['artist']]
            expected = ['/'.join(artists)] if expected_suffix in ('mp3', 'wav', 'aiff') else artists
            assert (title, artist, album) == ([meta['musicName']], expected, [meta['album']]), output
            assert images == [cover], output
            decoded = decoded_hash(output)
            if mode == '原格式' or (original == 'flac' and mode in ('WAV', 'AIFF', 'FLAC')):
                assert decoded == decoded_hash(payload), output
            print(f'{original} → {mode}: audio decoded, tags and cover verified', flush=True)
        assert original_bytes == source.read_bytes(), source


if __name__ == '__main__':
    bundle = Path(sys.argv[1]).resolve()
    executable = bundle / 'Contents/MacOS/NCMConverter'
    engine = bundle / 'Contents/Frameworks/vendor/ffmpeg'
    assert executable.is_file() and engine.is_file() and os.access(engine, os.X_OK)
    with tempfile.TemporaryDirectory(prefix='ncm smoke ') as directory:
        run(executable, engine, Path(directory))
