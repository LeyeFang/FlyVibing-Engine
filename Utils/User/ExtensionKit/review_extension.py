"""Extension 静态审查器 v0 — 扩展开发者的规范自查工具（无需引擎运行）。

用法:
    python Utils/User/ExtensionKit/review_extension.py <extension_dir> [<dir>...]
    python Utils/User/ExtensionKit/review_extension.py --all    # 扫仓库内全部 Functions/*/

检查项（对照 Doc/ExtDev/extension_dev_protocol.md）:

  [manifest]
    M1 extension.json 存在且为合法 JSON
    M2 id 合法（^[a-z][a-z0-9_]*$）
    M3 api_version 与宿主兼容（前缀 "1"）
    M4 entry 格式合法且文件存在（无 entry = planned/partial 允许）
    M5 capabilities 取值合法（ops/ui/nodes/threads/jobs/settings/device）
    M6 description 非空（菜单 tooltip）

  [code]（entry 存在时静态扫描）
    C1 capabilities 含 ui → entry 类继承 UIExtensionBase（语言层强制）
    C2 capabilities 含 ui → 实现 on_ui_event
    C3 register_window 调用声明 close_policy（窗口 X 语义显式化 — §7）
    C4 ops 注册名不得自带 "ext." 前缀（前缀由宿主强制）
    C5 无 monkey-patch 迹象（顶层引擎赋值启发式）
    C6 Application.* import 在常用白名单内

  [files]
    F2 TODO.md 存在（状态档案）

退出码: 0 = 无 FAIL（WARN 不失败）; 1 = 存在 FAIL; 2 = 用法错误。
"""

from __future__ import annotations

import json
import os
import re
import sys

_CAPABILITIES = {"ops", "ui", "nodes", "threads", "jobs", "settings", "device"}
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_IMPORT_RE = re.compile(
    r"^\s*from\s+(Application[\w\.]*)\s+import|^\s*import\s+(Application[\w\.]*)", re.M)
_IMPORT_ALLOW = (
    "Application.Core.Extension",
    "Application.Functions",
    "Application.Core.Events",
    "Application.Core.ThreadRegistry",
)
_MONKEY_RE = re.compile(r"^Application\w*(?:\.\w+)*\s*=", re.M)
_UI_BASE_RE = re.compile(r"class\s+\w+\s*\([^)]*UIExtensionBase")


class Report:
    """单扩展审查报告（可导入使用 — 测试/CI）。"""

    def __init__(self, ext_dir: str) -> None:
        self.dir = ext_dir
        self.lines: list[str] = []
        self.passes = 0
        self.warns = 0
        self.fails = 0

    def _add(self, level: str, code: str, msg: str) -> None:
        self.lines.append(f"  [{level:4}] {code:2} {msg}")
        if level == "PASS":
            self.passes += 1
        elif level == "WARN":
            self.warns += 1
        else:
            self.fails += 1

    def ok(self, code: str, msg: str = "") -> None:
        self._add("PASS", code, msg)

    def warn(self, code: str, msg: str) -> None:
        self._add("WARN", code, msg)

    def fail(self, code: str, msg: str) -> None:
        self._add("FAIL", code, msg)


def review_extension(ext_dir: str) -> Report:
    """审查单个扩展目录（纯静态 — 不 import 扩展代码）。"""
    rep = Report(ext_dir)
    manifest_path = os.path.join(ext_dir, "extension.json")
    if not os.path.isfile(manifest_path):
        rep.fail("M1", "extension.json 缺失")
        return rep
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        rep.ok("M1", "extension.json 合法")
    except Exception as e:  # noqa: BLE001
        rep.fail("M1", f"extension.json 解析失败: {e}")
        return rep

    ext_id = str(manifest.get("id", ""))
    if _ID_RE.match(ext_id):
        rep.ok("M2", f"id='{ext_id}' 合法")
    else:
        rep.fail("M2", f"id='{ext_id}' 非法（要求 ^[a-z][a-z0-9_]*$）")

    api = str(manifest.get("api_version", ""))
    if api.split(".")[0] == "1":
        rep.ok("M3", f"api_version='{api}'")
    else:
        rep.fail("M3", f"api_version='{api}' 与宿主不兼容（当前需要 1.x）")

    caps = manifest.get("capabilities") or []
    bad_caps = [c for c in caps if c not in _CAPABILITIES]
    if bad_caps:
        rep.fail("M5", f"capabilities 含非法值: {bad_caps}")
    else:
        rep.ok("M5", f"capabilities={caps if caps else '(未声明)'}")

    if str(manifest.get("description", "")).strip():
        rep.ok("M6", "description 非空")
    else:
        rep.warn("M6", "description 为空（Extensions 菜单 tooltip 建议填写）")

    entry = str(manifest.get("entry", ""))
    entry_file = entry.split(":")[0] if entry else ""
    if not entry:
        rep.ok("M4", "无 entry（planned/partial 允许; 提供后可启用）")
        _review_files(rep, ext_dir)
        return rep
    entry_path = os.path.join(ext_dir, entry_file)
    if not os.path.isfile(entry_path):
        rep.fail("M4", f"entry 文件不存在: {entry_file}")
        return rep
    rep.ok("M4", f"entry={entry}")

    # ── 代码静态检查 ────────────────────────────────────────────
    try:
        with open(entry_path, encoding="utf-8") as fh:
            src = fh.read()
    except Exception as e:  # noqa: BLE001
        rep.fail("C0", f"entry 读取失败: {e}")
        return rep

    if "ui" in caps:
        if _UI_BASE_RE.search(src):
            rep.ok("C1", "entry 类继承 UIExtensionBase")
        else:
            rep.fail("C1", "capabilities 含 ui → entry 类必须继承 UIExtensionBase（语言层强制）")
        if "def on_ui_event" in src:
            rep.ok("C2", "实现 on_ui_event")
        else:
            rep.fail("C2", "capabilities 含 ui → 必须实现 on_ui_event（窗口生命周期完备性）")

    if "register_window(" in src:
        if "close_policy" in src:
            rep.ok("C3", "register_window 声明 close_policy")
        else:
            rep.warn("C3", "register_window 未声明 close_policy（窗口 X 语义未显式化 — dev protocol §7）")

    if re.search(r"\.register\(\s*['\"]ext\.", src):
        rep.fail("C4", "ops 注册名不得自带 'ext.' 前缀（宿主自动加 ext.<id>.）")
    else:
        rep.ok("C4", "ops 注册名无 ext. 前缀")

    monkey = _MONKEY_RE.findall(src)
    if monkey:
        rep.warn("C5", f"疑似顶层引擎赋值（monkey-patch 黑名单, 人工复核）: {monkey[:3]}")
    else:
        rep.ok("C5", "无 monkey-patch 迹象")

    offenders = []
    for m in _IMPORT_RE.finditer(src):
        mod = m.group(1) or m.group(2)
        if mod and not any(mod.startswith(prefix) for prefix in _IMPORT_ALLOW):
            offenders.append(mod)
    if offenders:
        rep.warn("C6", f"import Application.* 超出常用白名单（人工复核）: {sorted(set(offenders))}")
    else:
        rep.ok("C6", "Application.* import 均在白名单")

    _review_files(rep, ext_dir)
    return rep


def _review_files(rep: Report, ext_dir: str) -> None:
    if os.path.isfile(os.path.join(ext_dir, "TODO.md")):
        rep.ok("F2", "TODO.md 存在（状态档案）")
    else:
        rep.warn("F2", "建议提供 TODO.md（状态档案 — 开发规范 §3）")


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args:
        print(__doc__)
        return 2
    if args == ["--all"]:
        root = os.path.abspath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "Functions"))
        if not os.path.isdir(root):
            print(f"Functions 目录不存在: {root}")
            return 2
        dirs = []
        for dirpath, _dirnames, filenames in os.walk(root):
            if "extension.json" in filenames:
                dirs.append(dirpath)
        dirs.sort()
    else:
        dirs = [os.path.abspath(a) for a in args]

    total_fail = 0
    for ext_dir in dirs:
        rep = review_extension(ext_dir)
        name = os.path.basename(ext_dir.rstrip("/\\"))
        print(f"== review: {name}  ({ext_dir}) ==")
        for line in rep.lines:
            print(line)
        print(f"   -> {rep.passes} pass / {rep.warns} warn / {rep.fails} fail")
        print()
        total_fail += rep.fails

    print(f"SUMMARY: {len(dirs)} extension(s), fails={total_fail} — "
          + ("OK" if total_fail == 0 else "FAIL"))
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
