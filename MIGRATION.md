# 场景 B：新机器 / 新平台完整交接步骤（QwenLiveTranslate）

> 适用：换电脑、换 Agent 平台（Claude Code / Codex / 其他）、或给协作者。仓库在 GitHub，clone 即得全部。
> 交接包 = 仓库（代码+文档）+ 记忆目录（决策上下文）+ 一个 API key。

## 前置确认（已完成，2026-09-24）
- [x] 工作区干净，master=远端=`53d528d`
- [x] 仓库内零本机绝对路径/零个人路径（`junbo`/`D:\Documents` 零命中）
- [x] HANDOFF.md 已入库（新机器 clone 后第一份要读的文件）

## 第 1 步：clone 仓库

```bash
git clone https://github.com/huankechong/QwenLiveTranslate.git
cd QwenLiveTranslate
```

## 第 2 步：环境（Python 3.13）

```powershell
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
```

## 第 3 步：配置 API key（二选一）

```powershell
setx DASHSCOPE_API_KEY <YOUR_DASHSCOPE_KEY>
# 或启动后在控制台 UI 粘贴（存本机 settings.json，不入库）
```

## 第 4 步：基线验证（必须 38 passed）

```bash
pytest tests/ -q
```

## 第 5 步：读文档（顺序固定）

1. `HANDOFF.md` 全文（架构/流程/坑/红线/迁移清单）
2. 记忆日志：从旧机器拷 `.workbuddy/memory/2026-09-19.md ~ 2026-09-23.md` 到新机器的 `.workbuddy/memory/`（跨机才需要；同机同 WorkBuddy 则已就位）

## 第 6 步：真机冒烟

```powershell
pyinstaller --noconfirm QwenLiveTranslate.spec
dist\QwenLiveTranslate.exe   # 标题栏应显示 v1.0.5
```

## 第 7 步：开工

按 HANDOFF.md §8 的 P1 路线（Phase 1 硅基流动多引擎）。

---

## 铁律提醒（HANDOFF.md §10 红线区，违者返工）

1. **commit/push/tag/Release 前必须获用户明示批准**
2. 引擎回调签名冻结（on_source/on_translation/on_status/on_error/on_disconnect）
3. 裁剪双约束：句数 + 显示高度
4. 推流循环严禁 sleep
5. settings 加键必须同步 DEFAULTS
6. settings.json / translation_history.db 含用户数据，永不入库
