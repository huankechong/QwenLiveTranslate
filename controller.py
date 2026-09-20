"""会话控制器：管理 采集+WS客户端+推流线程 的完整生命周期，供 UI 调用。

UI 线程 <-> controller 全部经回调/信号交互，不阻塞。
"""

from __future__ import annotations

import os
import threading
import time

import settings as st

from capture import AudioCapture
from realtime_client import LiveTranslateClient, push_audio_forever

# 会话状态
ST_IDLE = "idle"
ST_CONNECTING = "connecting"
ST_RUNNING = "running"
ST_STOPPING = "stopping"
ST_ERROR = "error"


class SessionController:
    def __init__(self, on_event):
        """on_event(kind, payload)：kind in source/translation/status/state/error
        source payload=(speaker,text,final)；translation payload=(text,final)"""
        self.on_event = on_event
        self.state = ST_IDLE
        self._client = None
        self._capture = None
        self._push_thread = None
        self._stop_flag = None
        self._lock = threading.Lock()
        # start 尝试令牌：stop/新 start 递增后，仍在连接中的旧尝试作废
        # （防"停止后会话自己连上"竞态，2026-09-20 审计抓到）
        self._start_token = 0

    # ---------- 内部 ----------
    def _emit(self, kind, payload):
        try:
            self.on_event(kind, payload)
        except Exception:  # noqa: BLE001
            pass

    def _set_state(self, s):
        self.state = s
        self._emit("state", s)

    def _wire_callbacks(self):
        def on_source(sp, text, final):
            self._emit("source", (sp, text, final))

        def on_translation(text, final):
            self._emit("translation", (text, final))

        def on_status(msg):
            self._emit("status", msg)

        def on_error(msg):
            self._emit("error", msg)

        return on_source, on_translation, on_status, on_error

    # ---------- 对外 ----------
    @property
    def running(self) -> bool:
        return self.state == ST_RUNNING

    def start(self) -> bool:
        with self._lock:
            if self.state in (ST_CONNECTING, ST_RUNNING):
                return True
            cfg = st.load()
            source = cfg["source"]
            lang = cfg["lang"]
            src_lang = cfg.get("source_lang", "auto")
            api_key = cfg.get("api_key") or None
            self._start_token += 1
            token = self._start_token
            self._set_state(ST_CONNECTING)
            self._emit("status", f"连接中…（{source} → {lang}）")

        # --- 锁外做耗时操作（连接最长 15s，持锁会让"停止"按钮假死）---
        client = LiveTranslateClient(
            lang, *self._wire_callbacks(),
            voice="Tina", source_lang=src_lang, api_key=api_key,
        )
        client.source = source
        capture = AudioCapture(source=source)
        try:
            capture.start()
        except Exception as e:  # noqa: BLE001
            capture.stop()
            with self._lock:
                self._set_state(ST_ERROR)
            self._emit("error", f"音频采集启动失败: {e}")
            return False

        ok = client.connect(timeout=15)
        if not ok:
            client.close()  # 超时也必须关闭：ws 线程可能仍在后台（审计 B）
            capture.stop()
            with self._lock:
                self._set_state(ST_ERROR)
            return False

        with self._lock:
            # 连接期间用户已停止/重启（token 变化）：作废本次尝试，直接收尾。
            # 只看 state==ST_STOPPING 不够——stop() 收尾已把状态置回 IDLE，
            # 旧逻辑会让"停止后的会话"照常跑起来（审计 A 竞态实锤）
            if self.state != ST_CONNECTING or self._start_token != token:
                capture.stop()
                try:
                    client.close()
                except Exception:  # noqa: BLE001
                    pass
                if self.state == ST_CONNECTING:
                    self._set_state(ST_IDLE)
                return False
            self._client = client
            self._capture = capture
            self._stop_flag = threading.Event()
            self._push_thread = threading.Thread(
                target=push_audio_forever,
                args=(client, capture, self._stop_flag),
                daemon=True,
            )
            self._push_thread.start()
            self._set_state(ST_RUNNING)
        return True

    def stop(self):
        with self._lock:
            if self.state in (ST_IDLE, ST_STOPPING):
                return
            self._start_token += 1  # 作废进行中的连接尝试（若在 CONNECTING）
            self._set_state(ST_STOPPING)
            flag, client, capture = self._stop_flag, self._client, self._capture
            self._stop_flag = self._client = self._capture = None

        if flag is not None:
            flag.set()
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
        if capture is not None:
            try:
                capture.stop()
            except Exception:  # noqa: BLE001
                pass
        self._set_state(ST_IDLE)

    def restart(self):
        """设置变更后重建会话（限流 RPM 10，UI 侧会做频率保护）。

        复查修复：旧 stop→sleep→start 与 start 的 CONNECTING 幂等检查
        存在时序窗口——旧会话的 stop 把状态置 IDLE 后、新 start 抢先
        进入 CONNECTING，旧 start 的后台线程醒来发现 token 不符直接
        退出（行为对但绕）；更糟的是 UI 在这 0.6s 里点"开始"会吃掉
        重启。改为原子换持：锁内完成状态切换，锁外顺序清理+起新会话。
        """
        with self._lock:
            if self.state in (ST_IDLE, ST_STOPPING):
                # 无活动会话：直接起（对齐 start 的幂等语义）
                threading.Thread(target=self.start, daemon=True).start()
                return
            self._start_token += 1  # 作废进行中的连接尝试
            self._set_state(ST_STOPPING)
            flag, client, capture = (self._stop_flag, self._client, self._capture)
            self._stop_flag = self._client = self._capture = None

        if flag is not None:
            flag.set()
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
        if capture is not None:
            try:
                capture.stop()
            except Exception:  # noqa: BLE001
                pass
        self._set_state(ST_IDLE)
        threading.Thread(target=self.start, daemon=True).start()
