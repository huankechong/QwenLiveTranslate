# -*- coding: utf-8 -*-
"""controller 生命周期：启停竞态 / 超时清理 / restart 原子化 / 自动重连。"""
import threading
import time

import controller as CTRL
from conftest import FakeClient  # pytest rootdir 内联 conftest


def _wait(cond, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _patch_engine(monkeypatch, module, cls):
    """把类包装成 build_engine 工厂（Phase 0 起 controller 经工厂取引擎）。"""
    monkeypatch.setattr(module, "build_engine",
                        lambda cfg, cb: cls(*cb[:4], on_disconnect=cb[4]))


class TestLifecycle:
    def test_start_stop_normal(self, fakes):
        c = CTRL.SessionController(on_event=lambda k, p: None)
        assert c.start() is True
        assert c.state == CTRL.ST_RUNNING
        c.stop()
        assert c.state == CTRL.ST_IDLE

    def test_stop_during_connect_kills_session(self, fakes, monkeypatch):
        """审计 A 回归：连接期间点停止，会话不得自己复活。"""
        import controller

        class SlowClient(FakeClient):
            def connect(self, timeout=15.0):
                time.sleep(0.4)
                self.connect_count += 1
                return True

        _patch_engine(monkeypatch, controller, SlowClient)
        c = controller.SessionController(on_event=lambda k, p: None)
        t = threading.Thread(target=c.start, daemon=True)
        t.start()
        time.sleep(0.1)
        c.stop()
        t.join(timeout=3)
        time.sleep(0.2)
        assert c.state == CTRL.ST_IDLE
        assert c._push_thread is None
        assert c._client is None

    def test_connect_timeout_closes_client(self, fakes, monkeypatch):
        """审计 B 回归：超时路径必须关 client（不留幽灵线程）。"""
        import controller

        class NeverReady(FakeClient):
            def connect(self, timeout=15.0):
                self.connect_count += 1
                return False  # 超时

        _patch_engine(monkeypatch, controller, NeverReady)
        c = controller.SessionController(on_event=lambda k, p: None)
        assert c.start() is False
        assert c.state == CTRL.ST_ERROR
        assert c._client is None

    def test_restart_atomic(self, fakes):
        c = CTRL.SessionController(on_event=lambda k, p: None)
        c.start()
        c.restart()
        assert _wait(lambda: c.state == CTRL.ST_RUNNING)
        c.stop()

    def test_restart_from_idle(self, fakes):
        c = CTRL.SessionController(on_event=lambda k, p: None)
        c.restart()
        assert _wait(lambda: c.state == CTRL.ST_RUNNING)
        c.stop()


class TestAutoReconnect:
    def test_reconnect_success(self, fakes, monkeypatch):
        CTRL.SessionController.RECONNECT_BACKOFF = (0.4, 0.6, 0.8)
        events = []
        c = CTRL.SessionController(on_event=lambda k, p: events.append((k, p)))
        assert c.start()
        c._on_unexpected_disconnect(1006, "unit")
        assert _wait(lambda: any(
            k == "status" and "已自动重连" in str(p) for k, p in events))
        assert c.state == CTRL.ST_RUNNING
        clients = fakes[0]
        assert clients[-1].connect_count >= 1
        c.stop()

    def test_user_stop_cancels_reconnect(self, fakes, monkeypatch):
        CTRL.SessionController.RECONNECT_BACKOFF = (0.4, 0.6, 0.8)
        c = CTRL.SessionController(on_event=lambda k, p: None)
        assert c.start()
        c._on_unexpected_disconnect(1006, "unit")
        c.stop()
        time.sleep(1.2)  # 越过第一档退避
        assert c.state == CTRL.ST_IDLE
        assert c._client is None  # 没有自动重连回来

    def test_reconnect_exhausted_to_error(self, fakes, monkeypatch):
        CTRL.SessionController.RECONNECT_BACKOFF = (0.2, 0.3, 0.4)
        events = []

        # 类级计数：controller 重连时会 new 新 client，实例级计数会重置
        counter = {"n": 0}

        class FailAfterFirst(FakeClient):
            def connect(self, timeout=15.0):
                counter["n"] += 1
                return counter["n"] <= 1  # 全局首次成功，之后全失败

        import controller
        from conftest import FakeCapture
        _patch_engine(monkeypatch, controller, FailAfterFirst)
        monkeypatch.setattr(controller, "AudioCapture", FakeCapture)
        c = controller.SessionController(on_event=lambda k, p: events.append((k, p)))
        assert c.start()
        with c._lock:
            c._set_state(CTRL.ST_RUNNING)
        c._on_unexpected_disconnect(1006, "unit")
        assert _wait(lambda: any(
            k == "error" and "自动重连" in str(p) for k, p in events), timeout=8)
        assert c.state == CTRL.ST_ERROR


class TestEngineIoErrorPath:
    def test_capture_error_reports_via_facade_and_exits(self):
        """capture 抛异常：经门面 on_error 上报（不穿透 _client）并退出循环。
        （第 8 轮审计 H1——engine_io 此前零测试覆盖的错误路径）"""
        import threading, time
        from providers.engine_io import engine_push_loop

        reported = []
        class NoClientEngine:
            # 模拟 SeparatedPipeline：没有 _client 属性，只有门面 on_error
            provider_id = "sep"; display_name = "Sep"
            def __init__(self):
                self.session_ready = threading.Event(); self.session_ready.set()
                self.connected = threading.Event(); self.connected.set()
                self.on_error = reported.append
        class BoomCap:
            def read_chunk(self):
                raise OSError("device gone")
        eng = NoClientEngine()
        flag = threading.Event()
        t = threading.Thread(target=engine_push_loop, args=(eng, BoomCap(), flag), daemon=True)
        t.start(); t.join(timeout=3)
        assert not t.is_alive(), "循环必须退出"
        assert reported and "device gone" in reported[0]
        assert any("音频读取失败" in m for m in reported)

    def test_build_engine_failure_lands_error_state(self, monkeypatch):
        """工厂抛异常 → ERROR 态 + error 事件（不崩 start 线程，M1）。"""
        import controller as CTRL
        from controller import SessionController, ST_ERROR
        events = []
        def boom(cfg, cb):
            raise ValueError("bad provider config")
        monkeypatch.setattr(CTRL, "build_engine", boom)
        monkeypatch.setattr(CTRL, "AudioCapture",
                            lambda source="mic", sample_rate=16000: None)
        c = SessionController(on_event=lambda k, p: events.append((k, p)))
        ok = c.start()
        assert ok is False
        assert c.state == ST_ERROR
        assert any(k == "error" and "引擎构建失败" in str(p) for k, p in events)
