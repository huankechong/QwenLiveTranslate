"""串行翻译 worker：句子进、译文出（分离式管线的 MT 侧执行器）。

设计（审计定稿）：
- 单线程串行 FIFO（顺序天然正确，无乱序回跳）
- queue maxsize=4：满则丢最旧（宁丢勿积压）
- 入队 >10s 未处理 → 过期跳过（软取消；LCT 的 Cancellation 降级版）
- 每句三段式重试：可重试错误退避 0.5/1.5/4s；auth/quota 立即放弃
- 全部失败 → on_error 上报（不进字幕正文/历史库），不拆会话
- stop(): drain 后线程退出（与推流循环 stop_flag 语义对齐）
"""

from __future__ import annotations

import queue
import threading
import time

from .mt.errors import TranslateError


class TranslationWorker:
    def __init__(self, translator, on_translation, on_error,
                 source_lang: str = "auto", target_lang: str = "zh",
                 max_queue: int = 4, stale_after_s: float = 10.0):
        """translator: 实现 translate(text, src, tgt, is_stale) -> str 的对象"""
        self.translator = translator
        self.on_translation = on_translation  # (text, final=True)
        self.on_error = on_error
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.stale_after_s = stale_after_s

        self._q: queue.Queue = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._dropped = 0

    # ---------- 对外 ----------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="mt-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t:
            t.join(timeout=3)

    def submit(self, text: str) -> bool:
        """入队一句原文；队列满丢最旧再入（返回是否入队）。"""
        item = (time.time(), text)
        while True:
            try:
                self._q.put_nowait(item)
                return True
            except queue.Full:
                try:
                    self._q.get_nowait()  # 丢最旧
                    self._dropped += 1
                except queue.Empty:
                    pass

    # ---------- 内部 ----------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                enq_t, text = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            # 过期软取消：说话都过去 10s 了这句译文已无意义
            if time.time() - enq_t > self.stale_after_s:
                continue
            self._translate_one(text)

    def _translate_one(self, text: str) -> None:
        delays = (0.5, 1.5, 4.0)
        last_err: TranslateError | None = None
        for attempt in range(len(delays) + 1):
            if self._stop.is_set():
                return
            if attempt > 0:
                time.sleep(delays[attempt - 1])
            try:
                out = self.translator.translate(
                    text, self.source_lang, self.target_lang,
                    is_stale=lambda: self._stop.is_set())
                if out:
                    self.on_translation(out, True)
                return  # 成功（或空结果静默）
            except TranslateError as e:
                last_err = e
                if not e.retryable:
                    break
            except Exception as e:  # noqa: BLE001 — 非分类异常按网络类处理
                last_err = TranslateError("network", str(e))
        # 重试耗尽/不可重试：上报但不拆会话
        if last_err is not None and not self._stop.is_set():
            try:
                self.on_error(f"翻译失败: {last_err.user_message()}")
            except Exception:  # noqa: BLE001
                pass
