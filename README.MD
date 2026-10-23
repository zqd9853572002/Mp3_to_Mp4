# 极速音频转 MP4 批量引擎 (YouTube 音频存档专用)

这是一个基于 **Python + FFmpeg** 的桌面工具：给音频文件套上一张静态封面图，批量转成 MP4 视频，专为 YouTube / Bilibili 等平台的音频存档场景设计。

视频帧率强制为 1 FPS（每秒 1 帧静态图），在保证音频质量的同时把视频体积压到最小，节省上传时间与云端存储空间。

---

## ✨ 主要特性

- **多格式输入**：MP3 / M4A / M4B / AAC / WAV / FLAC / OGG / OGA / OPUS / WMA / AIFF / APE 等 ffmpeg 可解的所有音频。
- **批量处理**：一次选择多个文件，队列式逐个转换，实时百分比进度，可随时取消。
- **极速渲染**：直接调用 FFmpeg 子进程（不经过 Python 媒体库），长音频也能秒级完成。
- **YouTube 兼容**：H.264 (`libx264`) + `yuv420p(tv)` + `faststart` + AAC 192k，上传即刻识别。
- **封面自适应**：默认 1920x1080，非 16:9 封面等比缩放并补黑边；可切换 720p / 原图尺寸。
- **省心细节**：自动探测系统 ffmpeg、记住上次设置、同名输出自动加序号不覆盖、异常弹窗提示。

## 📦 环境要求

1. **Python 3.8+** —— 仅使用标准库与 Tkinter，**无需 pip 安装任何第三方包**。
2. **FFmpeg** —— 需要包含 `libx264` 与 `aac` 编码器。

Windows 安装官方静态版（推荐）：

```powershell
winget install --id Gyan.FFmpeg -e
```

安装后 `ffmpeg` / `ffprobe` 会加入 PATH，其他软件也能直接调用。

程序启动时会按以下顺序自动探测，通常无需手动配置：

1. 配置文件里上次使用的路径
2. 程序所在目录的 `ffmpeg.exe` / `bin\ffmpeg.exe`
3. 系统 PATH
4. winget 安装目录（`%LOCALAPPDATA%\Microsoft\WinGet\...`）
5. 常见安装路径（`C:\ffmpeg\bin`、`C:\Program Files\ffmpeg\bin` 等）
6. 已安装的 `imageio-ffmpeg` 包

若都找不到，可点界面右上角「更换」手动指定 `ffmpeg.exe`，程序会记住该路径。

### 关于体积

- `Gyan.FFmpeg`（full 静态版）解压后约 **696 MB**：`ffmpeg.exe` 227MB + `ffprobe.exe` 227MB + `ffplay.exe` 229MB，三个 exe 各自内嵌全部库。
- 若在意空间：可改装 `Gyan.FFmpeg.Essentials`（更小），或从官方压缩包中只取 `ffmpeg.exe` 放到任意目录，再在程序里手动指定。
- 对照参考：MoviePy 方案表面上只是一个 Python 包（本体 wheel 0.1MB），但它依赖 `imageio-ffmpeg`（wheel 29.8MB，内含 ffmpeg 二进制）+ `numpy` + `pillow`，**本质仍是"ffmpeg + 封装层"**，并不会更省空间。

## 🚀 如何使用

1. 获取本项目（克隆或下载）。
2. 运行主程序：

   ```bash
   python MP3toMP4.py
   ```

3. 在界面中按步骤操作：

   | 步骤 | 操作 |
   |---|---|
   | 1 | 点击「选择批量音频文件」，可多选或 `Ctrl+A` 全选 |
   | 2 | 点击「选择封面图片」，支持 JPG / PNG / BMP / WEBP |
   | 3 | 点击「选择 MP4 输出文件夹」（不选则默认输出到音频所在目录） |
   | 尺寸 | 下拉选择 `1080p`（默认）/ `720p` / `原图尺寸` |
   | 4 | 点击「开始批量转换」，日志区实时显示结果 |

4. 完成后到输出目录取 MP4，直接上传 YouTube 即可。

> 输出参数：`1920x1080`（或所选尺寸）、`1 fps`、`H.264 High`、`AAC-LC 192k`、`+faststart`（便于网页端秒开）。
> 音频采样率保持源文件原样，不做多余重采样。

## 📁 项目结构

```
Py_Mp3_to_Mp4/
├── MP3toMP4.py            # 主程序（Tkinter GUI + FFmpeg 调度）
├── Black.png              # 纯黑封面占位图（9×8，可作极简背景）
├── README.MD              # 项目说明与开发日志
├── .gitignore             # 版本库忽略规则
├── .vscode/
│   └── settings.json      # 编辑器配置
└── Archive/
    └── MP3toMP4.py        # 历史归档版本（MoviePy 时期的快照，仅供追溯）
```

配置文件保存在 `%APPDATA%\Mp3ToMp4\config.json`，用于记住 ffmpeg 路径、封面图、输出目录与尺寸偏好，不进入版本库。

> 说明：版本变更记录统一维护在本 README 的「开发日志 (Changelog)」章节，不单独建立 `CHANGELOG.md`，避免多份记录不同步。

##  开发日志 (Changelog)

### v3.0 (FFmpeg 引擎版)
- **引擎切换**：由 MoviePy 改为直接调用 FFmpeg 子进程，速度更快、内存更低，且不再依赖任何 Python 媒体库。
- **多格式支持**：从仅支持 MP3 扩展到 M4A / AAC / WAV / FLAC / OGG / OPUS / WMA / AIFF / APE 等全部 ffmpeg 可解格式。
- **封面适配**：默认 1920x1080，等比缩放 + 黑边补齐；新增 720p 与原图尺寸选项；奇数尺寸自动修正为偶数。
- **YouTube 兼容**：显式转换 `yuv420p(tv)` 并启用 `faststart`，避免 full-range 封面导致上传后偏色。
- **体验增强**：实时百分比进度、中途取消、记住上次设置、同名输出自动加序号、启动异常弹窗提示。
- **健壮性**：自动探测 ffmpeg（含编码器能力校验），自动跳过不支持 `libx264` 的第三方内置版本。

### 仓库维护（Docs）
- **结构规范化**：新增 `.gitignore`；历史版本归档至 `Archive/`；README 补充「项目结构」说明。

### v2.1 (MoviePy 2.x 适配版)
- **语法重构**：完美适配 MoviePy v2.0+ 最新版 API。将废弃的 `set_duration` 和 `set_audio` 替换为全新的 `with_duration` 和 `with_audio` 链式调用方法。
- **核心引擎升级**：直接从 `moviepy` 根目录引入核心类，摒弃了已被官方移除的 `moviepy.editor` 子模块。

### v1.0 (极速渲染奠基版)
- **架构确立**：引入轻量级 MoviePy 作为核心调度引擎，底层隐式调用 FFmpeg 进行音视频混流封装。
- **核心算法优化**：针对"音频存档"的业务特性，强制覆写视频帧率为 1 FPS（每秒 1 帧静态图）。
- **批量自动化**：集成 Tkinter GUI，实现三步极简工作流。
