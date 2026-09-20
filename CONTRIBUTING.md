# 贡献指南（Contributing）

感谢你考虑为 Qwen LiveTranslate 贡献代码！

## 项目简介

Windows 实时双语同传字幕工具（Qwen3.8 Realtime API + PySide6）。贡献前建议先读 [README](./README.md) 的「踩坑实录」与「协议速查」两节——它们记录了真机联调中踩过的坑，能帮你少走弯路。

## 如何贡献

1. **Fork & Clone**
   ```powershell
   git clone https://github.com/<你的用户名>/QwenLiveTranslate.git
   cd QwenLiveTranslate
   ```
2. **建分支**：`git checkout -b feat/your-feature`（修复用 `fix/`，文档用 `docs/`）
3. **开发与自测**（见下方环境要求）
4. **提交**：commit message 用祈使句简述变更，如 `Add latency badge to overlay`
5. **Pull Request**：描述清楚改了什么、为什么改、如何验证

## 开发环境

- Windows 10/11（核心功能依赖 WASAPI loopback，暂不支持 macOS/Linux）
- Python 3.10+（开发验证用 3.13）
- 安装依赖：`pip install -r requirements.txt`
- 打包验证（可选）：`pip install pyinstaller` 后按 README「从源码打包 exe」一节执行

## 代码约定

- 单目录扁平结构，无包结构；新增模块直接放根目录
- UI 全部走 `theme.py` 的 token + QSS 生成器，**不要在业务代码里硬编码颜色/圆角**（圆角有 R_MICRO~R_WINDOW 常量体系）
- 涉及线程的改动必须注意：GUI 操作只允许主线程（跨线程用 Qt 信号中继，参考 `console.py` 的 `_HotkeyRelay`）
- 设置项走 `settings.py` 的 DEFAULTS 白名单，禁止落盘 API key 之外的任何凭据
- 中文注释欢迎，但公共 API 的 docstring 请保持信息完整（做了什么、为什么）

## 测试要求

- UI 改动：offscreen 冒烟（`QT_QPA_PLATFORM=offscreen`）至少验证启动不崩、控件存在、状态切换正常
- 协议/会话改动：说明你如何验证（可用 `sample_16k.wav`/`sample_en_16k.wav` 做端到端测试，注意 **API 限流 RPM 10**，别循环重建会话）
- 打包改动：附上 exe 时间戳断言或启动验证结果

## 报告 Issue

- Bug 报告请附：Windows 版本、Python 版本（或 exe 方式）、复现步骤、控制台错误信息（注意**先抹掉 key**）
- 功能建议请说明使用场景

## 行为准则

参与本项目即表示你同意遵守 [Code of Conduct](./CODE_OF_CONDUCT.md)。
