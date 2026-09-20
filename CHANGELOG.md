# Changelog

本项目的显著变更记录于此。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- 断线自动重连：意外断开后指数退避重连 3 次（5s/15s/45s），重连期间可被用户操作打断；次数用尽落入可见错误态
- 多屏支持：字幕窗按所在屏幕（而非主屏）钳制位置与宽度
- 测试套件（pytest，offscreen 无头可跑）：controller 生命周期/竞态回归、UI 冒烟、历史存储
- CI（GitHub Actions）：push 跑测试 + 构建 exe artifact；打 `v*` tag 自动发布 Release

### Fixed
- 连接期间点"停止"后会话可能自行恢复运行（启停竞态）
- 连接超时后 WebSocket 线程残留（幽灵会话）
- 停止时控制台误报"音频读取失败"
- 主动停止被误报"连接断开"
- 历史窗刷新每行读取一次 settings.json（500 行=500 次磁盘读）

## [1.0.0] - 2026-09-20

### Added
- 首个公开版本：Qwen3.8-LiveTranslate-Flash-Realtime 实时双语字幕
- 麦克风/系统声音（WASAPI loopback）双来源，16kHz 重采样
- 悬浮字幕窗：连续速录、句数裁剪、拖拽/边缘缩放+位置记忆、点击穿透、延迟角标
- 深/浅双主题（QSS token 引擎）、翻译历史（SQLite+CSV 导出）、全局热键
- 图形控制台：来源/语种/启停/外观实时调节、API key 管理
