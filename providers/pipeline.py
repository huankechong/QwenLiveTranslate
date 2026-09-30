"""分离式 ASR + MT 组合管线：缝合成统一 LiveEngine 门面。

controller 只见 SeparatedPipeline（与 QwenEngine 同构）：
- push_audio → BatchAsrStream（VAD 分句 + 批量识别）
- 识别终稿 on_source → 直通 UI + 提交 TranslationWorker
- worker 译文 → on_translation(final=True)
- 翻译失败不拆会话（ASR 原文继续显示）；状态行提示经 on_status
"""

from __future__ import annotations

import threading

from .base import AudioSpec, EngineCaps, LiveEngine
from .translation_worker import TranslationWorker


class SeparatedPipeline(LiveEngine):
    provider_id = "separated_pipeline"
    display_name = "分离式组合（ASR + 翻译）"
    caps = EngineCaps(streaming_asr=False, streaming_translation=False,
                      transport="hybrid")

    def __init__(self, asr_stream, translator, callbacks, source_lang="auto",
                 target_lang="zh"):
        """asr_stream: BatchAsrStream；translator: OpenAICompatTranslator 系；
        callbacks: (on_source, on_translation, on_status, on_error, on_disconnect)"""
        on_source, on_translation, on_status, on_error, on_disconnect = callbacks
        self.on_error = on_error
        self._on_disconnect = on_disconnect
        self._asr = asr_stream
        self._worker = TranslationWorker(
            translator, on_translation, on_error,
            source_lang=source_lang, target_lang=target_lang)
        # ASR 终稿：直通 UI + 入翻译队列
        self._asr.on_source = self._on_asr_final
        self._on_ui_source = on_source
        self.connected = asr_stream.connected
        self.session_ready = asr_stream.session_ready
        self.audio_spec = getattr(asr_stream, "audio_spec", AudioSpec(16000))
        self.display_name = (f"{getattr(asr_stream, 'display_name', 'ASR')} + "
                             f"{getattr(translator, 'model', 'MT')}")

    def _on_asr_final(self, speaker, text, final):
        if final and text:
            self._on_ui_source(speaker, text, final)
            self._worker.submit(text)
            # 句终分段（与 qwen 路径的 finalize_src_utterance 对齐由
            # console 的 on_source(final=True) 分支处理）

    # —— LiveEngine 协议 ——
    def connect(self, timeout: float = 15.0) -> bool:
        ok = self._asr.connect(timeout=timeout)
        if ok:
            self._worker.start()
        return ok

    def push_audio(self, pcm: bytes) -> None:
        self._asr.push_audio(pcm)

    def close(self) -> None:
        self._worker.stop()
        self._asr.close()
