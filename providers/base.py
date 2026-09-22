"""Provider 抽象层：统一引擎门面与组件协议（Phase 0 骨架）。

设计（借鉴 LiveCaptionsTranslator 考古 + 组合模式）：
- LiveEngine   —— controller 唯一依赖的统一门面；一体化引擎（qwen）与
                  分离式管线（ASR+MT，Phase 1+）都实现它，controller 对
                  后端拓扑无感知。
- AsrStream    ——（Phase 1+）分离式的 ASR 组件协议。
- Translator   ——（Phase 1+）分离式的翻译组件协议。

回调签名【完全冻结】：on_source(speaker, text, final) /
on_translation(text, final) / on_status(msg) / on_error(msg) /
on_disconnect(code, msg)——overlay/history/console 三层零感知的关键。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AudioSpec:
    """引擎要求的音频格式；capture 按此开流/重采样。"""

    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2  # 16-bit


@dataclass(frozen=True)
class EngineCaps:
    """引擎能力声明（UI 与历史统计用）。"""

    streaming_asr: bool          # 原文是否有流式 delta
    streaming_translation: bool  # 译文是否有流式 delta
    transport: str = "websocket"  # websocket | http | hybrid | local


class LiveEngine:
    """统一实时引擎门面（基类形态；qwen 一体化与分离管线同构）。

    子类必须提供 connected/session_ready 两个 threading.Event，语义与
    现 LiveTranslateClient 完全一致（推流循环按 session_ready 节拍），
    并在构造时持有 on_error 回调引用（engine_io 异常上报的唯一通道，
    不得穿透门面摸内部实现——第 8 轮审计 H1）。
    """

    provider_id: str = ""
    display_name: str = ""
    caps: EngineCaps = EngineCaps(True, True, "websocket")
    audio_spec: AudioSpec = AudioSpec()

    # 错误回调（构造注入；推流循环经此上报采集异常）
    on_error = None

    # —— 生命周期 ——
    def connect(self, timeout: float = 15.0) -> bool:  # pragma: no cover
        raise NotImplementedError

    def push_audio(self, pcm: bytes) -> None:  # pragma: no cover
        """送一帧音频（格式由 audio_spec 声明）。"""

    def close(self) -> None:  # pragma: no cover
        raise NotImplementedError

    # —— 状态（子类以实例属性提供） ——
    connected: threading.Event
    session_ready: threading.Event
