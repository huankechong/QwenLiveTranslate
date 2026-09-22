"""用户设置持久化（settings.json）。

API key 说明：默认走环境变量；用户在控制台明确粘贴保存时才落盘
settings.json（仅存本机，git 已忽略该文件）。环境变量始终优先供连接使用。
"""

import json
import os
import sys
import threading
from pathlib import Path


def _base_dir() -> Path:
    """打包成 exe 后 __file__ 指向临时解压目录，改用 exe 所在目录存设置。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


SETTINGS_PATH = _base_dir() / "settings.json"

# 读-改-写序列互斥（第 8 轮审计 M2：UI 线程 update 与重连/worker 线程
# resolve 交错时有丢失更新窗口；load/save 各自原子但序列不互斥）
_RW_LOCK = threading.Lock()

DEFAULTS = {
    "source": "mic",            # mic | loopback
    "source_lang": "auto",      # 源语言：auto=自动识别，或语种代码
    "lang": "zh",               # 目标语种代码（默认中文）
    "api_key": "",              # DashScope key（用户明确要求可存此处；env 变量优先）
    "font_scale": 1.0,          # 字号缩放 0.7~2.0
    "bg_opacity": 0.9,          # 字幕背景不透明度 0.4~1.0
    "width": 820,               # 字幕窗宽度 600~1400
    "show_original": True,      # 显示原文块
    "theme": "dark",            # 界面主题 dark | light（字幕窗恒深色）
    # show_speaker 已移除（2026-09-20）：qwen3.8 不下发说话人字段，功能从未生效
    "max_lines": 8,             # 连续速录：原文+译文合计最大行数 4~12
    "display_sentences": 4,     # （已弃用 UI，保留兼容）每块保留句数上限
    "height": None,             # 字幕窗用户高度（None=按字号行数自适应；拖拽后生效）
    "show_latency": False,      # 在字幕窗显示每句延迟（ms）
    "win_x": None,              # 字幕窗上次位置（None=默认右下角）
    "win_y": None,
    # ---- 多引擎（Phase 0 预留；Phase 1 起生效） ----
    "engine_mode": "integrated",   # integrated=一体化 | separated=分离式组合
    "provider": "qwen_livetranslate",  # integrated 模式的引擎 id
    "asr_provider": "",            # separated 模式：ASR 引擎 id
    "mt_provider": "",             # separated 模式：翻译引擎 id
    "provider_configs": {},        # 每引擎多套配置档 {engine_id: [profile,...]}
    "provider_indices": {},        # 每引擎当前用第几档 {engine_id: int}
}

# 控制台语言选项（代码 -> 中文名）
LANGUAGES = {
    "de": "德语",
    "en": "英语",
    "zh": "中文",
    "ja": "日语",
    "fr": "法语",
    "es": "西班牙语",
    "ru": "俄语",
}

# 源语言选项 = 自动识别 + 上述全部
SOURCE_LANGUAGES = {"auto": "自动识别", **LANGUAGES}


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        if SETTINGS_PATH.exists():
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                user = json.load(f)
            for k in DEFAULTS:
                if k in user:
                    data[k] = user[k]
    except Exception:  # noqa: BLE001
        pass
    return data


def save(data: dict):
    """原子写盘：先写临时文件再 os.replace——直接 open("w") 会在写入
    瞬间截断原文件，崩溃/断电时 settings.json 变空文件，全部设置丢失
    （第 7 轮审计 H1）。"""
    import os
    import tempfile
    try:
        payload = {k: data.get(k) for k in DEFAULTS}
        fd, tmp = tempfile.mkstemp(
            dir=str(SETTINGS_PATH.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, SETTINGS_PATH)  # 原子替换，无截断窗口
        except Exception:  # noqa: BLE001
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:  # noqa: BLE001
        pass


def update(**kwargs) -> dict:
    with _RW_LOCK:
        data = load()
        for k, v in kwargs.items():
            if k in DEFAULTS:
                data[k] = v
        save(data)
        return data


def resolve_provider_cfg(pid: str) -> dict:
    """取引擎 pid 的生效配置档（三级回退，向后兼容）：

    ① provider_configs[pid][provider_indices[pid]]  —— 新多档结构
    ② 顶层旧 api_key（qwen 专属回退，老用户零感知升级）
    ③ 空档 → 引擎层自会回退环境变量（DASHSCOPE_API_KEY 等）
    """
    with _RW_LOCK:
        return _resolve_provider_cfg_unlocked(pid)


def _resolve_provider_cfg_unlocked(pid: str) -> dict:
    data = load()
    profiles = (data.get("provider_configs") or {}).get(pid) or []
    if profiles:
        idx = int((data.get("provider_indices") or {}).get(pid, 0) or 0)
        idx = max(0, min(idx, len(profiles) - 1))
        prof = dict(profiles[idx])
        # qwen 档内未填 key 时回退旧顶层 key（平滑迁移）
        if pid == "qwen_livetranslate" and not prof.get("api_key"):
            prof["api_key"] = data.get("api_key") or ""
        return prof
    if pid == "qwen_livetranslate":
        return {"api_key": data.get("api_key") or ""}
    return {}
