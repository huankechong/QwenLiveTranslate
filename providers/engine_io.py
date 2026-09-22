"""引擎 IO：通用推流循环（自 realtime_client.push_audio_forever 泛化）。

行为与原实现逐字对齐（节拍/退出条件/错误语义），仅把"构造 qwen 信封"
换成 engine.push_audio(pcm)——协议细节内收进引擎。
"""

from __future__ import annotations

import threading
import time


def engine_push_loop(engine, capture, stop_flag: threading.Event):
    """推流循环：读采集帧 -> engine.push_audio；断线即退。

    节拍由 read_chunk 的阻塞读天然保证（~100ms/帧 = 实时速率）；
    **严禁再加额外 sleep**——否则吞吐 < 实时，长会话延迟无限增长
    （2026-09-20 审计抓到：曾加 0.1s sleep 导致半速推流）。
    """
    while not stop_flag.is_set():
        if not engine.session_ready.is_set():
            if not engine.connected.is_set():
                break  # 连接已断，退出推流
            time.sleep(0.05)
            continue
        try:
            pcm = capture.read_chunk()
        except Exception as e:  # noqa: BLE001
            # 停止流程中 capture.stop() 关流会让阻塞读抛异常——这是预期
            # 关闭时序，不是错误；stop_flag 已置时不再向用户报错（审计 D）
            if not stop_flag.is_set():
                # 经门面 on_error 上报（第 8 轮审计 H1：不得穿透
                # engine._client——SeparatedPipeline 无该属性会 AttributeError）
                cb = getattr(engine, "on_error", None)
                if cb is not None:
                    try:
                        cb(f"音频读取失败: {e}")
                    except Exception:  # noqa: BLE001
                        pass
            break
        if pcm:
            engine.push_audio(pcm)
