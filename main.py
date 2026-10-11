"""便捷启动器：`python main.py`

真正的应用入口是 [`src/musicdownload/main.py`](src/musicdownload/main.py)。
本文件只负责把 `src/` 加入模块搜索路径，让工程无需安装即可直接运行。
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from musicdownload.main import main  # noqa: E402  （必须在 sys.path 设置之后导入）

if __name__ == "__main__":
    main()
