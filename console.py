"""图形控制台：来源/语种选择、启停控制、外观实时调节、key 状态提示。

main.py 现在直接启动本控制台；字幕窗由本窗管理。
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSlider, QVBoxLayout, QWidget,
)

import settings as st
import config
import history
import theme
from controller import (
    ST_IDLE, ST_CONNECTING, ST_ERROR, ST_RUNNING, ST_STOPPING, SessionController,
)
from overlay import CaptionOverlay

SPEECH_STARTED_MARK = "🎤 检测到语音"
SPEECH_STOPPED_MARK = "… 静音，翻译中"   # 断句判定：真实翻译延迟的计时起点


class _HotkeyRelay(QObject):
    """keyboard 库回调线程 → Qt 主线程的信号中继（GUI 线程安全）。"""
    toggle_ct = Signal()
    switch_source = Signal()
    clear_captions = Signal()
    toggle_caption = Signal()


def _btn(text, checkable=False):
    b = QPushButton(text)
    b.setCheckable(checkable)
    b.setCursor(Qt.PointingHandCursor)
    return b


def _lbl(text, w=72):
    """字段标签：只读按钮实现（QLabel 的 QSS 背景不裁圆角），
    圆角胶囊底 + 居中；禁用交互但不用 disabled 态（会换灰样式）。"""
    from PySide6.QtWidgets import QPushButton
    b = QPushButton(text)
    b.setObjectName("fieldLabel")
    b.setFixedWidth(w)
    b.setCursor(Qt.ArrowCursor)
    b.setFocusPolicy(Qt.NoFocus)
    b.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # 鼠标完全穿透
    return b


def _val_lbl():
    """数值标签（滑杆右侧）：同 _lbl 病根——QLabel 背景不裁圆角且被全局
    QWidget 背景渲染成直角色块，改只读按钮胶囊。固定 48px 右对齐数值。"""
    from PySide6.QtWidgets import QPushButton
    b = QPushButton("")
    b.setObjectName("val")
    b.setFixedWidth(48)
    b.setCursor(Qt.ArrowCursor)
    b.setFocusPolicy(Qt.NoFocus)
    b.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    return b


class Console(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg = st.load()
        self.events: queue.Queue = queue.Queue()
        self.ctrl = SessionController(on_event=self._enqueue)
        # 上次重连时刻（perf_counter）；-inf 保证首次调用不被误节流
        # （perf_counter 原点接近 0 的系统上，0.0 初值会误拦第一次重连）
        self._restart_gate_ms = float("-inf")
        self._restart_pending = False        # 节流窗内已有排队重连
        # 历史入库 + 延迟计时状态
        self._hist_store = history.get_store()
        # 原文配对队列（FIFO）：按到达顺序与译文终稿配对，防乱序错配；
        # 超过 30s 未消费或积压超 3 条视为陈旧，宁缺勿错
        self._pending_srcs: list[dict] = []
        self._speech_t0: float | None = None  # 本句 speech_started 时间戳
        self._latency_ms: int | None = None

        self.overlay = CaptionOverlay(self.cfg)
        self.overlay.show()

        self.init_ui()
        self.apply_ui_from_cfg()
        self._apply_theme()
        self.refresh_key_status()

        # 事件泵：controller 线程 -> Qt 主线程
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._drain)
        self.timer.start(80)

        self._register_hotkeys()

    # ================= UI =================
    def _apply_theme(self):
        """按当前 cfg.theme 应用整套 QSS（切换主题即调此方法）。"""
        self.tk = theme.get(self.cfg.get("theme", "dark"))
        self.setStyleSheet(theme.console_qss(self.tk))
        # 语义色相关的独立控件同步
        self.lbl_key.setStyleSheet(
            f"color:{self._key_color()}; font-size:11px; font-weight:600;")
        self.lbl_err.setStyleSheet(
            f"color:{self.tk['bad']}; font-size:11px;")
        self.btn_theme.setToolTip(
            "切换浅色主题" if self.tk["name"] == "dark" else "切换深色主题")
        # 几何太阳/月亮图标（随主题切换 & 换色）
        try:
            from PySide6.QtGui import QIcon
            self._icons_theme = theme.sun_moon_icons(self.tk)
            # 暗色主题显示"太阳"（点了去亮）；亮色显示"月亮"
            self.btn_theme.setIcon(QIcon(self._icons_theme[
                "sun" if self.tk["name"] == "dark" else "moon"]))
            self.btn_theme.setIconSize(QSize(18, 18))
        except Exception:  # noqa: BLE001
            pass
        # 系统标题栏/边框随主题暗色化（Windows DWM，仅 Windows 生效）
        self._apply_titlebar_theme()
        # 眼睛图标随主题换色（fg_dim 不同）
        try:
            import theme as _th
            from PySide6.QtGui import QIcon
            self._icon_eye = _th.eye_icons(self.tk)
            self.btn_key_eye.setIcon(QIcon(self._icon_eye["closed"]))
        except Exception:  # noqa: BLE001
            pass

    def _key_color(self) -> str:
        saved = (self.cfg.get("api_key") or "").strip()
        env = os.environ.get(config.API_KEY_ENV, "").strip()
        return self.tk["ok"] if (saved or env) else self.tk["bad"]

    def _apply_titlebar_theme(self):
        """Windows DWM 标题栏/边框暗色化，与主题联动。

        DWMWA_USE_IMMERSIVE_DARK_MODE=20（Win10 1809+；旧系统回退 19），
        非 Windows 平台静默跳过。历史窗（若开着）同步处理。
        """
        if sys.platform != "win32":
            return
        import ctypes
        dark = self.tk["name"] == "dark"
        for hwnd in (int(self.winId()), ):
            for attr in (20, 19):  # 新版属性号优先，失败回退旧版
                r = ctypes.c_int(1 if dark else 0)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attr, ctypes.byref(r), 4) == 0:
                    break
        # 历史窗若开着，跟随（winId() 调用会强制 native，安全）
        try:
            import history_view
            if history_view._WIN is not None:
                hwnd = int(history_view._WIN.winId())
                for attr in (20, 19):
                    r = ctypes.c_int(1 if dark else 0)
                    if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attr, ctypes.byref(r), 4) == 0:
                        break
        except Exception:  # noqa: BLE001
            pass

    def _toggle_theme(self):
        new = "light" if self.cfg.get("theme", "dark") == "dark" else "dark"
        self.cfg["theme"] = new
        st.update(theme=new)
        self._apply_theme()
        # 历史窗若开着，跟随重刷
        try:
            import history_view
            if history_view._WIN is not None:
                history_view._WIN.retheme()
        except Exception:  # noqa: BLE001
            pass

    def init_ui(self):
        self.setWindowTitle(f"Qwen LiveTranslate v{config.__version__} · 同传字幕")
        self.setFixedWidth(436)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # ---- 标题 + 主题切换 + key 状态 ----
        top = QHBoxLayout()
        top.setSpacing(8)
        # 真居中：左右对称 stretch 包夹标题（label 自身 AlignCenter 不伸展无效）
        top.addStretch(1)
        title = QLabel("实时同传字幕")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        top.addWidget(title)
        top.addStretch(1)
        # 主题切换：几何太阳/月亮 PNG（emoji 14px 下塌成彩点，弃用）
        self.btn_theme = _btn("")
        self.btn_theme.setFocusPolicy(Qt.NoFocus)  # 全态无边框：不参与键盘焦点
        self.btn_theme.setObjectName("icon")
        self.btn_theme.setFixedSize(32, 32)
        self.btn_theme.setCursor(Qt.PointingHandCursor)
        self.btn_theme.clicked.connect(self._toggle_theme)
        top.addWidget(self.btn_theme)
        self.lbl_key = QLabel("●")
        self.lbl_key.setStyleSheet("font-size:11px;")
        top.addWidget(self.lbl_key)
        root.addLayout(top)

        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(12)

        # ---- 来源 ----
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        lab1 = _lbl("声音来源")
        self.btn_mic = _btn("麦克风", checkable=True)
        self.btn_loop = _btn("系统声音", checkable=True)
        grp = QButtonGroup(self)
        grp.addButton(self.btn_mic)
        grp.addButton(self.btn_loop)
        self.btn_mic.toggled.connect(lambda _c: self._on_source_changed())
        self.btn_loop.toggled.connect(lambda _c: self._on_source_changed())
        row1.addWidget(lab1)
        row1.addWidget(self.btn_mic, 1)
        row1.addWidget(self.btn_loop, 1)
        cl.addLayout(row1)

        # ---- 源语言 → 目标语言 ----
        row_lang = QHBoxLayout()
        row_lang.setSpacing(8)
        lab_s = _lbl("源语言")
        self.cmb_source_lang = QComboBox()
        for code, name in st.SOURCE_LANGUAGES.items():
            self.cmb_source_lang.addItem(f"{name}", code)
        self.cmb_source_lang.currentIndexChanged.connect(self._on_source_lang_changed)
        lab_t = _lbl("目标", w=48)
        self.cmb_lang = QComboBox()
        for code, name in st.LANGUAGES.items():
            self.cmb_lang.addItem(f"{name} ({code})", code)
        self.cmb_lang.currentIndexChanged.connect(self._on_lang_changed)
        row_lang.addWidget(lab_s)
        row_lang.addWidget(self.cmb_source_lang, 1)
        row_lang.addWidget(lab_t)
        row_lang.addWidget(self.cmb_lang, 1)
        cl.addLayout(row_lang)

        # ---- 启停 + 清空 + 历史 ----
        row_ctl = QHBoxLayout()
        row_ctl.setSpacing(8)
        self.btn_start = _btn("开始同传")
        self.btn_start.setObjectName("primary")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self._on_start_stop)
        self.btn_clear = _btn("清空")
        self.btn_clear.setToolTip("清空悬浮窗当前与历史字幕（快捷键 Ctrl+Alt+Backspace）")
        self.btn_clear.clicked.connect(self._clear_captions)
        self.btn_hist = _btn("历史")
        self.btn_hist.setToolTip("查看/导出翻译历史（SQLite 落库）")
        self.btn_hist.clicked.connect(self._open_history)
        self.btn_vocab = _btn("生词")
        self.btn_vocab.setToolTip("生词本：句终自动采集，支持 Anki 导出")
        self.btn_vocab.clicked.connect(self._open_vocab)
        row_ctl.addWidget(self.btn_start, 3)
        row_ctl.addWidget(self.btn_clear, 1)
        row_ctl.addWidget(self.btn_hist, 1)
        row_ctl.addWidget(self.btn_vocab, 1)
        cl.addLayout(row_ctl)

        # ---- 状态（领导要求整行不显示：隐藏控件，保留引用防十余处 setText 报错）----
        self.lbl_state = QLabel("")
        self.lbl_state.setObjectName("dim")
        self.lbl_state.setWordWrap(True)
        self.lbl_state.hide()
        cl.addWidget(self.lbl_state)

        root.addWidget(card)

        # ---- 翻译引擎（Phase 1：一体化/分离式切换 + ASR/MT 选配）----
        card_e = QFrame()
        card_e.setObjectName("card")
        ce = QVBoxLayout(card_e)
        ce.setContentsMargins(16, 12, 16, 12)
        ce.setSpacing(8)
        ce.addWidget(_lbl("翻译引擎"))

        row_mode = QHBoxLayout()
        row_mode.setSpacing(8)
        row_mode.addWidget(_lbl("模式"))
        self.cmb_engine_mode = QComboBox()
        self.cmb_engine_mode.addItem("Qwen 一体化（推荐）", "integrated")
        self.cmb_engine_mode.addItem("分离式组合（ASR+翻译）", "separated")
        self.cmb_engine_mode.currentIndexChanged.connect(self._on_engine_mode)
        row_mode.addWidget(self.cmb_engine_mode, 1)
        ce.addLayout(row_mode)

        row_asr = QHBoxLayout()
        row_asr.setSpacing(8)
        self.lab_asr = _lbl("识别")
        self.cmb_asr = QComboBox()
        row_asr.addWidget(self.lab_asr)
        row_asr.addWidget(self.cmb_asr, 1)
        ce.addLayout(row_asr)

        row_mt = QHBoxLayout()
        row_mt.setSpacing(8)
        self.lab_mt = _lbl("翻译")
        self.cmb_mt = QComboBox()
        row_mt.addWidget(self.lab_mt)
        row_mt.addWidget(self.cmb_mt, 1)
        ce.addLayout(row_mt)

        # 引擎 Key（写入当前选中预设的配置档；分离式时显示）
        row_ekey = QHBoxLayout()
        row_ekey.setSpacing(8)
        self.lab_ekey = _lbl("引擎 Key")
        self.edit_ekey = QLineEdit()
        self.edit_ekey.setEchoMode(QLineEdit.Password)
        self.edit_ekey.setPlaceholderText("留空则沿用上方通用 API Key / 环境变量")
        self.edit_ekey.editingFinished.connect(self._on_engine_key_edited)
        row_ekey.addWidget(self.lab_ekey)
        row_ekey.addWidget(self.edit_ekey, 1)
        ce.addLayout(row_ekey)

        self.btn_engine_test = _btn("测试连接")
        self.btn_engine_test.clicked.connect(self._on_engine_test)
        ce.addWidget(self.btn_engine_test)
        root.addWidget(card_e)
        self._init_engine_card()

        # ---- API Key ----
        card_k = QFrame()
        card_k.setObjectName("card")
        ck = QVBoxLayout(card_k)
        ck.setContentsMargins(16, 12, 16, 12)
        ck.setSpacing(8)
        row_k = QHBoxLayout()
        row_k.setSpacing(8)
        lab_k = _lbl("API Key")
        self.edit_key = QLineEdit()
        self.edit_key.setEchoMode(QLineEdit.Password)
        self.edit_key.editingFinished.connect(self._on_key_edited)
        self.btn_key_eye = _btn("👁")
        self.btn_key_eye.setObjectName("icon")
        self.btn_key_eye.setFixedSize(32, 32)
        self.btn_key_eye.setCheckable(True)
        self.btn_key_eye.setFocusPolicy(Qt.NoFocus)
        self.btn_key_eye.toggled.connect(self._toggle_key_visible)
        # 极简几何眼（QPainter 画的两态 PNG，抽象不吓人）
        from PySide6.QtGui import QIcon, QPixmap
        from PySide6.QtCore import QSize
        import theme as _th
        tk = _th.get(self.cfg.get("theme", "dark"))
        self._icon_eye = _th.eye_icons(tk)
        self.btn_key_eye.setIcon(QIcon(self._icon_eye["open"]))
        self.btn_key_eye.setIconSize(QSize(18, 12))
        self.btn_key_eye.setText("")
        self.btn_key_save = _btn("保存")
        self.btn_key_save.clicked.connect(self._on_key_edited)
        row_k.addWidget(lab_k)
        row_k.addWidget(self.edit_key, 1)
        row_k.addWidget(self.btn_key_eye)
        row_k.addWidget(self.btn_key_save)
        ck.addLayout(row_k)
        self.lbl_key_hint = QLabel(" ")
        self.lbl_key_hint.setObjectName("keyHint")
        self.lbl_key_hint.setAlignment(Qt.AlignCenter)
        ck.addWidget(self.lbl_key_hint)
        root.addWidget(card_k)

        # ---- 外观 ----
        card2 = QFrame()
        card2.setObjectName("card")
        c2 = QVBoxLayout(card2)
        c2.setContentsMargins(16, 12, 16, 12)
        c2.setSpacing(12)

        def labeled_slider(text, lo, hi, scale=100):
            row = QHBoxLayout()
            row.setSpacing(8)
            # 标签保持 fieldLabel 胶囊（勿改 objectName，否则掉出胶囊样式）
            lab = _lbl(text)
            sld = QSlider(Qt.Horizontal)
            sld.setRange(lo * scale, hi * scale)
            val = _val_lbl()  # 只读按钮胶囊（QLabel 直角色块病根）
            row.addWidget(lab)
            row.addWidget(sld, 1)
            row.addWidget(val)
            return sld, val, row

        self.sld_font, self.val_font, r = labeled_slider("字号", 0.7, 2.0)
        self.sld_font.valueChanged.connect(
            lambda v: self._on_slider("font_scale", v / 100, self.val_font, "{:.1f}x"))
        c2.addLayout(r)

        self.sld_opacity, self.val_opacity, r = labeled_slider("不透明度", 0.4, 1.0)
        self.sld_opacity.valueChanged.connect(
            lambda v: self._on_slider("bg_opacity", v / 100, self.val_opacity, "{:.0%}"))
        c2.addLayout(r)

        # 字幕宽度滑杆已移除（2026-09-20）：宽度走更直观的路径——
        # 拖字幕条左右边缘缩放（overlay 边缘热区 + _persist_geometry 持久化）

        self.sld_hist, self.val_hist, r = labeled_slider("最大行数", 4, 12, scale=1)
        self.sld_hist.valueChanged.connect(
            lambda v: self._on_slider("max_lines", int(v), self.val_hist, "{}"))
        c2.addLayout(r)

        self.sld_sent, self.val_sent, r = labeled_slider("保留句数", 1, 10, scale=1)
        self.sld_sent.setToolTip("连成整段后原文/译文各自保留的句数（超出删最旧）")
        self.sld_sent.valueChanged.connect(
            lambda v: self._on_slider("display_sentences", int(v), self.val_sent, "{}"))
        c2.addLayout(r)

        # 切换胶囊（原复选框）：圆角胶囊底，选中态着色（QCheckBox 背景不裁角故弃用）
        self.chk_orig = _btn("显示原文", checkable=True)
        self.chk_orig.setObjectName("togglePill")
        self.chk_orig.setCursor(Qt.PointingHandCursor)
        self.chk_orig.setToolTip("悬浮字幕上半部分显示识别原文")
        self.chk_lat = _btn("显示延迟", checkable=True)
        self.chk_lat.setObjectName("togglePill")
        self.chk_lat.setCursor(Qt.PointingHandCursor)
        self.chk_lat.setToolTip("字幕窗显示翻译延迟：说完话（静音断句）→ 译文完成")
        self.chk_orig.toggled.connect(lambda v: self._on_check("show_original", v))
        self.chk_lat.toggled.connect(lambda v: self._on_check("show_latency", v))

        row3 = QHBoxLayout()
        row3.setSpacing(8)
        row3.addWidget(self.chk_orig)
        row3.addWidget(self.chk_lat)
        row3.addStretch(1)
        c2.addLayout(row3)

        row4 = QHBoxLayout()
        row4.setSpacing(8)
        self.btn_caption = _btn("显示字幕", checkable=True)
        self.btn_caption.setObjectName("togglePill")
        self.btn_caption.setToolTip("显示/隐藏悬浮字幕条（最小化后从这里唤回；快捷键 Ctrl+Alt+B）")
        self.btn_caption.clicked.connect(self._toggle_caption)
        self.btn_ct = _btn("点击穿透", checkable=True)
        self.btn_ct.setObjectName("togglePill")
        self.btn_ct.setToolTip(f"快捷键 {config.HOTKEY_TOGGLE_CLICKTHROUGH}")
        self.btn_ct.clicked.connect(self._toggle_ct)
        row4.addWidget(self.btn_caption)
        row4.addWidget(self.btn_ct)
        row4.addStretch(1)
        c2.addLayout(row4)

        root.addWidget(card2)

        # ---- 错误 ----
        self.lbl_err = QLabel("")
        self.lbl_err.setObjectName("dim")
        self.lbl_err.setWordWrap(True)
        root.addWidget(self.lbl_err)

        root.addStretch(1)

    # ================= 初始化辅助 =================
    # ---------- 翻译引擎卡片（Phase 1）----------
    def _init_engine_card(self):
        """按 registry 填充 ASR/MT 下拉并回显当前配置。"""
        import providers.registry as reg
        self.cmb_asr.blockSignals(True)
        self.cmb_mt.blockSignals(True)
        self.cmb_asr.clear()
        self.cmb_mt.clear()
        for spec in reg.iter_by_kind("asr"):
            self.cmb_asr.addItem(spec.display_name, spec.id)
        for spec in reg.iter_by_kind("mt"):
            self.cmb_mt.addItem(spec.display_name, spec.id)
        # 回显
        mode = self.cfg.get("engine_mode", "integrated")
        self.cmb_engine_mode.setCurrentIndex(1 if mode == "separated" else 0)
        asr_pid = self.cfg.get("asr_provider") or "siliconflow_sensevoice"
        mt_pid = self.cfg.get("mt_provider") or "siliconflow_chat"
        i = self.cmb_asr.findData(asr_pid)
        if i >= 0:
            self.cmb_asr.setCurrentIndex(i)
        j = self.cmb_mt.findData(mt_pid)
        if j >= 0:
            self.cmb_mt.setCurrentIndex(j)
        self.cmb_asr.currentIndexChanged.connect(self._on_engine_pick)
        self.cmb_mt.currentIndexChanged.connect(self._on_engine_pick)
        self.cmb_asr.blockSignals(False)
        self.cmb_mt.blockSignals(False)
        self._sync_engine_visibility()

    def _sync_engine_visibility(self):
        """分离式才显示 ASR/MT/Key 行；一体化折叠。"""
        sep = self.cmb_engine_mode.currentData() == "separated"
        for w in (self.lab_asr, self.cmb_asr, self.lab_mt, self.cmb_mt,
                  self.lab_ekey, self.edit_ekey):
            w.setVisible(sep)
        if sep:
            self._refresh_engine_key()

    def _engine_key_profiles(self, pid: str | None = None) -> list:
        """取/建设置里某引擎的配置档列表（P1.5b：引擎卡片独立 key）。"""
        pid = pid or (self.cmb_asr.currentData() if self.cmb_asr.count() else "")
        if not pid:
            return []
        cfgs = self.cfg.get("provider_configs") or {}
        profs = cfgs.get(pid)
        if not isinstance(profs, list) or not profs:
            profs = [{}]
            cfgs[pid] = profs
            self.cfg["provider_configs"] = cfgs
        return profs

    def _refresh_engine_key(self):
        """把 ASR 预设档里存的 key 回显到输入框（仅显示，不落盘）。"""
        profs = self._engine_key_profiles()
        self.edit_ekey.setText((profs[0].get("api_key") or "") if profs else "")

    def _on_engine_key_edited(self):
        """编辑完成：key 只写入与 ASR 预设【同厂商域】的档。

        R12-H1：旧版无条件写 ASR+MT 双档——跨厂商组合（ASR=硅基 +
        MT=智谱）时硅基 key 被写进智谱档 → 测试连接必 401。
        现按 spec.defaults.base_url 的域分组：ASR 档恒写，MT 档仅
        同域才同步（跨厂商的 MT key 需在其档内另行填写——留空回退
        通用 key/env 的语义不变）。"""
        import providers.registry as reg
        text = self.edit_ekey.text().strip()
        asr_pid = self.cmb_asr.currentData() or ""
        mt_pid = self.cmb_mt.currentData() or ""

        def _domain(pid):
            spec = reg.get(pid) if pid else None
            url = (spec.defaults or {}).get("base_url", "") if spec else ""
            return url.split("//")[-1].split("/")[0].lower()

        targets = [asr_pid] if asr_pid else []
        if mt_pid and mt_pid != asr_pid and _domain(mt_pid) == _domain(asr_pid):
            targets.append(mt_pid)

        data = st.load()
        cfgs = data.get("provider_configs") or {}
        for pid in targets:
            profs = cfgs.get(pid)
            if not isinstance(profs, list) or not profs:
                profs = [{}]
            spec = reg.get(pid) if pid else None
            profs[0]["api_key"] = text
            if spec:
                for k, v in (spec.defaults or {}).items():
                    profs[0].setdefault(k, v)
            cfgs[pid] = profs
        data["provider_configs"] = cfgs
        st.update(**data)
        self._restart_if_running()

    def _on_engine_mode(self):
        mode = self.cmb_engine_mode.currentData()
        self.cfg["engine_mode"] = mode
        st.update(engine_mode=mode)
        self._sync_engine_visibility()
        self._restart_if_running()

    def _on_engine_pick(self):
        asr_pid = self.cmb_asr.currentData() or ""
        mt_pid = self.cmb_mt.currentData() or ""
        self.cfg["asr_provider"] = asr_pid
        self.cfg["mt_provider"] = mt_pid
        st.update(asr_provider=asr_pid, mt_provider=mt_pid)
        self._restart_if_running()

    def _on_engine_test(self):
        """后台线程测试当前引擎连通性（结果经 Qt Signal 回主线程显示）。

        R15 修复：原实现在线程里调 QTimer.singleShot——Qt 禁止跨线程
        操作 timer（静默丢弃回调）→ 用户点按钮"无反应"。Signal 的
        emit 跨线程安全，槽在主线程执行。"""
        cfg = dict(self.cfg)
        self.btn_engine_test.setEnabled(False)
        self.btn_engine_test.setText("测试中…")

        class _Relay(QObject):
            done = Signal(bool, str)

        relay = _Relay()
        relay.done.connect(self._show_engine_test_result)

        def _test():
            try:
                from providers import build_engine
                cb = (lambda *a: None,) * 4 + (lambda *a: None,)
                eng = build_engine(cfg, cb)
                ok, text = eng.test_connection()  # 门面方法（P1.5a）
            except Exception as e:  # noqa: BLE001
                ok, text = False, f"测试失败: {e}"
            relay.done.emit(ok, text)  # Signal emit 跨线程安全

        threading.Thread(target=_test, daemon=True).start()

    def _show_engine_test_result(self, ok: bool, text: str):
        """测试结果落 UI（主线程槽函数）。"""
        self.btn_engine_test.setEnabled(True)
        self.btn_engine_test.setText("测试连接")
        self.lbl_err.setText(("✅ " if ok else "⚠️ ") + text)
        self.lbl_err.setStyleSheet(
            f"color:{'#22a06b' if ok else '#e5484d'};"
            " font-size:11px; font-weight:600;")
        # 用户反馈：点击测试连接后 key 框被"选中"——链路是 editingFinished
        # → refresh_key_status 的 setText 在 Password 框上重置了光标/选区。
        # 测试流程结束即主动清除选区并归还焦点给按钮，保持视觉干净。
        self.edit_key.deselect()
        self.btn_engine_test.clearFocus()

    def refresh_key_status(self):
        """key 状态灯：settings 里的 key 优先，否则看环境变量。"""
        saved = self.cfg.get("api_key", "").strip()
        env = os.environ.get(config.API_KEY_ENV, "").strip()
        if saved:
            self.lbl_key.setText("● Key 已保存（本地 settings.json）")
        elif env:
            self.lbl_key.setText("● Key 用环境变量")
        else:
            self.lbl_key.setText("● 未配置 Key")
        self.lbl_key.setStyleSheet(
            f"color:{self._key_color()}; font-size:11px; font-weight:600;")
        # key 输入框回显（脱敏显示）——仅当值真变化时 setText：
        # 无差别重置会让 Password 框光标/选区跳变（用户反馈的"被选中"观感）
        if self.edit_key.text() != saved:
            self.edit_key.setText(saved)
        self.lbl_key_hint.setText(
            "保存后立即生效；留空则回退环境变量。key 仅存本机 settings.json。"
        )

    def apply_ui_from_cfg(self):
        """把 settings 回填到控件。

        必须屏蔽控件信号：否则 setCurrentIndex/setValue 会触发
        _on_lang_changed 等处理器——初始化期多余写 settings.json，
        更会把重启节流门 _restart_gate_ms 污染成真实时间戳，
        导致首次合法重连被误节流 3s（offscreen 回归测试抓到）。
        """
        from PySide6.QtCore import QSignalBlocker
        widgets = (
            self.btn_mic, self.btn_loop,
            self.cmb_source_lang, self.cmb_lang,
            self.sld_font, self.sld_opacity,
            self.sld_hist, self.sld_sent,
            self.chk_orig, self.chk_lat,
        )
        blockers = [QSignalBlocker(w) for w in widgets]  # noqa: F841
        self.btn_mic.setChecked(self.cfg["source"] == "mic")
        self.btn_loop.setChecked(self.cfg["source"] == "loopback")
        idx = list(st.SOURCE_LANGUAGES.keys()).index(self.cfg.get("source_lang", "auto")) \
            if self.cfg.get("source_lang", "auto") in st.SOURCE_LANGUAGES else 0
        self.cmb_source_lang.setCurrentIndex(idx)
        idx = list(st.LANGUAGES.keys()).index(self.cfg["lang"]) \
            if self.cfg["lang"] in st.LANGUAGES else 0
        self.cmb_lang.setCurrentIndex(idx)
        self.sld_font.setValue(int(self.cfg["font_scale"] * 100))
        self.sld_opacity.setValue(int(self.cfg["bg_opacity"] * 100))
        self.sld_hist.setValue(int(self.cfg.get("max_lines", 8)))
        self.sld_sent.setValue(int(self.cfg.get("display_sentences", 4)))
        self.chk_orig.setChecked(bool(self.cfg["show_original"]))
        self.chk_lat.setChecked(bool(self.cfg.get("show_latency", False)))
        self.btn_caption.setChecked(self.overlay.isVisible())
        del blockers  # 解除信号屏蔽（del 触发 QSignalBlocker 析构 = unblock）
        # 信号被屏蔽期间 valueChanged 不会触发 → 数值标签必须主动回填
        self.val_font.setText(f"{self.cfg['font_scale']:.1f}x")
        self.val_opacity.setText(f"{self.cfg['bg_opacity']:.0%}")
        self.val_hist.setText(f"{int(self.cfg.get('max_lines', 8))}")
        self.val_sent.setText(f"{int(self.cfg.get('display_sentences', 4))}")

    # ================= 事件泵 =================
    def _enqueue(self, kind, payload):
        self.events.put((kind, payload))

    def _drain(self):
        drained = 0
        while drained < 50:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            drained += 1
            if kind == "state":
                self._on_state(payload)
            elif kind == "status":
                # VAD 状态（检测到语音/静音翻译中）只用于内部分句与计时，不显示
                if payload not in (SPEECH_STARTED_MARK, SPEECH_STOPPED_MARK):
                    self.lbl_state.setText(payload)
                    # 连接生命周期消息（断开/重连中/已重连）同步刷字幕窗底部
                    # 状态行——lbl_state 被隐藏，重连等待期（最长约110s）用户
                    # 需在字幕条上看到进度，否则"死了还是在恢复"无从判断
                    s = str(payload)
                    if any(k in s for k in ("断开", "重连")):
                        self.overlay.set_status(s)
                        if "已自动重连" in s or "就绪" in s:
                            self.lbl_err.setText("")  # 成功后清残留错误
                if payload == SPEECH_STARTED_MARK:
                    self.overlay.begin_utterance()
                elif payload == SPEECH_STOPPED_MARK:
                    # 延迟计时起点（A 口径）：静音断句 → 翻译完成，
                    # 不含说话时长，与 LiveCaptionsTranslator 同口径
                    if self._speech_t0 is None:
                        self._speech_t0 = time.perf_counter()
            elif kind == "source":
                speaker, text, final = payload
                self.overlay.set_source(speaker, text)
                if final and text:
                    # 原文句终：复位段落状态，让下一个 item 的 delta 从
                    # 新段追加而非替换本句（diff 改造前旧实现靠"整段重写"
                    # 碰巧保留了旧句；diff 后必须显式分句，否则新句顶掉旧句
                    # ——只保留一句的回归即此因）
                    self.overlay.finalize_src_utterance()
                    self._pending_srcs.append(
                        {"speaker": speaker, "text": text, "ts": time.time()})
            elif kind == "translation":
                text, final = payload
                self.overlay.set_translation(text)
                if final and text:
                    self.overlay.finalize_utterance()
                    self._on_sentence_done(text)
            elif kind == "error":
                self.lbl_err.setText(str(payload)[:300])
        # 字幕可见性对齐（字幕窗 —/✕ 或热键路径改动后，按钮态跟随）
        if self.btn_caption.isChecked() != self.overlay.isVisible():
            self.btn_caption.blockSignals(True)
            self.btn_caption.setChecked(self.overlay.isVisible())
            self.btn_caption.blockSignals(False)

    def _pop_paired_src(self) -> dict:
        """取与本次译文终稿配对的原文（FIFO + 30s 新鲜度过滤，宁缺勿错配）。"""
        now = time.time()
        # 丢弃陈旧积压（>30s 未消费的原文，其译文大概率已丢失）
        self._pending_srcs = [p for p in self._pending_srcs
                              if now - p["ts"] <= 30.0]
        if not self._pending_srcs:
            return {}
        return self._pending_srcs.pop(0)

    def _on_sentence_done(self, translation_text: str):
        """一句译文终稿：算延迟 + 配对原文 + 入库 + 刷新角标。"""
        # 延迟 = 静音断句(speech_stopped) -> 译文终稿（A 口径，不含说话时长）
        if self._speech_t0 is not None:
            self._latency_ms = int((time.perf_counter() - self._speech_t0) * 1000)
            self._speech_t0 = None
        else:
            self._latency_ms = None
        self.overlay.set_latency(self._latency_ms)
        # 入库（原文 FIFO 配对；乱序/缺失时宁可留空也不错配）
        try:
            src = self._pop_paired_src()
            self._hist_store.add(
                source_lang=self.cfg.get("source_lang", "auto"),
                target_lang=self.cfg.get("lang", ""),
                speaker=src.get("speaker"),
                original=src.get("text", ""),
                translation=translation_text,
                latency_ms=self._latency_ms,
            )
            # 生词本采集（P2：句终自动入生词库，失败不影响主流程）
            try:
                import vocabulary as vocab
                vocab.store().record_sentence(
                    src.get("text", ""), translation_text,
                    source=self.cfg.get("source", ""))
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass

    def _on_state(self, s):
        m = {
            ST_IDLE: ("开始同传", False),
            ST_CONNECTING: ("连接中…", True),
            ST_RUNNING: ("停止", False),
            ST_STOPPING: ("停止中…", True),
            ST_ERROR: ("开始同传", False),
        }
        if s == ST_CONNECTING:
            # 新会话建立（含重连）：旧会话的待配对原文与新译文会错配
            # 入库（重连窗口 5-65s < 30s 新鲜度窗口，过滤拦不住）——
            # 连接开始即清空配对队列与延迟计时（第五轮审计 Bug2）
            self._pending_srcs.clear()
            self._speech_t0 = None
        if s in m:
            text, disabled = m[s]
            self.btn_start.setText(text)
            self.btn_start.setDisabled(disabled)
            if s != ST_ERROR:
                self.lbl_err.setText("")

    # ================= 交互 =================
    def _restart_if_running(self):
        """带 3 秒节流的重连（限流 RPM 10：连续改设置会撞限额 → 服务端 400）。"""
        now = time.perf_counter()
        if now - self._restart_gate_ms < 3.0:
            self.lbl_state.setText("设置已改（限流缓冲 3s 内合并重连）…")
            if self._restart_pending:
                return
            self._restart_pending = True

            def _do_restart():
                self._restart_pending = False
                if self.ctrl.running or self.ctrl.state == ST_CONNECTING:
                    self.ctrl.restart()
            QTimer.singleShot(3200, _do_restart)
            return
        self._restart_gate_ms = now
        if self.ctrl.running or self.ctrl.state == ST_CONNECTING:
            self.lbl_state.setText("设置已改，重连会话…（限流 RPM 10，稍候）")
            self.ctrl.restart()

    def _on_source_changed(self):
        new = "mic" if self.btn_mic.isChecked() else "loopback"
        if new == self.cfg["source"]:
            return
        self.cfg["source"] = new
        st.update(source=new)
        self._restart_if_running()

    def _on_source_lang_changed(self, _idx):
        new = self.cmb_source_lang.currentData()
        if new == self.cfg.get("source_lang", "auto"):
            return
        self.cfg["source_lang"] = new
        st.update(source_lang=new)
        self._restart_if_running()

    def _on_lang_changed(self, _idx):
        self.cfg["lang"] = self.cmb_lang.currentData()
        st.update(lang=self.cfg["lang"])
        self._restart_if_running()

    # ---------- key ----------
    def _on_key_edited(self):
        text = self.edit_key.text().strip()
        self.cfg["api_key"] = text
        st.update(api_key=text)
        self.refresh_key_status()

    def _toggle_key_visible(self, shown):
        self.edit_key.setEchoMode(QLineEdit.Normal if shown else QLineEdit.Password)
        # 极简几何眼两态切换：显示态睁眼、隐藏态闭眼（一条弧线）
        try:
            from PySide6.QtGui import QIcon
            self.btn_key_eye.setIcon(
                QIcon(self._icon_eye["open" if shown else "closed"]))
        except Exception:  # noqa: BLE001
            pass

    # ---------- 清空字幕 ----------
    def _clear_captions(self):
        self.overlay.clear_all()
        self.lbl_state.setText("字幕已清空")

    # ---------- 历史窗口 ----------
    def _open_vocab(self):
        """打开生词本窗口（浏览/搜索/删除/Anki 导出）。

        独立顶级窗口（无 parent）——带 parent 会嵌入主窗无法关闭。
        单例：已开则聚焦，避免多窗并存（R14-L1）。"""
        try:
            if getattr(self, "_vocab_win", None) is not None \
                    and self._vocab_win.isVisible():
                self._vocab_win.raise_()
                self._vocab_win.activateWindow()
                return
            from vocab_view import VocabView
            # 旧实例已关但引用还在：先清再建
            self._vocab_win = VocabView()
            self._vocab_win.show()
        except Exception as e:  # noqa: BLE001
            self.lbl_err.setText(f"生词本打开失败: {e}")

    def _open_history(self):
        try:
            import history_view
            history_view.open_window()
        except Exception as e:  # noqa: BLE001
            self.lbl_err.setText(f"历史窗口打开失败: {e}")

    # ---------- 显示/隐藏字幕 ----------
    def _toggle_caption_visible(self):
        """热键路径（Ctrl+Alt+B）：切换并同步按钮态。"""
        self._apply_caption_visibility(self.overlay.caption_hidden)

    def _toggle_caption(self, _checked=False):
        """按钮路径：按钮 checked 态已由 Qt 翻转，这里按目标态执行。
        checked=True -> 显示；False -> 隐藏。"""
        self._apply_caption_visibility(self.btn_caption.isChecked())

    def _apply_caption_visibility(self, show: bool):
        """目标态与当前动画目标一致时跳过——快速连按/热键+按钮双路径
        并发时防抖（淡出进行中再点显示会取消动画恢复，反之亦然；
        一致则零开销）。"""
        if show:
            if self.overlay.isVisible() and self.overlay.windowOpacity() > 0.5:
                return  # 已显示（或淡入中），不重启动画
            self.overlay.show_caption()
            self.lbl_state.setText("字幕已显示")
        else:
            if not self.overlay.isVisible():
                return  # 已隐藏
            self.overlay.fade_out_and_hide()
            self.lbl_state.setText("字幕已隐藏（Ctrl+Alt+B 或「显示字幕」按钮再显示）")
        # 双路径同步按钮态（blockSignals 防回环）
        self.btn_caption.blockSignals(True)
        self.btn_caption.setChecked(show)
        self.btn_caption.blockSignals(False)

    def _on_slider(self, key, value, val_lbl, fmt):
        val_lbl.setText(fmt.format(value))
        self.cfg[key] = value
        st.update(**{key: value})
        self.overlay.apply_cfg(self.cfg)

    def _on_check(self, key, value):
        self.cfg[key] = value
        st.update(**{key: value})
        self.overlay.apply_cfg(self.cfg)

    def _toggle_ct(self):
        on = self.overlay.toggle_click_through()
        self.btn_ct.setChecked(on)

    def _on_start_stop(self):
        if self.ctrl.running or self.ctrl.state == ST_CONNECTING:
            self.ctrl.stop()
            self.overlay.set_status("已停止")
        else:
            self.lbl_err.setText("")
            self.overlay.clear_all()
            self.ctrl.start()

    # ================= 热键 =================
    def _register_hotkeys(self):
        try:
            import keyboard
            # 跨线程中继：keyboard 回调线程只 emit 信号 -> Qt 主线程执行动作
            # （回调线程直接碰 GUI 控件是未定义行为，间歇崩溃根源）
            self._hotkey_relay = _HotkeyRelay()
            self._hotkey_relay.toggle_ct.connect(self._toggle_ct)
            self._hotkey_relay.switch_source.connect(self._hotkey_switch_source)
            self._hotkey_relay.clear_captions.connect(self._clear_captions)
            self._hotkey_relay.toggle_caption.connect(self._toggle_caption_visible)
            keyboard.add_hotkey(config.HOTKEY_TOGGLE_CLICKTHROUGH,
                                self._hotkey_relay.toggle_ct.emit)
            keyboard.add_hotkey(config.HOTKEY_SWITCH_SOURCE,
                                self._hotkey_relay.switch_source.emit)
            keyboard.add_hotkey(config.HOTKEY_CLEAR_CAPTIONS,
                                self._hotkey_relay.clear_captions.emit)
            keyboard.add_hotkey(config.HOTKEY_TOGGLE_CAPTION,
                                self._hotkey_relay.toggle_caption.emit)
        except Exception as e:  # noqa: BLE001
            # 不再全静默：无管理员权限等场景热键注册会失败，用户需要
            # 知道热键不可用（否则以为快捷键坏了到处找），控制台按钮仍可用
            self.lbl_err.setText(f"全局热键不可用（权限不足？按钮仍可正常用）: {e}"[:200])

    def _hotkey_switch_source(self):
        new = "loopback" if self.cfg["source"] == "mic" else "mic"
        self.cfg["source"] = new
        st.update(source=new)
        self.btn_mic.setChecked(new == "mic")
        self.btn_loop.setChecked(new == "loopback")
        self._restart_if_running()

    # ================= 退出 =================
    def closeEvent(self, e):
        self.ctrl.stop()
        # 先停事件泵再最后 drain 一次：关闭时队列里可能有迟到的译文终稿，
        # 不 drain 直接 shutdown 会静默丢最后一句入库（第五轮审计 Bug1）
        self.timer.stop()
        try:
            self._drain()
        except Exception:  # noqa: BLE001
            pass
        self.overlay.close()
        # 历史窗若开着：同步关闭（否则 app 因它存活变僵尸，且 store 已关会崩）
        try:
            import history_view
            if history_view._WIN is not None:
                history_view._WIN.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            history.shutdown()
        except Exception:  # noqa: BLE001
            pass
        # 生词窗同样处理（R14-M1：对照历史窗模式，否则孤儿窗口+连接不关）
        try:
            if getattr(self, "_vocab_win", None) is not None:
                self._vocab_win.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            import vocabulary
            vocabulary.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    # 应用图标（任务栏/标题栏）：teal→sky 渐变「译」
    try:
        import os as _os
        from PySide6.QtGui import QIcon
        _ico = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "app.ico")
        if not _os.path.exists(_ico):  # PyInstaller onefile 解包目录
            _ico = _os.path.join(sys._MEIPASS, "app.ico")  # type: ignore[attr-defined]
        app.setWindowIcon(QIcon(_ico))
    except Exception:  # noqa: BLE001
        pass
    w = Console()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
