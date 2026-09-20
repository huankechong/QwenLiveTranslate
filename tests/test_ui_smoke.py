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
        assert win.btn_caption.isChecked() is False
        win._apply_caption_visibility(True)
        assert win.btn_caption.isChecked() is True
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
