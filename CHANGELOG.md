# Changelog

本项目的显著变更记录于此。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [1.0.1] - 2026-09-20

第五/六轮审计修复（含退出与重连场景的数据完整性）。

### Fixed
- 退出时最后一句译文静默丢失：closeEvent 现在先停事件泵并 drain 完队列再关历史库
- 断线重连窗口（5-65s）内旧会话原文可能被新会话译文错配入库：进入连接态即清空配对队列与延迟计时
- 意外断线时"连接断开"提示双发导致字幕窗状态行闪烁：统一由重连引擎单点发布（含退避进度）
- ERROR 态下 restart 走完整收尾绕路：现与 IDLE 同路径直达重连
- 句子裁剪起点理论负偏移：前移量加 0 下界钳制，防裁剪窗口错位
- close() 在从未连接时不再起多余收尾线程；close 后迟到的服务器消息不再污染新会话
- restart() 的 0.6s sleep 竞态窗：改为锁内原子换持
- 连接期间点停止后会话自行复活（启停竞态）；连接超时后 WebSocket 幽灵线程
- 停止时误报"音频读取失败"；主动停止被误报"连接断开"；重连进度现显示在字幕窗状态行

### Added
- 会话边界回归测试（退出 drain / 配对队列清理），累计 26 用例

## [1.0.0] - 2026-09-20

首个公开版本（对应 git tag `v1.0.0`，含 Release exe）。

### Added
- 实时双语字幕：Qwen3.8-LiveTranslate-Flash-Realtime（DashScope WebSocket）
- 麦克风/系统声音（WASAPI loopback）双来源，16kHz 重采样
- 悬浮字幕窗：连续速录、句数裁剪、拖拽/边缘缩放+位置记忆、点击穿透、延迟角标
- 深/浅双主题（QSS token 引擎）、翻译历史（SQLite+CSV 导出）、全局热键
- 图形控制台：来源/语种/启停/外观实时调节、API key 管理
- 断线自动重连：意外断开后指数退避重连 3 次（5s/15s/45s），重连期间可被用户操作打断；次数用尽落入可见错误态；重连进度显示在字幕窗
- 多屏支持：字幕窗按所在屏幕（而非主屏）钳制位置与宽度
- 测试套件（pytest，offscreen 无头可跑）：controller 生命周期/竞态回归、UI 冒烟、历史存储，共 24 用例
- CI（GitHub Actions）：push 跑测试 + 构建 exe artifact；打 `v*` tag 自动发布 Release

### Fixed
- 连接期间点"停止"后会话可能自行恢复运行（启停竞态）
- 连接超时后 WebSocket 线程残留（幽灵会话）
- 停止时控制台误报"音频读取失败"
- 主动停止被误报"连接断开"
- 历史窗刷新每行读取一次 settings.json（500 行=500 次磁盘读）
