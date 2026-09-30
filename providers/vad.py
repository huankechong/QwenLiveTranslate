"""能量 VAD 分句器：把连续音频帧切成"句"（供批量 ASR 攒段用）。

策略（简洁版，音频场景够用）：
- 帧能量（RMS）> 阈值 → 说话中，累积
- 静音超过 hangover_ms（默认 300ms）→ 切句吐出
- 单句超过 max_ms（默认 8s）→ 强切（段小请求快、尾延迟低）
- 句间能量自适应：以近期噪声底为准（简单滑动最小值），免手工调阈值

回调语义与 qwen 的 VAD 事件对齐（console 延迟计时口径 A 零改动）：
- 语音开始 → speech_started（合成状态串）
- 语音结束且成句 → 吐 pcm 段
- 静音中丢弃
"""

from __future__ import annotations

import array
import threading


class VadSegmenter:
    def __init__(self, on_speech_started, on_segment,
                 frame_ms: int = 100,
                 hangover_ms: int = 300,
                 max_ms: int = 8000,   # 硅基流动 ASR 尾延迟高，段小成功率显著更好
                 start_rms_ratio: float = 3.0):
        self.on_speech_started = on_speech_started  # () -> None
        self.on_segment = on_segment                # (pcm: bytes) -> None
        self.frame_ms = frame_ms
        self.hangover_frames = max(1, hangover_ms // frame_ms)
        self.max_frames = max(1, max_ms // frame_ms)
        self.start_rms_ratio = start_rms_ratio

        self._buf: list[bytes] = []
        self._frames_in_seg = 0
        self._silence_run = 0
        self._speaking = False
        # 噪声底（滑动最小 RMS，缓慢跟随）
        self._noise_floor = 60.0
        self._lock = threading.Lock()

    # ---------- 内部 ----------
    @staticmethod
    def _rms(pcm: bytes) -> float:
        if not pcm:
            return 0.0
        a = array.array("h")
        a.frombytes(pcm)
        n = len(a)
        if n == 0:
            return 0.0
        acc = 0
        for v in a:
            acc += v * v
        return (acc / n) ** 0.5

    def _flush(self) -> None:
        """吐出当前句（若有内容）。"""
        if self._buf:
            pcm = b"".join(self._buf)
            self._buf.clear()
            try:
                self.on_segment(pcm)
            except Exception:  # noqa: BLE001 — 回调异常不杀分句器
                pass
        self._frames_in_seg = 0
        self._speaking = False

    # ---------- 对外 ----------
    def feed(self, pcm: bytes) -> None:
        """喂一帧（与 AudioCapture.read_chunk 同节拍 ~100ms）。"""
        with self._lock:
            rms = self._rms(pcm)
            # 噪声底：静音期缓慢下探、任何期缓慢回升（防误吃高噪声）
            if rms < self._noise_floor:
                self._noise_floor = 0.9 * self._noise_floor + 0.1 * rms
            else:
                self._noise_floor = min(400.0, 0.995 * self._noise_floor + 0.005 * rms)
            threshold = max(80.0, self._noise_floor * self.start_rms_ratio)

            if rms > threshold:
                if not self._speaking:
                    self._speaking = True
                    try:
                        self.on_speech_started()
                    except Exception:  # noqa: BLE001
                        pass
                self._silence_run = 0
                self._buf.append(pcm)
                self._frames_in_seg += 1
                if self._frames_in_seg >= self.max_frames:
                    self._flush()  # 超长强切
            else:
                if self._speaking:
                    self._buf.append(pcm)  # 静音帧也入段（自然过渡）
                    self._frames_in_seg += 1
                    self._silence_run += 1
                    if self._silence_run >= self.hangover_frames:
                        self._flush()
                # 未说话：丢弃

    def flush(self) -> None:
        """会话结束时清空残留（未成句的尾巴也吐出）。"""
        with self._lock:
            self._flush()
