"""providers 包：多引擎抽象层（Phase 1：qwen 一体化 + 硅基流动分离式）。

build_engine(cfg, callbacks) 是 controller 的唯一工厂入口。
callbacks = (on_source, on_translation, on_status, on_error, on_disconnect)
——签名与 controller._wire_callbacks() 现状完全一致，零适配。

引擎模式（settings.engine_mode）：
- integrated（默认）：单 provider（qwen_livetranslate）端到端 WS
- separated：ASR（硅基流动 SenseVoice 批量）+ MT（openai_compat 系）自由组合
"""

from __future__ import annotations

from .base import AudioSpec, EngineCaps, LiveEngine
from . import registry
from .qwen_livetranslate import QwenEngine
from .pipeline import SeparatedPipeline


def _resolve(cfg: dict, pid: str) -> dict:
    """取引擎配置档（三级回退：档 → 顶层 key → 环境变量）。

    env 层按 registry 里该 provider 声明的 env_keys 依次兜底
    （P1 自审 E1：此前 env_keys 声明了却无人消费，env 配置静默失效）。
    """
    import os

    import settings as st
    prof = st.resolve_provider_cfg(pid)
    if not (prof.get("api_key") or "").strip():
        prof["api_key"] = cfg.get("api_key") or ""
    if not (prof.get("api_key") or "").strip():
        spec = registry.get(pid)
        for env_name in (spec.env_keys if spec else ()):
            v = os.environ.get(env_name, "").strip()
            if v:
                prof["api_key"] = v
                break
    return prof


def build_engine(cfg: dict, callbacks) -> LiveEngine:
    """按 settings 组装引擎（integrated | separated 分派）。"""
    mode = cfg.get("engine_mode", "integrated")
    if mode == "separated":
        return _build_separated(cfg, callbacks)
    return QwenEngine(
        cfg.get("lang", "zh"),
        *callbacks[:4],
        voice="Tina",
        source_lang=cfg.get("source_lang", "auto"),
        api_key=cfg.get("api_key") or None,
        on_disconnect=callbacks[4],
    )


def _build_separated(cfg: dict, callbacks) -> SeparatedPipeline:
    from .asr.http_batch import HttpBatchAsr, BatchAsrStream

    asr_pid = cfg.get("asr_provider") or "siliconflow_sensevoice"
    mt_pid = cfg.get("mt_provider") or "siliconflow_chat"
    asr_cfg = _resolve(cfg, asr_pid)
    mt_cfg = _resolve(cfg, mt_pid)

    asr_client = HttpBatchAsr(
        api_key=asr_cfg.get("api_key") or "",
        model=asr_cfg.get("model") or "FunAudioLLM/SenseVoiceSmall",
        base_url=asr_cfg.get("base_url") or "https://api.siliconflow.cn/v1",
        language=None if cfg.get("source_lang", "auto") == "auto"
                   else cfg.get("source_lang"),
    )
    asr_stream = BatchAsrStream(
        asr_client,
        on_source=None,  # pipeline 接管
        on_status=callbacks[2],
        on_error=callbacks[3],
    )
    # MT：openai_compat 家族（预设决定 base_url/model）
    from .mt.openai_compat import OpenAICompatTranslator
    translator = OpenAICompatTranslator(
        api_key=mt_cfg.get("api_key") or "",
        model=mt_cfg.get("model") or "Qwen/Qwen2.5-7B-Instruct",
        base_url=mt_cfg.get("base_url") or "https://api.siliconflow.cn/v1",
    )
    return SeparatedPipeline(
        asr_stream, translator, callbacks,
        source_lang=cfg.get("source_lang", "auto"),
        target_lang=cfg.get("lang", "zh"),
    )


__all__ = ["build_engine", "LiveEngine", "AudioSpec", "EngineCaps",
           "registry", "QwenEngine", "SeparatedPipeline"]
