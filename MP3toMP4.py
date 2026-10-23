# -*- coding: utf-8 -*-
"""
====================================================================
项目名称：极速音频转 MP4 批量引擎 (YouTube 音频存档专用)
核心引擎：FFmpeg（子进程直调，无需 Python 媒体库）
功能描述：给批量音频垫上一张静态图片，以 1 FPS 渲染成视频，用于 YouTube 等平台存档。
作    者：ZQD
====================================================================

【开发日志 / Changelog】

v3.0 (FFmpeg 引擎版)
  - 引擎切换：由 MoviePy 改为直接调用 FFmpeg 子进程。速度更快、内存占用更低，且不再依赖 Python 媒体库。
  - 多格式支持：MP3 / M4A / AAC / WAV / FLAC / OGG / OPUS / WMA / AIFF / APE 等 ffmpeg 可解的所有音频。
  - 封面适配：默认输出 1920x1080，等比缩放 + 黑边补齐；可切换「原图尺寸 / 1080p / 720p」。
  - YouTube 兼容：libx264 + yuv420p + faststart + AAC 192k，上传即可识别。
  - 体验增强：实时百分比进度、可中途取消、记住上次设置、同名输出自动加序号不覆盖。
  - 健壮性：自动探测系统中的 ffmpeg（PATH / winget / 程序同目录 / 常见安装路径 / imageio-ffmpeg），
            并在启动失败时弹窗提示，不再“双击无反应”。

v2.1 (MoviePy 2.x 适配版)
  - 语法重构：适配 MoviePy v2.0+ API，`set_duration`/`set_audio` 替换为 `with_duration`/`with_audio`。
  - 核心引擎升级：直接从 `moviepy` 根目录引入核心类。

v1.0 (极速渲染奠基版)
  - 架构确立：引入 MoviePy 作为调度引擎，底层隐式调用 FFmpeg 混流封装。
  - 核心算法优化：强制视频帧率 1 FPS（每秒 1 帧静态图）。
  - 批量自动化：集成 Tkinter GUI，三步极简工作流。
====================================================================
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

# 🛑 隐藏 Windows 黑窗口（异常由 main() 统一弹窗提示）
if sys.platform == "win32":
    try:
        import ctypes

        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except Exception:
        pass

APP_NAME = "Mp3ToMp4"
APP_VERSION = "3.0"
APP_TITLE = "极速音频转 MP4 批量引擎"

AUDIO_EXTS = (
    ".mp3", ".m4a", ".m4b", ".aac", ".wav", ".flac", ".ogg", ".oga",
    ".opus", ".wma", ".aiff", ".aif", ".ape", ".wv", ".amr", ".ac3", ".dts",
)
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

AUDIO_FILETYPES = [
    ("全部支持的音频", " ".join("*" + e for e in AUDIO_EXTS)),
    ("全部文件", "*.*"),
]
IMAGE_FILETYPES = [
    ("图片文件", " ".join("*" + e for e in IMAGE_EXTS)),
    ("全部文件", "*.*"),
]

SIZE_MODES = {
    "1080p (1920x1080)": "1080p",
    "720p (1280x720)": "720p",
    "原图尺寸（仅偶数修正）": "orig",
}
SIZE_TARGETS = {"1080p": (1920, 1080), "720p": (1280, 720)}
DEFAULT_MODE = "1080p"

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# ==================== 配置持久化 ====================
def config_file() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME / "config.json"


def load_config() -> dict:
    try:
        with open(config_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    try:
        path = config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ==================== ffmpeg 探测 ====================
def run_quiet(args, timeout=30):
    """静默执行命令，永不抛异常。"""
    try:
        return subprocess.run(
            args, capture_output=True, text=True, timeout=timeout,
            errors="replace", creationflags=NO_WINDOW,
        )
    except Exception:
        return None


def ffmpeg_info(path: str):
    """返回 ffmpeg 的版本与编码器能力；无效路径返回 None。"""
    if not path or not os.path.isfile(path):
        return None
    ver = run_quiet([path, "-hide_banner", "-version"], timeout=20)
    if not ver or ver.returncode != 0:
        return None
    text = (ver.stdout or "") + (ver.stderr or "")
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    enc = run_quiet([path, "-hide_banner", "-encoders"], timeout=20)
    enc_text = ((enc.stdout or "") + (enc.stderr or "")) if enc else ""
    return {
        "path": path,
        "version": first,
        "libx264": "libx264" in enc_text,
        "aac": re.search(r"\baac\b", enc_text) is not None,
    }


def ffmpeg_candidates(saved=None):
    """按优先级生成候选 ffmpeg 路径。"""
    found = []

    def add(p):
        if p and p not in found:
            found.append(p)

    add(saved)
    here = Path(__file__).resolve().parent
    add(str(here / "ffmpeg.exe"))
    add(str(here / "bin" / "ffmpeg.exe"))
    add(shutil.which("ffmpeg"))

    local = os.environ.get("LOCALAPPDATA", "")
    patterns = [
        os.path.join(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe"),
        os.path.join(local, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "**", "bin", "ffmpeg.exe"),
        os.path.join(local, "Microsoft", "WinGet", "Packages", "BtbN.FFmpeg*", "**", "bin", "ffmpeg.exe"),
        os.path.join(local, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "**", "bin", "ffmpeg.exe"),
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Files\Software\ffmpeg\bin\ffmpeg.exe",
        r"C:\Files\Software\FormatFactory\ffmpeg.exe",
        os.path.join(local, "JianyingPro", "Apps", "*", "ffmpeg.exe"),
    ]
    for pattern in patterns:
        try:
            for hit in sorted(glob.glob(pattern, recursive=True), reverse=True):
                add(hit)
        except Exception:
            pass

    try:  # 可选依赖：装了 imageio-ffmpeg 也能用
        import imageio_ffmpeg

        add(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    return found


def discover_ffmpeg(saved=None):
    """返回 (可用的 ffmpeg 信息列表, 不可用但存在的列表)。"""
    usable, rejected = [], []
    for path in ffmpeg_candidates(saved):
        info = ffmpeg_info(path)
        if not info:
            continue
        (usable if (info["libx264"] and info["aac"]) else rejected).append(info)
    return usable, rejected


def probe_duration(ffmpeg: str, audio_path: str) -> float:
    """用 ffmpeg -i 的输出解析音频时长（秒）。"""
    res = run_quiet([ffmpeg, "-hide_banner", "-i", audio_path], timeout=30)
    text = ((res.stdout or "") + (res.stderr or "")) if res else ""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def build_video_filter(mode: str) -> str:
    """构造缩放/补边滤镜，保证输出宽高为偶数，并统一为 yuv420p(tv)。

    JPEG 封面的输入是 full-range（yuvj420p），不显式 format 会在输出里保留
    full-range 标记，导致播放器/YouTube 上出现色彩偏移，因此这里强制转换。
    """
    if mode == "orig":
        return "scale=trunc(iw/2)*2:trunc(ih/2)*2:out_range=tv,format=yuv420p"
    width, height = SIZE_TARGETS[mode]
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:out_range=tv,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
        f"format=yuv420p"
    )


def unique_path(path: str) -> str:
    """同名文件已存在时自动追加序号，避免覆盖。"""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    index = 1
    while True:
        candidate = f"{stem} ({index}){ext}"
        if not os.path.exists(candidate):
            return candidate
        index += 1


def convert_one(ffmpeg, audio_path, image_path, out_path, mode, duration, on_progress, should_stop):
    """执行单个转换，返回 (returncode, stderr 文本)。"""
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-framerate", "1", "-i", image_path,
        "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", build_video_filter(mode),
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-r", "1",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", "-shortest",
        "-progress", "pipe:1", "-nostats",
        out_path,
    ]
    err_file = tempfile.TemporaryFile(mode="w+b")
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=err_file,
        creationflags=NO_WINDOW, universal_newlines=True, bufsize=1,
    )
    try:
        for line in proc.stdout:
            if should_stop():
                proc.terminate()
                break
            line = line.strip()
            if line.startswith("out_time_us="):
                value = line.split("=", 1)[1]
                if value.isdigit() and duration > 0:
                    on_progress(min(99.0, int(value) / 1_000_000.0 / duration * 100.0))
        proc.wait()
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass

    err_file.seek(0)
    err_text = err_file.read().decode("utf-8", "replace").strip()
    err_file.close()
    return proc.returncode, err_text


# ==================== GUI ====================
class AudioToVideoApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.geometry("880x720")
        self.root.minsize(780, 620)
        self.root.configure(bg="#1E1E1E")

        self.cfg = load_config()
        self.audio_files = []
        self.image_path = ""
        self.output_dir = ""
        self.ffmpeg_path = ""
        self.ffmpeg_text = ""
        self._proc = None
        self._stop = False
        self._busy = False

        self.size_var = tk.StringVar(value=self._label_from_mode(self.cfg.get("size_mode", DEFAULT_MODE)))
        self.progress_var = tk.DoubleVar(value=0.0)
        self.stage_var = tk.StringVar(value="就绪")

        self.setup_ui()
        self._restore_saved_selection()
        self.root.after(100, self.refresh_ffmpeg)

    # ---------- 配置辅助 ----------
    @staticmethod
    def _label_from_mode(mode: str) -> str:
        for label, value in SIZE_MODES.items():
            if value == mode:
                return label
        return next(k for k, v in SIZE_MODES.items() if v == DEFAULT_MODE)

    def _persist(self):
        self.cfg.update({
            "ffmpeg_path": self.ffmpeg_path,
            "image_path": self.image_path,
            "output_dir": self.output_dir,
            "size_mode": SIZE_MODES.get(self.size_var.get(), DEFAULT_MODE),
        })
        save_config(self.cfg)

    def _restore_saved_selection(self):
        saved_image = self.cfg.get("image_path", "")
        if saved_image and os.path.isfile(saved_image):
            self.image_path = saved_image
            self.lbl_img.config(text=os.path.basename(saved_image), fg="#4AF626")
        saved_out = self.cfg.get("output_dir", "")
        if saved_out and os.path.isdir(saved_out):
            self.output_dir = saved_out
            self.lbl_dir.config(text=saved_out, fg="#4AF626")

    # ---------- 界面 ----------
    def setup_ui(self):
        # --- FFmpeg 状态栏 ---
        engine_frame = tk.Frame(self.root, bg="#252526", pady=8)
        engine_frame.pack(fill="x", padx=0, pady=0)

        tk.Label(engine_frame, text="⚙ FFmpeg 引擎：", bg="#252526", fg="#CCCCCC",
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left", padx=(20, 0))
        self.lbl_engine = tk.Label(engine_frame, text="检测中...", bg="#252526", fg="#A9A9A9",
                                   font=("Microsoft YaHei", 9), anchor="w")
        self.lbl_engine.pack(side="left", fill="x", expand=True, padx=8)

        self.btn_engine = tk.Button(engine_frame, text="更换", font=("Microsoft YaHei", 9),
                                    bg="#3C3C3C", fg="white", relief="flat", width=6,
                                    command=self.choose_ffmpeg)
        self.btn_engine.pack(side="right", padx=(0, 6))
        self.btn_redetect = tk.Button(engine_frame, text="重新检测", font=("Microsoft YaHei", 9),
                                      bg="#3C3C3C", fg="white", relief="flat", width=9,
                                      command=self.refresh_ffmpeg)
        self.btn_redetect.pack(side="right", padx=(0, 6))

        # --- 控制面板 ---
        control = tk.Frame(self.root, bg="#1E1E1E", pady=16)
        control.pack(fill="x", padx=20)

        row1 = tk.Frame(control, bg="#1E1E1E")
        row1.pack(fill="x", pady=5)
        self.btn_audio = tk.Button(row1, text="1. 🎵 选择批量音频文件", font=("Microsoft YaHei", 10, "bold"),
                                   bg="#007ACC", fg="white", width=26, relief="flat",
                                   command=self.select_audio)
        self.btn_audio.pack(side="left")
        self.lbl_audio = tk.Label(row1, text="未选择音频", bg="#1E1E1E", fg="#A9A9A9",
                                  font=("Microsoft YaHei", 9))
        self.lbl_audio.pack(side="left", padx=15)

        row2 = tk.Frame(control, bg="#1E1E1E")
        row2.pack(fill="x", pady=8)
        self.btn_img = tk.Button(row2, text="2. 🖼️ 选择封面图片", font=("Microsoft YaHei", 10, "bold"),
                                 bg="#D97706", fg="white", width=26, relief="flat",
                                 command=self.select_image)
        self.btn_img.pack(side="left")
        self.lbl_img = tk.Label(row2, text="未选择图片", bg="#1E1E1E", fg="#A9A9A9",
                                font=("Microsoft YaHei", 9))
        self.lbl_img.pack(side="left", padx=15)

        row3 = tk.Frame(control, bg="#1E1E1E")
        row3.pack(fill="x", pady=5)
        self.btn_dir = tk.Button(row3, text="3. 📁 选择 MP4 输出文件夹", font=("Microsoft YaHei", 10, "bold"),
                                 bg="#8B5CF6", fg="white", width=26, relief="flat",
                                 command=self.select_directory)
        self.btn_dir.pack(side="left")
        self.lbl_dir = tk.Label(row3, text="未指定（默认与音频同目录）", bg="#1E1E1E", fg="#A9A9A9",
                                font=("Microsoft YaHei", 9))
        self.lbl_dir.pack(side="left", padx=15)

        row4 = tk.Frame(control, bg="#1E1E1E")
        row4.pack(fill="x", pady=(10, 4))
        tk.Label(row4, text="输出尺寸：", bg="#1E1E1E", fg="#CCCCCC",
                 font=("Microsoft YaHei", 9)).pack(side="left")
        self.cmb_size = ttk.Combobox(row4, textvariable=self.size_var, state="readonly",
                                     values=list(SIZE_MODES.keys()), width=24,
                                     font=("Microsoft YaHei", 9))
        self.cmb_size.pack(side="left", padx=6)
        self.cmb_size.bind("<<ComboboxSelected>>", lambda _e: self._persist())
        tk.Label(row4, text="（非 16:9 封面会等比缩放并补黑边）", bg="#1E1E1E", fg="#777777",
                 font=("Microsoft YaHei", 8)).pack(side="left", padx=6)

        # --- 执行区 ---
        exec_frame = tk.Frame(self.root, bg="#1E1E1E")
        exec_frame.pack(fill="x", padx=20, pady=(0, 8))
        self.btn_start = tk.Button(exec_frame, text="4. ▶ 开始批量转换", font=("Microsoft YaHei", 12, "bold"),
                                   bg="#10B981", fg="white", activebackground="#059669",
                                   activeforeground="white", relief="flat", width=24,
                                   command=self.start_processing)
        self.btn_start.pack(side="left")
        self.btn_cancel = tk.Button(exec_frame, text="■ 取消", font=("Microsoft YaHei", 10, "bold"),
                                    bg="#B91C1C", fg="white", activebackground="#991B1B",
                                    activeforeground="white", relief="flat", width=10,
                                    state=tk.DISABLED, command=self.cancel_processing)
        self.btn_cancel.pack(side="left", padx=10)
        tk.Label(exec_frame, textvariable=self.stage_var, bg="#1E1E1E", fg="#A9A9A9",
                 font=("Microsoft YaHei", 9)).pack(side="left", padx=12)

        style = ttk.Style(self.root)
        try:
            style.theme_use("default")
        except Exception:
            pass
        style.configure("Zoo.Horizontal.TProgressbar", troughcolor="#2D2D30",
                        background="#10B981", thickness=16)
        self.progress = ttk.Progressbar(self.root, variable=self.progress_var, maximum=100.0,
                                        style="Zoo.Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=20, pady=(0, 10))

        # --- 日志区 ---
        self.text_area = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, font=("Consolas", 10),
                                                   bg="#0C0C0C", fg="#4AF626", padx=10, pady=10,
                                                   borderwidth=0)
        self.text_area.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.text_area.tag_config("error", foreground="#FF4500")
        self.text_area.tag_config("info", foreground="#5CB3FF")

        self.log(f">>> 欢迎使用 {APP_TITLE} v{APP_VERSION}（FFmpeg 引擎）。\n")
        self.log(">>> 渲染逻辑：1 帧/秒，视频极小，音频保持原样重编码为 AAC 192k。\n")
        self.log(">>> 支持 " + " / ".join(e.lstrip(".").upper() for e in AUDIO_EXTS[:10]) + " 等格式。\n\n")

    # ---------- 日志 / 进度 ----------
    def log(self, text, is_error=False):
        self.root.after(0, self._insert_text, text, is_error)

    def _insert_text(self, text, is_error):
        self.text_area.insert(tk.END, text, "error" if is_error else "normal")
        self.text_area.see(tk.END)

    def set_progress(self, value):
        self.root.after(0, lambda: self.progress_var.set(max(0.0, min(100.0, value))))

    def set_stage(self, text):
        self.root.after(0, lambda: self.stage_var.set(text))

    # ---------- 引擎 ----------
    def refresh_ffmpeg(self):
        saved = self.cfg.get("ffmpeg_path")
        usable, rejected = discover_ffmpeg(saved)
        if usable:
            best = usable[0]
            self.ffmpeg_path = best["path"]
            ver = best["version"].replace("ffmpeg version", "").strip()
            short = ver.split("Copyright")[0].strip()[:60]
            self.ffmpeg_text = f"{best['path']}  ({short})"
            self.lbl_engine.config(text=self.ffmpeg_text, fg="#4AF626")
            self.log(f">>> ✅ 已启用 FFmpeg: {self.ffmpeg_text}\n")
            if rejected:
                self.log(">>> ⚠ 已跳过缺少 libx264/aac 的 ffmpeg: " +
                         "; ".join(os.path.dirname(r["path"]) for r in rejected) + "\n")
            self._persist_path_only()
        else:
            self.ffmpeg_path = ""
            self.lbl_engine.config(text="未找到可用的 ffmpeg（点击右侧「更换」手动指定）", fg="#FF4500")
            self.log(">>> ❌ 未找到可用的 ffmpeg（需支持 libx264 与 aac）。\n", is_error=True)
            if rejected:
                self.log(">>> 检测到但不可用的版本:\n", is_error=True)
                for r in rejected:
                    self.log(f"    - {r['path']} (libx264={r['libx264']}, aac={r['aac']})\n", is_error=True)

    def _persist_path_only(self):
        if self.ffmpeg_path and self.cfg.get("ffmpeg_path") != self.ffmpeg_path:
            self.cfg["ffmpeg_path"] = self.ffmpeg_path
            save_config(self.cfg)

    def choose_ffmpeg(self):
        path = filedialog.askopenfilename(title="请选择 ffmpeg.exe", filetypes=[("ffmpeg", "ffmpeg.exe"), ("全部文件", "*.*")])
        if not path:
            return
        info = ffmpeg_info(path)
        if not info:
            messagebox.showerror("不可用", "无法执行该文件，请确认它是有效的 ffmpeg.exe。")
            return
        if not (info["libx264"] and info["aac"]):
            messagebox.showerror(
                "缺少编码器",
                f"该 ffmpeg 缺少必要编码器（libx264={info['libx264']}, aac={info['aac']}），无法生成兼容 MP4。\n"
                "建议安装官方静态版：winget install --id Gyan.FFmpeg -e",
            )
            return
        self.ffmpeg_path = path
        self.ffmpeg_text = f"{path}  ({info['version'].split('Copyright')[0].strip()[:60]})"
        self.lbl_engine.config(text=self.ffmpeg_text, fg="#4AF626")
        self._persist_path_only()
        self.log(f">>> ✅ 已手动指定 FFmpeg: {path}\n")

    # ---------- 选择文件 ----------
    def select_audio(self):
        files = filedialog.askopenfilenames(
            title="请选择音频文件（可多选 / Ctrl+A 全选）", filetypes=AUDIO_FILETYPES)
        if not files:
            return
        self.audio_files = list(files)
        self.lbl_audio.config(text=f"已选中 {len(self.audio_files)} 个音频", fg="#4AF626")
        self.log(f">>> [步骤 1] 已导入 {len(self.audio_files)} 个音频文件。\n")
        if not self.output_dir:
            first_dir = os.path.dirname(self.audio_files[0])
            self.output_dir = first_dir
            self.lbl_dir.config(text=first_dir, fg="#4AF626")
            self.log(f">>> 已自动设定输出目录为音频所在目录: {first_dir}\n")
            self._persist()

    def select_image(self):
        path = filedialog.askopenfilename(title="请选择一张封面图片", filetypes=IMAGE_FILETYPES)
        if not path:
            return
        self.image_path = path
        self.lbl_img.config(text=os.path.basename(path), fg="#4AF626")
        self.log(f">>> [步骤 2] 封面图片已就绪: {os.path.basename(path)}\n")
        self._persist()

    def select_directory(self):
        directory = filedialog.askdirectory(title="请选择 MP4 输出目录")
        if not directory:
            return
        self.output_dir = directory
        self.lbl_dir.config(text=directory, fg="#4AF626")
        self.log(f">>> [步骤 3] 输出目录已设定为: {directory}\n")
        self._persist()

    # ---------- 执行 ----------
    def lock_ui(self, locked: bool):
        self._busy = locked
        state = tk.DISABLED if locked else tk.NORMAL
        for button in (self.btn_audio, self.btn_img, self.btn_dir, self.btn_engine, self.btn_redetect, self.cmb_size):
            button.config(state=state)
        if locked:
            self.btn_start.config(state=tk.DISABLED, text="⏳ 正在转换...")
            self.btn_cancel.config(state=tk.NORMAL)
        else:
            self.btn_start.config(state=tk.NORMAL, text="4. ▶ 开始批量转换")
            self.btn_cancel.config(state=tk.DISABLED)

    def start_processing(self):
        if not self.ffmpeg_path:
            messagebox.showwarning("缺少 FFmpeg", "未检测到可用的 ffmpeg，请先点击「更换」指定 ffmpeg.exe。")
            self.choose_ffmpeg()
            return
        if not self.audio_files:
            messagebox.showwarning("提示", "请先选择至少一个音频文件。")
            return
        if not self.image_path:
            messagebox.showwarning("提示", "请先选择一张封面图片。")
            return
        if not self.output_dir:
            self.output_dir = os.path.dirname(self.audio_files[0])
            self.lbl_dir.config(text=self.output_dir, fg="#4AF626")

        self._stop = False
        self.progress_var.set(0)
        self.lock_ui(True)
        self.log("=" * 64 + "\n")
        self.log(f">>> 🚀 开始批量转换，共 {len(self.audio_files)} 个文件。\n\n")
        threading.Thread(target=self._worker, daemon=True).start()

    def cancel_processing(self):
        self._stop = True
        self.set_stage("正在取消...")
        self.log(">>> 🛑 已请求取消，正在停止当前任务...\n", is_error=True)
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def _worker(self):
        mode = SIZE_MODES.get(self.size_var.get(), DEFAULT_MODE)
        total = len(self.audio_files)
        success = failed = 0

        for index, audio_path in enumerate(self.audio_files, start=1):
            if self._stop:
                break
            base_name = os.path.basename(audio_path)
            stem = os.path.splitext(base_name)[0]
            out_path = unique_path(os.path.join(self.output_dir, f"{stem}.mp4"))

            self.set_stage(f"第 {index}/{total} 个 · {base_name}")
            self.set_progress(0)
            self.log(f"[{index}/{total}] {base_name}\n")

            duration = probe_duration(self.ffmpeg_path, audio_path)
            if duration <= 0:
                self.log("  ⚠ 无法读取时长，进度条将不准确（不影响转换）。\n")

            self._proc = None
            started = threading.Event()

            rc, err = convert_one(
                self.ffmpeg_path, audio_path, self.image_path, out_path, mode, duration,
                on_progress=self.set_progress,
                should_stop=lambda: self._stop,
            )

            if self._stop:
                if os.path.exists(out_path):
                    try:
                        os.remove(out_path)
                    except Exception:
                        pass
                self.log("  🛑 已取消，已删除未完成的输出文件。\n", is_error=True)
                break

            if rc == 0 and os.path.exists(out_path):
                success += 1
                size_mb = os.path.getsize(out_path) / 1048576.0
                self.log(f"  ✅ 成功: {os.path.basename(out_path)}  ({size_mb:.2f} MB)\n")
            else:
                failed += 1
                detail = (err or "未知错误").splitlines()
                detail_text = " | ".join(detail[-3:]) if detail else "未知错误"
                self.log(f"  ❌ 失败: {detail_text[:400]}\n", is_error=True)
            self.set_progress(100)

        self.log("\n" + "=" * 64 + "\n")
        if self._stop:
            self.log(f">>> 任务已取消。成功 {success} 个，失败 {failed} 个。\n")
        else:
            self.log(f">>> 🎉 批量任务完成：成功 {success} 个，失败 {failed} 个。\n")
            self.log(f">>> 📂 输出目录: {self.output_dir}\n")
            self.log(">>> 💡 下一步：打开 YouTube Studio 批量上传即可。\n")

        self._proc = None
        self.set_stage("完成" if not self._stop else "已取消")
        self.root.after(0, lambda: self.lock_ui(False))


def main():
    try:
        root = tk.Tk()
    except Exception:
        import traceback

        print(traceback.format_exc())
        return

    def report_exception(exc, value, tb):
        import traceback

        detail = "".join(traceback.format_exception(exc, value, tb))
        try:
            messagebox.showerror("程序异常", detail[-1500:])
        except Exception:
            print(detail)

    root.report_callback_exception = report_exception
    AudioToVideoApp(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        trace = traceback.format_exc()
        print(trace)
        try:
            fallback = tk.Tk()
            fallback.withdraw()
            messagebox.showerror("启动失败", trace[-1500:])
            fallback.destroy()
        except Exception:
            pass
