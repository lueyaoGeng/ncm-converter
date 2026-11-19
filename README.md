# NCM 转换器

离线批量转换本机的 NCM 音频。导出时把标题、艺术家、专辑和原有封面写入音频文件。

## 下载和使用

1. 在 [GitHub Releases](https://github.com/lueyaoGeng/ncm-converter/releases/latest) 下载 `NCMConverter.exe`。支持 64 位 Windows。
2. 双击 EXE，添加一个或多个 NCM 文件，也可以添加整个文件夹。
3. 选择输出格式和目录，点击 **开始转换**。

支持 WAV、FLAC、MP3、OGG Vorbis、M4A AAC、AIFF 和原格式提取。原格式提取沿用源文件中的 MP3 或 FLAC 音频编码。可设置采样率、MP3 和 M4A 码率以及 WAV 和 AIFF 位深。

每首歌生成一个音频文件。源文件缺少封面、艺术家或专辑时会在列表提示。重名时添加编号。部分播放器不会显示 WAV、OGG 或 AIFF 中的内嵌封面，可以用支持相应标签格式的播放器或标签编辑器检查。Windows 的属性列由系统为各个格式提供的读取组件决定。

## 从源码运行

需要 Python 3.11、Tk 和 FFmpeg。将 FFmpeg 加入 PATH 或放到 `vendor/ffmpeg.exe`，然后运行：

```powershell
python -m pip install -r requirements.txt
python converter.py
```

指定输入文件和输出格式可以直接在终端批量转换。

```powershell
python converter.py "D:\NCM" -f WAV --depth 16 --rate 44100 -o "D:\WAV"
```

## 构建 Windows EXE

在 [v1.0.0 发布页](https://github.com/lueyaoGeng/ncm-converter/releases/tag/v1.0.0) 下载 `corresponding-sources.zip`，解压其中的 FFmpeg、LAME、libogg 和 libvorbis 源码归档。脚本会校验这些归档的 SHA-256。

在 Ubuntu 或 WSL 的 Ubuntu 中执行：

```bash
sudo apt-get install build-essential gcc-mingw-w64-x86-64-posix pkg-config nasm
mkdir -p vendor
bash build-ffmpeg.sh /path/to/extracted-archives vendor/ffmpeg.exe
```

在 64 位 Windows 下使用 Python 3.11 构建，成品在 `dist/NCMConverter.exe`。

```powershell
py -3.11 -m venv .venv
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install -r build-requirements.txt
.\build.ps1 -Python $python
```

## 许可

应用以 [GPL-3.0-or-later](LICENSE) 发布。可转发本项目的 Release 链接，让接收者同时取得程序、源码和许可。第三方组件详见 [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt)。NCM 格式说明参考 [taurusxin/ncmdump](https://github.com/taurusxin/ncmdump)。
