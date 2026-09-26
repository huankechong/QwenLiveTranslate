"""主入口：直接启动图形控制台（console.py）。

旧命令行用法已由 UI 取代：
    - 来源/语种/外观 -> 控制台里点选，自动保存 settings.json
    - start.bat 双击即用

全局异常兜底（第 11 轮审计 H1）：exe 模式下未捕获异常原本直接退进程，
用户只看到"窗口消失"零提示零诊断。现在：
  1. 堆栈写入 exe 旁 crash.log（带时间戳，方便 issue 附上）
  2. 弹窗展示错误摘要（用户至少知道发生了什么）
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path


def _crash_log_path() -> Path:
    """crash.log 跟随 settings 的目录策略（含只读回退，与 M1 同策略）。"""
    try:
        from settings import _base_dir
        return _base_dir() / "crash.log"
    except Exception:  # noqa: BLE001 — 崩溃路径必须最稳
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent / "crash.log"
        return Path(__file__).parent / "crash.log"


def _fatal(exc: BaseException) -> None:
    """未捕获异常的最终处理：落盘 + 弹窗（弹窗失败则退化为控制台输出）。"""
    log = _crash_log_path()
    try:
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
    except Exception:  # noqa: BLE001 — 崩溃处理器自身绝不能再抛
        pass
    msg = (f"发生未处理的错误，程序即将退出。\n\n{type(exc).__name__}: {exc}"
           f"\n\n详细信息已写入：{log}")
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "Qwen LiveTranslate — 错误", msg)
    except Exception:  # noqa: BLE001
        print(msg, file=sys.stderr)


def main():
    from console import main as run_console
    try:
        run_console()
    except SystemExit:
        raise  # 正常退出码透传
    except BaseException as exc:  # noqa: BLE001 — 兜底必须最宽
        _fatal(exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
