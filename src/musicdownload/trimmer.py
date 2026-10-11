"""音频剪辑：时长探测、波形图生成与裁剪执行。

时长探测的一个关键坑：ADTS `.aac` 没有索引，`ffprobe` 的 `format=duration` 只是
按码率估算，实测 4.5 分钟的音频误差可达 2 秒。因此这里改用"包数量 × 每帧采样数"
计算真实时长（实测与解码采样点数完全一致，且只需 0.04 秒）。
"""

import json
import os
import subprocess
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

# 各编码每帧的采样点数（用于精确换算时长）
SAMPLES_PER_FRAME = {
    "aac": 1024,
    "mp3": 1152,
    "opus": 960,
    "flac": 4096,
    "alac": 4096,
}

MIN_CLIP_SECONDS = 0.2
AUDIO_BITRATE = "192k"


def format_time(seconds: float) -> str:
    """把秒数格式化为 `mm:ss.d`（超过 1 小时则为 `h:mm:ss.d`）。"""
    seconds = max(0.0, float(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours >= 1:
        return f"{int(hours)}:{int(minutes):02d}:{secs:04.1f}"
    return f"{int(minutes)}:{secs:04.1f}"


def parse_time(text: str) -> float | None:
    """解析 `ss`、`mm:ss`、`h:mm:ss`（秒数可带小数）；无法解析返回 None。

    按冒号个数判定语义，避免 `1:30` 被误判成 1 小时 30 分。
    """
    text = (text or "").strip()
    if not text:
        return None

    parts = text.split(":")
    if len(parts) > 3:
        return None
    try:
        values = [float(part) for part in parts]
    except ValueError:
        return None

    if len(parts) == 1:
        return values[0]
    if len(parts) == 2:
        minutes, seconds = values
        return minutes * 60 + seconds
    hours, minutes, seconds = values
    return hours * 3600 + minutes * 60 + seconds


def _run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True)


def probe_duration(path: str | Path) -> float:
    """返回音频真实时长（秒）；探测失败返回 0.0。"""
    path = str(path)

    try:
        result = _run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a:0",
                "-count_packets",
                "-show_entries", "stream=codec_name,sample_rate,nb_read_packets",
                "-of", "json", path,
            ]
        )
        if result.returncode == 0 and result.stdout:
            stream = json.loads(result.stdout).get("streams", [{}])[0]
            codec = stream.get("codec_name")
            sample_rate = stream.get("sample_rate")
            packets = stream.get("nb_read_packets")
            samples_per_frame = SAMPLES_PER_FRAME.get(codec or "")
            if samples_per_frame and sample_rate and packets and int(packets) > 0:
                return int(packets) * samples_per_frame / float(sample_rate)
    except Exception:
        pass

    # 回退：容器格式已知时长时可用，但对 ADTS AAC 只是估算值
    try:
        result = _run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", path,
            ]
        )
        if result.returncode == 0:
            return float(result.stdout.decode("utf-8", "ignore").strip())
    except Exception:
        pass

    return 0.0


def generate_waveform(path: str | Path, width: int, height: int) -> bytes:
    """用 ffmpeg 把整段音频渲染成一张 PNG 波形图（返回 PNG 字节）。"""
    width = max(50, int(width))
    height = max(40, int(height))
    result = _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(path),
            "-filter_complex", f"showwavespic=s={width}x{height}:colors=#1C7ED6",
            "-frames:v", "1",
            "-f", "image2pipe", "-vcodec", "png", "-",
        ]
    )
    if result.returncode != 0 or not result.stdout:
        message = result.stderr.decode("utf-8", "ignore").strip() or "ffmpeg 未输出波形数据"
        raise RuntimeError(f"生成波形失败: {message}")
    return result.stdout


def unique_target_path(source: Path, suffix: str = "-剪辑") -> Path:
    """在源文件同目录下生成不冲突的新文件名，如 `歌曲-剪辑.aac`。"""
    candidate = source.with_name(f"{source.stem}{suffix}{source.suffix}")
    index = 2
    while candidate.exists():
        candidate = source.with_name(f"{source.stem}{suffix}({index}){source.suffix}")
        index += 1
    return candidate


class WaveformWorker(QThread):
    """后台生成波形图（长音频渲染需要一点时间）。"""

    ready = pyqtSignal(bytes)
    failed = pyqtSignal(str)

    def __init__(self, source: str | Path, width: int, height: int, parent=None):
        super().__init__(parent)
        self.source = Path(source)
        self.width = width
        self.height = height

    def run(self) -> None:
        try:
            self.ready.emit(generate_waveform(self.source, self.width, self.height))
        except Exception as exc:
            self.failed.emit(str(exc))


class DurationWorker(QThread):
    """后台探测真实时长（大文件解析可能需要一点时间）。"""

    ready = pyqtSignal(float)
    failed = pyqtSignal(str)

    def __init__(self, source: str | Path, parent=None):
        super().__init__(parent)
        self.source = Path(source)

    def run(self) -> None:
        duration = probe_duration(self.source)
        if duration > 0:
            self.ready.emit(duration)
        else:
            self.failed.emit("无法读取音频时长")


class TrimWorker(QThread):
    """后台执行裁剪，避免长时间阻塞界面。"""

    finished_signal = pyqtSignal(bool, str)
    log_message = pyqtSignal(str)

    def __init__(
        self,
        source: str | Path,
        start: float,
        end: float,
        target: str | Path,
        parent=None,
    ):
        super().__init__(parent)
        self.source = Path(source)
        # 注意：不能命名为 self.start / self.end，否则会覆盖 QThread.start 等方法
        self.clip_start = float(start)
        self.clip_end = float(end)
        self.target = Path(target)

    def run(self) -> None:
        duration = self.clip_end - self.clip_start
        if duration < MIN_CLIP_SECONDS:
            self.finished_signal.emit(False, f"选区过短（至少要 {MIN_CLIP_SECONDS} 秒）")
            return

        # 先写临时文件再替换：这样"覆盖原文件"时不会中途损坏源文件
        temp_path = self.target.with_name(f".{self.target.name}.tmp{self.target.suffix}")

        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{self.clip_start:.3f}",
            "-t", f"{duration:.3f}",
            "-i", str(self.source),
            "-vn",
            "-acodec", "aac",
            "-b:a", AUDIO_BITRATE,
            str(temp_path),
        ]
        self.log_message.emit("执行命令: " + " ".join(command))

        try:
            result = subprocess.run(command, capture_output=True, text=True)
        except FileNotFoundError:
            self.finished_signal.emit(False, "找不到 ffmpeg，请先安装并加入 PATH")
            return

        if result.returncode != 0 or not temp_path.exists():
            detail = (result.stderr or "").strip() or f"退出码 {result.returncode}"
            temp_path.unlink(missing_ok=True)
            self.finished_signal.emit(False, f"剪辑失败: {detail}")
            return

        try:
            os.replace(temp_path, self.target)
        except OSError as exc:
            temp_path.unlink(missing_ok=True)
            self.finished_signal.emit(False, f"保存失败: {exc}")
            return

        real_length = probe_duration(self.target)
        self.finished_signal.emit(
            True, f"已保存: {self.target.name}（{format_time(real_length)}）"
        )
