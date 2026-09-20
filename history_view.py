"""历史记录查看窗口（体验层功能包 2026-09-19）。

- 表格列出最近 500 条：时间 / 语种 / 原文 / 译文 / 延迟（说话人列已移除：qwen3.8 不下发该字段）
- 双击行 = 复制该条译文
- 导出 CSV（默认导出到 exe/脚本同目录 translation_history_YYYYMMDD_HHMM.csv）
- 清空历史（二次确认）

修复记录（2026-09-19 代码审查）：
- 顶层窗口必须持有强引用（模块级 _WIN），否则函数返回后 Python GC 会销毁
  C++ 窗口对象（weakref 实测确认）——show 后闪退的根因
- 定时器回调访问窗口前防御 C++ 对象已销毁（RuntimeError）
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import history
import settings as st
import theme

LANG_NAMES = {"auto": "自动", "de": "德", "en": "英", "zh": "中",
              "ja": "日", "fr": "法", "es": "西", "ru": "俄"}


def _lang(code: str) -> str:
    return LANG_NAMES.get(code or "", code or "?")


class HistoryWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.store = history.get_store()
        self.setWindowTitle("翻译历史 · Qwen LiveTranslate")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.resize(920, 560)
        self.init_ui()
        self.retheme()
        self.refresh()

    def retheme(self):
        """按 settings.theme 应用样式（主题切换时由 console 联动调用）。"""
        tk = theme.get(st.load().get("theme", "dark"))
        self.setStyleSheet(theme.history_qss(tk))

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        top = QHBoxLayout()
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("dim")
        top.addWidget(self.lbl_count)
        top.addStretch(1)
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self.refresh)
        btn_csv = QPushButton("导出 CSV")
        btn_csv.setObjectName("accent")
        btn_csv.clicked.connect(self.export_csv)
        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(self.clear_all)
        for b in (btn_refresh, btn_csv, btn_clear):
            b.setCursor(Qt.PointingHandCursor)
            top.addWidget(b)
        root.addLayout(top)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["时间", "语种", "原文", "译文", "延迟"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignCenter)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.cellDoubleClicked.connect(self._copy_row)
        root.addWidget(self.table, 1)

        hint = QLabel("双击行复制译文 · 共享存储 translation_history.db（与 exe 同目录）")
        hint.setObjectName("dim")
        root.addWidget(hint)

    # ---------- 数据 ----------
    def refresh(self):
        rows = self.store.recent(limit=500)
        # 主题色只读一次（原实现每行读一次 settings.json——500 行=500 次磁盘读）
        from PySide6.QtGui import QColor
        orig_color = QColor(theme.get(st.load().get("theme", "dark"))["fg_dim"])
        self.table.setRowCount(0)
        for r in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            self.table.setItem(i, 0, QTableWidgetItem(
                time.strftime("%m-%d %H:%M:%S", time.localtime(r["ts"]))))
            pair = QTableWidgetItem(f"{_lang(r['source_lang'])}→{_lang(r['target_lang'])}")
            pair.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 1, pair)
            # 说话人列已移除（qwen3.8 不下发该字段，恒空列浪费宽度）
            it_o = QTableWidgetItem(r["original"] or "")
            it_o.setForeground(orig_color)
            self.table.setItem(i, 2, it_o)
            self.table.setItem(i, 3, QTableWidgetItem(r["translation"] or ""))
            lat = "—" if r["latency_ms"] is None else f"{r['latency_ms']}ms"
            it_l = QTableWidgetItem(lat)
            it_l.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 4, it_l)
        total = self.store.count()
        self.lbl_count.setText(f"最近 500 条 / 共 {total} 条")

    def _copy_row(self, row: int, _col: int):
        item = self.table.item(row, 3)  # 译文列（说话人列移除后从 4 前移）
        text = item.text() if item else ""
        if text:
            QApplication.clipboard().setText(text)
            self.setWindowTitle("翻译历史 · 已复制译文 ✔")
            QTimer.singleShot(1200, self._restore_title)

    def _restore_title(self):
        """定时器回调：窗口可能已被用户关闭销毁，访问前必须防御。"""
        try:
            self.setWindowTitle("翻译历史 · Qwen LiveTranslate")
        except RuntimeError:
            pass  # C++ 对象已销毁（WA_DeleteOnClose），无需恢复

    def export_csv(self):
        default = history.db_dir() / time.strftime(
            "translation_history_%Y%m%d_%H%M.csv", time.localtime())
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 CSV", str(default), "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            n = self.store.export_csv(path)
            QMessageBox.information(self, "导出成功", f"已导出 {n} 条到\n{path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(e))

    def clear_all(self):
        ret = QMessageBox.question(
            self, "清空历史", f"确定删除全部 {self.store.count()} 条历史记录？不可恢复。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.store.clear()
            self.refresh()


# ---------- 单例窗口管理（强引用，防 GC） ----------
_WIN: HistoryWindow | None = None


def _on_win_destroyed():
    global _WIN
    _WIN = None


def open_window() -> HistoryWindow:
    """打开（或聚焦已打开的）历史窗口。

    必须由模块级 _WIN 持有强引用：顶层窗口无父对象，函数局部变量被回收后
    PySide6 的 Python 包装器无引用 → GC 连带销毁 C++ 窗口（闪退根因）。
    """
    global _WIN
    if _WIN is not None:
        try:
            _WIN.raise_()
            _WIN.activateWindow()
            _WIN.refresh()
            return _WIN
        except RuntimeError:
            _WIN = None  # 已销毁的残余引用，重建
    w = HistoryWindow()
    w.setAttribute(Qt.WA_DeleteOnClose)
    w.destroyed.connect(_on_win_destroyed)
    _WIN = w
    w.show()
    return w
