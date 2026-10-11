#!/usr/bin/env python3
"""检查工程目录结构是否符合约定。

对应 Smart Notch 工程里的 Development/Tools/audit_build_layout.py：
用一条命令确认"目录没有跑偏"，避免生成产物或临时文件混进仓库。

用法：
    python3 tools/audit_layout.py
    python3 tools/audit_layout.py --write-report
"""

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 应用代码只应存在于这些目录下（相对工程根目录）
ALLOWED_CODE_DIRS = ("src/musicdownload", "tools")

# 允许放在工程根目录的 Python 文件（入口启动器）
ALLOWED_ROOT_FILES = {"main.py"}

# 仓库中必须存在的路径
REQUIRED_PATHS = (
    "main.py",
    "requirements.txt",
    "README.md",
    ".gitignore",
    "src/musicdownload/__init__.py",
    "src/musicdownload/__main__.py",
    "src/musicdownload/main.py",
    "src/musicdownload/ui.py",
    "src/musicdownload/downloader.py",
    "src/musicdownload/updater.py",
    "src/musicdownload/config.py",
    "resources/icon.svg",
    "docs",
    "tools",
    "packaging",
)

# 不应进入 Git 索引的名字/后缀（生成产物与系统文件）
FORBIDDEN_DIR_NAMES = {"__pycache__", ".DS_Store", "build", "dist", ".venv", "venv"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo"}


def iter_project_files() -> list[Path]:
    """遍历工程内的文件，跳过 .git。"""
    files = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.relative_to(PROJECT_ROOT).parts[0] == ".git":
            continue
        files.append(path)
    return sorted(files)


def tracked_files() -> list[str]:
    """Git 索引中的文件列表；不是 Git 仓库时返回空列表。"""
    try:
        result = subprocess.run(
            ["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def is_generated(relative: Path) -> bool:
    return any(part in FORBIDDEN_DIR_NAMES for part in relative.parts) or (
        relative.suffix in FORBIDDEN_SUFFIXES
    )


def is_source_location_ok(relative: Path) -> bool:
    if relative.parent == Path("."):
        return relative.name in ALLOWED_ROOT_FILES
    posix = relative.as_posix()
    return any(posix.startswith(f"{directory}/") for directory in ALLOWED_CODE_DIRS)


def main() -> int:
    parser = argparse.ArgumentParser(description="检查工程目录结构")
    parser.add_argument(
        "--write-report", action="store_true", help="把文件清单写入 docs/FileInventory.md"
    )
    args = parser.parse_args()

    issues: list[str] = []
    notes: list[str] = []

    for relative in REQUIRED_PATHS:
        if not (PROJECT_ROOT / relative).exists():
            issues.append(f"缺少必需路径: {relative}")

    # 1) 生成产物绝不能进入 Git 索引
    for tracked in tracked_files():
        if is_generated(Path(tracked)):
            issues.append(f"Git 索引中存在生成产物（应执行 git rm --cached）: {tracked}")

    # 2) 工作区中不应残留构建输出
    for path in iter_project_files():
        relative = path.relative_to(PROJECT_ROOT)
        if relative.parts[0] in {"build", "dist"}:
            issues.append(f"工作区残留构建输出: {relative}")

    # 3) Python 源码位置
    for path in iter_project_files():
        relative = path.relative_to(PROJECT_ROOT)
        if path.suffix == ".py" and not is_source_location_ok(relative):
            issues.append(f"Python 源码位置不符合约定（应在 {ALLOWED_CODE_DIRS}）: {relative}")

    # 4) 提示性信息：缓存目录在开发期属正常，已被 .gitignore 覆盖
    cached = [p for p in iter_project_files() if "__pycache__" in p.parts]
    if cached:
        notes.append(f"工作区有 {len(cached)} 个 __pycache__ 文件（已被 .gitignore 忽略）")

    print(f"工程根目录: {PROJECT_ROOT}")
    print(f"必需路径: {len(REQUIRED_PATHS)} 项")
    print(f"Git 跟踪文件: {len(tracked_files())} 个")

    if issues:
        print(f"\n发现 {len(issues)} 个问题:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\n目录检查通过。")

    for note in notes:
        print(f"提示: {note}")

    if args.write_report:
        inventory = [
            path.relative_to(PROJECT_ROOT).as_posix()
            for path in iter_project_files()
            if not is_generated(path.relative_to(PROJECT_ROOT))
        ]
        report_path = PROJECT_ROOT / "docs" / "FileInventory.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# 工程文件清单", "", f"共 {len(inventory)} 个文件。", ""]
        lines += [f"- `{item}`" for item in inventory]
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n已写入文件清单: {report_path.relative_to(PROJECT_ROOT)}")

    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
