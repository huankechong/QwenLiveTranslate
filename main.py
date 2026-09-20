"""主入口：直接启动图形控制台（console.py）。

旧命令行用法已由 UI 取代：
    - 来源/语种/外观 -> 控制台里点选，自动保存 settings.json
    - start.bat 双击即用
"""

from __future__ import annotations

import sys


def main():
    from console import main as run_console
    run_console()


if __name__ == "__main__":
    main()
