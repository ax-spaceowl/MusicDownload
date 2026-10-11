# 故障排查

## 下载 B 站视频报 HTTP 412

**现象**

```
[BiliBili] xxxxxxxxxxx: Unable to download JSON metadata: HTTP Error 412: Precondition Failed
```

**原因**

报错发生在向 `api.bilibili.com/x/player/wbi/playurl` 取播放地址的阶段，
视频还没开始下载就被站点的反爬机制拦截。最常见的原因是 **yt-dlp 版本过旧**：
B 站的接口签名规则更新后，旧版本算不出合法签名，服务端直接返回 412。

与以下因素**无关**（已实测排除）：UA 伪造、缺少 `Referer`、代理、Cookie、网络。

**解决**

```bash
# 访问 pypi.org 缓慢时建议使用镜像
python3 -m pip install -U yt-dlp -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**验证方法**：同一链接在旧版本上稳定复现 412，升级后即可正常取到全部清晰度。

界面上的「立即检查更新」可直接确认版本状态；该功能会在后台异步检查，
并把结果缓存 24 小时，因此不会每次启动都请求网络。

## 下载报 HTTP 403

通常是该清晰度或内容需要登录态。1080p 以上（如 4K、大会员画质）需要提供浏览器
Cookie 才能取到，未登录时 yt-dlp 只能拿到最高 1080p 的流。

## 检查更新一直失败

不影响下载，属于网络问题。更新检查会依次尝试清华镜像、阿里云镜像、
`pypi.org`，全部不可达时才报失败。若长期失败，可手动执行上面的升级命令。

## 转换阶段报错或进度不动

确认 `ffmpeg` 与 `ffprobe` 已安装且在 `PATH` 中：

```bash
which ffmpeg ffprobe
# macOS 安装
brew install ffmpeg
```

## 剪辑窗口的问题

**波形一直显示「正在生成波形...」**

波形由 ffmpeg 渲染，先确认 `ffmpeg` 在 `PATH` 中（见上一节）。
文件损坏或不是音频时也会失败，此时状态栏会显示具体原因。

**试听没有声音**

试听使用 PyQt6 自带的 QtMultimedia（macOS 上走系统解码），确认系统音量与
输出设备正常。试听不影响剪辑本身，可以直接点「保存」。

**剪辑结果比预期长了几十毫秒**

AAC 每帧固定 1024 个采样点（44.1kHz 下约 23 毫秒），裁剪边界只能落在帧边界上，
因此会有最多一帧的偏差，属正常现象。

**担心覆盖原文件**

「覆盖原文件」会先二次确认，且实现上是先写临时文件再原子替换，
中途失败不会损坏原文件。若仍不放心，保持不勾选即可另存为
`<原名>-剪辑.aac`。

## 找不到下载后的文件

`download_root` 下会创建 `videos/`（视频）与 `audios/`（AAC 音频）两个子目录。
默认 `download_root` 为 `~/Documents/SpaceOwl/musicdownload`，
界面底部会显示当前配置文件的完整路径。
