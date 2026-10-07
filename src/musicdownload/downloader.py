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


class DownloadWorker(QThread):
    progress_changed = pyqtSignal(int)
    status_changed = pyqtSignal(str)
    log_message = pyqtSignal(str)
    conversion_progress_changed = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, url: str, download_root: str, parent=None):
        super().__init__(parent)
        self.url = url.strip()
        self.download_root = Path(download_root).expanduser().resolve()
        self.download_folder = self.download_root / "videos"
        self.audio_folder = self.download_root / "audios"
        self.download_folder.mkdir(parents=True, exist_ok=True)
        self.audio_folder.mkdir(parents=True, exist_ok=True)
        self.info = None
        self.filename = None

    def log(self, message: str) -> None:
        self.log_message.emit(message)

    def run(self) -> None:
        if not self.url:
            self.finished_signal.emit(False, "请输入视频链接")
            return

        try:
            self.status_changed.emit("开始下载视频...")
            self.download_video()
            if not self.filename:
                raise RuntimeError("无法确定下载后的文件名")

            self.status_changed.emit("开始提取 AAC 音频...")
            self.convert_to_aac()
            self.finished_signal.emit(True, "下载并提取完成")
        except Exception as exc:
            self.log(str(exc))
            self.finished_signal.emit(False, str(exc))

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
                self.status_changed.emit("视频下载完成，准备提取音频")
                self.filename = d.get("filename")

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
                    # info may contain the final filename after post-processing
                    self.info = info
                    if info and "_filename" in info:
                        # prefer the final filename reported by yt-dlp
                        self.filename = info["_filename"]
                    break
            except DownloadError as exc:
                self.log(f"格式 {fmt} 下载失败: {exc}")
                last_exception = exc
                continue

        if not getattr(self, "info", None):
            raise last_exception or RuntimeError("无法下载视频")

        # If yt-dlp post-processing changed the filename (e.g. merged to mp4),
        # try to locate the real final file by title as a fallback.
        if self.info and self.info.get("title") and (not self.filename or not Path(self.filename).exists()):
            title = self.info["title"]
            try:
                candidates = list(self.download_folder.glob(f"{title}*"))
                if candidates:
                    chosen = max(candidates, key=lambda p: p.stat().st_mtime)
                    self.filename = str(chosen)
            except Exception:
                pass

        if not self.filename:
            if self.info and "_filename" in self.info:
                self.filename = self.info["_filename"]
            elif self.info and "title" in self.info:
                ext = self.info.get("ext", "mp4")
                self.filename = str(self.download_folder / f"{self.info['title']}.{ext}")

    def convert_to_aac(self) -> None:
        if not self.filename:
            raise FileNotFoundError("下载视频文件不存在")

        source_path = Path(self.filename)
        if not source_path.exists():
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
            filename = f"{safe_title}-{"_".join(safe_artists)}"
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
