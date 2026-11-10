"""test_runner 选测语义守卫 — `--affected` / `--changed` 的选取规则。

锁定（协议: dev/test_protocol §1/§2）:
  1. 源码路径 → 按 `test_nodes.json` 的 covers 选中对应测试
  2. 测试文件 / UI 场景文件自身被改动 → 选中它自己（covers 只描述「源码 → 测试」）
  3. `--affected/--changed` 默认档位 **不选** manual / live；显式 `--tier` 时尊重用户
  4. 文档 / 配置类改动 → 映射为空（由调用方决定「显式路径=错、--changed=正常」）

背景: 这套「改哪跑哪」的框架曾因入口没写清而被 `--tier core` 全量替代，加上测试文件
自身不会被选中、未跟踪目录不展开，实际用起来会漏测或干脆退化成全量 —— 本测试把语义钉住。

用法:
    .venv-py314t\\Scripts\\python.exe Test/Application/Core/test_test_runner_selection.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
while ROOT and not os.path.exists(os.path.join(ROOT, "startup.bat")):
    parent = os.path.dirname(ROOT)
    if parent == ROOT:
        ROOT = ""
        break
    ROOT = parent
assert ROOT, "repo root not found"
DEV = os.path.join(ROOT, "Utils", "Dev")
if DEV not in sys.path:
    sys.path.insert(0, DEV)

import test_runner as tr  # noqa: E402

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        _failures.append(name)


def main() -> int:
    print("-- 1. 源码路径 → covers --")
    names, reasons = tr._affected_names(["Application/Editor/Services/PortLedger.py"])
    check("PortLedger → test_port_ledger", names == {"test_port_ledger"}, str(names))
    check("给出选取理由", "covers:" in reasons.get("test_port_ledger", ""),
          str(reasons.get("test_port_ledger")))

    names, _ = tr._affected_names(["Application/Editor/StartupOptions.py"])
    check("StartupOptions → 两个测试", {"test_editor_settings", "test_port_ledger"} <= names,
          str(sorted(names)))

    print("-- 2. 测试 / 场景文件 → 它自己 --")
    names, reasons = tr._affected_names(["Test/Application/Editor/test_port_ledger.py"])
    check("测试文件选中自己", names == {"test_port_ledger"}, str(names))
    check("理由标 self:test", reasons.get("test_port_ledger") == "self:test",
          str(reasons.get("test_port_ledger")))

    names, reasons = tr._affected_names(["Test/Application/Editor/scenarios/panels_smoke.py"])
    check("场景文件选中自己", names == {"panels_smoke"}, str(names))
    check("理由标 self:scenario", reasons.get("panels_smoke") == "self:scenario",
          str(reasons.get("panels_smoke")))

    print("-- 3. 文档 / 未知路径 --")
    names, _ = tr._affected_names(["CHANGELOG.md", "Doc/Dev/test_protocol.md"])
    check("文档类改动不映射测试", names == set(), str(names))

    print("-- 4. 档位策略（manual/live 不自动跑）--")
    fake = [
        ("Test/Application/Editor/test_port_ledger.py", "x", "core"),
        ("Test/Application/Editor/test_live_ui.py", "x", "manual"),
        ("Test/Application/Editor/test_e2e_node_group_live.py", "x", "live"),
        ("Test/Application/Renderer/test_gl_pixels.py", "x", "core"),
    ]
    kept, skipped = tr._apply_tier_policy(fake, affected=True, tier=None)
    check("affected 默认去掉 manual/live", {t[2] for t in kept} == {"core"}, str([t[2] for t in kept]))
    check("被跳过的数量", len(skipped) == 2, str(len(skipped)))

    kept, skipped = tr._apply_tier_policy(fake, affected=True, tier="live")
    check("显式 --tier 尊重用户", len(kept) == 4 and not skipped, f"{len(kept)}/{len(skipped)}")

    kept, skipped = tr._apply_tier_policy(fake, affected=False, tier=None)
    check("全量门禁不受影响", len(kept) == 4 and not skipped, f"{len(kept)}/{len(skipped)}")

    print("-- 5. 未跟踪目录展开 --")
    check("非源码根不展开（产物目录）", tr._expand_untracked_dir("MISSSEP_recordings/") == [])
    check("普通文件原样返回",
          tr._expand_untracked_dir("Application/Editor/Services/PortLedger.py")
          == ["Application/Editor/Services/PortLedger.py"])

    print()
    if _failures:
        print(f"RESULT: FAILED ({len(_failures)}) — " + ", ".join(_failures))
        return 1
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
