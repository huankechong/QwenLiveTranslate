"""生词本浏览窗：查词 / 搜索 / 删除 / 高频排序 / Anki 导出。

布局仿 history_view（同款表格交互），数据来自 vocabulary.store()。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import theme
import vocabulary as vocab


def _vocab_dir() -> Path:
    return vocab.db_path().parent


class VocabView(QWidget):
    def __init__(self):
        super().__init__()  # 无 parent：独立顶级窗口（修复：带 parent 会被渲染成
        # 嵌入主窗的子控件——没有标题栏/关闭按钮，用户无法关闭）
        self.setWindowTitle("生词本 · Qwen LiveTranslate")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)  # 与历史窗同款置顶
        self.resize(720, 480)
        tk = theme.get("dark")
        self.setStyleSheet(theme.history_qss(tk))  # 复用历史窗表格样式
        self._mode = "recent"  # recent | top | search

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # 搜索行
        row_search = QHBoxLayout()
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("搜索单词…（回车）")
        self.edit_search.returnPressed.connect(self._do_search)
        btn_search = QPushButton("搜索")
        btn_search.clicked.connect(self._do_search)
        btn_recent = QPushButton("最近")
        btn_recent.clicked.connect(lambda: self._load("recent"))
        btn_top = QPushButton("高频")
        btn_top.clicked.connect(lambda: self._load("top"))
        row_search.addWidget(self.edit_search, 1)
        row_search.addWidget(btn_search)
        row_search.addWidget(btn_recent)
        row_search.addWidget(btn_top)
        root.addLayout(row_search)

        self.lbl_count = QLabel("")
        root.addWidget(self.lbl_count)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["单词", "释义/句译", "出处句", "次数", "首次遇到"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        row_ctl = QHBoxLayout()
        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(self._delete_selected)
        btn_anki = QPushButton("导出 Anki TSV")
        btn_anki.clicked.connect(self._export_anki)
        row_ctl.addWidget(btn_del)
        row_ctl.addWidget(btn_anki)
        row_ctl.addStretch(1)
        root.addLayout(row_ctl)

        self._load("recent")

    # ---------- 数据 ----------
    def _load(self, mode: str, q: str = ""):
        self._mode = mode
        s = vocab.store()
        if mode == "top":
            rows = s.top(limit=500)
        elif mode == "search" and q:
            rows = s.search(q)
        else:
            rows = s.recent(limit=500)
        self.table.setRowCount(0)
        for r in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            self.table.setItem(i, 0, QTableWidgetItem(r["word"]))
            self.table.setItem(i, 1, QTableWidgetItem(r.get("translation") or ""))
            self.table.setItem(i, 2, QTableWidgetItem(r.get("context") or ""))
            hits = QTableWidgetItem(str(r.get("hits", 1)))
            hits.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 3, hits)
            ts = r.get("first_ts")
            self.table.setItem(
                i, 4, QTableWidgetItem(
                    datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else ""))
        self.table.setColumnHidden(2, mode == "search")  # 搜索时句列更紧凑可选显示
        total = s.count()
        self.lbl_count.setText(f"{total} 词 · 显示 {len(rows)} 条"
                               + ("（按高频排序）" if mode == "top" else ""))

    def _do_search(self):
        q = self.edit_search.text().strip()
        if q:
            self._load("search", q)

    def _delete_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()},
                      reverse=True)
        if not rows:
            return
        if QMessageBox.question(
                self, "删除", f"删除选中的 {len(rows)} 个词？") != QMessageBox.Yes:
            return
        s = vocab.store()
        for r in rows:
            wid_item = self.table.item(r, 0)
            if wid_item is None:
                continue
            # 用 word 定位（id 未入表）
            for rec in s.search(wid_item.text()):
                if rec["word"] == wid_item.text().lower():
                    s.delete(rec["id"])
                    break
        self._load(self._mode)

    def _export_anki(self):
        s = vocab.store()
        if s.count() == 0:
            QMessageBox.information(self, "导出", "生词本为空，先跑一会同传再导出")
            return
        default = _vocab_dir() / (
            "vocabulary_" + datetime.now().strftime("%Y%m%d_%H%M") + ".txt")
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 Anki TSV", str(default), "Anki TSV (*.txt)")
        if not path:
            return
        try:
            n = s.export_anki_tsv(path)
            QMessageBox.information(
                self, "导出完成",
                f"已导出 {n} 词 → {path}\n\nAnki 导入：File → Import，"
                f"选择 Basic (and reversed card) 牌组，字段分隔符选 Tab。")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(e))
