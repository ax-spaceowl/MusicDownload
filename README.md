# MusicDownload

一个基于 PyQt6 的桌面应用：用 yt-dlp 下载在线视频，再用 ffmpeg 提取 AAC 音频，
并按 `<歌曲>-<歌手>` 规则自动命名输出文件。适用于 yt-dlp 能解析的站点
（YouTube、B 站等）。

## 功能

- **下载模式**：可选「视频 + 音频」「仅视频」「仅音频（不保留视频）」三种，
  选择会被记住。「仅音频」只下载音频流，体积远小于完整视频。
- **下载与转换**：下载视频后提取 192k AAC 音频，界面分别显示下载与转换进度。
- **音频剪辑**：下载完成后可直接在波形上拖选起止点、试听选区并保存，
  支持另存为新文件或覆盖原文件。
- **格式回退**：按 `bestvideo+bestaudio/best` → `best` → `bestaudio/best` 依次重试。
- **智能命名**：从标题中识别 `《》`/引号内的歌曲名与 `#标签` 歌手。
- **更新提示**：启动时后台异步检查 yt-dlp 版本，结果缓存 24 小时，
  不会每次启动都请求网络。
- **日志输出**：完整展示 yt-dlp 与 ffmpeg 的执行过程，便于排查问题。

## 环境要求

- Python 3.8 或更高版本。
- `ffmpeg` 与 `ffprobe`，需在 `PATH` 中。
- 能访问 yt-dlp 所支持的目标站点。

## 安装

```bash
python3 -m pip install -r requirements.txt

# macOS 安装 ffmpeg
brew install ffmpeg
```

若访问 `pypi.org` 较慢，可追加国内镜像：

```bash
python3 -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 运行

```bash
python3 main.py
```

## 工程目录

工程按**应用源码、运行资源、开发资料、分发配置**分类：

```text
MusicDownload/
├── src/musicdownload/        应用源码（主程序包）
│   ├── __init__.py           包标识与版本号
│   ├── __main__.py           支持 python -m musicdownload 启动
│   ├── main.py               Qt 应用入口：创建 QApplication 与主窗口
│   ├── ui.py                 主界面：布局、目录选择、进度、日志、更新提示
│   ├── downloader.py         DownloadWorker：下载、格式回退、转换 AAC
│   ├── trim_dialog.py        剪辑窗口：波形选区、试听、保存
│   ├── waveform.py           波形显示与起止手柄交互
│   ├── trimmer.py            时长探测、波形渲染、裁剪执行
│   ├── updater.py            UpdateCheckWorker：后台检查 yt-dlp 更新
│   └── config.py             配置读写与路径常量
├── resources/                运行资源
│   └── icon.svg              应用图标
├── docs/                     开发文档（不随程序分发）
│   ├── Development.md        模块职责、环境注意事项、实现记录
│   └── Troubleshooting.md    常见故障排查（HTTP 412 / 403 等）
├── tools/                    辅助脚本（不随程序分发）
│   └── audit_layout.py       目录检查与文件清单生成
├── packaging/                打包配置（不随程序分发）
│   ├── README.md             打包与分发说明
│   └── macOS/Info.plist      app bundle 元数据
├── main.py                   便捷启动器：把 src/ 加入模块搜索路径
├── requirements.txt
├── .gitignore
└── README.md
```

应用入口是 [`src/musicdownload/main.py`](src/musicdownload/main.py)，
根目录的 `main.py` 只是负责设置模块搜索路径的启动器。

## 目录与分发边界

| 目录或文件 | 处理方式 |
| --- | --- |
| `src/musicdownload/` | 应用源码，随程序分发 |
| `resources/icon.svg` | 运行资源，打包时随程序分发 |
| `main.py` | 本地启动器；打包时由 `--paths src` 取代 |
| `docs/` | 开发文档，不参与运行 |
| `tools/` | 辅助脚本，不参与运行 |
| `packaging/` | 打包配置；仅 `Info.plist` 会被写入 app bundle |
| `requirements.txt` | 依赖声明，不随程序分发 |
| `build/`、`dist/`、`__pycache__/` | 生成产物，已被 `.gitignore` 忽略 |

目录规则由脚本校验，新增文件后可随时检查：

```bash
python3 tools/audit_layout.py
```

## 使用说明

1. 粘贴视频链接。
2. 选择下载目录（默认 `~/Documents/SpaceOwl/musicdownload`）。
3. 按需要选择「下载内容」（选择会被记住，下次启动沿用）：

   | 选项 | 行为 | 产物 |
   | --- | --- | --- |
   | 视频 + 音频 | 下载视频并提取 AAC（默认） | `videos/` 视频 + `audios/` 音频 |
   | 仅视频 | 只下载视频，不做转换 | `videos/` 视频 |
   | 仅音频（不保留视频） | 只下载音频流，转换后删除源文件 | `audios/` 音频 |

4. 点击下载按钮（按钮文字会随模式变化）。
5. 转换完成后会自动打开剪辑窗口（可在面板上用「下载完成后自动打开剪辑」关闭）；
   也可以在下载完成后随时点击「剪辑音频」。
6. 在波形上拖动橙色手柄选择要保留的区间，可「试听选区」确认，然后点「保存」。

输出目录结构（位于 `download_root` 下）：

- `videos/` — 下载的视频文件
- `audios/` — 提取的 AAC 音频文件

剪辑结果默认保存在同目录下，命名为 `<原名>-剪辑.aac`（若已存在则自动加序号）；
勾选「覆盖原文件」则直接替换原文件，替换前会二次确认。

### 剪辑操作说明

| 操作 | 效果 |
| --- | --- |
| 拖动橙色手柄 | 调整保留区间的起点 / 终点 |
| 在波形空白处拖动 | 以按下点为锚点重新拉选区间 |
| 单击波形 | 跳转播放位置到该处 |
| 「取当前位置」 | 把当前播放位置设为起点 / 终点 |
| 「试听选区」 | 从起点播放到终点后自动暂停 |
| 「重置为全曲」 | 把选区恢复为整段音频 |

时间输入框接受 `秒`、`分:秒`、`时:分:秒` 三种写法（例如 `90`、`1:30`、`1:02:05.2`）。

配置文件位于 `~/Documents/SpaceOwl/musicdownload/config.json`，
界面底部会显示实际路径。

## 文件命名规则

输出文件名采用：

```text
<song>-<artist1>_<artist2>.aac
```

识别优先级：

- 从标题中提取 `《》`（中文书名号）或引号内容作为歌曲名。
- 从标题中提取 `#标签` 作为歌手，并移除与歌曲名重复的标签。
- 解析 `Artist - Song` 或 `Song (Artist)` 格式作为后备。
- 若无元数据，回退到 `uploader` 或文件名。

仅移除文件系统禁止字符（`\ / : * ? " < > |`），保留中文与英文名称。

## 文档

- [开发说明](docs/Development.md) — 模块职责、环境注意事项、实现记录
- [故障排查](docs/Troubleshooting.md) — HTTP 412 / 403、ffmpeg 等问题
- [打包与分发](packaging/README.md) — macOS 打包说明
