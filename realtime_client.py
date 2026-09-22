"""Qwen3.8-LiveTranslate-Flash-Realtime WebSocket 客户端（协议层）。

协议（qwen3.8）：
  1. 连接  wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=...
           鉴权 Authorization: Bearer $DASHSCOPE_API_KEY
  2. 收    session.created
  3. 发    session.update {output_modalities:["text"], translation:{language:...}}
  4. 循环  input_audio_buffer.append {audio: base64(16k/16bit/mono PCM)}
  5. 收    conversation.item.input_audio_transcription.delta / .completed   原文
           response.text.delta / response.text.done                        译文
           input_audio_buffer.speech_started / speech_stopped               VAD
           error / session.created 后异常处理
  6. 结束  session.finish -> session.finished -> close

线程模型：WebSocketApp 在独立线程跑 run_forever；音频采集在主线程推流。
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import uuid

import websocket  # pip install websocket-client

import config


class LiveTranslateClient:
    """把服务器事件流翻译成简单回调：on_source / on_translation / on_status / on_error。"""

    def __init__(self, target_lang: str, on_source, on_translation, on_status, on_error,
                 voice: str = "Tina", source_lang: str = "auto", api_key: str | None = None,
                 on_disconnect=None):
        self.target_lang = target_lang
        self.source_lang = source_lang  # "auto"=自动识别，或语种代码
        self.api_key_override = api_key  # None=用环境变量
        self.voice = voice  # qwen3.8 需显式指定输出音色（服务端默认 Chelsie 不可用）
        self.on_source = on_source          # (speaker, text, final: bool)
        self.on_translation = on_translation  # (text, final: bool)
        self.on_status = on_status          # (msg: str)
        self.on_error = on_error            # (msg: str)
        # 意外断线通知（主动 close 不触发）：controller 据此走自动重连
        self.on_disconnect = on_disconnect  # (code, msg) | None

        self.ws: websocket.WebSocketApp | None = None
        self.session_id: str | None = None
        self.connected = threading.Event()
        self.session_ready = threading.Event()
        self._closed = threading.Event()

        # 原文按 item 聚合：item_id -> {"speaker": str|None, "parts": [str]}
        self._asr_items: dict[str, dict] = {}
        # 译文按 response 聚合：response_id -> [parts]
        self._resp_text: dict[str, list[str]] = {}

    # ---------- 发送 ----------
    def _send(self, obj: dict):
        if self.ws is None or not self.connected.is_set():
            return  # 连接已断，静默丢弃（避免断线后刷屏报错）
        try:
            self.ws.send(json.dumps(obj, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            self.on_error(f"发送失败: {e}")

    @staticmethod
    def _eid() -> str:
        return "event_" + uuid.uuid4().hex[:22]

    # ---------- 生命周期 ----------
    def connect(self, timeout: float = 15.0) -> bool:
        api_key = self.api_key_override or os.environ.get(config.API_KEY_ENV, "")
        if not api_key:
            self.on_error(
                f"未配置 key：请在控制台设置或设环境变量 {config.API_KEY_ENV}"
            )
            return False

        headers = [f"Authorization: Bearer {api_key}"]
        self.ws = websocket.WebSocketApp(
            config.WS_URL,
            header=headers,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
        )
        t = threading.Thread(target=self.ws.run_forever, daemon=True,
                             kwargs={"ping_interval": 20, "ping_timeout": 10})
        t.start()
        # 等 session.update 确认（session.updated）
        if not self.session_ready.wait(timeout):
            # 超时必须彻底关闭：ws 线程可能仍在后台慢慢握手，
            # 稍后连上会成为幽灵会话（回调混进 UI + 线程泄漏，审计 B）
            self._abort()
            self.on_error("连接/会话建立超时，检查网络与 key")
            return False
        return True

    def _abort(self):
        """超时/放弃路径的强制清理（不等 session.finished）。"""
        self._closed.set()
        try:
            if self.ws is not None:
                self.ws.close()
        except Exception:  # noqa: BLE001
            pass

    def close(self):
        # 先置 _closed 再关：ws.close() 可能触发 on_close 回调抢跑，
        # 若 _closed 未置位会向用户误报"连接断开"（审计 F）
        self._closed.set()
        try:
            if self.ws is not None and self.connected.is_set():
                self._send({"event_id": self._eid(), "type": "session.finish"})
                # finish→ws.close 挪到后台线程：原实现 sleep(0.3) 阻塞
                # UI 线程 300ms（每次停止/切设置都卡一下，审计 C）。
                # connected 守卫：ws 已断/超时 abort 过时不再起多余收尾线程
                # （复查修复：原实现 _send 静默 no-op 后 _fin 线程照起）
                def _fin():
                    time.sleep(0.3)  # 给服务器留出发送 session.finished 的时间
                    try:
                        self.ws.close()
                    except Exception:  # noqa: BLE001
                        pass
                threading.Thread(target=_fin, daemon=True).start()
        except Exception:  # noqa: BLE001
            pass

    # ---------- 回调（ws 线程） ----------
    def _on_open(self, _ws):
        self.connected.set()
        self.on_status("已连接，等待会话创建…")

    def _on_ws_error(self, _ws, err):
        self.on_error(f"WebSocket 错误: {err}")

    def _on_ws_close(self, _ws, code, msg):
        self.session_ready.clear()
        self.connected.clear()
        if not self._closed.is_set():
            # 意外断线（非主动 close）：交由 controller 的重连引擎统一
            # 发可见提示（含退避进度）；此处若也发"连接断开"会同帧双发，
            # 字幕窗状态行闪烁且第一条信息不全（第六轮审计 A）
            if self.on_disconnect is not None:
                try:
                    self.on_disconnect(code, msg)
                except Exception:  # noqa: BLE001
                    pass
            else:
                self.on_status(f"连接断开 (code={code} {msg})")

    # ---------- 事件路由 ----------
    def _on_message(self, _ws, message: str):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            self.on_error(f"非 JSON 消息: {message[:120]}")
            return
        # 已 close/abort 的会话：迟到消息一律丢弃（复查修复：close 后
        # 服务器残余事件仍会触发回调，污染新会话的 UI/字幕/历史库）
        if self._closed.is_set():
            return
        t = data.get("type", "")

        # ---- 会话 ----
        if t == "session.created":
            self.session_id = data.get("session", {}).get("id")
            self.on_status(f"会话已创建 {self.session_id or ''}")
            # qwen3.8 嵌套结构：audio.output.voice 必须显式指定，
            # 否则服务端默认音色 Chelsie 会触发 400 InternalError
            session = {
                "output_modalities": ["text"],
                "translation": {"language": self.target_lang},
                "audio": {"output": {"voice": self.voice}},
            }
            # 源语言：auto 时省略（服务端自动识别）；指定时走 input_audio_transcription.language
            if self.source_lang and self.source_lang != "auto":
                session["input_audio_transcription"] = {"language": self.source_lang}
            self._send({"type": "session.update", "session": session})
        elif t == "session.updated":
            self.session_ready.set()
            self.on_status(f"就绪 · {self.source_label()} → {self.target_lang.upper()} · 开始说话")
        elif t == "session.finished":
            self.on_status("会话已结束")
            try:
                self.ws.close()
            except Exception:  # noqa: BLE001
                pass

        # ---- 原文（ASR，qwen3.8 = .delta 系） ----
        elif t == "conversation.item.input_audio_transcription.delta":
            item_id = data.get("item_id", "?")
            delta = data.get("delta", "")
            speaker = data.get("speaker") or data.get("speaker_id") or data.get("speaker_label")
            rec = self._asr_items.setdefault(item_id, {"speaker": None, "parts": []})
            if speaker:
                rec["speaker"] = speaker
            rec["parts"].append(delta)
            self.on_source(self._speaker_tag(rec["speaker"]), "".join(rec["parts"]), final=False)
        elif t == "conversation.item.input_audio_transcription.completed":
            item_id = data.get("item_id", "?")
            rec = self._asr_items.pop(item_id, None)
            text = data.get("transcript") or ("".join(rec["parts"]) if rec else "")
            speaker = (data.get("speaker") or (rec or {}).get("speaker"))
            self.on_source(self._speaker_tag(speaker), text, final=True)
        elif t == "conversation.item.input_audio_transcription.failed":
            # 失败也必须 pop：该 item 的 delta 已入 _asr_items，不清理则
            # 长会话反复失败会持续泄漏（第 7 轮审计 H2）
            item_id = data.get("item_id", "?")
            self._asr_items.pop(item_id, None)
            err = data.get("error", {}).get("message", "识别失败")
            self.on_error(f"ASR 失败: {err}")

        # ---- 译文（仅文本模态：response.text.delta） ----
        elif t == "response.text.delta":
            rid = data.get("response_id", "?")
            self._resp_text.setdefault(rid, []).append(data.get("delta", ""))
            self.on_translation("".join(self._resp_text[rid]), final=False)
        elif t == "response.text.done":
            rid = data.get("response_id", "?")
            text = data.get("text") or "".join(self._resp_text.pop(rid, []))
            self.on_translation(text, final=True)
        elif t in ("response.cancelled", "response.failed",
                   "response.incomplete", "response.interrupted"):
            # 中断/失败的 response：只发过 delta 没发 done 的条目必须清理，
            # 否则字典永久残留（第 7 轮审计 H3）
            rid = data.get("response_id")
            if rid is not None:
                self._resp_text.pop(rid, None)

        # ---- VAD 提示 ----
        elif t == "input_audio_buffer.speech_started":
            self.on_status("🎤 检测到语音")
        elif t == "input_audio_buffer.speech_stopped":
            self.on_status("… 静音，翻译中")

        # ---- 错误 ----
        elif t == "error":
            e = data.get("error", {})
            self.on_error(f"[{e.get('code','')}] {e.get('message','未知错误')}")

        # 其余事件（response.created / output_item.* 等）静默忽略

    # ---------- 工具 ----------
    @staticmethod
    def _speaker_tag(speaker) -> str | None:
        if not speaker:
            return None
        s = str(speaker)
        # 兼容 "Speaker 1" / "speaker_1" / "S1" 等返回形式
        digits = "".join(ch for ch in s if ch.isdigit())
        return f"S{digits}" if digits else s[:8]

    def source_label(self) -> str:
        return {"mic": "麦克风", "loopback": "系统声音"}.get(self.source, self.source)

    source = "mic"  # 由 main.py 赋值，仅用于状态栏显示

    def push_audio(self, pcm: bytes) -> None:
        """送一帧 PCM（16k/16bit/mono）——qwen 信封内收于此。

        （providers.QwenEngine 与 engine_io.engine_push_loop 的协议边界；
        协议细节不再泄漏进推流循环。）"""
        self._send({
            "event_id": self._eid(),
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm).decode("ascii"),
        })


def push_audio_forever(client: LiveTranslateClient, capture, stop_flag: threading.Event):
    """推流循环（薄别名→providers.engine_io.engine_push_loop）。

    保留原符号以兼容既有引用；实现已泛化为引擎无关版本。
    """
    from providers.engine_io import engine_push_loop
    return engine_push_loop(client, capture, stop_flag)
