# -*- coding: utf-8 -*-
"""UI offscreen 冒烟：控件存在性 / 胶囊样式 / 主题切换 / 穿透 / 显隐。"""


class TestConsoleUI:
    def test_boot_no_crash(self, qapp):
        import console as C
        win = C.Console()
        win.show()
        win.overlay.close()
        win.close()

    def test_slider_pills(self, qapp):
        import console as C
        from PySide6.QtWidgets import QPushButton
        win = C.Console()
        for nm in ("val_font", "val_opacity", "val_hist", "val_sent"):
            w = getattr(win, nm)
            assert isinstance(w, QPushButton) and w.objectName() == "val", nm
        # 宽度滑杆已移除
        assert not hasattr(win, "sld_width")
        win.overlay.close(); win.close()

    def test_toggle_pills(self, qapp):
        import console as C
        win = C.Console()
        for nm in ("btn_caption", "btn_ct", "chk_orig", "chk_lat"):
            assert getattr(win, nm).objectName() == "togglePill", nm
        win.overlay.close(); win.close()

    def test_theme_toggle_roundtrip(self, qapp):
        import console as C
        import settings as st
        before = st.load()["theme"]
        win = C.Console()
        win._toggle_theme()
        win._toggle_theme()
        assert st.load()["theme"] == before
        win.overlay.close(); win.close()

    def test_click_through_flow(self, qapp):
        import console as C
        win = C.Console()
        b = win.overlay._click_through
        win._toggle_ct()
        assert win.overlay._click_through != b
        assert win.btn_ct.isChecked() == win.overlay._click_through
        if win.overlay._click_through:
            win.overlay.toggle_click_through()
        win.overlay.close(); win.close()

    def test_caption_visibility_sync(self, qapp):
        import console as C
        win = C.Console()
        win._apply_caption_visibility(False)
        # 淡出语义：动画进行中仍可见，但按钮态立即同步
        assert win.btn_caption.isChecked() is False
        # 等淡出动画（120ms）完成
        deadline = __import__("time").time() + 1.0
        while win.overlay.isVisible() and __import__("time").time() < deadline:
            qapp.processEvents()
            __import__("time").sleep(0.02)
        assert not win.overlay.isVisible(), "淡出完成后应隐藏"
        win._apply_caption_visibility(True)
        assert win.btn_caption.isChecked() is True
        assert win.overlay.isVisible()
        win.overlay.close(); win.close()

    def test_status_tag_survives_overwrite(self, qapp):
        """穿透中状态更新不丢「👻穿透中」标签（Bug2 回归）。"""
        import console as C
        win = C.Console()
        win.overlay.toggle_click_through()  # 开穿透
        assert "穿透中" in win.overlay.lbl_status.text()
        win.overlay.set_status("已停止")
        assert "穿透中" in win.overlay.lbl_status.text()
        win.overlay.toggle_click_through()
        assert "穿透中" not in win.overlay.lbl_status.text()
        win.overlay.close(); win.close()


class TestRealtimeClient:
    def test_late_message_dropped(self, qapp):
        import json
        import threading
        import realtime_client as RC
        c = RC.LiveTranslateClient.__new__(RC.LiveTranslateClient)
        c.on_error = lambda m: None
        c.on_status = lambda m: None
        c.session_ready = threading.Event()
        c.connected = threading.Event()
        c._closed = threading.Event()
        c._asr_items = {}
        c._resp_text = {}
        c.session_id = None
        c._closed.set()
        c._on_message(None, json.dumps({"type": "session.created", "session": {"id": "G"}}))
        assert c.session_id is None  # 迟到消息被丢弃

    def test_close_guards_unconnected(self, qapp):
        import threading
        import realtime_client as RC
        c = RC.LiveTranslateClient.__new__(RC.LiveTranslateClient)
        c.on_error = lambda m: None
        c.session_ready = threading.Event()
        c.connected = threading.Event()  # 未连接
        c._closed = threading.Event()
        c.ws = None
        before = threading.active_count()
        c.close()
        time = __import__("time"); time.sleep(0.1)
        assert threading.active_count() <= before + 1
        assert c._closed.is_set()


class TestReconnectVisibility:
    def test_reconnect_status_shown_on_overlay(self, qapp):
        """重连进度必须刷到字幕窗状态行（lbl_state 隐藏，overlay 是唯一可见通道）。"""
        import console as C
        win = C.Console()
        win.show()
        win.timer.stop()
        win.lbl_err.setText("旧错误")
        for msg in (
            "连接断开 (code=1006 x)，5s 后自动重连（第 1/3 次）…",
            "已自动重连（第 1 次尝试成功）",
        ):
            win._enqueue("status", msg)
            win._drain()
        assert "自动重连" in win.overlay.lbl_status.text()
        assert win.lbl_err.text() == ""  # 成功后清残留

    def test_ordinary_status_not_on_overlay(self, qapp):
        import console as C
        win = C.Console()
        win.show()
        win.timer.stop()
        win._enqueue("status", "会话已创建 abc123")
        win._drain()
        assert "会话已创建" not in win.overlay.lbl_status.text()
        win.overlay.close(); win.close()


class TestSessionBoundary:
    def test_close_drains_pending_queue(self, qapp):
        """退出时未 drain 的译文终稿不因 shutdown 丢（第五轮 Bug1）。"""
        from PySide6.QtGui import QCloseEvent
        import console as C
        win = C.Console()
        win.show()
        win.timer.stop()
        win._enqueue("translation", ("tail sentence", True))
        win.closeEvent(QCloseEvent())  # 不崩即过（异常会冒泡）

    def test_connecting_clears_pairing_queue(self, qapp):
        """新会话（含重连）开始时清空旧配对队列与延迟计时（第五轮 Bug2）。"""
        import time
        import console as C
        from controller import ST_CONNECTING
        win = C.Console()
        win._pending_srcs.append({"speaker": None, "text": "ghost", "ts": time.time()})
        win._speech_t0 = 1.23
        win._on_state(ST_CONNECTING)
        assert win._pending_srcs == []
        assert win._speech_t0 is None
        win.overlay.close(); win.close()


class TestOverlayAnimations:
    def test_fade_toggle_and_reverse(self, qapp):
        """淡出进行中反向显示：动画被接管，窗口保持可见（防快速切换错乱）。"""
        import overlay as O
        import settings as st
        o = O.CaptionOverlay(st.load())
        o.show()
        o.setWindowOpacity(1.0)
        o.fade_out_and_hide()
        assert o._fade is not None
        o.show_caption()  # 立刻反向
        qapp.processEvents()
        assert o.isVisible()
        o.close()

    def test_stream_prefix_diff_append(self, qapp):
        """delta 快照按前缀 diff 只追加新增尾部；不兼容快照回退整句替换。"""
        import overlay as O
        import settings as st
        o = O.CaptionOverlay(st.load())
        h = lambda s: f"<span style='color:#FFFFFF'>{s}</span>"
        o._stream(o.trn_browser, o._trn_state, h("Hello"), True, "Hello")
        o._stream(o.trn_browser, o._trn_state, h("Hello world"), True)
        o._stream(o.trn_browser, o._trn_state, h("Hello world!"), True)
        assert o._trn_state["html"] == h("Hello world!")
        assert o.trn_browser.toPlainText().strip() == "Hello world!"
        # 不兼容快照（服务器改写前缀）
        o._stream(o.trn_browser, o._trn_state, h("Rewritten"), True)
        assert o.trn_browser.toPlainText().strip() == "Rewritten"
        o.close()

    def test_apply_visibility_debounce(self, qapp):
        """目标态一致时跳过：已显示再点显示不重启动画（幂等防抖）。"""
        import console as C
        win = C.Console()
        win.show()
        win._apply_caption_visibility(True)
        op1 = win.overlay.windowOpacity()
        win._apply_caption_visibility(True)  # 重复触发
        qapp.processEvents()
        assert win.overlay.isVisible()
        assert win.btn_caption.isChecked()
        win.overlay.close(); win.close()


class TestOverlayLayoutNoOverlap:
    def test_small_height_no_overlap(self, qapp):
        """拖小时原文/译文不得重叠：按需削减分配，各保底一行。"""
        import overlay as O
        base = {"font_scale": 1.0, "max_lines": 8, "show_original": True,
                "height": 120, "width": 600, "bg_opacity": 0.9, "display_sentences": 4}
        for h in (None, 200, 120, 90, 60):
            cfg = dict(base, height=h)
            o = O.CaptionOverlay(cfg)
            o.apply_cfg(cfg)
            o.show()
            qapp.processEvents()
            g1, g2 = o.src_browser.geometry(), o.trn_browser.geometry()
            assert not g1.intersects(g2), f"height={h} 重叠"
            assert g2.bottom() <= o.height(), f"height={h} 译文超出窗体"
            # 各自至少一行高
            assert o.src_browser.height() >= 15, f"height={h} 原文过扁"
            assert o.trn_browser.height() >= 15, f"height={h} 译文过扁"
            o.close()

    def test_orig_font_base_15px(self, qapp):
        """原文基准字号 15px（用户反馈 13 偏小）。"""
        import overlay as O
        cfg = {"font_scale": 1.0, "max_lines": 8, "show_original": True,
               "height": None, "width": 600, "bg_opacity": 0.9, "display_sentences": 4}
        o = O.CaptionOverlay(cfg)
        o.apply_cfg(cfg)
        from PySide6.QtGui import QFont
        f = o.src_browser.font()
        f.setPixelSize(15)
        assert o.src_browser.height() >= O._line_h(15), "至少一行高"
        o.close()


class TestSrcSentenceAccumulation:
    def test_source_sentences_accumulate(self, qapp):
        """原文多句必须累积保留（diff 改造回归：新句曾顶掉旧句只剩一行）。
        句终需 finalize_src_utterance 分段，下一句从新段追加。"""
        import overlay as O
        cfg = {"font_scale": 1.0, "max_lines": 12, "show_original": True,
               "height": 256, "width": 677, "bg_opacity": 0.76,
               "display_sentences": 10}
        o = O.CaptionOverlay(cfg)
        o.apply_cfg(cfg)
        o.show()
        qapp.processEvents()
        for deltas in (["第一句 One", "第一句 One 完成"],
                       ["第二句 Two"], ["第三句 Three"]):
            for d in deltas:
                o.set_source(None, d)
            o.finalize_src_utterance()
        txt = o.src_browser.toPlainText()
        for k in ("第一句", "第二句", "第三句"):
            assert k in txt, f"{k} 被顶掉: {txt!r}"
        starts = o.src_browser.property("sent_starts")
        assert len(starts) == 3
        o.close()


class TestTrimFitsViewport:
    def test_wrapped_sentences_trimmed_to_viewport(self, qapp):
        """长句折行超出视口时按显示行裁剪（修复"第二行遮第一行"）；
        单句超视口保底不裁（防字幕清空）。"""
        import overlay as O
        from PySide6.QtGui import QTextCursor
        cfg = {"font_scale": 1.0, "max_lines": 12, "show_original": True,
               "height": None, "width": 677, "bg_opacity": 0.76,
               "display_sentences": 10}
        o = O.CaptionOverlay(cfg)
        o.apply_cfg(cfg)
        o.show()
        qapp.processEvents()
        big = lambda t: " ".join(f"{t}{i}" for i in range(30))
        # 单长句：保底
        o.set_source(None, big("alpha"))
        qapp.processEvents()
        assert len(o.src_browser.property("sent_starts")) == 1
        assert len(o.src_browser.toPlainText()) > 0, "单句被裁光"
        # 第二句：旧句裁掉，新句首行在视口顶
        o.set_source(None, big("beta"))
        qapp.processEvents()
        assert len(o.src_browser.property("sent_starts")) == 1
        cur = o.src_browser.cursorForPosition(
            o.src_browser.viewport().rect().topLeft())
        cur.select(QTextCursor.LineUnderCursor)
        assert cur.selectedText().startswith("beta0"), "新句首行被遮"
        # 短句零误裁
        o.close()
        o2 = O.CaptionOverlay(cfg)
        o2.apply_cfg(cfg)
        o2.show()
        qapp.processEvents()
        for i in range(1, 4):
            o2.set_source(None, f"Short {i}")
            o2.finalize_src_utterance()
        qapp.processEvents()
        assert len(o2.src_browser.property("sent_starts")) == 3
        o2.close()


class TestPhase1Components:
    def test_registry_presets(self):
        """P1：1 integrated + 1 asr + 3 mt（三免费翻译预设）。"""
        import providers.registry as reg
        assert len(reg.iter_by_kind("mt")) == 3
        assert len(reg.iter_by_kind("asr")) == 1
        assert len(reg.iter_by_kind("integrated")) == 1

    def test_translate_error_semantics(self):
        """错误分类：可重试（timeout/network/429/5xx）vs 永久（401/402/4xx）。"""
        from providers.mt.errors import TranslateError, from_http_status
        assert TranslateError("timeout", "x").retryable
        assert from_http_status(429).retryable
        assert from_http_status(500).retryable
        assert not from_http_status(401).retryable
        assert not from_http_status(402).retryable
        assert "key" in from_http_status(401).user_message()

    def test_vad_segmentation(self):
        """VAD：学习期后语音+静音切句；高噪冷启动不误报；超长强切。"""
        import array
        import math
        from providers.vad import VadSegmenter
        tone = array.array(
            "h", [int(8000 * math.sin(i * 0.05)) for i in range(1600)]
        ).tobytes()
        silence = b"\x00" * 3200
        # 场景1：静音环境冷启动 → 语音 → 静音 → 一句
        segs, started = [], []
        v = VadSegmenter(lambda: started.append(1), segs.append)
        for _ in range(10):
            v.feed(silence)          # 学习期（静音，噪底校准到低位）
        for _ in range(3):
            v.feed(tone)
        for _ in range(5):
            v.feed(silence)
        assert len(segs) == 1 and started
        # 场景2（R13-M2）：高噪冷启动——学习期不误报
        started2 = []
        v2 = VadSegmenter(lambda: started2.append(1), lambda p: None)
        for _ in range(12):
            v2.feed(tone)            # 学习期+之后全是"高噪"
        assert len(started2) == 0    # 噪底已拉高 → 不再当语音
        # 场景3：超长强切（max_ms=1500；学习期帧也计入 max 计数前先静音学完）
        segs3 = []
        v3 = VadSegmenter(lambda: None, segs3.append, max_ms=1500)
        for _ in range(10):
            v3.feed(silence)         # 学习期
        for _ in range(25):
            v3.feed(tone)
        assert len(segs3) >= 1

    def test_worker_retry_and_permanent(self):
        """worker：直通成功 / 401 立即放弃上报 / stop 幂等。"""
        import time
        from providers.translation_worker import TranslationWorker
        from providers.mt.errors import TranslateError

        outs, errs = [], []

        class FakeTr:
            def __init__(self, err=None):
                self.err = err
                self.calls = 0

            def translate(self, text, s, t, is_stale=None):
                self.calls += 1
                if self.err:
                    raise self.err
                return f"T:{text}"

        tr = FakeTr()
        w = TranslationWorker(tr, lambda t, f: outs.append(t), errs.append)
        w.start()
        w.submit("hi")
        time.sleep(0.4)
        w.stop()
        assert outs == ["T:hi"]
        # 401 永久失败
        tr2 = FakeTr(TranslateError("auth", "bad", 401))
        outs.clear()
        w2 = TranslationWorker(tr2, lambda t, f: outs.append(t), errs.append)
        w2.start()
        w2.submit("x")
        time.sleep(0.4)
        w2.stop()
        assert outs == [] and len(errs) == 1 and tr2.calls == 1

    def test_pipeline_event_flow(self):
        """SeparatedPipeline：ASR 终稿直通 UI + 经 worker 出译文。"""
        import threading
        import time
        from providers.base import AudioSpec
        from providers.pipeline import SeparatedPipeline

        events = []

        class FakeAsr:
            provider_id = "a"
            display_name = "FA"
            audio_spec = AudioSpec(16000)

            def __init__(self):
                self.connected = threading.Event()
                self.session_ready = threading.Event()
                self.on_source = None

            def connect(self, timeout=15):
                self.connected.set()
                self.session_ready.set()
                return True

            def push_audio(self, pcm):
                pass

            def close(self):
                pass

        class FakeMt:
            model = "FM"

            def translate(self, text, s, t, is_stale=None):
                return f"译:{text}"

        cb = (lambda sp, t, f: events.append(("src", t)),
              lambda t, f: events.append(("trn", t)),
              lambda m: events.append(("st", m)),
              lambda m: events.append(("err", m)),
              lambda c, m: events.append(("disc", c)))
        fa = FakeAsr()
        pipe = SeparatedPipeline(fa, FakeMt(), cb)
        assert pipe.connect()
        fa.on_source(None, "hello world", True)
        time.sleep(0.6)
        pipe.close()
        assert ("src", "hello world") in events
        assert any(k == "trn" and v == "译:hello world" for k, v in events)

    def test_engine_card_ui(self, qapp):
        """控制台引擎卡片：模式下拉切换可见性、registry 填充。"""
        import console as C
        win = C.Console()
        win.show()
        qapp.processEvents()
        # 默认一体化：ASR/MT 行隐藏
        assert not win.cmb_asr.isVisible()
        # 切分离式
        win.cmb_engine_mode.setCurrentIndex(1)
        qapp.processEvents()
        assert win.cmb_asr.isVisible() and win.cmb_mt.isVisible()
        assert win.cmb_asr.count() >= 1 and win.cmb_mt.count() >= 3
        import settings as st
        assert st.load().get("engine_mode") == "separated"
        # 还原默认（一体化）
        win.cmb_engine_mode.setCurrentIndex(0)
        qapp.processEvents()
        assert st.load().get("engine_mode") == "integrated"
        win.close()


class TestPhase15:
    def test_engine_key_editing_persists(self, qapp, tmp_path):
        """P1.5b：引擎 Key 输入框写入选中预设的档（ASR+MT 同存）。"""
        import settings as st
        st.SETTINGS_PATH = tmp_path / "settings.json"
        import console as C
        win = C.Console()
        win.show()
        qapp.processEvents()
        win.cmb_engine_mode.setCurrentIndex(1)
        qapp.processEvents()
        assert win.edit_ekey.isVisible()
        win.edit_ekey.setText("sk-test-per-engine")
        win._on_engine_key_edited()
        pc = st.load().get("provider_configs") or {}
        assert pc["siliconflow_sensevoice"][0]["api_key"] == "sk-test-per-engine"
        assert pc["siliconflow_chat"][0]["api_key"] == "sk-test-per-engine"
        assert pc["siliconflow_sensevoice"][0]["model"] == "FunAudioLLM/SenseVoiceSmall"
        # 档 key 优先于顶层
        from providers import _resolve
        assert _resolve({"api_key": "sk-top"}, "siliconflow_sensevoice")["api_key"] \
            == "sk-test-per-engine"
        win.close()

    def test_test_connection_facade(self):
        """P1.5a：一体化引擎的 test_connection 真探活（假 key → 401）。"""
        from providers import build_engine
        eng = build_engine({"engine_mode": "integrated", "api_key": "sk-fake"},
                           (lambda *a: None,) * 5)
        ok, msg = eng.test_connection()
        assert not ok  # 假 key 必须被服务端拒绝（真连网验证，非仅存在性检查）
        eng2 = build_engine({"engine_mode": "integrated", "api_key": ""},
                            (lambda *a: None,) * 5)
        ok2, msg2 = eng2.test_connection()
        assert not ok2 and "未配置" in msg2


class TestR12Fixes:
    def test_key_no_cross_vendor_leak(self, qapp, tmp_path):
        """R12-H1：跨厂商组合时 key 不串档（硅基 key 不进智谱档）。"""
        import settings as st
        st.SETTINGS_PATH = tmp_path / "settings.json"
        import console as C
        win = C.Console()
        win.show()
        qapp.processEvents()
        win.cmb_engine_mode.setCurrentIndex(1)
        qapp.processEvents()
        i = win.cmb_mt.findData("bigmodel_glm4flash")
        win.cmb_mt.setCurrentIndex(i)
        qapp.processEvents()
        win.edit_ekey.setText("sk-sf-only")
        win._on_engine_key_edited()
        pc = st.load().get("provider_configs") or {}
        # 跨厂商：GLM 档完全不被创建（比空 key 更干净）
        assert "bigmodel_glm4flash" not in pc
        assert pc["siliconflow_sensevoice"][0]["api_key"] == "sk-sf-only"
        # 同厂商仍同步
        j = win.cmb_mt.findData("siliconflow_chat")
        win.cmb_mt.setCurrentIndex(j)
        qapp.processEvents()
        win.edit_ekey.setText("sk-sf-both")
        win._on_engine_key_edited()
        pc = st.load().get("provider_configs") or {}
        assert pc["siliconflow_sensevoice"][0]["api_key"] == "sk-sf-both"
        assert pc["siliconflow_chat"][0]["api_key"] == "sk-sf-both"
        win.close()

    def test_non_json_response_classified_permanent(self):
        """R12-H2：非 JSON 响应 → permanent（不误当 network 重试）。"""
        import io
        from unittest import mock
        import providers.mt.openai_compat as OC
        from providers.mt.openai_compat import OpenAICompatTranslator
        from providers.mt.errors import TranslateError

        class FakeResp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        t = OpenAICompatTranslator("sk-x", "m")
        with mock.patch.object(OC.urllib.request, "urlopen",
                               return_value=FakeResp(b"<html>err</html>")):
            try:
                t.translate("hi", "en", "zh")
                raise AssertionError("should raise")
            except TranslateError as e:
                assert e.kind == "permanent" and not e.retryable

    def test_vad_odd_byte_frame(self):
        """R12-M1：奇数字节帧不抛 ValueError。"""
        from providers.vad import VadSegmenter
        v = VadSegmenter(lambda: None, lambda p: None)
        v.feed(b"\x01\x02\x03")  # 1.5 样本
        v.feed(b"\x01")          # 单字节


class TestVocabularyP2:
    def test_extract_and_store(self, tmp_path):
        """P2：分词/停用词/去重 + 新词入库 + 重复计次。"""
        import vocabulary as V
        s = V.VocabStore(tmp_path / "v.db")
        c = V.VocabStore.extract_candidates(
            "The quick brown fox jumps really quickly!")
        assert "quick" in c and "the" not in c and "really" not in c
        assert len(set(c)) == len(c)
        new1 = s.record_sentence("The algorithm sorts the array", "算法排序")
        new2 = s.record_sentence("The algorithm runs fast", "算法运行")
        assert "algorithm" in new1 and "algorithm" not in new2
        hits = {r["word"]: r["hits"] for r in s.top()}
        assert hits["algorithm"] == 2
        assert s.count() >= 4
        s.close()

    def test_anki_tsv_export(self, tmp_path):
        """P2：TSV 三列（word/context/translation），Tab 分隔。"""
        import vocabulary as V
        s = V.VocabStore(tmp_path / "v.db")
        s.record_sentence("binary search tree", "二叉查找树")
        s.record_sentence("recursion depth", "递归深度")
        out = tmp_path / "anki.txt"
        n = s.export_anki_tsv(out)
        lines = out.read_text(encoding="utf-8").strip().splitlines()
        assert n == len(lines) >= 3
        assert all(ln.count("\t") == 2 for ln in lines)
        s.close()

    def test_vocab_view_ui(self, qapp, tmp_path, monkeypatch):
        """P2：生词窗浏览/搜索（经 store 单例）。"""
        import vocabulary as V
        s = V.VocabStore(tmp_path / "v.db")
        s.record_sentence("pointer arithmetic", "指针运算")
        monkeypatch.setattr(V, "_STORE", s)
        from vocab_view import VocabView
        w = VocabView()
        w.show()
        qapp.processEvents()
        assert w.table.rowCount() >= 2
        w.edit_search.setText("pointer")
        w._do_search()
        qapp.processEvents()
        assert w.table.rowCount() == 1
        w.close()
        s.close()
