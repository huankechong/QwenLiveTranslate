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


# ---- qwen 一体化（Phase 0 唯一 provider） ----
register(ProviderSpec(
    kind="integrated",
    id="qwen_livetranslate",
    display_name="Qwen3.8 同传（一体化）",
    env_keys=("DASHSCOPE_API_KEY",),
))
