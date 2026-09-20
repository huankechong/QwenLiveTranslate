"""音频采集层：麦克风 或 系统声音（WASAPI loopback），基于 PyAudioWPatch。

用法：
    python capture.py --list-devices          # 枚举设备，找输入设备索引
    来源选择在控制台 UI（settings.json）里配置：mic / loopback。
"""

import argparse
import sys

try:
    import pyaudiowpatch as pyaudio
except ImportError:
    print("缺少依赖 PyAudioWPatch：pip install PyAudioWPatch")
    sys.exit(1)


def list_devices():
    """打印全部输入/输出设备与默认 loopback 设备，便于配置索引。"""
    p = pyaudio.PyAudio()
    print("=" * 72)
    print("输入/输出设备（Input / Output）：")
    print("=" * 72)
    try:
        default_in = p.get_default_input_device_info()
        print(f"[默认输入] #{default_in['index']} {default_in['name']}")
    except Exception:
        print("[默认输入] 未检测到")
    try:
        default_out = p.get_default_output_device_info()
        print(f"[默认输出] #{default_out['index']} {default_out['name']}")
    except Exception:
        print("[默认输出] 未检测到")
    print("-" * 72)
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    default_loop = None
    try:
        default_loop = p.get_default_wasapi_loopback()
        print(f"[默认Loopback] #{default_loop['index']} {default_loop['name']}")
    except Exception:
        pass
    print("-" * 72)
    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        tag = ""
        if default_loop is not None and info["index"] == default_loop["index"]:
            tag = "  <-- 默认loopback"
        try:
            if info.get("is_loopback"):
                tag += "  [loopback]"
        except Exception:
            pass
        ch_in = info.get("maxInputChannels", 0)
        ch_out = info.get("maxOutputChannels", 0)
        kind = f"in:{ch_in}/out:{ch_out}"
        print(f"#{i:2d} {kind:<14} {info['name']}{tag}")
    print("=" * 72)
    print(f"WASAPI host api: {wasapi.get('name')} (devices: {wasapi.get('deviceCount')})")
    p.terminate()


class AudioCapture:
    """统一的音频采集器。yield 16kHz/16bit/mono 的 bytes 帧。"""

    def __init__(self, source: str = "mic", input_device_index: int | None = None,
                 loopback_device_index: int | None = None):
        self.source = source
        self.input_device_index = input_device_index
        self.loopback_device_index = loopback_device_index
        self._pa = None
        self._stream = None

    # ---------- 内部 ----------
    def _open_mic(self):
        return self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            input_device_index=self.input_device_index,  # None=默认麦克风
            frames_per_buffer=1600,
        )

    def _open_loopback(self):
        dev = self.loopback_device_index
        if dev is None:
            dev = self._pa.get_default_wasapi_loopback()["index"]
        info = self._pa.get_device_info_by_index(dev)
        loop_rate = int(info.get("defaultSampleRate", 48000))
        return self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=loop_rate,          # loopback 常为 48k，需重采样到 16k
            input=True,
            input_device_index=dev,
            frames_per_buffer=int(loop_rate * 0.1),  # 100ms
        ), loop_rate

    def _resample_16k(self, pcm: bytes, src_rate: int) -> bytes:
        """简单线性重采样到 16kHz mono（整数倍场景直接抽样，否则线性插值）。"""
        n = len(pcm) // 2
        if n == 0:
            return b""
        if src_rate == 16000:
            return pcm
        import array
        src = array.array("h")
        src.frombytes(pcm)
        if len(src) == 0:
            return b""
        step = src_rate / 16000.0
        out_len = int(n / step)
        out = array.array("h")
        pos = 0.0
        for _ in range(out_len):
            i = int(pos)
            frac = pos - i
            if i + 1 < n:
                v = src[i] * (1 - frac) + src[i + 1] * frac
            else:
                v = src[i]
            out.append(int(max(-32768, min(32767, v))))
            pos += step
        return out.tobytes()

    # ---------- 对外 ----------
    def start(self):
        self._pa = pyaudio.PyAudio()
        if self.source == "loopback":
            self._stream, self._loop_rate = self._open_loopback()
        else:
            self._stream = self._open_mic()
            self._loop_rate = 16000

    def read_chunk(self) -> bytes:
        """读一帧（约100ms）16k/16bit/mono bytes；loopback 自动重采样。"""
        data = self._stream.read(1600 if self._loop_rate == 16000 else int(self._loop_rate * 0.1),
                                 exception_on_overflow=False)
        if self._loop_rate != 16000:
            data = self._resample_16k(data, self._loop_rate)
        return data

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            finally:
                self._stream = None
        if self._pa is not None:
            try:
                self._pa.terminate()
            finally:
                self._pa = None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-devices", action="store_true")
    args = ap.parse_args()
    if args.list_devices:
        list_devices()
    else:
        print("用法：python capture.py --list-devices")
