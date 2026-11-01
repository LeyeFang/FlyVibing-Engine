"""裸 print 清单新鲜度（core，无头）。

`Doc/Dev/print_inventory.md` 由 `Utils/Dev/print_audit.py` 生成；本测试保证
"新增/删除裸 print 而清单未更新" 会立刻变红（评审可见 diff）。
迁移约定见清单 §4。
"""

# TIER: core

from __future__ import annotations

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

_ROOT = os.path.dirname(os.path.abspath(__file__))
while _ROOT and not os.path.exists(os.path.join(_ROOT, "startup.bat")):
    _parent = os.path.dirname(_ROOT)
    if _parent == _ROOT:
        _ROOT = ""
        break
    _ROOT = _parent
sys.path.insert(0, os.path.join(_ROOT, "Utils", "Dev"))
import print_audit  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def main() -> int:
    print("== print inventory freshness ==")
    rendered = print_audit.render()
    try:
        with open(print_audit.OUT, encoding="utf-8") as fh:
            current = fh.read()
    except OSError:
        current = ""
    check("print_inventory.md exists", bool(current), print_audit.OUT)
    check("print_inventory.md is fresh", rendered == current,
          "run: .venv-py314t\\Scripts\\python.exe Utils/Dev/print_audit.py")

    total_line = [l for l in rendered.splitlines() if l.startswith("| **合计**")]
    print(f"  [info] {total_line[0] if total_line else 'n/a'}")

    total = _RESULTS["pass"] + _RESULTS["fail"]
    ok = _RESULTS["fail"] == 0
    print()
    print(f"RESULT: {'OK' if ok else 'FAIL'} ({_RESULTS['pass']}/{total})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
