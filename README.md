# YouTube 视频下载与 AAC 提取 UI

一个基于 PyQt6 的桌面应用，用于从 YouTube 下载视频并提取 AAC 音频。

## 项目结构

- `main.py` — 程序启动器（调用 `src.main`）。
- `src/main.py` — Qt 应用入口。
- `src/ui.py` — 主界面、下载目录选择、日志与进度显示。
- `src/downloader.py` — `DownloadWorker`：负责下载、格式回退、后处理及 AAC 转换。
- `src/config.py` — 配置管理（默认路径见下）。

## 默认配置与输出

配置文件：

`~/Documents/SpaceOwl/musicdownload/config.json`

默认输出目录结构（在 `download_root` 下）：

- `videos/` — 下载的视频文件
- `audios/` — 提取的 AAC 音频文件

## 依赖

- Python 3.8+
- `yt-dlp`
- `PyQt6`
- `ffmpeg`（需安装并在 PATH 中）

安装 Python 依赖：

```bash
python3 -m pip install -r requirements.txt
```

macOS 安装 `ffmpeg`：

```bash
brew install ffmpeg
```

## 运行

```bash
python3 main.py
```

## 使用说明

1. 在界面中粘贴 YouTube 视频链接。
2. 选择或输入下载目录（默认保存在 `~/Documents/SpaceOwl/musicdownload`）。
3. 点击“下载并提取 AAC”。
4. 查看下载和转换进度，转换完成后在 `audios/` 中找到 `.aac` 文件。

## 文件命名规则

输出文件名采用：

```
<song>-<artist1>_<artist2>.aac
```

策略（优先级）：

- 从标题中提取 `《》`（中文书名号）或引号内容作为歌曲名。
- 从标题中提取 `#标签` 作为歌手（会移除与歌曲名重复的标签）。
- 解析 `Artist - Song` 或 `Song (Artist)` 格式作为后备。
- 若无元数据，回退到 `uploader` 或文件名。

仅移除文件系统禁止字符（例如 `\/ : * ? " < > |`），保留中文与英文名称。

## 主要修复与实现记录

- 使用 `certifi` 确保 macOS 上的 SSL 根证书有效。
- 移除会导致格式不可用的 `extractor_args` 强制设置。
- 将 `retries` 设置为整数（符合 `yt-dlp` 期望），避免类型错误。
- 处理 `yt-dlp` 可能返回的字典型进度字段（`total_bytes`、`speed` 等）。
- 增加后处理文件名回退逻辑：若 yt-dlp 在合并后修改文件扩展名，程序会在输出目录按标题查找最终文件。
- 改进中文标题与 `#` 标签解析以生成友好的文件名（例如 `无名的人-孙楠_陈楚生.aac`）。
- 添加格式回退顺序：`bestvideo+bestaudio/best`, `best`, `bestaudio/best`。

## 仓库清理

- 已移除开发中产生的临时测试目录（`test_run*`）。

## 其它操作

如果需要，我可以：

- 批量重命名 `audios/` 中现有文件为新的命名格式（先生成预览映射）；
- 为生成的 AAC 添加 ID3 标签（艺术家/作品/专辑）；
- 增加更严格的字符替换或长度限制以兼容老旧设备。

---

启动应用并运行测试：

```bash
python3 main.py
```

