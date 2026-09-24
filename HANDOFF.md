# QwenLiveTranslate 项目交接文档

> 生成日期：2026-09-24 ｜ 版本：**v1.0.5（`fbea43b` + 1.0.5 发版提交）** ｜ 目标读者：接手本项目的下一个 AI Agent 或人类开发者
> 配套记忆：`.workbuddy/memory/2026-09-19~23.md`（每日开发日志，含全部决策上下文）

---

## 1. 项目定位与一句话概括

**Windows 实时同传字幕工具**：采集麦克风或系统声音（loopback），推流到阿里云 DashScope 的 `qwen3.8-livetranslate-flash-realtime` WebSocket 端点做端到端"语音→翻译"，流式渲染到悬浮双语字幕条。PySide6 桌面应用 + PyInstaller 单文件 exe 发布。

- 仓库：https://github.com/huankechong/QwenLiveTranslate（master 已推平，CI windows-latest + Python 3.13）
- 状态：**v1.0.5 已发布**（6 个 Release），38 测试全绿，10 轮审计完成
- 定位双目标：开源热度（对标 SakiRinn/LiveCaptions-Translator 3746★）+ 作者作品集

## 2. 技术栈与依赖

| 类别 | 内容 |
|------|------|
| 语言 | Python 3.13（CI 固定），本地同版本 |
| UI | PySide6 ≥6.7（QTextBrowser 流式渲染 / QPropertyAnimation / QSS 主题） |
| 音频 | PyAudioWPatch ≥0.2.12（WASAPI loopback 是它家的独有能力） |
| 网络协议 | websocket-client ≥1.8（同步 WS，无 asyncio——**线程模型是全项目根基**） |
| 导出 | openpyxl ≥3.1（历史 xlsx） |
| 其他 | keyboard ≥0.13.5（全局热键，Windows 需管理员权限才可靠） |
| 打包 | PyInstaller ≥6.0，spec：`QwenLiveTranslate.spec`（onefile+windowed，datas 含 config.py/theme.py/app.ico） |

**requirements.txt 与实际 import 逐一对齐（第 9 轮审计验证过），无冗余依赖。**

## 3. 目录结构与模块职责（约 3700 行 Python）

```
qwen-livetranslate/
├── main.py               # 入口：装配 Console
├── console.py            # 主控制台 UI（设置/启停/热键/历史入口/延迟计时口径A）
├── overlay.py            # 悬浮字幕窗（最复杂：流式写入/裁剪/高度分配/动画/拖拽缩放/穿透）
├── controller.py         # SessionController 状态机（IDLE/CONNECTING/RUNNING/STOPPING/ERROR
│                         #   + start_token 竞态防护 + 5/15/45s×3 指数退避重连引擎）
├── providers/            # 多引擎抽象层（Phase 0 刚落地，仅 qwen 一个 provider）
│   ├── base.py           #   LiveEngine 门面 Protocol + AudioSpec/EngineCaps
│   ├── registry.py       #   显式注册表（ProviderSpec，拒绝反射发现）
│   ├── engine_io.py      #   engine_push_loop 通用推流循环
│   ├── qwen_livetranslate.py  # QwenEngine：包装 LiveTranslateClient（client 类零改动）
│   └── __init__.py       #   build_engine(cfg, callbacks) 唯一工厂入口
├── realtime_client.py    # qwen3.8 WS 协议层（事件路由/聚合字典/信封内收 push_audio）
├── capture.py            # AudioCapture（mic/loopback，采样率参数化，线性重采样）
├── history.py            # SQLite 历史（WAL+锁；CSV/xlsx 双导出）
├── history_view.py       # 历史窗 UI
├── settings.py           # settings.json 持久化（DEFAULTS 白名单 + 原子写 + _RW_LOCK
│                         #   + resolve_provider_cfg 三级回退：档→旧顶层key→env）
├── config.py             # 静态常量（__version__/端点/热键）
├── theme.py              # 深浅主题 token + QSS 生成（exe 必须带，缺了启动即崩）
├── tests/                # 38 测试（pytest，offscreen 可跑，无需音频设备/key）
│   ├── conftest.py       #   fakes fixture：patch 的是 CTRL.build_engine 工厂！
│   ├── test_controller.py    # 状态机/重连/竞态
│   ├── test_history.py       # 存储/导出/原子写/字典清理
│   └── test_ui_smoke.py      # UI 冒烟/动画/布局矩阵
├── .github/workflows/ci.yml  # 双 job：test（offscreen pytest）+ build→release（打 tag 触发）
├── README.md / README.en.md  # 中英双语（已与实现对齐，第 9 轮审计）
├── CHANGELOG.md          # Keep a Changelog，1.0.0~1.0.4 完整
└── QwenLiveTranslate.spec
```

**模块依赖方向（勿破坏）**：`console → controller → providers.build_engine → realtime_client`；`console/overlay → settings`；`history ← console/history_view`。

## 4. 核心执行流程（读代码的推荐顺序）

```
main → Console(UI) → 用户点"开始"
  → SessionController.start()（锁内：幂等检查+token+1+置 CONNECTING）
  → 锁外：build_engine(cfg, callbacks) 造 QwenEngine
  → AudioCapture.start()（按 engine.audio_spec.sample_rate）
  → engine.connect(15s) → engine_push_loop 线程（100ms/帧实时节拍，严禁 sleep）
  → WS: session.update → 音频 append → 收 transcription.delta/completed(原文)
       + response.text.delta/done(译文) + speech_started/stopped(VAD)
  → controller._emit → console._enqueue（事件泵，QTimer 80ms drain）
  → overlay.set_source/set_translation（前缀 diff 增量写入 + QTimer.singleShot(0) 滚动）
  → _trim_lines 裁剪（句数+显示高度双约束，保底优先级 both2→src2+trn1→both1）
  → 句终 → history.add（配对 _pending_srcs 30s 新鲜度窗口）
意外断线 → on_disconnect → 重连引擎（新 token，5/15/45s 退避，3 次耗尽 → ERROR）
```

## 5. 构建 / 运行 / 测试

```powershell
# 运行（源码）
pip install -r requirements.txt
python main.py            # 或 start.bat（需已 setx key）

# 测试（offscreen，无音频/key 要求）
pytest tests/ -q          # 38 用例，约 10s

# 打包
pyinstaller --noconfirm QwenLiveTranslate.spec
dist\QwenLiveTranslate.exe   # 49MB 单文件
```

**真机验证套路**（改 UI/布局必做）：`dist` 下启动 exe → EnumWindows 抓标题栏核对版本号 → tasklist 确认进程。

## 6. 配置与环境变量

| 项 | 位置 | 说明 |
|---|---|---|
| `DASHSCOPE_API_KEY` | 环境变量 | key 三级回退链的第三级（最优先的是 settings 里的档/顶层 key） |
| settings.json | exe 旁 / 脚本同目录 | DEFAULTS 白名单过滤——**新增任何 key 必须同步加进 DEFAULTS，否则 save 时静默丢弃**（第 1 坑） |
| 关键键 | — | source/source_lang/lang/api_key/height/width/font_scale/max_lines/display_sentences/engine_mode/provider/asr_provider/mt_provider/provider_configs/provider_indices |

**注意**：settings.json 含用户明文 key，**git 已忽略，永不入库**。

## 7. 已完成功能（v1.0.0→v1.0.5）

1. 核心同传（双音频源/流式双语字幕/延迟角标）
2. 历史 + xlsx/CSV 双导出（真日期单元格）
3. 字幕体验：淡入淡出、前缀 diff 流式（零闪烁）、字号 15px 基准、点击穿透、拖拽缩放
4. 稳定性：10 轮审计累计修 30+ bug（退出丢末句/跨会话错配/原子写盘/内存泄漏/裁剪粒度等）
5. **v1.0.4/v1.0.5 字幕布局双修复**：折行长句遮顶行（显示高度裁剪）+ 原文只剩一两句（三层根因：relayout 覆盖/比例削穿保底/窗高物理不足→bare_min 护栏）
6. providers 抽象层（Phase 0，零行为变化，qwen 无缝迁入）
7. 开源基建：双语 README/CI/Issue 模板/社区规范/隐私声明

## 8. 进行中 / 待办（按优先级）

| 优先级 | 任务 | 状态 |
|--------|------|------|
| 🟠 P1 | Phase 1 多引擎垂直切片：硅基流动（SenseVoice ASR + Chat 翻译，用户已有 key）→ v1.1.0。方案详见记忆 2026-09-23 | 设计完成待开工 |
| 🟠 P1' | 翻译注册表一次挂 3 免费预设：siliconflow_chat / bigmodel_glm4flash / hunyuan_mt（腾讯混元翻译，免费） | 同上 |
| 🟡 P2 | 生词本 + Anki 导出（用户刚需+传播故事） | 未开工 |
| 🟡 P2' | OBS Browser Source 网页字幕条（传播引爆点） | 未开工 |
| ⚪ P3 | winget 发布 / 延迟统计图 / GPT-Realtime-Translate / 豆包同传 / 本地 whisper | 远期 |

## 9. 已知问题与技术债

| 级别 | 项 | 说明 |
|------|---|------|
| 🟡 | capture.stop() 非线程安全 | `_stream=None` 无锁，靠 PyAudio 异常+推流侧兜底"巧合性安全"；防御重构风险>收益，第 8 轮审计决定注记不修 |
| 🟡 | M1 遗留：`_relayout_browsers` 与 `apply_cfg` 的双重写权 | v1.0.4 后 relayout 已去覆盖化（只处理拖大），但两个写点并存仍是复杂度来源——Phase 1 动布局时建议合并为单一分配函数 |
| 🟡 | 测试盲区 | `engine_io` 错误路径已补测，但 `resizeEvent`/拖拽缩放（WM_NCHITTEST 路径）无自动化——改 overlay 布局必须真机验证 |
| 🟢 | e2e_*.txt 三个 0KB 空日志 | 历史遗留，可删 |
| 🟢 | sample_16k.wav 系测试资产 | 端到端验证脚本曾用，现在测试已不引用——保留无害 |
| 🟢 | `__pycache__` 陷阱 | **offscreen 测试改代码后必须 `rm -rf __pycache__` + `python -B`**，否则跑旧字节码——9/23 排障被坑 5 轮 |

## 10. 潜在风险与红线

1. **qwen3.8 是项目唯一引擎**——阿里协议变更即全瘫；providers 抽象层就是为此而生（Phase 1 必须走完）
2. **settings 白名单吞键**：每次加配置键，DEFAULTS 同步是硬约束（已有专项意识，无测试强制）
3. **PyInstaller 收集**：providers/ 若改为懒加载导入，spec 的 hiddenimports 必须显式加
4. **叠加时序坑**：overlay 的 `resizeEvent`/`_relayout_browsers`/`apply_cfg` 三者都写高度——**改布局前先 grep 所有 setFixedHeight 调用点**
5. **用户审批制**：commit/push/tag/Release 必须先列改动清单获用户明示批准（用户红线第 0 条，9/22 曾因违例被严厉警告）
6. **隐私**：settings.json/translation_history.db 含用户数据，任何调试产物不得入库

## 11. 迁移注意事项与建议交接顺序

### 必须保留的关键上下文（否则重蹈覆辙）

1. **回调签名冻结**：`on_source(speaker, text, final)` 等五回调是 overlay/history/console 零改动的契约——改引擎时签名绝对不能动
2. **`display_sentences` 限句数 vs 视口限显示行**是两回事——裁剪必须双约束（9/23 修了一整天）
3. **推流循环严禁加 sleep**（吞吐<实时=延迟无限涨，历史事故）
4. **9/23 的"原文只剩一两句"修复**（已入库 `fbea43b`）是三层根因叠加的产物：_relayout 覆盖 + 比例削穿保底 + 窗高物理不足——别只看 diff 表面
5. **测试桩打的是 build_engine 工厂**，不是 client 类（Phase 0 改的，别回退）
6. 端到端验证要用 **WAV 样本推流**（麦克风环境静音时零事件是正常现象，不是 bug）

### 建议交接顺序

```
第 1 步：读本交接文档 + 记忆文件（9/19~9/23 日志）
第 2 步：跑 pytest tests/ -q 确认 38 绿（基线健康检查）
第 3 步：真机启动 dist exe 复现一遍用户场景（h=256 + display_sentences=10）
第 4 步：按 P1 路线开 Phase 1（先读记忆里的完整 Phase 0/1 方案）
第 5 步：每次发版走既定节奏：测试→打包→真机验版本号→暂存→用户批三连→CI→Release
```

### 快速验证清单（接手后 10 分钟自检）

```bash
git log --oneline -3          # 应见 1.0.5 发版提交在顶
git status --short            # 干净（无未提交/未跟踪文件）
pytest tests/ -q              # 38 passed
python -c "import config; print(config.__version__)"   # 1.0.5
```

## 12. 外部服务依赖

| 服务 | 用途 | 依赖方式 |
|------|------|---------|
| 阿里云 DashScope | qwen3.8 同传 WS | 唯一推理引擎；`wss://dashscope.aliyuncs.com/api-ws/v1/realtime` |
| GitHub Actions | CI + Release 自动构建 | windows-latest + Py 3.13，打 tag 触发 release job |
| （计划）硅基流动/智谱/DeepL 等 | Phase 1+ 多引擎 | OpenAI 兼容协议，openai_compat 一个类覆盖 |

**无其他外部服务**。历史数据/设置全部本地。
