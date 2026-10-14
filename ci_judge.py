"""CI 测试裁决器：读 pytest 输出文件判定绿/红（退出码即裁决结果）。

背景：Windows runner 上 Qt offscreen 在解释器退出期的崩溃会把 shell
退出码污染成 1 / 0xC0000135 / 127 家族——shell 层（无论 pwsh 还是
bash + grep 管道）都可能带着这些码死去。因此把"pytest 全过即绿"的
判定放进独立的 python 进程：它不加载 Qt，退出码可信。

规则：
- 最后一行 summary 匹配 "N passed"（N>0）且无 " failed"/" error" 计数
  → exit 0
- 其他（含 0 collected / no tests ran）→ exit 1 并回显关键行
"""
import re
import sys
from pathlib import Path


def main() -> int:
    out = Path("pytest_out.txt")
    if not out.exists():
        print("ci_judge: pytest_out.txt missing", file=sys.stderr)
        return 1
    text = out.read_text(encoding="utf-8", errors="replace")
    # 回显（截断防日志爆炸）
    lines = text.splitlines()
    tail = lines[-25:]
    for ln in tail:
        print(ln)
    m = re.search(r"^(\d+) passed([^\n]*)$", text, re.M)
    summary_extra = m.group(2) if m else ""
    if (m and int(m.group(1)) > 0
            and " failed" not in summary_extra
            and " error" not in summary_extra
            and "no tests ran" not in text):
        print(f"ci_judge: GREEN ({m.group(1)} passed)")
        return 0
    print("ci_judge: RED (no clean pass summary)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
