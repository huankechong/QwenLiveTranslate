"""静态配置：API 端点与音频参数（UI 可调项见 settings.py，此处只放协议/硬件级常量）。"""

# ============ 版本（SemVer；发布时与 git tag 对齐） ============
__version__ = "1.0.5"

# ============ API ============
API_KEY_ENV = "DASHSCOPE_API_KEY"
WS_URL = (
    "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
    "?model=qwen3.8-livetranslate-flash-realtime"
)

# ============ 音频 ============
SAMPLE_RATE = 16000        # DashScope realtime 要求 16kHz
CHANNELS = 1
SAMPLE_WIDTH = 2           # 16-bit
CHUNK_MS = 100             # 每帧 100ms
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_MS // 1000   # 1600 samples = 3200 bytes
BYTES_PER_CHUNK = CHUNK_SAMPLES * SAMPLE_WIDTH * CHANNELS

# ============ 快捷键（keyboard 库全局热键） ============
HOTKEY_TOGGLE_CLICKTHROUGH = "ctrl+alt+space"   # 切换字幕点击穿透
HOTKEY_SWITCH_SOURCE = "ctrl+alt+s"             # 切换 麦克风 <-> 系统声音
HOTKEY_CLEAR_CAPTIONS = "ctrl+alt+backspace"   # 清空字幕条（当前+历史）
HOTKEY_TOGGLE_CAPTION = "ctrl+alt+b"           # 显示/隐藏字幕窗（会话保持）
