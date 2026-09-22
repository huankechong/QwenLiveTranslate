"""providers 包：多引擎抽象层（Phase 0 = 仅 qwen 一体化）。

build_engine(cfg, callbacks) 是 controller 的唯一工厂入口。
callbacks = (on_source, on_translation, on_status, on_error, on_disconnect)
——签名与 controller._wire_callbacks() 现状完全一致，零适配。
"""

from __future__ import annotations

from .base import AudioSpec, EngineCaps, LiveEngine
from . import registry
from .qwen_livetranslate import QwenEngine


def build_engine(cfg: dict, callbacks) -> LiveEngine:
    """按 settings 组装引擎。Phase 0：engine_mode 恒为 integrated（qwen）。

    key 取用链（向后兼容）：provider_configs 档（Phase 1+ 生效）→
    旧顶层 api_key → 环境变量（由 client 层处理）。
    """
    # engine_mode = cfg.get("engine_mode", "integrated")
    # Phase 1+ 在此分派 separated 管线（AsrStream + Translator 组合）
    return QwenEngine(
        cfg.get("lang", "zh"),
        *callbacks[:4],
        voice="Tina",
        source_lang=cfg.get("source_lang", "auto"),
        api_key=cfg.get("api_key") or None,
        on_disconnect=callbacks[4],
    )


__all__ = ["build_engine", "LiveEngine", "AudioSpec", "EngineCaps",
           "registry", "QwenEngine"]
