# -*- coding: utf-8 -*-
"""共享 fixture：offscreen Qt 环境 + 假 client/capture 工厂。

真实 WS/音频设备在 CI 不可用——生命周期测试全部走桩。
"""
import os
import sys
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeClient:
    """可控假客户端：connect 结果、断线触发均可编程。"""

    def __init__(self, *a, **k):
        self.session_ready = threading.Event()
        self.session_ready.set()
        self.connected = threading.Event()
        self.connected.set()
        self._closed = threading.Event()
        self.ws = None
        self.on_disconnect = k.get("on_disconnect")
        self.connect_results = [True]  # 依次弹出；耗尽用最后一个
        self.close_count = 0
        self.connect_count = 0

    def connect(self, timeout=15.0):
        self.connect_count += 1
        idx = min(self.connect_count - 1, len(self.connect_results) - 1)
        return self.connect_results[idx]

    def close(self):
        self.close_count += 1

    def _send(self, obj):
        pass

    @staticmethod
    def _eid():
        return "e"

    source = "mic"


class FakeCapture:
    def __init__(self, source="mic"):
        self.stopped = 0

    def start(self):
        pass

    def stop(self):
        self.stopped += 1

    def read_chunk(self):
        return b""


@pytest.fixture
def fakes(monkeypatch):
    """打桩 controller 的 client/capture，返回 (clients, captures) 收集器。"""
    import controller as CTRL

    clients, captures = [], []

    def mk_client(*a, **k):
        c = FakeClient(*a, **k)
        clients.append(c)
        return c

    def mk_capture(source="mic"):
        c = FakeCapture(source)
        captures.append(c)
        return c

    monkeypatch.setattr(CTRL, "LiveTranslateClient", mk_client)
    monkeypatch.setattr(CTRL, "AudioCapture", mk_capture)
    return clients, captures
