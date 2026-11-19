# SPDX-License-Identifier: GPL-3.0-or-later
"""Local NCM conversion. Container layout reference: taurusxin/ncmdump.
No network access; source files are never modified.
"""
from __future__ import annotations
import argparse
import base64
import errno
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import queue
import sys

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from PIL import Image
from mutagen import File as AudioFile
from mutagen.wave import WAVE
from mutagen.aiff import AIFF
from mutagen.mp3 import MP3
from mutagen.flac import FLAC, Picture
from mutagen.oggvorbis import OggVorbis
from mutagen.mp4 import MP4, MP4Cover
from mutagen.id3 import TIT2, TPE1, TALB, APIC

FORMATS = ('WAV', 'FLAC', 'MP3', 'OGG', 'M4A', 'AIFF', '原格式')
RATE_VALUES = ('与源一致', '8000', '11025', '12000', '16000', '22050', '24000', '32000', '44100', '48000', '88200', '96000')
APP_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
RESOURCE_DIR = Path(getattr(sys, '_MEIPASS', APP_DIR))
ON_MAC = sys.platform == 'darwin'
DEFAULT_OUTPUT = (Path.home() / 'Music' if ON_MAC else APP_DIR) / 'NCM 转换结果'


def ffmpeg_path():
    filename = 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'
    bundled = RESOURCE_DIR / 'vendor' / filename
    if bundled.is_file():
        return str(bundled)
    installed = shutil.which('ffmpeg')
    if installed:
        return installed
    raise RuntimeError('找不到 FFmpeg。请使用打包版，或将 FFmpeg 加入 PATH。')

def read_exact(f, n):
    b = f.read(n)
    if len(b) != n:
        raise ValueError('NCM 文件截断或损坏')
    return b

def u32(f):
    return struct.unpack('<I', read_exact(f, 4))[0]

def block(f, limit):
    n = u32(f)
    if n > limit:
        raise ValueError('NCM 头部长度异常')
    return read_exact(f, n)

def unpack_ncm(path, folder):
    with path.open('rb') as f:
        if read_exact(f, 8) != b'CTENFDAM':
            raise ValueError('不是有效的 NCM 文件')
        read_exact(f, 2)
        key = block(f, 1024 * 1024)
        key = unpad(AES.new(bytes.fromhex('687A4852416D736F356B496E62617857'), AES.MODE_ECB).decrypt(bytes(x ^ 0x64 for x in key)), 16)
        if not key.startswith(b'neteasecloudmusic'):
            raise ValueError('无法解析 NCM 音频密钥')
        key = key[17:]
        if not key:
            raise ValueError('NCM 音频密钥为空')
        enc_meta = block(f, 16 * 1024 * 1024)
        meta = {}
        if enc_meta:
            decoded = bytes(x ^ 0x63 for x in enc_meta)
            raw = unpad(AES.new(bytes.fromhex('2331346C6A6B5F215C5D2630553C2728'), AES.MODE_ECB).decrypt(base64.b64decode(decoded[22:])), 16)
            raw = raw.split(b':', 1)[1]
            meta = json.loads(raw.decode('utf-8'))
            if 'mainMusic' in meta:
                meta = meta['mainMusic']
        read_exact(f, 5)
        capacity, size = u32(f), u32(f)
        if size > capacity or capacity > 64 * 1024 * 1024:
            raise ValueError('NCM 封面长度异常')
        cover = read_exact(f, size)
        read_exact(f, capacity - size)
        mime = None
        if cover:
            with Image.open(io.BytesIO(cover)) as im:
                mime = Image.MIME.get(im.format)
                im.verify()
            if mime not in ('image/jpeg', 'image/png'):
                raise ValueError('封面不是受支持的 JPEG/PNG')
        box = list(range(256))
        j = 0
        for i in range(256):
            j = (j + box[i] + key[i % len(key)]) & 255
            box[i], box[j] = box[j], box[i]
        stream = bytes(box[(box[(i + 1) & 255] + box[(box[(i + 1) & 255] + ((i + 1) & 255)) & 255]) & 255] for i in range(256))
        # Each byte position uses a 256-byte repeating XOR pattern.
        payload = folder / 'decoded.audio'
        offset = 0
        with payload.open('wb') as out:
            while data := f.read(1024 * 1024):
                buf = bytearray(data)
                for i in range(256):
                    part = buf[i::256]
                    buf[i::256] = part.translate(bytes(x ^ stream[(offset + i) & 255] for x in range(256)))
                out.write(buf)
                offset += len(data)
        # Use the parsed audio type so FLAC with a leading ID3 tag is recognized.
        probe = AudioFile(payload)
        if isinstance(probe, FLAC):
            original_format = 'flac'
        elif isinstance(probe, MP3):
            original_format = 'mp3'
        else:
            raise ValueError('NCM 中的音频不是受支持的 FLAC 或 MP3')
        return payload, original_format, meta, cover, mime

def riff_chunk(key, data):
    return key + struct.pack('<I', len(data)) + data + (b'\0' if len(data) & 1 else b'')

def write_tags(path, title, artists, album, cover, mime):
    fmt = path.suffix.lower()
    if fmt in ('.wav', '.mp3', '.aiff'):
        cls = {'.wav': WAVE, '.mp3': MP3, '.aiff': AIFF}[fmt]
        a = cls(path)
        if a.tags is None:
            a.add_tags()
        for name in ('TIT2', 'TPE1', 'TALB', 'APIC'):
            a.tags.delall(name)
        if title: a.tags.add(TIT2(encoding=1, text=[title]))
        if artists: a.tags.add(TPE1(encoding=1, text=['/'.join(artists)]))
        if album: a.tags.add(TALB(encoding=1, text=[album]))
        if cover: a.tags.add(APIC(encoding=1, type=3, mime=mime, desc='Front cover', data=cover))
        a.save(v2_version=3)
        if fmt == '.wav':
            # Explorer's WAV reader expects a trailing INFO list, as written by Mp3tag.
            fields = [(b'INAM', title), (b'IART', '; '.join(artists)), (b'IPRD', album)]
            info = b'INFO' + b''.join(riff_chunk(k, v.encode('utf-8') + b'\0') for k, v in fields if v)
            extra = riff_chunk(b'LIST', info)
            with path.open('r+b') as f:
                f.seek(0, 2)
                f.write(extra)
                end = f.tell()
                if end - 8 > 0xFFFFFFFF:
                    raise ValueError('WAV 超出标准 RIFF 4GB 限制')
                f.seek(4)
                f.write(struct.pack('<I', end - 8))
    elif fmt == '.flac':
        a = FLAC(path)
        for k, v in [('title', [title]), ('artist', artists), ('album', [album])]:
            if any(v): a[k] = v
        a.clear_pictures()
        if cover: a.add_picture(picture(cover, mime))
        a.save()
    elif fmt == '.ogg':
        a = OggVorbis(path)
        for k, v in [('title', [title]), ('artist', artists), ('album', [album])]:
            if any(v): a[k] = v
        if cover: a['metadata_block_picture'] = [base64.b64encode(picture(cover, mime).write()).decode('ascii')]
        a.save()
    elif fmt == '.m4a':
        a = MP4(path)
        for k, v in [('\xa9nam', [title]), ('\xa9ART', artists), ('\xa9alb', [album])]:
            if any(v): a[k] = v
        if cover: a['covr'] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_PNG if mime == 'image/png' else MP4Cover.FORMAT_JPEG)]
        a.save()

def picture(data, mime):
    p = Picture()
    p.type, p.mime, p.data = 3, mime, data
    with Image.open(io.BytesIO(data)) as im:
        p.width, p.height, p.depth = im.width, im.height, len(im.getbands()) * 8
    return p

def read_tags(path):
    a = AudioFile(path)
    fmt = path.suffix.lower()
    if fmt in ('.wav', '.mp3', '.aiff'):
        def val(k): return list(a.tags[k].text) if a.tags and k in a.tags else []
        return val('TIT2'), val('TPE1'), val('TALB'), [p.data for p in a.tags.getall('APIC')] if a.tags else []
    if fmt == '.m4a':
        return a.get('\xa9nam', []), a.get('\xa9ART', []), a.get('\xa9alb', []), [bytes(x) for x in a.get('covr', [])]
    pics = [x.data for x in a.pictures] if fmt == '.flac' else [Picture(base64.b64decode(x)).data for x in a.get('metadata_block_picture', [])]
    return a.get('title', []), a.get('artist', []), a.get('album', []), pics

def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:150]
    if not name or name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        name = '_' + name
    return name

def publish_file(staged, target):
    if os.name == 'nt':
        staged.rename(target)  # Windows rename refuses an existing target.
        return
    try:
        os.link(staged, target)
    except OSError as error:
        if error.errno not in (errno.ENOTSUP, errno.EOPNOTSUPP, errno.EPERM):
            raise
        # Filesystems such as exFAT lack hard links. Claim the name before replacing it.
        with target.open('xb'):
            pass
        try:
            staged.replace(target)
        except OSError:
            target.unlink(missing_ok=True)
            raise


def convert(source, outdir, fmt='WAV', bitrate=320, rate=0, depth=24):
    source, outdir = Path(source).expanduser(), Path(outdir).expanduser()
    if fmt not in FORMATS: raise ValueError('未知输出格式')
    outdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ncm-', dir=outdir) as tmp:
        work = Path(tmp)
        audio, original, meta, cover, mime = unpack_ncm(source, work)
        title = str(meta.get('musicName') or source.stem)
        artists = [str(x[0]) for x in meta.get('artist', []) if x and x[0]]
        album = str(meta.get('album') or '')
        suffix = original if fmt == '原格式' else fmt.lower()
        name = safe_name(('; '.join(artists) + ' - ' if artists else '') + title)
        staged = work / ('output.' + suffix)
        if fmt == '原格式':
            shutil.copyfile(audio, staged)
        else:
            encoders = {'WAV': ['-c:a', f'pcm_s{depth}le'], 'AIFF': ['-c:a', f'pcm_s{depth}be'], 'FLAC': ['-c:a', 'flac'], 'MP3': ['-c:a', 'libmp3lame', '-b:a', f'{bitrate}k'], 'OGG': ['-c:a', 'libvorbis', '-q:a', '6'], 'M4A': ['-c:a', 'aac', '-b:a', f'{bitrate}k']}
            cmd = [ffmpeg_path(), '-v', 'error', '-nostdin', '-y', '-i', str(audio), '-map', '0:a:0', '-map_metadata', '-1', '-vn']
            if rate: cmd += ['-ar', str(rate)]
            cmd += encoders[fmt] + [str(staged)]
            proc = subprocess.run(
                cmd, stdin=subprocess.DEVNULL, capture_output=True,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            if proc.returncode: raise RuntimeError(proc.stderr.decode('utf-8', 'replace')[-2000:])
        write_tags(staged, title, artists, album, cover, mime)
        t, ar, al, pics = read_tags(staged)
        expected_artists = ['/'.join(artists)] if suffix in ('wav', 'mp3', 'aiff') else artists
        if t != [title]:
            raise ValueError('标题回读失败')
        if artists and ar != expected_artists:
            raise ValueError('艺术家回读失败')
        if album and al != [album]:
            raise ValueError('专辑回读失败')
        if cover and cover not in pics:
            raise ValueError('封面回读失败')
        warnings = []
        if not cover: warnings.append('源 NCM 未包含封面')
        if not artists: warnings.append('源 NCM 未包含艺术家')
        if not album: warnings.append('源 NCM 未包含专辑')
        # The staging directory is on the output drive. Publish the complete file
        # in one operation and use a new name if another conversion got there first.
        count = 0
        while True:
            stem = f'{name} ({count})' if count else name
            target = outdir / f'{stem}.{suffix}'
            try:
                publish_file(staged, target)
                break
            except FileExistsError:
                count += 1
        return {'output': str(target.resolve()), 'warnings': warnings}

def gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    root = tk.Tk()
    root.title('NCM 转换器 · 保留封面与歌曲信息')
    root.geometry('1040x720')
    root.minsize(880, 600)
    style = ttk.Style(root)
    style.theme_use('clam')
    font = 'PingFang SC' if ON_MAC else 'Microsoft YaHei UI'
    style.configure('.', font=(font, 10))
    style.configure('Treeview', rowheight=29)
    outer = ttk.Frame(root, padding=18); outer.pack(fill='both', expand=True)
    ttk.Label(outer, text='NCM 音乐转换', font=(font, 21, 'bold')).pack(anchor='w')
    ttk.Label(outer, text='保留封面、标题、艺术家和专辑 · 本地处理 · 原文件不变').pack(anchor='w', pady=(4,14))
    toolbar = ttk.Frame(outer); toolbar.pack(fill='x', pady=(0,10))
    files = {}; busy = False; stop = threading.Event(); events = queue.Queue()
    def add(paths):
        if busy: return
        for path in paths:
            p = Path(path).resolve()
            if p.suffix.lower() == '.ncm' and p not in files.values():
                idx = tree.insert('', 'end', values=(p.name, '等待转换', ''))
                files[idx] = p
    ttk.Button(toolbar, text='添加 NCM 文件', command=lambda: add(filedialog.askopenfilenames(filetypes=[('NCM 音乐','*.ncm')]))).pack(side='left', padx=(0,8))
    def add_folder():
        folder = filedialog.askdirectory()
        if folder: add(sorted(Path(folder).rglob('*.[nN][cC][mM]')))
    ttk.Button(toolbar, text='添加文件夹', command=add_folder).pack(side='left', padx=(0,8))
    def clear():
        if not busy:
            for key in files: tree.delete(key)
            files.clear()
    ttk.Button(toolbar, text='清空列表', command=clear).pack(side='left')
    area = ttk.Frame(outer); area.pack(fill='both', expand=True)
    tree = ttk.Treeview(area, columns=('name','status','detail'), show='headings')
    for k,t,w in [('name','文件',360),('status','状态',120),('detail','结果 / 提示',380)]:
        tree.heading(k,text=t); tree.column(k,width=w)
    scroll = ttk.Scrollbar(area, orient='vertical', command=tree.yview); tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y'); tree.pack(fill='both', expand=True)
    settings = ttk.LabelFrame(outer,text='转换设置',padding=12); settings.pack(fill='x',pady=12)
    fmt=tk.StringVar(value='WAV'); bit=tk.StringVar(value='320'); rate=tk.StringVar(value='与源一致'); depth=tk.StringVar(value='24')
    controls=[]
    for col,label,var,values in [(0,'输出格式',fmt,FORMATS),(2,'MP3/M4A 码率 kbps',bit,('32','64','96','128','192','256','320')),(4,'采样率 Hz',rate,RATE_VALUES),(6,'WAV/AIFF 位深',depth,('16','24','32'))]:
        ttk.Label(settings,text=label).grid(row=0,column=col,sticky='w',padx=(0,5))
        widget=ttk.Combobox(settings,textvariable=var,values=values,state='readonly',width=12)
        widget.grid(row=0,column=col+1,padx=(0,10)); controls.append(widget)
    output=tk.StringVar(value=str(DEFAULT_OUTPUT))
    line=ttk.Frame(outer); line.pack(fill='x')
    ttk.Label(line,text='保存到：').pack(side='left')
    entry=ttk.Entry(line,textvariable=output); entry.pack(side='left',fill='x',expand=True,padx=6)
    def choose_output():
        if busy:return
        d=filedialog.askdirectory()
        if d:output.set(d)
    ttk.Button(line,text='选择目录',command=choose_output).pack(side='left')
    def open_output():
        path = Path(output.get()).expanduser()
        if not path.is_dir():
            return
        try:
            if ON_MAC:
                subprocess.Popen(['/usr/bin/open', str(path.resolve())])
            else:
                os.startfile(path)
        except OSError as error:
            messagebox.showerror('打开目录', str(error))
    ttk.Button(line, text='打开目录', command=open_output).pack(side='left', padx=(8, 0))
    note=tk.StringVar()
    def update_note(*_):
        notes = {
            '原格式': '直接提取原音频，保留源采样率和编码。',
            'WAV': 'PCM 音频。给 DJ 设备使用时可选 16 位 / 44100 Hz。',
            'FLAC': '无损压缩。',
            'OGG': 'Vorbis 有损压缩，使用品质 6。',
            'MP3': 'MP3 有损压缩。',
            'M4A': 'AAC 有损压缩。',
            'AIFF': 'PCM 音频。',
        }
        note.set(notes[fmt.get()])
        controls[1].configure(state='readonly' if fmt.get() in ('MP3','M4A') else 'disabled')
        controls[2].configure(state='disabled' if fmt.get()=='原格式' else 'readonly')
        controls[3].configure(state='readonly' if fmt.get() in ('WAV','AIFF') else 'disabled')
    fmt.trace_add('write',update_note); update_note()
    ttk.Label(outer,textvariable=note,wraplength=970).pack(anchor='w',pady=(9,0))
    ttk.Label(outer,text='封面和歌曲信息直接写入音频。不同播放器对 WAV、OGG 和 AIFF 封面的显示支持不同。',wraplength=970).pack(anchor='w',pady=4)
    bottom=ttk.Frame(outer); bottom.pack(fill='x',pady=(8,0))
    status=tk.StringVar(value='请添加文件。')
    ttk.Label(bottom,textvariable=status).pack(side='left')
    progress=ttk.Progressbar(outer); progress.pack(fill='x',pady=(10,0))
    def start():
        nonlocal busy
        if busy or not files:return
        if not output.get().strip():messagebox.showerror('保存目录','请选择输出目录');return
        selected_format=fmt.get(); selected_bit=int(bit.get()); selected_rate=0 if rate.get()=='与源一致' else int(rate.get()); selected_depth=int(depth.get()); dest=Path(output.get())
        items=list(files.items()); busy=True; stop.clear(); start_button.configure(state='disabled'); entry.configure(state='disabled')
        for c in controls:c.configure(state='disabled')
        progress.configure(maximum=len(items),value=0)
        def work():
            good=bad=0
            for idx,path in items:
                if stop.is_set():break
                events.put(('working',idx))
                try:
                    result=convert(path,dest,selected_format,selected_bit,selected_rate,selected_depth)
                    events.put(('ok',idx,result));good+=1
                except Exception as e:
                    events.put(('error',idx,str(e)));bad+=1
            events.put(('done',good,bad))
        threading.Thread(target=work,daemon=True).start()
    start_button=ttk.Button(bottom,text='开始转换',command=start);start_button.pack(side='right')
    ttk.Button(bottom,text='完成当前文件后停止',command=stop.set).pack(side='right',padx=10)
    def show_licenses():
        dialog = tk.Toplevel(root)
        dialog.title('开源许可')
        dialog.geometry('760x540')
        contents = tk.Text(dialog, wrap='word', padx=15, pady=12)
        scrollbar = ttk.Scrollbar(dialog, command=contents.yview)
        contents.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        contents.pack(fill='both', expand=True)
        for name in ('THIRD_PARTY_NOTICES.txt', 'LICENSE'):
            path = RESOURCE_DIR / name
            if path.is_file():
                contents.insert('end', path.read_text(encoding='utf-8') + '\n\n')
        for path in sorted((RESOURCE_DIR / 'licenses').glob('*.txt')):
            contents.insert('end', f'\n{path.stem}\n\n' + path.read_text(encoding='utf-8', errors='replace'))
        contents.configure(state='disabled')
    ttk.Button(bottom, text='开源许可', command=show_licenses).pack(side='right')
    def poll():
        nonlocal busy
        while not events.empty():
            event=events.get();kind=event[0]
            if kind=='working':tree.set(event[1],'status','正在转换');status.set('正在转换：'+files[event[1]].name)
            elif kind in ('ok','error'):
                tree.set(event[1],'status','完成' if kind=='ok' else '失败')
                detail=('；'.join(event[2]['warnings']) or '封面和歌曲信息回读通过') if kind=='ok' else event[2]
                tree.set(event[1],'detail',detail);progress['value'] += 1
            elif kind=='done':
                busy=False;start_button.configure(state='normal');entry.configure(state='normal');controls[0].configure(state='readonly');update_note()
                status.set(f'成功 {event[1]} 首，失败 {event[2]} 首。'+(' 已停止。' if stop.is_set() else ''))
        root.after(150,poll)
    def close():
        if busy:
            messagebox.showinfo('正在转换','请先停止转换，并等待当前文件完成。');return
        root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    poll();root.mainloop()

def main():
    parser=argparse.ArgumentParser(description='NCM 本地转换，保留标题、艺术家、专辑和封面')
    parser.add_argument('inputs',nargs='*',type=Path)
    parser.add_argument('-o','--output',type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument('-f','--format',choices=FORMATS,default='WAV')
    parser.add_argument('--bitrate',type=int,choices=(32,64,96,128,192,256,320),default=320)
    parser.add_argument('--rate',type=int,choices=(0,8000,11025,12000,16000,22050,24000,32000,44100,48000,88200,96000),default=0)
    parser.add_argument('--depth',type=int,choices=(16,24,32),default=24)
    args=parser.parse_args()
    if not args.inputs:gui();return 0
    inputs=[]
    for p in args.inputs:
        p = p.expanduser()
        inputs.extend(sorted(p.rglob('*.ncm')) if p.is_dir() else [p])
    inputs=list(dict.fromkeys(p.resolve() for p in inputs));errors=0
    if not inputs: print('没有找到 NCM 文件');return 1
    for p in inputs:
        try:
            r=convert(p,args.output,args.format,args.bitrate,args.rate,args.depth)
            print('完成:',r['output'], '; '.join(r['warnings']))
        except Exception as e: print('失败:',p,str(e));errors+=1
    return 1 if errors else 0

if __name__=='__main__':
    raise SystemExit(main())
