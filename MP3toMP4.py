"""
====================================================================
项目名称：极速 MP3 转 MP4 批量引擎 (YouTube 音频存档专用)
核心引擎：MoviePy 2.x 版本
功能描述：给批量 MP3 垫上一张静态图片，以极低帧率渲染成视频，用于云端视频平台存档。
作    者：ZQD
====================================================================

【开发日志 / Changelog】

v2.1 (MoviePy 2.x 适配版)
  - 语法重构：完美适配 MoviePy v2.0+ 最新版 API。将废弃的 `set_duration` 和 `set_audio` 替换为全新的 `with_duration` 和 `with_audio` 链式调用方法，彻底解决 Attribute 报错崩溃问题。
  - 核心引擎升级：直接从 `moviepy` 根目录引入核心类，摒弃了已被官方移除的 `moviepy.editor` 子模块。

v1.0 (极速渲染奠基版)
  - 架构确立：引入轻量级 MoviePy 作为核心调度引擎，底层隐式调用 FFmpeg 进行音视频混流封装。
  - 核心算法优化：针对“音频存档”的业务特性，强制覆写视频帧率为 1 FPS（每秒 1 帧静态图）。
  - 批量自动化：集成 Tkinter GUI，实现了三步极简工作流。
====================================================================
"""
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox
import threading
import os
import sys
import ctypes
# 适配 MoviePy 2.x 新版引入路径
from moviepy import AudioFileClip, ImageClip

# 🛑 隐藏 Windows 黑窗口
if sys.platform == "win32":
    try:
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except Exception:
        pass

class AudioToVideoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube 音频伪装器 - MP3 转 MP4 批量引擎 v2.1")
        self.root.geometry("750x650")
        self.root.configure(bg="#1E1E1E")
        
        self.mp3_files = []
        self.image_path = ""
        self.output_dir = ""
        
        self.setup_ui()

    def setup_ui(self):
        # --- 控制面板 ---
        control_frame = tk.Frame(self.root, bg="#1E1E1E", pady=15)
        control_frame.pack(fill="x", padx=20)
        
        # 1. 选择 MP3 文件
        mp3_frame = tk.Frame(control_frame, bg="#1E1E1E")
        mp3_frame.pack(fill="x", pady=5)
        self.btn_mp3 = tk.Button(mp3_frame, text="1. 🎵 选择批量 MP3 文件", font=("Microsoft YaHei", 10, "bold"), bg="#007ACC", fg="white", width=28, relief="flat", command=self.select_mp3)
        self.btn_mp3.pack(side="left")
        self.lbl_mp3 = tk.Label(mp3_frame, text="未选择音频", bg="#1E1E1E", fg="#A9A9A9", font=("Microsoft YaHei", 9))
        self.lbl_mp3.pack(side="left", padx=15)

        # 2. 选择背景图片
        img_frame = tk.Frame(control_frame, bg="#1E1E1E")
        img_frame.pack(fill="x", pady=10)
        self.btn_img = tk.Button(img_frame, text="2. 🖼️ 选择背景图片 (JPG/PNG)", font=("Microsoft YaHei", 10, "bold"), bg="#D97706", fg="white", width=28, relief="flat", command=self.select_image)
        self.btn_img.pack(side="left")
        self.lbl_img = tk.Label(img_frame, text="未选择图片", bg="#1E1E1E", fg="#A9A9A9", font=("Microsoft YaHei", 9))
        self.lbl_img.pack(side="left", padx=15)

        # 3. 选择输出目录
        dir_frame = tk.Frame(control_frame, bg="#1E1E1E")
        dir_frame.pack(fill="x", pady=5)
        self.btn_dir = tk.Button(dir_frame, text="3. 📁 选择 MP4 输出文件夹", font=("Microsoft YaHei", 10, "bold"), bg="#8B5CF6", fg="white", width=28, relief="flat", command=self.select_directory)
        self.btn_dir.pack(side="left")
        self.lbl_dir = tk.Label(dir_frame, text="未指定输出目录", bg="#1E1E1E", fg="#A9A9A9", font=("Microsoft YaHei", 9))
        self.lbl_dir.pack(side="left", padx=15)

        # 4. 开始转换按钮
        exec_frame = tk.Frame(control_frame, bg="#1E1E1E")
        exec_frame.pack(fill="x", pady=15)
        self.btn_start = tk.Button(exec_frame, text="4. ▶ 开始极速渲染生成 MP4", font=("Microsoft YaHei", 12, "bold"), bg="#10B981", fg="white", activebackground="#059669", activeforeground="white", relief="flat", width=35, command=self.start_processing)
        self.btn_start.pack(side="left")

        # --- 日志输出区 ---
        self.text_area = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, font=("Consolas", 10), bg="black", fg="#4AF626", padx=10, pady=10, borderwidth=0)
        self.text_area.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.text_area.tag_config('error', foreground='#FF4500')
        
        self.log(">>> 欢迎使用 MP3 批量伪装引擎 (适配 MoviePy v2.x)。\n")
        self.log(">>> 渲染逻辑：1帧/秒 (1 FPS)，极大压缩视频体积，专注保护音频质量。\n")
        self.log(">>> 请按上方 1、2、3 步骤依次挂载资源，最后点击执行。\n\n")

    def log(self, text, is_error=False):
        self.root.after(0, self._insert_text, text, is_error)

    def _insert_text(self, text, is_error):
        tag = 'error' if is_error else 'normal'
        self.text_area.insert(tk.END, text, tag)
        self.text_area.see(tk.END)

    def lock_ui(self, locked=True):
        state = tk.DISABLED if locked else tk.NORMAL
        self.btn_mp3.config(state=state)
        self.btn_img.config(state=state)
        self.btn_dir.config(state=state)
        if locked:
            self.btn_start.config(state=tk.DISABLED, text="⏳ 正在全速渲染中...")
        else:
            self.btn_start.config(state=tk.NORMAL, text="4. ▶ 开始极速渲染生成 MP4")

    def select_mp3(self):
        files = filedialog.askopenfilenames(title="请选择需要转换的 MP3 文件 (可多选)", filetypes=[("Audio Files", "*.mp3")])
        if files:
            self.mp3_files = list(files)
            self.lbl_mp3.config(text=f"已选中 {len(self.mp3_files)} 个音频", fg="#4AF626")
            self.log(f">>> [步骤 1] 已成功挂载 {len(self.mp3_files)} 个 MP3 文件。\n")

    def select_image(self):
        path = filedialog.askopenfilename(title="请选择一张背景图片", filetypes=[("Image Files", "*.jpg *.jpeg *.png")])
        if path:
            self.image_path = path
            self.lbl_img.config(text=os.path.basename(path), fg="#4AF626")
            self.log(f">>> [步骤 2] 背景图片已就绪: {os.path.basename(path)}\n")

    def select_directory(self):
        directory = filedialog.askdirectory(title="请选择 MP4 生成后的保存目录")
        if directory:
            self.output_dir = directory
            self.lbl_dir.config(text=self.output_dir, fg="#4AF626")
            self.log(f">>> [步骤 3] 输出目录已设定为: {self.output_dir}\n")

    def start_processing(self):
        if not self.mp3_files:
            messagebox.showwarning("提示", "请先选择至少一个 MP3 文件！")
            return
        if not self.image_path:
            messagebox.showwarning("提示", "请先选择一张背景图片！")
            return
        if not self.output_dir:
            messagebox.showwarning("提示", "请先指定转换后的视频存放目录！")
            return

        self.lock_ui(locked=True)
        self.log("="*60 + "\n")
        self.log(">>> 🚀 渲染引擎启动！开始批量处理...\n\n")
        
        threading.Thread(target=self._process_files_thread, daemon=True).start()

    def _process_files_thread(self):
        success_count = 0
        
        for idx, mp3_path in enumerate(self.mp3_files):
            base_name = os.path.basename(mp3_path)
            name_without_ext, _ = os.path.splitext(base_name)
            
            mp4_path = os.path.join(self.output_dir, f"{name_without_ext}.mp4")

            self.log(f"[任务 {idx+1}/{len(self.mp3_files)}] 正在重组: {base_name}\n")

            try:
                # 1. 加载音频
                audio_clip = AudioFileClip(mp3_path)
                
                # 2. 加载图片，并将其时长设置为与音频完全一致 (使用 2.x 新语法 with_duration)
                image_clip = ImageClip(self.image_path).with_duration(audio_clip.duration)
                
                # 3. 将音频轨道合成到图片视频上 (使用 2.x 新语法 with_audio)
                video = image_clip.with_audio(audio_clip)
                
                # 4. 导出为 MP4
                video.write_videofile(
                    mp4_path, 
                    fps=1, 
                    codec="libx264", 
                    audio_codec="aac", 
                    logger=None
                )
                
                # 显式关闭对象以释放内存
                audio_clip.close()
                image_clip.close()
                video.close()
                
                success_count += 1
                self.log(f"  ✅ 渲染成功！已生成: {name_without_ext}.mp4\n")

            except Exception as e:
                self.log(f"  ❌ 处理失败: {str(e)}\n", is_error=True)

        self.log("\n" + "="*60 + "\n")
        self.log(f">>> 🎉 批量任务执行完毕！共成功生成 {success_count} 个视频文件。\n")
        self.log(f">>> 📂 请前往输出目录查看: {self.output_dir}\n")
        self.log(">>> 💡 下一步：打开 YouTube Studio 批量上传吧！\n")
        
        self.root.after(0, lambda: self.lock_ui(locked=False))

if __name__ == "__main__":
    root = tk.Tk()
    app = AudioToVideoApp(root)
    root.mainloop()