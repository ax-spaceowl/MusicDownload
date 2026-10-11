import os
import re
import shlex
import subprocess
from pathlib import Path

import certifi
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from PyQt6.QtCore import QThread, pyqtSignal
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

# 下载模式
MODE_VIDEO_AND_AUDIO = "video_and_audio"
MODE_VIDEO_ONLY = "video_only"
MODE_AUDIO_ONLY = "audio_only"

MODE_LABELS = {
    MODE_VIDEO_AND_AUDIO: "视频 + 音频",
    MODE_VIDEO_ONLY: "仅视频",
    MODE_AUDIO_ONLY: "仅音频（不保留视频）",
}

MODE_BUTTON_LABELS = {
    MODE_VIDEO_AND_AUDIO: "下载并提取 AAC",
    MODE_VIDEO_ONLY: "仅下载视频",
    MODE_AUDIO_ONLY: "仅提取音频",
}


class DownloadWorker(QThread):
    progress_changed = pyqtSignal(int)
    status_changed = pyqtSignal(str)
    log_message = pyqtSignal(str)
    conversion_progress_changed = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(
        self,
        url: str,
        download_root: str,
        mode: str = MODE_VIDEO_AND_AUDIO,
        parent=None,
    ):
        super().__init__(parent)
        self.url = url.strip()
        self.mode = mode if mode in MODE_LABELS else MODE_VIDEO_AND_AUDIO
        self.download_root = Path(download_root).expanduser().resolve()
        self.download_folder = self.download_root / "videos"
        self.audio_folder = self.download_root / "audios"
        self.download_folder.mkdir(parents=True, exist_ok=True)
        self.audio_folder.mkdir(parents=True, exist_ok=True)
        self.info = None
        self.filename = None
        self.downloaded_files = []
        # 转换完成后产出的 AAC 文件路径，供剪辑功能使用
        self.audio_path = None

    def log(self, message: str) -> None:
        self.log_message.emit(message)

    def run(self) -> None:
        if not self.url:
            self.finished_signal.emit(False, "请输入视频链接")
            return

        try:
            self.status_changed.emit(
                "开始下载音频流..." if self.mode == MODE_AUDIO_ONLY else "开始下载视频..."
            )
            self.download_video()
            if not self.filename:
                raise RuntimeError("无法确定下载后的文件名")

            if self.mode == MODE_VIDEO_ONLY:
                self.finished_signal.emit(True, "视频下载完成")
                return

            self.status_changed.emit("开始提取 AAC 音频...")
            self.convert_to_aac()

            if self.mode == MODE_AUDIO_ONLY:
                self._remove_source_media()
                self.finished_signal.emit(True, "音频提取完成（已删除下载的源文件）")
            else:
                self.finished_signal.emit(True, "下载并提取完成")
        except Exception as exc:
            message = self._friendly_error(exc)
            self.log(str(exc))
            self.finished_signal.emit(False, message)

    def _remove_source_media(self) -> None:
        """仅音频模式下，转换成功后删除下载的源文件（通常是 m4a / webm）。"""
        if not self.filename:
            return
        path = Path(self.filename)
        if not path.exists():
            return
        try:
            path.unlink()
            self.log(f"已删除下载的源文件: {path.name}")
        except OSError as exc:
            self.log(f"删除源文件失败（可手动清理）: {exc}")

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        """把底层异常翻译成可操作的提示信息。"""
        raw = str(exc)
        lowered = raw.lower()
        if "http error 412" in lowered or "precondition failed" in lowered:
            return (
                "站点返回 HTTP 412（反爬拦截）。多数情况下是 yt-dlp 版本过旧，"
                "无法通过站点最新的接口校验。\n"
                "解决办法：在终端执行  pip install -U yt-dlp  后重试。"
            )
        if "http error 403" in lowered or "forbidden" in lowered:
            return (
                "站点返回 HTTP 403。该清晰度或内容可能需要登录后才能访问，"
                "可尝试提供浏览器 Cookie（--cookies-from-browser）。\n"
                f"原始错误：{raw}"
            )
        return raw

    def download_video(self) -> None:
        def progress_hook(d):
            status = d.get("status")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                downloaded = d.get("downloaded_bytes", 0)
                # Normalize possible dict-wrapped numeric values returned by yt-dlp
                try:
                    if isinstance(total, dict):
                        total = total.get("value") or total.get("bytes") or None
                    if isinstance(downloaded, dict):
                        downloaded = downloaded.get("value") or downloaded.get("bytes") or 0
                    if total:
                        percent = int(int(downloaded) * 100 / int(total))
                    else:
                        percent = 0
                except Exception:
                    percent = 0
                try:
                    speed = d.get("speed")
                except Exception:
                    speed = None
                eta = d.get("eta")
                self.status_changed.emit(
                    f"下载中: {d.get('filename', '')} {percent}% {self._format_speed(speed)} ETA {eta}s"
                )
            elif status == "finished":
                self.progress_changed.emit(100)
                self.status_changed.emit("下载完成")
                filename = d.get("filename")
                if filename:
                    self.downloaded_files.append(filename)
                    self.filename = filename

        base_opts = {
            "merge_output_format": "mp4",
            "outtmpl": str(self.download_folder / "%(title)s.%(ext)s"),
            "noplaylist": True,
            "progress_hooks": [progress_hook],
            "ignoreerrors": False,
            "quiet": True,
            "no_warnings": True,
            "prefer_ffmpeg": True,
            "socket_timeout": 30,
            "retries": 5,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
            # Do not force youtube extractor player_client; some videos
            # become unavailable for certain player variants. Leave extractor
            # args unset so yt-dlp can choose the best available extractor.
        }

        if self.mode == MODE_AUDIO_ONLY:
            # 只取音频流：体积远小于完整视频，多数站点无需合并
            formats_to_try = ["bestaudio/best", "best"]
        else:
            formats_to_try = [
                "bestvideo+bestaudio/best",
                "best",
                "bestaudio/best",
            ]
        last_exception = None

        for fmt in formats_to_try:
            self.log(f"尝试下载格式: {fmt}")
            ydl_opts = {**base_opts, "format": fmt}
            try:
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(self.url, download=True)
                    self.info = info
                    self.filename = self._resolve_downloaded_file(ydl, info)
                    break
            except DownloadError as exc:
                self.log(f"格式 {fmt} 下载失败: {exc}")
                last_exception = exc
                continue

        if not getattr(self, "info", None):
            raise last_exception or RuntimeError("无法下载视频")

        if not self.filename:
            self.filename = self._resolve_downloaded_file(None, self.info)

    def convert_to_aac(self) -> None:
        if not self.filename:
            raise FileNotFoundError("下载视频文件不存在")

        source_path = Path(self.filename)
        if not source_path.exists():
            resolved = self._resolve_downloaded_file(None, self.info)
            if resolved:
                source_path = Path(resolved)
                self.filename = resolved
            else:
                raise FileNotFoundError(f"下载文件不存在: {source_path}")

        duration = self._get_duration(source_path)
        filename = self._extract_audio_filename(source_path)
        target_path = self.audio_folder / f"{filename}.aac"

        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-acodec",
            "aac",
            "-b:a",
            "192k",
            str(target_path),
            "-progress",
            "pipe:1",
        ]

        self.log(f"执行命令: {' '.join(shlex.quote(x) for x in command)}")
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        if not process.stdout:
            raise RuntimeError("无法读取 ffmpeg 输出")

        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            self.log(f"ffmpeg: {line}")
            if line.startswith("out_time_ms=") and duration > 0:
                out_time_ms = int(line.split("=", 1)[1])
                progress = min(100, int(out_time_ms / (duration * 1000) * 100))
                self.conversion_progress_changed.emit(progress)
                self.status_changed.emit(f"转换中: {progress}%")
            elif line.startswith("progress=") and line.split("=", 1)[1] == "end":
                self.conversion_progress_changed.emit(100)

        exit_code = process.wait()
        if exit_code != 0:
            raise RuntimeError(f"ffmpeg 转换失败，退出码 {exit_code}")

        self.audio_path = str(target_path)

    def _resolve_downloaded_file(self, ydl, info) -> str | None:
        candidates = []

        def add_candidate(value) -> None:
            if not value:
                return
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = self.download_folder / path
            candidates.append(path)

        add_candidate(self.filename)
        for downloaded_file in self.downloaded_files:
            add_candidate(downloaded_file)

        if info:
            add_candidate(info.get("filepath"))
            add_candidate(info.get("_filename"))
            for item in info.get("requested_downloads") or []:
                add_candidate(item.get("filepath"))
                add_candidate(item.get("_filename"))
                add_candidate(item.get("filename"))
            if ydl:
                try:
                    add_candidate(ydl.prepare_filename(info))
                    merged_info = {**info, "ext": "mp4"}
                    add_candidate(ydl.prepare_filename(merged_info))
                except Exception:
                    pass

        for path in candidates:
            if path.exists():
                return str(path)

        title = info.get("title") if info else None
        if title:
            safe_title = self._sanitize_filename(title)
            title_matches = [
                path
                for path in self.download_folder.iterdir()
                if path.is_file()
                and (
                    path.stem == title
                    or path.stem == safe_title
                    or path.name.startswith(title)
                    or path.name.startswith(safe_title)
                )
            ]
            if title_matches:
                return str(max(title_matches, key=lambda p: p.stat().st_mtime))

        media_exts = {".mp4", ".m4a", ".webm", ".mkv", ".mov", ".aac", ".opus"}
        recent_media = [
            path
            for path in self.download_folder.iterdir()
            if path.is_file() and path.suffix.lower() in media_exts
        ]
        if recent_media:
            return str(max(recent_media, key=lambda p: p.stat().st_mtime))

        return None

    def _get_duration(self, source_path: Path) -> float:
        if self.info and self.info.get("duration"):
            return float(self.info["duration"])
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            self.log(f"ffprobe failed: {result.stderr.strip()}")
            return 0.0
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 0.0

    def _extract_audio_filename(self, source_path: Path) -> str:
        # Desired filename format: "<song>-<artist1>_<artist2>" (preserve Chinese)
        title = None
        artists = []
        if self.info:
            raw_artist = (
                self.info.get("artist")
                or self.info.get("album_artist")
                or self.info.get("creator")
                or self.info.get("uploader")
            )
            raw_track = self.info.get("track") or self.info.get("title")

            # Heuristics for Chinese titles and hashtag artists (e.g. "#孙楠 #陈楚生 给《#无名的人》")
            if raw_track:
                # extract song inside Chinese book quotes 《》 or other quotes first
                m = re.search(r'《([^》]+)》', raw_track)
                if not m:
                    m = re.search(r'“([^”]+)”', raw_track)
                if not m:
                    m = re.search(r'"([^"]+)"', raw_track)
                if m:
                    song = m.group(1).strip()
                    # remove leading hash if present
                    song = song.lstrip('#')
                    title = song

                # extract tags like #Name (prefer these over uploader)
                tags = re.findall(r"#([\w\u4e00-\u9fff·]+)", raw_track)
                if tags:
                    # remove tag that equals the song title if present
                    clean_tags = [t.strip() for t in tags if t and t.strip()]
                    if title:
                        clean_tags = [t for t in clean_tags if t != title]
                    artists = clean_tags

                # If we still don't have title or artists, try generic parsing
                if not title:
                    parsed = self._parse_title_artist(raw_track)
                    if isinstance(parsed, str) and " - " in parsed:
                        a, s = parsed.split(" - ", 1)
                        parts = re.split(r"\s*(?:/|,|&|\\+|;|、|feat\.?|ft\.?| and |\band\b)\s*", a, flags=re.IGNORECASE)
                        artists = artists or [p.strip() for p in parts if p and p.strip()]
                        title = s.strip()
                    else:
                        title = parsed.strip()

            # Parse artist list from raw_artist (uploader) as fallback
            if raw_artist and not artists:
                parts = re.split(r"\s*(?:/|,|&|\\+|;|、|feat\.?|ft\.?| and |\band\b)\s*", raw_artist, flags=re.IGNORECASE)
                artists = [p.strip() for p in parts if p and p.strip()]

        if not title:
            title = source_path.stem

        # Build final filename: song-artist1_artist2
        safe_title = self._sanitize_filename(title)
        safe_artists = [self._sanitize_filename(a) for a in artists] if artists else []
        if safe_artists:
            artist_text = "_".join(safe_artists)
            filename = f"{safe_title}-{artist_text}"
        else:
            filename = safe_title
        return filename

    def _parse_title_artist(self, title: str) -> str:
        patterns = [
            r"^(?P<artist>[^-–—]+)\s*[-–—]\s*(?P<song>.+)$",
            r"^(?P<song>.+)\s*\((?P<artist>[^\)]+)\)$",
        ]
        for pattern in patterns:
            match = re.match(pattern, title)
            if match:
                artist = match.groupdict().get("artist") or ""
                song = match.groupdict().get("song") or title
                return f"{artist.strip()} - {song.strip()}" if artist else song.strip()
        return title.strip()

    @staticmethod
    def _sanitize_filename(value: str) -> str:
        cleaned = re.sub(r"[\\/:*?\"<>|]+", "", value)
        return cleaned.strip() or "audio"

    @staticmethod
    def _format_speed(speed):
        if not speed:
            return ""
        # yt-dlp may return a dict for speed (with keys like 'current' or 'value')
        if isinstance(speed, dict):
            for key in ("current", "value", "mean", "speed"):
                val = speed.get(key)
                if isinstance(val, (int, float)):
                    speed = val
                    break
            else:
                # try to extract numeric from common keys
                speed = speed.get("bytes") if isinstance(speed.get("bytes", None), (int, float)) else None
        try:
            speed = float(speed)
        except Exception:
            return ""
        units = ["B/s", "KB/s", "MB/s", "GB/s"]
        index = 0
        while speed >= 1024 and index < len(units) - 1:
            speed /= 1024.0
            index += 1
        return f"{speed:.1f}{units[index]}"
