"""OpenAI 兼容批量 ASR（/audio/transcriptions）+ VAD 适配成 AsrStream。

链路：AudioCapture 帧喂 VadSegmenter → 成句 pcm → WAV 编码 →
POST multipart → 终稿文本 → on_source(None, text, final=True)。
错误经 on_error 上报丢句（不拆会话——ASR 挂了字幕会停，翻译还能靠
worker 继续处理已识别句；连续失败由 pipeline 层上报状态）。
"""

from __future__ import annotations

import io
import json
import threading
import urllib.error
import urllib.request
import uuid
import wave

from ..base import AudioSpec
from ..mt.errors import TranslateError, from_http_status
from ..vad import VadSegmenter

_TIMEOUT_S = 30.0  # 4.7s 段实测 11s+（网络抖动），20s 余量不足


def pcm_to_wav(pcm: bytes, sample_rate: int = 16000,
               channels: int = 1, sample_width: int = 2) -> bytes:
    """裸 PCM → WAV 容器（/audio/transcriptions 要求可读音频格式）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


class HttpBatchAsr:
    """OpenAI 兼容 /audio/transcriptions 客户端（无状态、线程安全只读）。"""

    def __init__(self, api_key: str, model: str,
                 base_url: str = "https://api.siliconflow.cn/v1",
                 language: str | None = None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.language = language  # None=自动检测

    def transcribe(self, wav_bytes: bytes) -> str:
        boundary = f"----wb{uuid.uuid4().hex}"
        parts: list[bytes] = []
        def field(name: str, value: str) -> None:
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; "
                f"name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))
        field("model", self.model)
        if self.language:
            field("language", self.language)
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f"name=\"file\"; filename=\"chunk.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n".encode("utf-8"))
        parts.append(wav_bytes)
        parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)
        req = urllib.request.Request(
            f"{self.base_url}/audio/transcriptions", data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            }, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            txt = ""
            try:
                txt = e.read().decode("utf-8", "ignore")
            except Exception:  # noqa: BLE001
                pass
            raise from_http_status(e.code, txt) from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise TranslateError("network", str(e)) from None
        return (data.get("text") or "").strip()

    def test_connection(self) -> tuple[bool, str]:
        req = urllib.request.Request(
            f"{self.base_url}/models",
            headers={"Authorization": f"Bearer {self.api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=8):
                return True, "ASR 服务连接正常"
        except urllib.error.HTTPError as e:
            return False, from_http_status(e.code).user_message()
        except Exception as e:  # noqa: BLE001
            return False, f"网络异常: {e}"


class BatchAsrStream:
    """AsrStream 形态：吃音频帧，吐终稿句（VAD 分句 + 批量识别）。

    供 SeparatedPipeline 组合；实现 LiveEngine 对 push_audio 的语义
    （帧进→分句→识别→回调），connect 恒成功（HTTP 无会话）。
    """

    provider_id = ""
    display_name = "批量 ASR"
    audio_spec = AudioSpec(16000)

    def __init__(self, client: HttpBatchAsr, on_source, on_status, on_error,
                 sample_rate: int = 16000):
        self._client = client
        self.on_source = on_source      # (speaker, text, final)
        self._status_cb = on_status
        self.on_error_cb = on_error
        self.connected = threading.Event()
        self.session_ready = threading.Event()
        self.provider_id = f"asr:{client.model}"
        self.display_name = f"批量 ASR · {client.model}"
        self._vad = VadSegmenter(
            on_speech_started=lambda: _safe(on_status, "🎤 检测到语音"),
            on_segment=self._on_segment)
        self._sample_rate = sample_rate

    def _on_segment(self, pcm: bytes) -> None:
        """VAD 成句 → WAV → 识别（网络错退避重试）→ 终稿回调。

        识别在推流线程串行执行——重试期间推流暂停会让音频积压在
        capture 侧，故只对网络类错误重试（1s/2s 退避共三次尝试；
        HTTP 4xx 重试无意义）。切句即发 STOPPED 哨兵——console 的
        延迟计时 A 口径以"静音断句"为起点（P1 自审 E2）。"""
        import time as _t
        _safe(self._status_cb, "… 静音，翻译中")
        wav = pcm_to_wav(pcm, self._sample_rate)
        text = ""
        backoffs = (1.0, 2.0)
        for attempt in range(len(backoffs) + 1):
            try:
                text = self._client.transcribe(wav)
                break
            except TranslateError as e:
                if attempt < len(backoffs) and e.kind in ("network", "timeout"):
                    _t.sleep(backoffs[attempt])
                    continue
                _safe(self.on_error_cb, f"识别失败（本句丢弃）: {e.user_message()}")
                return
            except Exception as e:  # noqa: BLE001
                _safe(self.on_error_cb, f"识别异常（本句丢弃）: {e}")
                return
        if text:
            self.on_source(None, text, True)

    # —— AsrStream 协议 ——
    def connect(self, timeout: float = 15.0) -> bool:
        self.connected.set()
        self.session_ready.set()
        return True

    def push_audio(self, pcm: bytes) -> None:
        self._vad.feed(pcm)

    def close(self) -> None:
        self._vad.flush()
        self.connected.clear()
        self.session_ready.clear()


def _safe(cb, *args):
    if cb is None:
        return
    try:
        cb(*args)
    except Exception:  # noqa: BLE001
        pass
