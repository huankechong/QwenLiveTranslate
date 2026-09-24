"""悬浮双语字幕窗（连续速录版）。

架构（2026-09-19 定稿，替代逐句 QLabel 堆方案）：
- 原文一个连续块 + 译文一个连续块（QTextBrowser），识别/翻译一句追加一段，
  上下文连续可读；超出固定高度自动滚到最新（滚动条隐藏）
- 窗口与文本块高度恒定（按 max_lines 设置计算）——尺寸永不变化 = 零闪烁
- 流式更新用 QTextCursor 就地替换末段文本，不增删控件 = 零重建
- 文本控件鼠标穿透（WA_TransparentForMouseEvents）→ 整条字幕任意位置可拖动
- 历史与当前句同色同字号（用户要求，无新旧视觉区分）
- 2026-09-19 体验包：display_sentences 段落裁剪（超限删最旧段）；
  窗口位置记忆（拖动松手存 settings）；延迟角标（show_latency）
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes

import theme

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtCore import QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QFontMetrics, QGuiApplication
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

GWL_EX_STYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000

FONT_FAMILY = "Microsoft YaHei UI"

# 边缘缩放热区（px，物理像素；16px 手感宽松，8px 需要太精准）
EDGE_MARGIN = 16
MIN_W, MAX_W_EXTRA = 500, 1600   # 宽度范围（MAX 与屏幕钳制取小）
MIN_H, MAX_H = 90, 1200          # 高度范围

# Windows 原生边缘缩放（WM_NCHITTEST）
WM_NCHITTEST = 0x0084
WM_ENTERSIZEMOVE = 0x0231
WM_EXITSIZEMOVE = 0x0232
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17


def _set_click_through(hwnd: int, enable: bool):
    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EX_STYLE)
    if enable:
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
    else:
        style &= ~WS_EX_TRANSPARENT
        style &= ~WS_EX_NOACTIVATE
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EX_STYLE, style)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _line_h(px: int) -> int:
    f = QFont(FONT_FAMILY)
    f.setPixelSize(px)
    return QFontMetrics(f).height()


class CaptionOverlay(QWidget):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self._fade: QPropertyAnimation | None = None  # 显示/隐藏过渡动画
        self._click_through = False
        self._press_pos = None
        self._geo_save_timer = None
        # 流式状态：每块当前句的起始光标位（None=下一段从新起）
        self._src_state = {"start": None, "speaker": None, "html": ""}
        self._trn_state = {"start": None, "html": ""}
        # 延迟角标（show_latency 开时显示）
        self._latency_ms: int | None = None
        # 状态行基底文本（穿透标签由 _refresh_status 单独叠加）
        self._status_base = " "
        self.init_ui()
        self.apply_cfg(cfg)

    # ---------- UI ----------
    def init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.frame = QFrame()
        self.frame.setObjectName("captionFrame")
        self.frame.setCursor(Qt.SizeAllCursor)
        root.addWidget(self.frame)

        self.lay = QVBoxLayout(self.frame)
        self.lay.setContentsMargins(18, 8, 18, 8)
        self.lay.setSpacing(4)

        # 顶部小行：左侧延迟角标 + 右侧隐藏/关闭按钮
        top = QHBoxLayout()
        self.lbl_latency = QLabel("")
        self.lbl_latency.setStyleSheet(
            f"color:#8B93A8; font-size:10px; font-family:'{FONT_FAMILY}';"
            f" letter-spacing: 0.3px;"
        )
        self.lbl_latency.setVisible(False)
        top.addWidget(self.lbl_latency)
        top.addStretch(1)
        self.btn_min = QPushButton("—")
        self.btn_min.setFixedSize(22, 22)
        self.btn_min.setToolTip("隐藏字幕（会话保持，Ctrl+Alt+B 显示）")
        self.btn_min.clicked.connect(self._on_minimize)
        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.setToolTip("清空并隐藏字幕（会话保持，Ctrl+Alt+B 显示）")
        self.btn_close.clicked.connect(self._on_close_caption)
        for b in (self.btn_min, self.btn_close):
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ border:none; border-radius:{theme.R_INPUT}px;"
                " background:rgba(255,255,255,0.06); color:#9AA1B2; font-size:12px; }"
                "QPushButton:hover { background:rgba(248,113,113,0.85); color:white; }"
            )
        top.addWidget(self.btn_min)
        top.addWidget(self.btn_close)
        self.lay.addLayout(top)

        # 原文连续块
        self.src_browser = self._make_browser()
        self.lay.addWidget(self.src_browser)
        # 译文连续块
        self.trn_browser = self._make_browser()
        self.lay.addWidget(self.trn_browser)

        self.lbl_status = QLabel(" ")
        self.lbl_status.setStyleSheet(
            f"color:#888888; font-size:10px; font-family:'{FONT_FAMILY}';"
        )
        self.lay.addWidget(self.lbl_status)

        screen = self._current_screen_geo()
        w = min(int(self.cfg.get("width", 820)), screen.width() - 80)
        self.resize(w, 200)
        self._restore_or_default_pos(screen)

    def _restore_or_default_pos(self, screen):
        """优先恢复上次位置（含屏幕边界校验），否则默认右下角。"""
        x, y = self.cfg.get("win_x"), self.cfg.get("win_y")
        if x is not None and y is not None:
            if 0 <= x <= screen.right() + 1 - 120 and 0 <= y <= screen.bottom() + 1 - 60:
                self.move(x, y)
                return
        w = self.width()
        self.move(max(0, screen.right() - w - 40), max(0, screen.bottom() - 280))

    def _make_browser(self) -> QTextBrowser:
        b = QTextBrowser()
        b.setFrameShape(QTextBrowser.NoFrame)
        b.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        b.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        b.setReadOnly(True)
        b.setOpenLinks(False)
        b.setUndoRedoEnabled(False)
        b.setTextInteractionFlags(Qt.NoTextInteraction)
        # 鼠标穿透：文字区不抢事件 → 整条字幕可拖动
        b.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        b.viewport().setAttribute(Qt.WA_TransparentForMouseEvents, True)
        b.setStyleSheet("background:transparent; border:none; padding:0; margin:0;")
        return b

    # ---------- 外观/尺寸 ----------
    def apply_cfg(self, cfg: dict):
        self.cfg = cfg
        screen = self._current_screen_geo()
        width = min(int(cfg.get("width", 820)), screen.width() - 80)
        scale = float(cfg.get("font_scale", 1.0))
        opacity = float(cfg.get("bg_opacity", 0.9))
        max_lines = int(cfg.get("max_lines", 8))
        show_orig = bool(cfg.get("show_original", True))

        alpha = int(round(opacity * 255))
        self.frame.setStyleSheet(
            f"#captionFrame {{"
            f" background: rgba(16,18,24,{alpha});"
            f" border-radius: {theme.R_WINDOW}px;"
            f" border: 1px solid rgba(120,128,160,{int(alpha * 0.28)});"
            f"}}"
        )

        fs_orig = max(10, int(15 * scale))   # 原文基准 13→15px（用户反馈偏小）
        fs_trans = max(11, int(17 * scale))
        src_lines = max(2, round(max_lines * 0.4))
        trans_lines = max(2, max_lines - src_lines)
        src_h = src_lines * _line_h(fs_orig) + 4
        trans_h = trans_lines * _line_h(fs_trans) + 4

        status_h = 16
        btn_h = 24
        pads = 8 + 4 + 4 + 8 + 4   # 上下边距+间距
        auto_total = pads + btn_h + status_h + trans_h + (src_h if show_orig else 0)
        # 用户拖出的高度优先（None=自适应）；至少能装下按钮行+状态行。
        # 极端矮窗护栏：用户高度装不下"两块各一行+固定件"时，忽略用户
        # 高度、退回自适应（原文只显示一两句的最终解——窗口太矮是物理
        # 无解，撑到能装下为止）
        min_total = pads + btn_h + status_h + 40
        if show_orig:
            bare_min = (pads + btn_h + status_h
                        + (_line_h(fs_orig) + 4) + (_line_h(fs_trans) + 4))
            min_total = max(min_total, bare_min)
        total = max(min_total, int(cfg["height"])) if cfg.get("height") else auto_total

        # ---------- 文本块高度分配（修复拖小时重叠） ----------
        # 可用空间 = 总高 - 非文本部分。旧代码只处理"拖大给译文"，
        # 拖小时 src/trn 固定高度之和超出可用空间 → 布局压缩重叠。
        # 现按需求分配：富余全给译文；不足时按【需求比例】削减（各保底
        # 2 行）——按需削减会把原文削到 1 行（用户实测"原文只能显示
        # 一两句"），比例削减保住原文的合理占比。
        avail = total - (pads + btn_h + status_h)
        if show_orig:
            floor2_src = 2 * _line_h(fs_orig) + 4   # 目标保底：两行（v1.0.4 反馈）
            floor2_trn = 2 * _line_h(fs_trans) + 4
            floor1_src = _line_h(fs_orig) + 4       # 极端下限：一行
            floor1_trn = _line_h(fs_trans) + 4
            # 保底优先级（空间紧张时逐级退让，译文先让路）：
            # both2 → src2+trn1 → both1（bare_min 护栏保证 both1 恒可达）
            if floor2_src + floor2_trn <= avail:
                h_min_src, h_min_trn = floor2_src, floor2_trn
            elif floor2_src + floor1_trn <= avail:
                h_min_src, h_min_trn = floor2_src, floor1_trn
            else:
                h_min_src, h_min_trn = floor1_src, floor1_trn
            want_src = max(h_min_src, src_h)
            want_trn = max(h_min_trn, trans_h)
            if want_src + want_trn <= avail:
                src_alloc = want_src            # 富余（拖大）：增量全给译文
                trn_alloc = avail - want_src
            else:                               # 不足（拖小）：按需求比例削减
                over = want_src + want_trn - avail
                cut_src = max(h_min_src,
                              want_src - round(over * want_src / (want_src + want_trn)))
                cut_trn = max(h_min_trn,
                              want_trn - round(over * want_trn / (want_src + want_trn)))
                # 比例削完仍超（某块已到保底）：剩余缺口从【另一块】扣，
                # 且被扣块自身不许击穿保底——击穿则本块回吐（宁超不叠）
                rest = cut_src + cut_trn - avail
                while rest > 0:
                    moved = False
                    if cut_src > h_min_src:
                        give = min(rest, cut_src - h_min_src)
                        cut_src -= give; rest -= give; moved = True
                    if cut_trn > h_min_trn:
                        give = min(rest, cut_trn - h_min_trn)
                        cut_trn -= give; rest -= give; moved = True
                    if not moved:
                        break  # 双双保底仍超（极端矮窗）：layout 已尽力，接受
                src_alloc = cut_src
                trn_alloc = cut_trn
            self.src_browser.setFixedHeight(src_alloc)
            self.trn_browser.setFixedHeight(trn_alloc)
        else:
            self.trn_browser.setFixedHeight(max(_line_h(fs_trans) + 4, avail))
        self.src_browser.setVisible(show_orig)
        self.src_browser.setStyleSheet(
            f"background:transparent; border:none; padding:0; margin:0;"
            f" font-family:'{FONT_FAMILY}'; font-size:{fs_orig}px;"
        )
        self.trn_browser.setStyleSheet(
            f"background:transparent; border:none; padding:0; margin:0;"
            f" font-family:'{FONT_FAMILY}'; font-size:{fs_trans}px;"
        )
        self._apply_latency_badge()

        # 不用 setFixed*：钉死尺寸会让 OS 原生边缘缩放（WM_NCHITTEST 路径）被
        # 布局约束弹回。改为 min 限制下限 + max 留足缩放空间。
        self.setMinimumWidth(min(MIN_W, width))
        self.setMinimumHeight(min(MIN_H, total))
        self.setMaximumWidth(min(MAX_W_EXTRA, screen.width()))
        self.setMaximumHeight(MAX_H)
        self.resize(width, total)
        # 钳制到屏幕内；记忆位置由 g.x()/g.y() 保持（只钳制，不重排锚点）
        g = self.geometry()
        self.move(
            max(0, min(g.x(), screen.right() + 1 - width)),
            max(0, min(g.y(), screen.bottom() + 1 - total)),
        )

    # ---------- 句子裁剪（整段化：按 sent_starts 起始位记录删整句） ----------

    def _trim_lines(self, browser: QTextBrowser, limit: int):
        """裁剪：按句数上限删最旧句，且保证剩余内容不超过视口显示行数。

        两层约束（用户实测"第二行遮第一行"修复）：
        ① 句数 ≤ display_sentences；
        ② 文档实际高度 ≤ 视口高度 ×1.05（余量）——句子折行时"2 句"
          可能占 8 显示行而视口只装 4 行，滚到底顶部行必然被滚出，
          必须继续裁最旧句直到整体装得下。
        """
        if limit <= 0:
            return
        doc = browser.document()
        starts = browser.property("sent_starts")
        starts = starts if isinstance(starts, list) else []
        guard = 0
        while len(starts) > 1 and guard < 100:
            guard += 1
            doc_h = doc.size().height()
            vp_h = browser.viewport().height()
            fits = doc_h <= vp_h * 1.05 + 2
            if len(starts) <= limit and fits:
                break
            # 保底：只剩最后一句时不再裁（单句超视口属显示问题，
            # 裁掉=字幕瞬间清空，比滚动更糟；句内滚动可见最新内容）
            # 删最旧一句：从其起点到下一句起点（或文尾）
            cut_from = starts[0]
            cut_to = starts[1] if len(starts) > 1 else doc.characterCount() - 1
            cur = QTextCursor(doc)
            cur.setPosition(min(cut_from, doc.characterCount() - 1))
            cur.setPosition(min(cut_to, doc.characterCount() - 1),
                            QTextCursor.KeepAnchor)
            cur.removeSelectedText()
            removed = cut_to - cut_from
            starts = starts[1:]
            # 剩余句起点统一前移 removed（它们都在 cut_to 之后）；
            # 等值边界（前句起点==被删句终点）也必须前移，否则起点重复；
            # max(0,·) 下界钳制：removed 与 Qt 实删数若有偏差（HTML 实体
            # 折算等）防止负起点导致后续裁剪窗口错位（第五轮审计 Bug3）
            starts = [max(0, s - removed) for s in starts]
            # 当前流式段起点同步修正：只有被删的是历史句（start 恒指向
            # 最后一句=保留窗口内，正常不会命中此分支），仅防御异常顺序
            state = self._src_state if browser is self.src_browser else self._trn_state
            if state["start"] is not None:
                if state["start"] > cut_to:
                    state["start"] -= removed
                elif state["start"] > cut_from:
                    # 起点落在被删区间内：复位，但保留已有文本标记，
                    # 下次 delta 走"从当前句尾继续"而非重开新句重复全文
                    state["start"] = max(0, cut_from)
        browser.setProperty("sent_starts", starts)

    # ---------- 流式写入 ----------
    def _stream(self, browser: QTextBrowser, state: dict, html: str, new_para: bool,
                plain_head: str = ""):
        """增量写入：句子连成整段（智能分隔），流式 delta 就地追加。

        防 flicker 关键：delta 到达时只 append 新增尾部（前缀 diff），
        绝不整段 KeepAnchor 重写——整段重排是高频 delta 下闪烁/
        跳动的根源。state["html"] 缓存本句已写入的 HTML。"""
        doc = browser.document()
        cur = QTextCursor(doc)
        if state["start"] is None:
            cur.movePosition(QTextCursor.End)
            if doc.characterCount() > 1 and new_para:
                # 连成整段：句间智能空格（拉丁字母/数字粘连防护）
                tail = doc.characterAt(doc.characterCount() - 2)
                head_c = plain_head[0] if plain_head else ""
                if (head_c and tail and tail.isascii() and tail.isalnum()
                        and head_c.isascii() and head_c.isalnum()):
                    cur.insertText(" ")
            state["start"] = cur.position()
            # 记录本句起始位（裁剪按此删除整句）
            starts = browser.property("sent_starts")
            starts = starts if isinstance(starts, list) else []
            starts.append(state["start"])
            browser.setProperty("sent_starts", starts)
            state["html"] = ""  # 新句从零累积
        else:
            cur.setPosition(state["start"], QTextCursor.MoveAnchor)
        # 前缀 diff：只写入新增部分（delta 是本句 HTML 的完整快照）
        old_html = state.get("html", "")
        if html.startswith(old_html):
            delta = html[len(old_html):]
            state["html"] = html
            if delta:
                cur.movePosition(QTextCursor.End)
                cur.insertHtml(delta)
        else:
            # 快照不兼容（服务器改写了前缀）：退回整句替换保正确性
            cur.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
            cur.insertHtml(html)
            state["html"] = html
        sb = browser.verticalScrollBar()
        # 滚到底必须在【布局完成后】执行：insertHtml 后立即 setValue(max)
        # 拿到的是旧文档的 max（Qt 排版延迟到事件循环），新句首行会被
        # 滚出视口"遮住"，直到下一条 delta 才跳出来（用户实测报告）。
        # singleShot(0) 把滚动排到本轮事件循环的布局之后。
        def _scroll_bottom():
            sb.setValue(sb.maximum())
        QTimer.singleShot(0, _scroll_bottom)

    def begin_utterance(self):
        """新句开始：两块的下一次写入各起新段。"""
        if self._src_state["start"] is not None or self._trn_state["start"] is not None:
            self._src_state = {"start": None, "speaker": None, "html": ""}
            self._trn_state = {"start": None, "html": ""}

    def set_source(self, speaker, text):
        # 注：qwen3.8 实际不下发说话人字段（speaker 恒 None），
        # 说话人标签功能已于 2026-09-20 移除；参数保留兼容调用方签名
        html = f"<span style='color:#9EC9FF'>{_esc(text)}</span>"
        self._stream(self.src_browser, self._src_state, html, new_para=True,
                     plain_head=text)
        self._trim_lines(self.src_browser, int(self.cfg.get("display_sentences", 4)))

    def set_translation(self, text):
        html = f"<span style='color:#FFFFFF'>{_esc(text)}</span>"
        self._stream(self.trn_browser, self._trn_state, html, new_para=True,
                     plain_head=text)
        self._trim_lines(self.trn_browser, int(self.cfg.get("display_sentences", 4)))

    def finalize_utterance(self):
        # 段内容已就地写入，只需复位段起点（下句起新段）
        self._src_state = {"start": None, "speaker": None, "html": ""}
        self._trn_state = {"start": None, "html": ""}

    def finalize_src_utterance(self):
        """原文句终：只复位原文段状态（译文块独立节奏，互不影响）。"""
        self._src_state = {"start": None, "speaker": None, "html": ""}

    def set_status(self, msg: str):
        # 基底与穿透标签分离：穿透中任何状态更新都不丢「👻穿透中(热键切回)」
        # 提示（原实现直接 setText 会把标签吞掉，用户失去退出指引）
        self._status_base = msg
        self._refresh_status()

    def _refresh_status(self):
        tag = "👻穿透中(热键切回) · " if self._click_through else ""
        self.lbl_status.setText(tag + (self._status_base or " "))

    def clear_all(self):
        self.src_browser.clear()
        self.trn_browser.clear()
        self.src_browser.setProperty("sent_starts", [])
        self.trn_browser.setProperty("sent_starts", [])
        self._src_state = {"start": None, "speaker": None, "html": ""}
        self._trn_state = {"start": None, "html": ""}

    # ---------- 延迟角标 ----------
    def set_latency(self, ms: int | None):
        self._latency_ms = ms
        self._apply_latency_badge()

    def _apply_latency_badge(self):
        on = bool(self.cfg.get("show_latency"))
        self.lbl_latency.setVisible(on)
        if on:
            ms = self._latency_ms
            if ms is None:
                self.lbl_latency.setText("⚡ —")
            elif ms < 1000:
                self.lbl_latency.setText(f"⚡ {ms} ms")
            else:
                self.lbl_latency.setText(f"⚡ {ms / 1000:.1f} s")

    # ---------- Windows 原生边缘缩放 ----------
    def nativeEvent(self, event_type, message):
        """WM_NCHITTEST：把窗口边缘上报为原生缩放边框（OS 接管拖拽）。

        真机可靠方案——此前 Qt 手动 mousePress/Move 分流方案在真实事件
        分发链上被子控件遮挡不可靠（offscreen 直调处理器掩盖了该问题）。

        坐标全程用物理像素（GetWindowRect + lParam 均为物理），
        天然规避高 DPI 下逻辑/物理像素错位的热区偏移。
        """
        if self._click_through:
            return super().nativeEvent(event_type, message)
        try:
            # Qt/Windows 原生事件类型串是大写 MSG（写成小写会静默不匹配）
            if event_type == "windows_generic_MSG":
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_NCHITTEST:
                    rect = ctypes.wintypes.RECT()
                    hwnd = int(self.winId())
                    if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                        sx = ctypes.c_short(msg.lParam & 0xFFFF).value
                        sy = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                        px, py = sx - rect.left, sy - rect.top
                        w, h = rect.right - rect.left, rect.bottom - rect.top
                        m = EDGE_MARGIN
                        near_l = px <= m
                        near_r = px >= w - m
                        near_t = py <= m
                        near_b = py >= h - m
                        if near_r and near_b:
                            return True, HTBOTTOMRIGHT
                        if near_l and near_b:
                            return True, HTBOTTOMLEFT
                        if near_l and near_t:
                            return True, HTTOPLEFT
                        if near_r and near_t:
                            return True, HTTOPRIGHT
                        if near_l:
                            return True, HTLEFT
                        if near_r:
                            return True, HTRIGHT
                        if near_t:
                            return True, HTTOP
                        if near_b:
                            return True, HTBOTTOM
                elif msg.message == WM_EXITSIZEMOVE:
                    # OS 缩放/移动循环结束（鼠标可能已松开，mouseButtons 探测
                    # 不可靠）→ 此刻直接落盘几何
                    self._persist_geometry()
                elif msg.message == WM_ENTERSIZEMOVE:
                    # 进入缩放循环：取消可能在飞的防抖保存（结束时会统一存）
                    if self._geo_save_timer is not None:
                        self._geo_save_timer.stop()
        except Exception:  # noqa: BLE001
            pass
        return super().nativeEvent(event_type, message)


    # ---------- 多屏支持 ----------
    def _current_screen_geo(self):
        """字幕窗所在屏的可用区（多屏正确）；取不到回退主屏。"""
        scr = QGuiApplication.screenAt(self.frameGeometry().center())
        if scr is None:
            scr = QGuiApplication.primaryScreen()
        return scr.availableGeometry()

    def _edge_at(self, pos):
        """返回命中边缘：'left'/'right'/'bottom'/'bottom_left'/'bottom_right'，中央 None。"""
        w, h = self.width(), self.height()
        m = EDGE_MARGIN
        near_l = pos.x() <= m
        near_r = pos.x() >= w - m
        near_b = pos.y() >= h - m
        if near_r and near_b:
            return "bottom_right"
        if near_l and near_b:
            return "bottom_left"
        if near_l:
            return "left"
        if near_r:
            return "right"
        if near_b:
            return "bottom"
        return None

    def event(self, e):
        """Qt 路径（整窗拖动）的几何持久化（防抖 600ms）。

        原生缩放走 WM_EXITSIZEMOVE 直接落盘，不经此路径；
        程序性 resize（启动 apply_cfg/双击恢复）时 mouseButtons 为空，天然不触发。
        """
        if e.type() == QEvent.Resize and self.isVisible():
            if QGuiApplication.mouseButtons() != Qt.NoButton:
                if self._geo_save_timer is None:
                    self._geo_save_timer = QTimer(self)
                    self._geo_save_timer.setSingleShot(True)
                    self._geo_save_timer.timeout.connect(self._persist_geometry)
                self._geo_save_timer.start(600)
        return super().event(e)

    def _persist_geometry(self):
        """把用户缩放/移动后的几何写回 settings（防抖后调用）。

        宽度按 600~1400 钳制（与 settings.DEFAULTS 注释口径一致，
        防极端拖拽把后续 apply_cfg 的 min(1400) 顶死）。"""
        try:
            import settings as st
            w = max(600, min(1400, self.width()))
            h = self.height()
            st.update(width=int(w), height=int(h), win_x=self.x(), win_y=self.y())
            self.cfg["width"] = int(w)
            self.cfg["height"] = int(h)
        except Exception:  # noqa: BLE001
            pass

    def _relayout_browsers(self):
        """窗口高度变化后，把增量分配给译文块（原文块保持行数高度）。

        只处理【拖大】（avail 有富余全给译文）；拖小由 apply_cfg 的
        比例分配负责——这里若抢着 setFixedHeight 会把 apply_cfg 刚算好
        的原文两行保底压回一行（v1.0.4 后续反馈的根因之一）。
        译文保底两行，不足则不动（等下次 apply_cfg）。"""
        pads = 8 + 4 + 4 + 8 + 4
        fixed = pads + 24 + 16  # 按钮+状态行
        src_h = (self.src_browser.height()
                 if self.cfg.get("show_original", True) else 0)
        rest = self.height() - fixed - src_h
        if rest > 2 * _line_h(max(11, int(17 * float(self.cfg.get("font_scale", 1.0))))) + 4:
            self.trn_browser.setFixedHeight(rest)

    def resizeEvent(self, e):
        """OS 原生缩放驱动的高度变化分配给译文块。"""
        super().resizeEvent(e)
        # 延迟到布局稳定后重分配（resize 中 height() 可能是旧值）
        from PySide6.QtCore import QTimer as _QTimer
        _QTimer.singleShot(0, self._relayout_browsers)

    # ---------- 拖动 & 穿透 & 隐藏 ----------
    def mousePressEvent(self, e):
        if self._click_through or e.button() != Qt.LeftButton:
            return
        self._press_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._press_pos is not None and e.buttons() & Qt.LeftButton:
            screen = self._current_screen_geo()
            g = self.frameGeometry()
            target = e.globalPosition().toPoint() - self._press_pos
            x = max(0, min(target.x(), screen.right() + 1 - g.width()))
            y = max(0, min(target.y(), screen.bottom() + 1 - g.height()))
            self.move(x, y)

    def mouseReleaseEvent(self, _e):
        if self._press_pos is not None:
            try:
                import settings as st
                st.update(win_x=self.x(), win_y=self.y())
            except Exception:  # noqa: BLE001
                pass
        self._press_pos = None

    def mouseDoubleClickEvent(self, e):
        """双击非边缘区：高度恢复自适应（清除用户高度）。"""
        if self._edge_at(e.position().toPoint()) is None:
            try:
                import settings as st
                # 先停掉可能在飞的防抖保存，防止旧高度在 600ms 后回写
                if self._geo_save_timer is not None:
                    self._geo_save_timer.stop()
                st.update(height=None)
                self.cfg["height"] = None
                self.apply_cfg(self.cfg)
                self.set_status("高度已恢复自适应")
            except Exception:  # noqa: BLE001
                pass

    def toggle_click_through(self) -> bool:
        self._click_through = not self._click_through
        _set_click_through(int(self.winId()), self._click_through)
        self._refresh_status()
        return self._click_through

    @property
    def click_through(self) -> bool:
        return self._click_through

    def _on_minimize(self):
        self.hide()

    def _on_close_caption(self):
        self.clear_all()
        self.hide()

    def show_caption(self):
        """淡入显示（150ms ease-out）。隐藏动画进行中的反向请求由
        _fade 的 stop 兜底——同属性动画直接 stop 后重设方向即接管。"""
        self._fade_to(1.0)
        self.show()
        self.raise_()

    def fade_out_and_hide(self):
        """淡出隐藏（120ms），完成后才真正 hide()。淡出期间再次 show
        会被 _fade_to 取消动画并恢复——快速来回切换无状态错乱。"""
        self._fade_to(0.0, hide_when_done=True)

    def _fade_to(self, target: float, hide_when_done: bool = False):
        if self._fade is not None:
            self._fade.stop()
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(150 if target > 0 else 120)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(target)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        if hide_when_done:
            self._fade.finished.connect(self.hide)
        self._fade.start(QPropertyAnimation.DeleteWhenStopped)

    @property
    def caption_hidden(self) -> bool:
        return not self.isVisible()
