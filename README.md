# Qwen LiveTranslate 悬浮字幕客户端

[![License: MIT](https://img.shields.io/badge/License-MIT-14B8A6.svg)](./LICENSE)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows%2010%2F11-0EA5E9.svg)]()
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)]()
[![API: Qwen3.8 Realtime](https://img.shields.io/badge/API-Qwen3.8%20Realtime-6E56CF.svg)]()

基于阿里云百炼 **Qwen3.8-LiveTranslate-Flash-Realtime** 同传模型（DashScope WebSocket API）的实时双语字幕工具，形态类似 Live Captions Translator：**图形控制台 + 透明置顶悬浮双语字幕**，支持麦克风与系统声音双来源、整段连续字幕、深/浅双主题、外观实时调节。

> 适合场景：看外语视频/会议实时出双语字幕、外语课堂同传辅助、给 OBS/直播叠加字幕条。仅 Windows（依赖 WASAPI 系统声音采集）。

## 功能一览

| 能力 | 说明 |
|---|---|
| **深/浅双主题** | 标题栏 ☀/🌙 一键切换（记忆偏好）：teal→sky 渐变强调色（#14B8A6→#0EA5E9，主按钮/滑杆/选中态）+ 冷调青灰中性色阶；全控件文字居中；字幕窗恒深色保证叠视频可读 |
| 图形控制台 | 来源（麦克风/系统声音）、**源语言（自动识别/德/英/中/日/法/西/俄）**与目标语种点选即存，一键启停，状态实时显示 |
| Key 管理 | 控制台内直接粘贴保存 key（密码框可显显隐，存本地 settings.json；留空回退环境变量 DASHSCOPE_API_KEY） |
| 字幕清理 | **🗑 清空字幕**按钮 / 快捷键 Ctrl+Alt+Backspace，一键清除当前+历史字幕条 |
| 实时同传 | 语音 → 原文（ASR）→ 译文，双语同屏流式刷新 |
| 悬浮字幕 | 透明圆角置顶窗，可拖动，Ctrl+Alt+Space 或控制台按钮切换点击穿透 |
| **边缘缩放** | **拖字幕条左/右边缘调宽度、下边缘/右下角调高度**（所见即所得，松手持久化；双击字幕条恢复自适应高度；宽度钳制屏内） |
| 字幕增强 | 字号 0.7~2.0x、背景不透明度、最大行数实时滑杆调节（**启动即显数值**）；显示原文/延迟开关（宽度直接拖字幕条边缘） |
| 保留句数上限 | **display_sentences 滑杆（1~10）**：整段化后原文/译文各自保留的句数（超出删最旧整句）；句子**连成整段**——CJK 无缝、拉丁句间智能空格 |
| 翻译历史 | **🕘 历史**按钮打开历史窗：SQLite 落库每句终稿（时间/语种/原文/译文/延迟），双击行复制译文，一键导出 CSV（UTF-8-BOM），可清空 |
| 窗口位置记忆 | 字幕窗拖到哪，下次启动在哪（松手即存 settings.json；含屏幕边界校验） |
| 显示延迟 | **⚡ 显示延迟**开关：字幕窗左上角实时显示每句翻译延迟（speech_started → 译文终稿，毫秒） |
| 双来源 | 麦克风（对话/口语练习）/ 系统声音 loopback（网课/视频/会议），运行中热切换自动重连 |
| 设置持久化 | settings.json 自动保存（**不存 key**），下次启动记住全部偏好 |

## 1. 申请 API Key（付费模型，注意限流）

1. 打开 https://bailian.console.aliyun.com/ （阿里云百炼，即 DashScope）
2. 注册/登录 → 左侧「API-KEY」→「创建新的 API-KEY」→ 复制 `sk-` 开头的 key
3. 该模型为付费调用（无免费额度时需充值少量金额），限流 RPM 10 / TPM 100K

## 2. 环境依赖与安装

| 依赖 | 要求 |
|---|---|
| 操作系统 | Windows 10/11（系统声音采集依赖 WASAPI loopback） |
| Python | 3.10+（exe 方式无需） |
| 网络 | 能访问 `dashscope.aliyuncs.com` |

```powershell
pip install -r requirements.txt
```

依赖：`websocket-client`（协议）、`PySide6`（悬浮窗）、`PyAudioWPatch`（采集，含 WASAPI loopback）、`keyboard`（全局热键）。（开发/测试期另装过 edge-tts、soundfile、PyInstaller，均非运行时依赖）

## 3. 运行

### 方式一：exe（推荐）
从 [Releases](../../releases) 下载 `QwenLiveTranslate.exe`（44MB 单文件，无需 Python 环境）。
- 前提：系统环境变量 `DASHSCOPE_API_KEY` 已 setx（用户级即可）
- 首次启动比脚本慢几秒（自解压）；settings.json 存在 exe 同目录
- 换电脑：拷 exe + 在新机 setx key 即可

### 方式二：Python 脚本
双击 `start.bat` 或命令行 `python main.py`（同样进 UI）。

### 从源码打包 exe
```powershell
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name QwenLiveTranslate --add-data "config.py;." --add-data "theme.py;." --add-data "app.ico;." --icon app.ico main.py
```

---

启动后：
1. 选声音来源：`🎤 麦克风` / `🔊 系统声音`
2. 选目标语种（德/英/中/日/法/西/俄）
3. 点 **开 始 同 传** → 右下角悬浮字幕窗出现（key 也可不 setx，直接粘进控制台 API Key 框保存）
4. 外观卡片区实时调：字号/不透明度/行数滑杆，显示原文、延迟开关，点击穿透按钮（宽度拖字幕条边缘）
5. 关闭控制台窗口即全部退出

## 4. 使用技巧与快捷键

**全局热键（运行中随时可用）：**

| 快捷键 | 功能 |
|---|---|
| `Ctrl+Alt+Space` | 切换字幕**点击穿透**（穿透时鼠标可点穿字幕操作底下窗口） |
| `Ctrl+Alt+B` | 显示/隐藏字幕窗（会话保持） |
| `Ctrl+Alt+Backspace` | 清空字幕条（当前+历史） |
| `Ctrl+Alt+S` | 切换声音来源 麦克风 ↔ 系统声音（自动重连） |

**典型场景：**

- **看外语视频出双语字幕**：来源选「系统声音」→ 目标语种选「中文」→ 播放视频即出「原文+中文译文」同屏字幕
- **网课/会议同传辅助**：来源选「麦克风」放讲台音，或「系统声音」听远端；开「显示延迟」可观察翻译实时性
- **边看边干别的**：字幕条拖到合适位置后按 `Ctrl+Alt+Space` 开穿透——字幕浮在上层但完全不挡操作
- 运行中改来源/语种会**自动重连**（限流 RPM 10，别频繁切）
- 原文行浅蓝、译文行白色大字；翻译历史点控制台「历史」查看/导出 CSV

## 5. 排障

| 现象 | 处理 |
|---|---|
| 提示未设置 key | 确认已 `setx DASHSCOPE_API_KEY "sk-xxx"`（用户级，setx 后需**新开**终端/双击才生效；脚本方式也可当前会话 `$env:` 临时设） |
| 连接/会话超时 | 检查网络；确认 key 有效（百炼控制台可查）；限流 RPM 10，别高频重启 |
| 无字幕 | 状态栏看"检测到语音"是否出现；系统声音模式需电脑正在播放声音 |
| 采集失败 | 运行 `python capture.py --list-devices` 检查设备（蓝牙耳机需处于连接状态才会出现在 loopback 列表） |

## 6. 文件结构

```
qwen-livetranslate/
├── main.py              # 入口：启动图形控制台
├── console.py           # 图形控制台（来源/语种/启停/外观/历史入口/延迟开关）
├── controller.py        # 会话控制器（采集+WS+推流生命周期，启停竞态防护）
├── realtime_client.py   # WebSocket 协议层（qwen3.8 事件流路由）
├── capture.py           # 音频采集（mic / loopback + 重采样；--list-devices 枚举设备）
├── overlay.py           # 悬浮双语字幕窗（连续速录+句数裁剪+位置记忆+延迟角标+点击穿透）
├── history.py           # 翻译历史 SQLite 存储（线程安全+CSV 导出）
├── history_view.py      # 历史查看窗（表格/复制/导出/清空）
├── settings.py          # 设置持久化 settings.json（key 白名单落盘；exe 旁存储）
├── config.py            # 静态配置（端点/采样参数/热键）
├── theme.py             # 主题引擎（深/浅 token + QSS 生成 + 几何图标）
├── make_icon.py         # 应用图标生成脚本（Pillow 画「对话双泡」→ app.ico，可重跑再生）
├── app.ico              # 应用图标（渐变「译」字，多尺寸）
├── QwenLiveTranslate.spec  # PyInstaller 打包配置
├── start.bat            # 双击启动（脚本方式，key 已 setx）
├── sample_16k.wav       # 端到端测试样本（中文）
├── sample_en_16k.wav    # 端到端测试样本（英语）
├── e2e_*.txt            # 端到端验证日志（协议联调实录）
├── requirements.txt     # 运行时依赖
├── LICENSE / CONTRIBUTING.md / CODE_OF_CONDUCT.md
└── .gitignore           # 拦截 build/dist/本地配置/历史库等
```

重新打包（**用 `--windowed`**，无黑色控制台窗，2026-09-20 类名枚举法实测双 Qt 窗口+零控制台正常。注：2026-09-19 曾判 windowed 静默失败，后证实系当时按标题匹配枚举 Qt Tool 窗漏检所致，平反）：见上文「从源码打包 exe」完整命令（必须带 `--add-data "theme.py;."`，否则 exe 缺主题引擎启动即崩）

## 7. 踩坑实录（2026-09-19 真机联调验证）

| 坑 | 解法 |
|---|---|
| **qwen3.8 默认音色 Chelsie 触发 400**（`InternalError.Algo.InvalidParameter: Voice 'Chelsie' is not supported`） | `session.update` 必须显式指定 `audio.output.voice`（已内置 `"Tina"`，验证可用） |
| 断线后推流线程盲发报错刷屏 | `_send` 前检查连接状态 + 推流循环断线即退（已修复） |
| **推流循环曾加 0.1s sleep → 半速推流**（每 200ms 墙钟只推 100ms 音频，长会话延迟无限增长——短样本 E2E 测不出，真机长会话才暴露） | 节拍由 read_chunk 阻塞读天然保证（~10帧/s 实测），**严禁再加 sleep**（2026-09-20 审计修复） |
| **`<br>` 不是 QTextBlock**（QTextBrowser 连续速录版句数裁剪踩坑） | `<br>` 是块内软换行（U+2028），按 block 数段落永远是 1，裁剪静默失效；必须按字符级行分隔符扫描后用 QTextCursor 删头部区间（2026-09-19 offscreen 测试抓到） |
| PySide6 `characterAt()` 返回 str 不是 QChar | 用 `ord(ch)` 取码点，不能 `.unicode()` |
| E2E 验证结果 | ① 中→德：6.65s 中文 TTS 样本 → ASR 原文逐字正确 → 德语译文完整（`e2e_log.txt`）；② 英→中：英语样本 → 英语原文 + 中文字幕两轮完整输出，逐句对应（`e2e_en2zh_log.txt`）；③ 体验包四件套（句数裁剪/历史/位置记忆/延迟）offscreen 全过（2026-09-19） |

## 8. 协议速查（qwen3.8-livetranslate-flash-realtime）

- 端点：`wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=qwen3.8-livetranslate-flash-realtime`
- 鉴权：`Authorization: Bearer $DASHSCOPE_API_KEY`
- 会话：`session.update {output_modalities:["text"], translation:{language:"de"}, audio:{output:{voice:"Tina"}}}`（3.8 的 ASR 常开免费；注意 3.8 用 `output_modalities`，3.5 才是 `modalities`；**voice 必须显式指定**，默认 Chelsie 会 400）
- 推流：`input_audio_buffer.append {audio: base64(16kHz/16bit/mono PCM)}`，100ms/帧
- 原文：`conversation.item.input_audio_transcription.delta/.completed`（3.8 是 `.delta` 系；3.5 是 `.text` 系）
- 译文：`response.text.delta` → `response.text.done`（文本模态）
- 结束：`session.finish` → 等 `session.finished` → 断开

---

## License

[MIT](./LICENSE) © 2026

## 隐私说明

- API key 仅存本机（环境变量或 settings.json），不经过任何第三方服务器，直连阿里云 DashScope
- 翻译历史存本地 SQLite（`translation_history.db`），不上传
- 音频仅实时推流至 DashScope 做识别翻译，不落盘

## 参与贡献

欢迎 PR 与 Issue！开发约定（环境要求/代码规范/测试要求）见 [CONTRIBUTING](./CONTRIBUTING.md)；行为准则见 [Code of Conduct](./CODE_OF_CONDUCT.md)。
