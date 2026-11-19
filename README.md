# NCM 转换器

离线批量转换本机的 NCM 音频。导出时把标题、艺术家、专辑和原有封面写入音频文件。

## 下载和使用

| 系统 | 安装包 |
| --- | --- |
| macOS Apple 芯片 | [NCMConverter-macos-arm64.zip](https://github.com/lueyaoGeng/ncm-converter/releases/download/v1.1.0/NCMConverter-macos-arm64.zip) |
| macOS Intel 芯片 | [NCMConverter-macos-x86_64.zip](https://github.com/lueyaoGeng/ncm-converter/releases/download/v1.1.0/NCMConverter-macos-x86_64.zip) |
| Windows x64 | [NCMConverter.exe](https://github.com/lueyaoGeng/ncm-converter/releases/download/v1.0.0/NCMConverter.exe) |

Mac 解压 ZIP 后打开 `NCMConverter.app`。Windows 直接打开 EXE。添加 NCM 文件或文件夹，选择输出格式和目录，再点击 **开始转换**。两种安装包都自带运行环境。

Mac 版默认将成品保存到用户的 `音乐/NCM 转换结果` 文件夹。通过「苹果菜单 → 关于本机」查看芯片型号。这两个 Mac 安装包采用临时签名，尚未通过 Apple 公证。首次打开如果看到系统提示，可查看 [Apple 官方说明](https://support.apple.com/zh-cn/102445)。

支持 WAV、FLAC、MP3、OGG Vorbis、M4A AAC、AIFF 和原格式提取。原格式提取沿用源文件中的 MP3 或 FLAC 音频编码。可设置采样率、MP3 和 M4A 码率以及 WAV 和 AIFF 位深。

每首歌生成一个音频文件。源文件缺少封面、艺术家或专辑时会在列表提示。重名时添加编号。部分播放器不会显示 WAV、OGG 或 AIFF 中的内嵌封面，可以用支持相应标签格式的播放器或标签编辑器检查。Windows 的属性列由系统为各个格式提供的读取组件决定。

## 从源码运行

需要 Python 3.11 或 3.13、Tk 和 FFmpeg。将 FFmpeg 加入 PATH，或将它放到项目里的 `vendor/ffmpeg.exe`（Windows）或 `vendor/ffmpeg`（Mac）。

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

## 构建 macOS App

GitHub Actions 的「Build macOS apps」流程分别构建并检查 Apple 芯片和 Intel 版本。手动构建需要 Mac、Xcode 命令行工具、`pkg-config`，以及带 Tk 的 [Python 3.13.17](https://www.python.org/downloads/release/python-31317/)。

将发布页的 `corresponding-sources.zip` 解压到同一个源码归档目录，然后在 Mac 上运行以下命令。ZIP 成品位于 `dist/`。

```bash
bash build-ffmpeg.sh /path/to/extracted-archives vendor/ffmpeg
python3.13 -m venv .venv
.venv/bin/python -m pip install -r build-requirements.txt
PYTHON=.venv/bin/python bash build-macos.sh
```

## 许可

应用以 [GPL-3.0-or-later](LICENSE) 发布。可转发本项目的 Release 链接，让接收者同时取得程序、源码和许可。第三方组件详见 [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt)。NCM 格式说明参考 [taurusxin/ncmdump](https://github.com/taurusxin/ncmdump)。
