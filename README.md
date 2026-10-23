# 极速音频转 MP4 批量引擎 (YouTube 音频存档专用)

这是一个基于 **Python + FFmpeg** 的桌面工具：给音频文件套上一张静态封面图，批量转成 MP4 视频，专为 YouTube / Bilibili 等平台的音频存档场景设计。

视频帧率强制为 1 FPS（每秒 1 帧静态图），在保证音频质量的同时把视频体积压到最小，节省上传时间与云端存储空间。

从 **v4.0** 起集成 **faster-whisper 语音识别**：可为每个音频生成同名的 `.srt` 字幕与 `.txt` 文稿，支持中英混合识别，并可在识别前选择 RNNoise / GTCRN 降噪。

---

## ✨ 主要特性

- **音频转 MP4**：MP3 / M4A / M4B / AAC / WAV / FLAC / OGG / OGA / OPUS / WMA / AIFF / APE 等 ffmpeg 可解的所有音频。
- **批量处理**：一次选择多个文件，队列式逐个处理，实时百分比进度，可随时取消。
- **极速渲染**：直接调用 FFmpeg 子进程（不经过 Python 媒体库），长音频也能秒级完成。
- **语音转文字**：基于 faster-whisper（CTranslate2 推理），输出与 MP4 同名的 `.srt` 字幕与 `.txt` 文本，可单独上传 YouTube。
- **中英混合识别**：默认自动检测语种，中英混说无需切换；也可强制指定中文或英文。
- **识别模型可选**：`large-v3-turbo`（默认，精度优先）/ `medium` / `small`（速度快）/ `base` / `tiny`，随时切换。
- **前置降噪**：RNNoise（零额外依赖，0.3 MB 模型）/ GTCRN 神经网络（0.5 MB 模型）两级可选。
- **原声保留**：降噪只作用于「送去识别的音频」，成片 MP4 的音轨始终是原始音质。
- **YouTube 兼容**：H.264 (`libx264`) + `yuv420p(tv)` + `faststart` + AAC 192k，上传即刻识别。
- **封面自适应**：默认 1920x1080，非 16:9 封面等比缩放并补黑边；可切换 720p / 原图尺寸。
- **省心细节**：自动探测系统 ffmpeg、记住上次设置、同名输出自动加序号不覆盖、异常弹窗提示。

## 📦 环境要求

1. **Python 3.8+**（本项目在 Python 3.14 + Windows 10 上实测通过）。
2. **FFmpeg** —— 需要包含 `libx264` 与 `aac` 编码器；降噪还需要 `arnndn` 滤镜（官方 full 版自带，essentials 版可能没有）。

### 只转 MP4（不生成字幕）

无需安装任何 Python 第三方包，标准库 + Tkinter 即可运行。

### 需要语音识别 / 字幕

安装一次依赖（安装后约 200 MB 占用）：

```powershell
python -m pip install faster-whisper sherpa-onnx
```

| 依赖 | 作用 | 体积 |
|---|---|---|
| `faster-whisper` + `ctranslate2` + `av` + `onnxruntime` | 语音识别核心与 VAD 切句 | 约 200 MB |
| `sherpa-onnx` | GTCRN 神经网络降噪（可选，只用 RNNoise 可不装） | 约 45 MB |

> 识别模型不包含在 pip 包里，首次选用某个模型时才会自动下载到
> `%APPDATA%\Mp3ToMp4\models\whisper`，可随时手动删除，不影响程序运行。
>
> 国内网络下载慢时，先设置镜像环境变量再启动程序：
>
> ```powershell
> set HF_ENDPOINT=https://hf-mirror.com
> python MP3toMP4.py
> ```

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
   | 字幕 | 需要文字稿时勾选「识别语音并生成字幕」，再选模型 / 语种 / 降噪 |
   | 4 | 点击「开始批量转换」，日志区实时显示结果 |

4. 完成后到输出目录取 MP4，直接上传 YouTube 即可；如生成了字幕，再单独上传 `.srt`。

> 输出参数：`1920x1080`（或所选尺寸）、`1 fps`、`H.264 High`、`AAC-LC 192k`、`+faststart`（便于网页端秒开）。
> 音频采样率保持源文件原样，不做多余重采样。

## 🎧 语音识别与字幕（v4.0）

勾选「识别语音并生成字幕」后，程序会对每个音频执行：

```
原始音频 ──(可选降噪)──> 16kHz 单声道 WAV ──> faster-whisper ──> .srt + .txt
                                                        │
                                                        └──> 原 MP4 渲染流程（音轨保持原声）
```

- 输出文件与 MP4 **同名同目录**：`会议录音.mp4` + `会议录音.srt` + `会议录音.txt`。
- `SRT` 时间轴来自 Whisper 分段 + Silero VAD 切句，中文按显示宽度自动折行（每行约 21 个汉字）。
- `TXT` 是按段落拼接的连续文稿，中文之间不插空格，英文之间保留空格。
- 字幕不烧进画面、也不封装进 MP4，属于外挂字幕，YouTube / Bilibili 都可单独上传。

### 识别模型

| 模型 | 下载体积 | CPU 速度（1 小时音频，估算） | 适用场景 |
|---|---|---|---|
| `large-v3-turbo`（默认） | 1.55 GB | 30–90 分钟 | 嘈杂环境、口音重、要求最高准确率 |
| `medium` | 1.46 GB | 25–70 分钟 | turbo 之前的折中选择 |
| `small` | 464 MB | 5–15 分钟 | 会议录音清晰、追求速度 |
| `base` | 141 MB | 3–6 分钟 | 快速过一遍大意 |
| `tiny` | 75 MB | 1–3 分钟 | 只做关键词检索 |

> 同一时间只加载一个模型，切换模型会自动释放上一个，不会叠加内存占用。
> 模型下载支持断点续传，存放在 `%APPDATA%\Mp3ToMp4\models\whisper`。

### 降噪

| 模式 | 依赖 | 模型 | 说明 |
|---|---|---|---|
| 关闭 | 无 | 无 | 原始音频直接识别，速度最快 |
| 轻度 · RNNoise（默认） | 仅 ffmpeg 的 `arnndn` 滤镜 | 0.29 MB | 抑制空调、风扇、路噪、键盘等底噪，几乎不耗时 |
| 强力 · GTCRN | `sherpa-onnx` | 0.51 MB | 神经网络降噪，嘈杂环境更干净，约 1–3 倍实时耗时 |

- 两个降噪模型都会在首次使用时自动下载到 `%APPDATA%\Mp3ToMp4\models\denoise`。
- 若 GTCRN 依赖缺失，会自动回退 RNNoise，不会中断任务。
- **降噪只影响识别输入，不改动 MP4 音轨**，成片始终保留原始音质。
- 降噪不是越强越好：过度降噪会削掉辅音，反而降低识别率。干净录音建议直接「关闭」。

### 关于中英混合

Whisper 的语种参数是**整段音频级别**的检测，不是逐句切换。因此：

- 默认「自动检测」会用前 30 秒判断语种，之后整段沿用该语言 token；
- 由于 Whisper 训练数据包含大量 code-switch，即使判定为中文，夹杂的英文单词通常也能正确转写；
- 若你明确知道整段是英文/中文，手动指定反而更稳（减少误判）；
- 不建议为了"逐句切换语种"去切分音频，收益很小且会破坏时间轴。

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

配置文件保存在 `%APPDATA%\Mp3ToMp4\config.json`，用于记住 ffmpeg 路径、封面图、输出目录、尺寸，以及字幕开关 / 模型 / 语种 / 降噪偏好，不进入版本库。

模型缓存位于 `%APPDATA%\Mp3ToMp4\models`：

```
models/
├── whisper/     # faster-whisper 模型（按需下载，可整个删除）
└── denoise/     # bd.rnnn（RNNoise）与 gtcrn_simple.onnx（GTCRN）
```

> 说明：版本变更记录统一维护在本 README 的「开发日志 (Changelog)」章节，不单独建立 `CHANGELOG.md`，避免多份记录不同步。

##  开发日志 (Changelog)

### v4.0 (语音识别 / 降噪字幕版)
- **语音识别**：集成 faster-whisper 1.2.x + CTranslate2，输出同名 `.srt` 与 `.txt`，MP4 渲染逻辑完全不变。
- **混合语种**：默认自动检测，支持强制中文 / 英文；中英混说可直接识别。
- **模型可选**：`large-v3-turbo`（默认）/ `medium` / `small` / `base` / `tiny`，下拉切换，按需下载并缓存。
- **前置降噪**：RNNoise（ffmpeg `arnndn`，零新增依赖）与 GTCRN（sherpa-onnx）两级，自动下载 0.3–0.5 MB 小模型。
- **健壮性**：FFmpeg 统一解码为 16k 单声道 WAV 后以 numpy 送入模型，规避 faster-whisper 内置 PyAV 与新版 `av` 的接口不兼容问题。
- **原声保留**：降噪仅作用于识别输入，成片音轨不做任何处理。
- **失败隔离**：识别/降噪异常只跳过字幕，不影响 MP4 生成；GTCRN 不可用时自动回退 RNNoise。

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
