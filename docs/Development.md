# 开发说明

面向维护者。目录结构总览见根目录 [README](../README.md)。

## 模块职责

| 文件 | 职责 |
| --- | --- |
| `src/musicdownload/__init__.py` | 包标识与版本号 |
| `src/musicdownload/__main__.py` | 支持 `python -m musicdownload` 启动 |
| `src/musicdownload/main.py` | Qt 应用入口：创建 `QApplication`、设置窗口图标、显示主窗口 |
| `src/musicdownload/ui.py` | `MainWindow`：界面布局、下载目录选择、进度与日志、更新检查交互 |
| `src/musicdownload/downloader.py` | `DownloadWorker`：yt-dlp 下载、格式回退、ffmpeg 转 AAC、输出文件定位 |
| `src/musicdownload/trim_dialog.py` | `TrimDialog`：剪辑窗口（波形选区、试听、保存） |
| `src/musicdownload/waveform.py` | `WaveformView`：波形绘制与起止手柄交互 |
| `src/musicdownload/trimmer.py` | 时长探测、波形渲染、`TrimWorker` / `WaveformWorker` / `DurationWorker` |
| `src/musicdownload/updater.py` | `UpdateCheckWorker`：后台检查 yt-dlp 版本，含 24 小时缓存 |
| `src/musicdownload/config.py` | 用户配置读写、默认路径与资源路径常量 |

## 下载模式

`DownloadWorker` 通过 `mode` 参数区分三种行为，取值定义在 `downloader.py` 顶部：

| 常量 | 值 | 行为 |
| --- | --- | --- |
| `MODE_VIDEO_AND_AUDIO` | `video_and_audio` | 下载视频 → 提取 AAC，两者都保留 |
| `MODE_VIDEO_ONLY` | `video_only` | 只下载视频，不调用转换 |
| `MODE_AUDIO_ONLY` | `audio_only` | 只取 `bestaudio/best` 音频流 → 转 AAC → 删除源文件 |

- 非法或缺失的 `mode` 会回退到 `MODE_VIDEO_AND_AUDIO`。
- 「仅音频」用 `bestaudio/best` 只拉音频流，实测同一视频只需下载 5.35 MiB，
  而完整 4K 视频要大得多；转换后源文件（多为 `.m4a`）会被删除。
- 三个模式共用同一套输出文件名解析逻辑，`_resolve_downloaded_file()` 的候选扩展名
  已包含 `.m4a` / `.webm` / `.opus`，因此音频流也能正确定位。
- 模式选择持久化在配置键 `download_mode`。

分层关系：`ui` 只负责界面与信号连接，耗时的下载、检查与裁剪分别由
`downloader`、`updater`、`trimmer` 中的 `QThread` 子类在后台执行，
通过信号回传结果，因此界面不会被阻塞。

## 音频剪辑实现要点

- **时长必须自己算**。ADTS `.aac` 没有索引，`ffprobe` 的 `format=duration`
  只是按码率估算：实测一段 273.83 秒的音频被报成 271.67 秒（差 2.16 秒）。
  这会让波形横轴与时间轴错位，所以 `probe_duration()` 改用
  `nb_read_packets × 每帧采样数 ÷ 采样率` 计算，实测误差 0.001 秒、耗时 0.04 秒。
- **波形由 ffmpeg 渲染**，用 `showwavespic` 滤镜输出 PNG 到 stdout，
  再交给 `QPixmap` 显示，因此不引入任何新的 Python 依赖。
- **裁剪用 `-ss` + `-t` 而不是 `-to`**。`-ss` 放在 `-i` 之前配合重新编码，
  既能快速定位又能精确到帧（实测请求 45 秒得到 45.023 秒）。
- **覆盖原文件时先写临时文件再 `os.replace()`**，避免中途失败把源文件写坏。
- 试听用 `PyQt6.QtMultimedia` 的 `QMediaPlayer`，播放选区时记录终点位置，
  在 `positionChanged` 中到点自动暂停。
- 注意：`TrimWorker` 里的区间字段命名为 `clip_start` / `clip_end`，
  不能叫 `start` / `end` —— 那会覆盖 `QThread.start()` 导致线程无法启动。


## 运行

```bash
# 推荐：根目录启动器会自动把 src/ 加入模块搜索路径
python3 main.py

# 或者
cd src && python3 -m musicdownload
```

## 依赖与外部程序

- Python 3.8+（开发环境为 3.14）
- `PyQt6`、`yt-dlp`、`certifi`（见 `requirements.txt`）
- `ffmpeg` / `ffprobe`，需在 `PATH` 中（macOS：`brew install ffmpeg`）

```bash
python3 -m pip install -r requirements.txt
```

### 环境注意事项

- **pip 需要镜像**。本机访问 `pypi.org` 会超时，安装依赖时建议追加
  `-i https://pypi.tuna.tsinghua.edu.cn/simple`。
- **SSL 根证书**。`downloader.py` 会把 `SSL_CERT_FILE` 指向 `certifi` 的证书包，
  否则 Python 3.14 在 macOS 上可能出现证书校验失败。
- **不要降级 yt-dlp**。站点接口变动频繁，旧版本会直接导致下载失败，
  详见 [故障排查](Troubleshooting.md)。

## 目录约定

工程按角色分类，规则由 `tools/audit_layout.py` 校验：

| 目录 | 用途 | 是否随程序分发 |
| --- | --- | --- |
| `src/musicdownload/` | 应用源码 | 是 |
| `resources/` | 图标等运行资源 | 是 |
| `docs/` | 开发文档、排查记录 | 否 |
| `tools/` | 辅助脚本（目录检查等） | 否 |
| `packaging/` | 打包与分发配置 | 否 |

```bash
# 检查目录是否跑偏
python3 tools/audit_layout.py

# 顺便生成文件清单到 docs/FileInventory.md
python3 tools/audit_layout.py --write-report
```

## 实现记录

- 使用 `certifi` 确保 macOS 上的 SSL 根证书有效。
- 移除会导致格式不可用的 `extractor_args` 强制设置。
- 将 `retries` 设置为整数（符合 `yt-dlp` 期望），避免类型错误。
- 处理 `yt-dlp` 可能返回的字典型进度字段（`total_bytes`、`speed` 等）。
- 增加后处理文件名回退逻辑：若 yt-dlp 在合并后修改文件扩展名，
  程序会在输出目录按标题查找最终文件。
- 改进中文标题与 `#` 标签解析以生成友好的文件名
  （例如 `无名的人-孙楠_陈楚生.aac`）。
- 添加格式回退顺序：`bestvideo+bestaudio/best`、`best`、`bestaudio/best`。
- 把底层异常翻译成可操作的提示（HTTP 412 / 403），避免只弹英文堆栈。
- 新增启动时异步检查 yt-dlp 更新，结果缓存 24 小时。
- 新增音频剪辑窗口：波形拖选区间、试听、另存或覆盖原文件。
- 新增下载模式选择：视频 + 音频 / 仅视频 / 仅音频。
