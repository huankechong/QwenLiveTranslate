"""Provider 注册表：显式注册（非反射/非扫描），可 grep、PyInstaller 友好。

借鉴 LiveCaptionsTranslator 的"字典注册表 + 立即生效查表"，摒弃其命名
约定反射发现（类型安全差、打包易漏）。Phase 0 仅注册 qwen 一家。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderSpec:
    kind: str          # "integrated" | "asr" | "mt"（Phase 1+ 扩展后两类）
    id: str            # 注册表 id（settings 引用它）
    display_name: str  # UI/历史显示名
    defaults: dict = field(default_factory=dict)   # 配置档缺省字段
    env_keys: tuple = ()                             # key 回退环境变量


_REGISTRY: dict[str, ProviderSpec] = {}


def register(spec: ProviderSpec) -> ProviderSpec:
    if spec.id in _REGISTRY:
        raise ValueError(f"duplicate provider id: {spec.id}")
    _REGISTRY[spec.id] = spec
    return spec


def get(pid: str) -> ProviderSpec | None:
    return _REGISTRY.get(pid)


def iter_by_kind(kind: str) -> list[ProviderSpec]:
    return [s for s in _REGISTRY.values() if s.kind == kind]


# ---- qwen 一体化 ----
register(ProviderSpec(
    kind="integrated",
    id="qwen_livetranslate",
    display_name="Qwen3.8 同传（一体化）",
    env_keys=("DASHSCOPE_API_KEY",),
))

# ---- 分离式 ASR（Phase 1）----
register(ProviderSpec(
    kind="asr",
    id="siliconflow_sensevoice",
    display_name="硅基流动 SenseVoice（免费）",
    defaults={"model": "FunAudioLLM/SenseVoiceSmall",
              "base_url": "https://api.siliconflow.cn/v1"},
    env_keys=("SILICONFLOW_API_KEY",),
))

# ---- 分离式翻译（Phase 1：三个免费预设，一个类全盖）----
register(ProviderSpec(
    kind="mt",
    id="siliconflow_chat",
    display_name="硅基流动 Qwen2.5-7B（免费）",
    defaults={"model": "Qwen/Qwen2.5-7B-Instruct",
              "base_url": "https://api.siliconflow.cn/v1"},
    env_keys=("SILICONFLOW_API_KEY",),
))
register(ProviderSpec(
    kind="mt",
    id="siliconflow_hunyuan_mt",
    display_name="硅基流动 混元翻译专用（免费）",
    defaults={"model": "tencent/Hunyuan-MT-7B",
              "base_url": "https://api.siliconflow.cn/v1"},
    env_keys=("SILICONFLOW_API_KEY",),
))
register(ProviderSpec(
    kind="mt",
    id="bigmodel_glm4flash",
    display_name="智谱 GLM-4-Flash（免费）",
    defaults={"model": "glm-4-flash",
              "base_url": "https://open.bigmodel.cn/api/paas/v4"},
    env_keys=("ZHIPU_API_KEY", "GLM_API_KEY"),
))
