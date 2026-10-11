# 打包与分发

本目录放置**不参与日常运行**的打包配置。源码与运行资源分别位于 `src/` 和
`resources/`，本目录的内容不会被打包进应用一并分发（`Info.plist` 除外，
它会被打包工具读取并写入 app bundle）。

## 现状

目前工程以源码方式运行（`python3 main.py`），尚未接入自动打包流程。
本目录先提供 macOS 打包所需的 bundle 元数据，供后续接入时使用。

## macOS 打包说明

`macOS/Info.plist` 描述 app bundle 的元数据：

| 键 | 值 | 说明 |
| --- | --- | --- |
| `CFBundleIdentifier` | `com.axspaceowl.musicdownload` | 与 Smart Notch 使用同一前缀 |
| `CFBundleShortVersionString` | `0.1.0` | 需与 `src/musicdownload/__init__.py` 的 `__version__` 保持一致 |
| `CFBundleIconFile` | `icon.icns` | 由 `resources/icon.svg` 转换而来 |

用 PyInstaller 生成 `.app` 时，把上面的信息作为参数传入，
并确保 `resources/` 被一并收集：

```bash
# 1) 生成图标（macOS 自带 sips / iconutil）
mkdir -p build/icon.iconset
for size in 16 32 64 128 256 512; do
  sips -s format png -z $size $size resources/icon.svg \
    --out build/icon.iconset/icon_${size}x${size}.png >/dev/null
done
iconutil -c icns build/icon.iconset -o build/icon.icns

# 2) 打包
python3 -m PyInstaller \
  --noconfirm --windowed --name MusicDownload \
  --icon build/icon.icns \
  --osx-bundle-identifier com.axspaceowl.musicdownload \
  --add-data "resources:resources" \
  --paths src \
  main.py
```

产物在 `build/`（`dist/` 与 `build/` 均已被 `.gitignore` 忽略）。

注意：`ffmpeg` / `ffprobe` 是外部程序，不会自动打包。
分发时需要在目标机器单独安装（`brew install ffmpeg`），
或改为随应用内嵌二进制。
