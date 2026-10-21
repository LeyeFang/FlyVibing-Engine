"""扩展边界守卫（2026-10-16 事故复盘后立项首版 — 详见 Doc/Dev/extension_protocol.md §9）。

锁定:
  1. 内置扩展清单白名单 — Application/Functions/**（内置扫描根）的 extension.json id
     必须 ∈ 白名单。新增内置扩展 = 显式更新白名单（主团队意图动作），
     防止社区/三方插件被"顺手"放入扫描根（Gtec 事故类 — R2 红线）。
  2. 品牌词切断扫描 — Application/ Test/ Doc/ .github/ 全树禁止事故品牌字样
     （2026-10-16 已整体剥离）。豁免: 事故归档目录、运行产物（_runs / 编辑器 Config）、
     本地夹具关联文件、本测试自身。

运行: python Utils/Dev/test_runner.py --only extension_boundary
"""
# TIER: core

from __future__ import annotations

import json
import os
import re
import sys

_d = os.path.dirname(os.path.abspath(__file__))
_ROOT = _d
while _ROOT and not os.path.exists(os.path.join(_ROOT, "_path_setup.py")):
    _ROOT = os.path.dirname(_ROOT)
if _ROOT:
    sys.path.insert(0, _ROOT)
    import _path_setup  # noqa: E402
_REPO = os.path.dirname(_ROOT) if _ROOT else ""   # _ROOT = Test/ → 仓库根再向上一级

# 内置扩展白名单（主团队自研 —— 新增必须显式改这里, 见 extension_protocol.md §9 R2）
_BUILTIN_WHITELIST = {"sigproc", "bci", "device", "virtual"}
# 本地兼容夹具（社区插件恢复副本, git-ignored — 仅作扩展体系兼容性测试;
# 见 Application/Functions/Gtec/LOCAL_COMPAT.md 与 test_gtec_compat.py）
_LOCAL_COMPAT_IDS = {"gtec"}

# 事故品牌词（2026-10-16 剥离）; 未来同类处置在 §9 案例档案维护时同步加入
_BRAND_RE = re.compile(r"gtec|pygds|hiamp", re.IGNORECASE)
_SCAN_ROOTS = ("Application", "Test", "Doc", ".github")
_SCAN_EXT = {".py", ".md", ".json", ".scene", ".txt", ".cmd", ".bat"}
_SKIP_DIRS = {"_gtec_archive_20261016", "_archive", "_runs", "__pycache__", ".git", "dist"}
# 品牌探针路径豁免: 本地兼容夹具（Gtec 插件本体 — git-ignored, 专业豁免）+
# 运行产物（编辑器状态 Application/Editor/Config — git-ignored, 同 _runs 类）
_SKIP_PATHS = (os.path.join(_REPO, "Application", "Functions", "Gtec"),
               os.path.join(_REPO, "Application", "Editor", "Config"))
# 文件级豁免: 本地夹具关联测试/场景（git-ignored 本地资产）+ 引用夹具路径的守卫 + 本测试自身
_TEST_DIR = os.path.join(_REPO, "Test", "Application")
_SKIP_FILES = {os.path.abspath(__file__),
               os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_gtec_compat.py"),
               os.path.join(_TEST_DIR, "Extensions", "e2e_gtec_monitor_check.py"),
               os.path.join(_TEST_DIR, "Extensions", "test_gtec_extension.py"),
               os.path.join(_TEST_DIR, "Editor", "scenarios", "gtec_panel_smoke.py"),
               # 陈旧测试（EEGDevice 已解散; 待归档 — 标注 2026-10-16）
               os.path.join(_TEST_DIR, "Functions", "test_eeg_service.py"),
               os.path.join(_TEST_DIR, "Functions", "test_gtec_device.py"),
               # 线程边界守卫（引用夹具路径字面量 — 与 test_gtec_compat 同口径）
               os.path.join(_TEST_DIR, "Core", "test_thread_boundary.py")}

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _builtin_ids() -> dict:
    """扫描内置扩展根（Application/Functions/**/extension.json）→ {目录名: id}（递归）。"""
    found: dict[str, str] = {}
    root = os.path.join(_REPO, "Application", "Functions")
    if not os.path.isdir(root):
        return found
    for cur, _dirs, files in os.walk(root):
        if "extension.json" not in files:
            continue
        name = os.path.basename(cur)
        try:
            with open(os.path.join(cur, "extension.json"), "r", encoding="utf-8") as fh:
                found[name] = json.load(fh).get("id", "")
        except Exception as exc:  # noqa: BLE001 — 读不出也要报（清单损坏同属违规）
            found[name] = f"<unreadable: {exc}>"
    return found


def _brand_hits() -> list:
    hits: list[str] = []
    for rel in _SCAN_ROOTS:
        base = os.path.join(_REPO, rel)
        if not os.path.isdir(base):
            continue
        for cur, dirs, files in os.walk(base):
            if any(os.path.normcase(cur) == os.path.normcase(p)
                   or os.path.normcase(cur).startswith(os.path.normcase(p) + os.sep)
                   for p in _SKIP_PATHS):
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for fn in files:
                if os.path.splitext(fn)[1].lower() not in _SCAN_EXT:
                    continue
                path = os.path.join(cur, fn)
                if os.path.abspath(path) in _SKIP_FILES:
                    continue
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                        text = fh.read()
                except OSError:
                    continue
                # 归档路径字面量（工具/测试引用）不算品牌内容 — 掩码后再查
                masked = text.replace("_gtec_archive_20261016", "")
                m = _BRAND_RE.search(masked)
                if m:
                    line = masked[: m.start()].count("\n") + 1
                    hits.append(f"{os.path.relpath(path, _REPO)}:{line}")
    return hits


def main() -> int:
    print("=" * 60)
    print("extension boundary guard (built-in inventory + brand tripwire)")
    print("=" * 60)

    # ── 1. 内置扩展清单白名单（R2: 内置根只允许主团队自研件） ──
    print("── builtin inventory whitelist ──")
    inv = _builtin_ids()
    ids = set(inv.values())
    check("plugin dirs discovered", len(inv) >= 1, str(inv))
    extra = ids - _BUILTIN_WHITELIST - _LOCAL_COMPAT_IDS
    check("inventory ⊆ team whitelist", not extra,
          f"unexpected: {sorted(extra)} (inv={inv})")
    check("whitelist entries present", _BUILTIN_WHITELIST <= ids,
          f"missing: {sorted(_BUILTIN_WHITELIST - ids)} (inv={inv})")

    # ── 2. 品牌词切断扫描（R1 的事故回归网） ──
    print("── brand tripwire ──")
    hits = _brand_hits()
    detail = ""
    if hits:
        detail = "; ".join(hits[:6]) + (f" (+{len(hits) - 6} more)" if len(hits) > 6 else "")
    check("no brand strings in Application/Test/Doc/.github", not hits, detail)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
