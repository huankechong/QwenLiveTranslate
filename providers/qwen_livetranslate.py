"""QwenEngine：现 LiveTranslateClient 的 LiveEngine 包装（薄适配层）。

协议细节（session.update 信封 / base64 append）全部内收到 client 本体与
本包装；controller 只见 push_audio(pcm)。client 类一行不改——Phase 0 的
核心承诺：qwen 主路径行为与 v1.0.2 逐项一致。
"""

from __future__ import annotations

from .base import AudioSpec, EngineCaps, LiveEngine
from realtime_client import LiveTranslateClient


class QwenEngine(LiveEngine):
    provider_id = "qwen_livetranslate"
    display_name = "Qwen3.8 同传（一体化）"
    caps = EngineCaps(streaming_asr=True, streaming_translation=True,
                      transport="websocket")
    audio_spec = AudioSpec(sample_rate=16000)

    def __init__(self, target_lang, on_source, on_translation, on_status,
                 on_error, voice="Tina", source_lang="auto",
                 api_key=None, on_disconnect=None):
        self.on_error = on_error  # 门面层错误回调（engine_io 上报通道）
        self._client = LiveTranslateClient(
            target_lang, on_source, on_translation, on_status, on_error,
            voice=voice, source_lang=source_lang, api_key=api_key,
            on_disconnect=on_disconnect,
        )

    # 事件对象直接透传（推流循环按 session_ready 节拍）
    @property
    def connected(self):
        return self._client.connected

    @property
    def session_ready(self):
        return self._client.session_ready

    @property
    def source(self):
        return self._client.source

    @source.setter
    def source(self, v):
        self._client.source = v  # 状态栏显示用（main.py 惯例）

    def connect(self, timeout: float = 15.0) -> bool:
        return self._client.connect(timeout=timeout)

    def push_audio(self, pcm: bytes) -> None:
        self._client.push_audio(pcm)

    def close(self) -> None:
        self._client.close()
