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
        self._cfg_api_key = api_key or ""  # test_connection 基类检查用
        self._client = LiveTranslateClient(
            target_lang, on_source, on_translation, on_status, on_error,
            voice=voice, source_lang=source_lang, api_key=api_key,
            on_disconnect=on_disconnect,
        )

    def test_connection(self) -> tuple[bool, str]:
        """DashScope /models 探活（有 key 才真测；env 变量也认）。"""
        import json
        import os
        import urllib.error
        import urllib.request

        import config
        key = self._cfg_api_key or os.environ.get(config.API_KEY_ENV, "")
        if not key:
            return False, "未配置 key"
        req = urllib.request.Request(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
            headers={"Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                n = len(json.loads(resp.read().decode("utf-8")).get("data", []))
                return True, f"DashScope 连接正常（{n} 个模型可用）"
        except urllib.error.HTTPError as e:
            return False, f"key 无效或未授权（HTTP {e.code}）"
        except Exception as e:  # noqa: BLE001
            return False, f"网络异常: {e}"

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
