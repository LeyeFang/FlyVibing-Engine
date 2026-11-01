"""LogBus 控制台环形缓冲（core，无头）。

背景（2026-11-01，用户反馈 A4）:
  设备类节点失败时原因只进引擎控制台，CLI / agent 侧完全取不到。
  新增 `LogBus`（stdout/stderr tee + 环形缓冲）与 op `console.tail`。

本测试锁定:
  1. push 多行 → 行号递增，tail 可取回
  2. install 后 print 会被捕获（tee 不影响原输出）
  3. level 过滤（info / warn / error 启发式）
  4. since 增量轮询 + lines 上限
  5. clear 重置
"""

# TIER: core

from __future__ import annotations

import io
import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _parent = os.path.dirname(_d)
    if _parent == _d:
        _d = ""
        break
    _d = _parent
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402,F401

from Application.Core.Diagnostics.LogBus import LogBus  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def main() -> int:
    print("== LogBus tests ==")

    LogBus.clear()
    LogBus.push("alpha\nbeta\n")
    out = LogBus.tail(lines=10)
    check("push splits lines", [e["text"] for e in out["lines"]] == ["alpha", "beta"],
          str(out["lines"]))
    check("seq starts at 1", out["lines"][0]["seq"] == 1, str(out["lines"]))
    check("next_since is last seq", out["next_since"] == 2, str(out["next_since"]))

    out = LogBus.tail(since=1, lines=10)
    check("since skips older lines", [e["text"] for e in out["lines"]] == ["beta"])

    out = LogBus.tail(lines=1)
    check("lines limits result", len(out["lines"]) == 1, str(out["lines"]))

    LogBus.clear()
    LogBus.push("[ERROR] open failed: serial missing\n[WARN] retrying\ninfo line\n")
    out = LogBus.tail(level="error")
    check("level filter error", [e["text"] for e in out["lines"]] == ["[ERROR] open failed: serial missing"],
          str(out["lines"]))
    out = LogBus.tail(level="warn")
    check("level filter warn", len(out["lines"]) == 1 and out["lines"][0]["level"] == "warn",
          str(out["lines"]))
    out = LogBus.tail()
    check("info lines classified", any(e["level"] == "info" for e in out["lines"]), str(out["lines"]))

    LogBus.clear()
    original = sys.stdout
    sink = io.StringIO()
    sys.stdout = sink
    try:
        LogBus.install()
        print("hello from tee")
        LogBus.uninstall()
    finally:
        LogBus.uninstall()
        sys.stdout = original
    out = LogBus.tail()
    check("tee captures print", any("hello from tee" in e["text"] for e in out["lines"]),
          str(out["lines"]))
    check("tee forwards to original stream", "hello from tee" in sink.getvalue(), sink.getvalue())

    LogBus.clear()
    out = LogBus.tail()
    check("clear resets buffer", out["lines"] == [] and out["next_since"] == 0)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    ok = _RESULTS["fail"] == 0
    print()
    print(f"RESULT: {'OK' if ok else 'FAIL'} ({_RESULTS['pass']}/{total})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
