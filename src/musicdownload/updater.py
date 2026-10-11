"""后台异步检查 yt-dlp 是否有新版本。

设计要点：
- 全部工作放在 QThread 中，绝不阻塞 UI（启动时也能安全调用）。
- 按顺序尝试多个软件源，优先使用国内可达的镜像。
- 只比较稳定版（形如 2026.08.19），忽略 PyPI 上的 nightly / dev 预发布版本，
  否则会误报有更新（pip install -U 默认不会安装预发布版）。
- 检查结果缓存 24 小时，避免每次启动都请求网络；手动检查会绕过缓存。
"""

import json
import re
import ssl
import time
import urllib.request

import certifi
import yt_dlp
from PyQt6.QtCore import QThread, pyqtSignal
from yt_dlp.utils import version_tuple

from musicdownload.config import DEFAULT_CONFIG_DIR

# 按顺序尝试，优先国内镜像
VERSION_SOURCES = (
    "https://pypi.tuna.tsinghua.edu.cn/simple/yt-dlp/",
    "https://mirrors.aliyun.com/pypi/simple/yt-dlp/",
    "https://pypi.org/simple/yt-dlp/",
)

CACHE_TTL_SECONDS = 24 * 60 * 60
CACHE_PATH = DEFAULT_CONFIG_DIR / "update_cache.json"

_NETWORK_TIMEOUT = 8
_FILENAME_VERSION_RE = re.compile(r"yt_dlp-([0-9][0-9a-zA-Z.]*?)(?:-py3|-none|\.tar\.gz)")
_STABLE_RELEASE_RE = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}$")
_ARCHIVE_RE = re.compile(r'yt_dlp-[0-9][^"\s<>]*?\.(?:whl|tar\.gz)')


def installed_version() -> str:
    """当前已安装的 yt-dlp 版本。"""
    return yt_dlp.version.__version__


def compare_versions(a: str, b: str) -> int:
    """比较两个版本号，返回 -1 / 0 / 1。"""
    left, right = version_tuple(a), version_tuple(b)
    if left == right:
        return 0
    return 1 if left > right else -1


def _ssl_context() -> ssl.SSLContext:
    # Python 自带证书链在部分环境下不可用，显式使用 certifi
    return ssl.create_default_context(cafile=certifi.where())


def _extract_versions(payload: bytes) -> list[str]:
    """从 PyPI simple 索引（JSON 或 HTML 两种格式）中提取所有版本号。"""
    text = payload.decode("utf-8", errors="ignore")
    try:
        data = json.loads(text)
    except ValueError:
        data = None

    if isinstance(data, dict) and isinstance(data.get("files"), list):
        filenames = [item.get("filename", "") for item in data["files"] if isinstance(item, dict)]
    else:
        filenames = _ARCHIVE_RE.findall(text)

    versions = set()
    for filename in filenames:
        match = _FILENAME_VERSION_RE.search(filename)
        if match:
            versions.add(match.group(1))
    return sorted(versions)


def _latest_stable(versions: list[str]) -> str | None:
    stable = [v for v in versions if _STABLE_RELEASE_RE.match(v)]
    return max(stable, key=version_tuple) if stable else None


def fetch_latest_version() -> str:
    """返回 PyPI 上最新的稳定版 yt-dlp 版本号；所有源都失败时抛出异常。"""
    errors = []
    for url in VERSION_SOURCES:
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/vnd.pypi.simple.v1+json, text/html",
                    "User-Agent": "MusicDownload-UpdateChecker",
                },
            )
            with urllib.request.urlopen(
                request, timeout=_NETWORK_TIMEOUT, context=_ssl_context()
            ) as response:
                payload = response.read()
        except Exception as exc:  # 网络、证书、超时等，换下一个源
            errors.append(f"{url} -> {exc}")
            continue

        try:
            latest = _latest_stable(_extract_versions(payload))
        except Exception as exc:
            errors.append(f"{url} -> 解析失败: {exc}")
            continue

        if latest:
            return latest
        errors.append(f"{url} -> 未找到稳定版本")

    raise RuntimeError("无法获取 yt-dlp 版本信息: " + "；".join(errors))


def load_cache() -> dict | None:
    """读取 24 小时内的有效缓存；不存在、过期或已升级 yt-dlp 时返回 None。"""
    try:
        with CACHE_PATH.open("r", encoding="utf-8") as handle:
            cache = json.load(handle)
    except Exception:
        return None

    if not isinstance(cache, dict):
        return None

    checked_at = cache.get("checked_at")
    latest = cache.get("latest")
    if not isinstance(checked_at, (int, float)) or not isinstance(latest, str):
        return None

    if time.time() - checked_at > CACHE_TTL_SECONDS:
        return None

    # 本地 yt-dlp 已被升级/降级时，旧结论不再可信
    if cache.get("installed") != installed_version():
        return None

    return cache


def save_cache(installed: str, latest: str) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CACHE_PATH.open("w", encoding="utf-8") as handle:
            json.dump(
                {"checked_at": time.time(), "installed": installed, "latest": latest},
                handle,
                indent=2,
            )
    except Exception:
        # 缓存写入失败不应影响主流程
        pass


class UpdateCheckWorker(QThread):
    """后台检查更新线程。"""

    # 已安装版本, 最新版本, 是否有更新, 是否来自缓存
    check_finished = pyqtSignal(str, str, bool, bool)
    check_failed = pyqtSignal(str)

    def __init__(self, force: bool = False, parent=None):
        super().__init__(parent)
        # force=True 时忽略缓存（用于用户手动点击"立即检查更新"）
        self.force = force

    def run(self) -> None:
        installed = installed_version()

        if not self.force:
            cached = load_cache()
            if cached:
                self.check_finished.emit(
                    installed,
                    cached["latest"],
                    compare_versions(cached["latest"], installed) > 0,
                    True,
                )
                return

        try:
            latest = fetch_latest_version()
        except Exception as exc:
            self.check_failed.emit(str(exc))
            return

        save_cache(installed, latest)
        self.check_finished.emit(installed, latest, compare_versions(latest, installed) > 0, False)
