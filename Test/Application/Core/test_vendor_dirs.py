"""第三方 / 工具生成目录的统一判定（core，无 GUI）。

背景（2026-11-17，社区扩展反馈）:
  本地扩展把实机用的虚拟环境放进扩展目录（名字形如 `.venv-<ext>`）后，凡是
  "按目录名跳过"的地方都只认**精确名**（`.venv` / `venv` / `env`），于是同一个
  虚拟环境被当成源码：

  | 位置 | 症状 |
  |---|---|
  | 工具仓评审 `_scan_py_files` | C12「写死解释器路径」对 cffi / numpy 报错（已在工具仓修） |
  | 本仓 `_copy_tree_for_export` | 219 MB / 5,434 个文件被打进游戏层 |
  | `print_audit` / `imgui_docgen` | 第三方 print / `imgui.*` 被统计成"我们的代码" |

本测试锁定:
  1. `is_vendor_dir` 的前缀语义（`.venv-ext` / `venv-x` 命中；正常目录不误伤）
  2. 导出复制真的跳过 `.venv-*` / `.git`，同时保留扩展自己的源码
  3. 两个开发工具（print_audit / imgui_docgen）用的是同一判定（不再各自维护名字表）

运行: python Utils/Dev/test_runner.py --only vendor_dirs
"""

# TIER: core

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "startup.bat")):
    _parent = os.path.dirname(_d)
    if _parent == _d:
        _d = ""
        break
    _d = _parent
if _d:
    sys.path.insert(0, _d)
    sys.path.insert(0, os.path.join(_d, "Utils", "Dev"))

from Application.Core.FileSystem.VendorDirs import (  # noqa: E402
    COPY_SKIP_DIR_NAMES,
    VENDOR_DIR_NAMES,
    is_copy_skip_dir,
    is_vendor_dir,
)
from Test.Helpers.tree import iter_py  # noqa: E402

ROOT = _d or ""   # 仓库根（= Test/ 的上一级）
_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def main() -> int:
    print("== VendorDirs — 第三方目录判定 ==")

    # ── 1. 前缀语义（这次的真实回归点） ──
    print("── 1. prefix semantics ──")
    positive = [
        ".venv", ".venv-ext", ".venv-py314t", "venv", "venv-ext", "venv314",
        "env", "site-packages", "node_modules",
        "__pycache__", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        ".tox", ".nox", ".idea", ".vscode",
    ]
    for name in positive:
        check(f"vendor: {name}", is_vendor_dir(name))
    negative = ["", "Application", "Editor", "device", "Doc", "Examples", "Extensions",
                "environment", "vendor", "events", "Core"]
    for name in negative:
        check(f"not vendor: {name!r}", not is_vendor_dir(name))
    check("non-str input is safe", not is_vendor_dir(None) and not is_vendor_dir(""))  # type: ignore[arg-type]
    check("names set is a frozenset", isinstance(VENDOR_DIR_NAMES, frozenset))

    # ── 2. 导出复制: 跳过 venv / vcs, 保留源码 ──
    print("── 2. export copy skips vendor dirs ──")
    from Application.Editor.ProjectManager import EXPORT_SKIP_DIR_NAMES, ProjectManager

    check("export skip set is the COPY set",
          EXPORT_SKIP_DIR_NAMES is COPY_SKIP_DIR_NAMES)
    check("COPY set keeps site-packages out of the skip list",
          "site-packages" not in EXPORT_SKIP_DIR_NAMES)
    check("scan set still treats site-packages as vendor",
          is_vendor_dir("site-packages") and not is_copy_skip_dir("site-packages"))

    tmp = tempfile.mkdtemp(prefix="fv_vendor_")
    try:
        src = os.path.join(tmp, "src")
        dst = os.path.join(tmp, "dst")
        os.makedirs(os.path.join(src, ".venv-ext", "Lib", "site-packages", "numpy"))
        os.makedirs(os.path.join(src, ".git", "objects"))
        os.makedirs(os.path.join(src, "device"))
        # 运行时镜像形态: `Lib/site-packages/<pkg>` —— 复制时必须保留
        os.makedirs(os.path.join(tmp, "runtime", "Lib", "site-packages", "numpy"))
        files = {
            os.path.join(src, "extension.py"): "print('real')\n",
            os.path.join(src, "device", "driver.py"): "# device code\n",
            os.path.join(src, ".venv-ext", "pyvenv.cfg"): "home = C:/Python\n",
            os.path.join(src, ".venv-ext", "Lib", "site-packages",
                         "numpy", "__init__.py"): "# third party\n",
            os.path.join(src, ".git", "config"): "[core]\n",
            os.path.join(tmp, "runtime", "python3.14t.exe"): "exe",
            os.path.join(tmp, "runtime", "Lib", "site-packages",
                         "numpy", "__init__.py"): "# runtime dep\n",
        }
        for path, text in files.items():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)

        warnings: list[str] = []
        errors: list[str] = []
        count, _bytes = ProjectManager._copy_tree_for_export(src, dst, warnings, errors=errors)

        def copied(rel: str) -> bool:
            return os.path.isfile(os.path.join(dst, rel))

        check("real source copied", copied("extension.py"))
        check("package source copied", copied(os.path.join("device", "driver.py")))
        check(".venv-ext NOT copied", not copied("pyvenv.cfg")
              and not os.path.isdir(os.path.join(dst, ".venv-ext")))
        check("third-party payload NOT copied",
              not copied(os.path.join(".venv-ext", "Lib", "site-packages",
                                      "numpy", "__init__.py")))
        check(".git NOT copied", not os.path.isdir(os.path.join(dst, ".git")))
        check("file count counts real sources only", count == 2, str(count))
        check("no copy warnings/errors", not warnings and not errors, str(warnings + errors))

        # ── 2b. 运行时镜像: site-packages 必须保留（2026-11-17 回归） ──
        rt_dst = os.path.join(tmp, "runtime_out")
        ProjectManager._copy_tree_for_export(os.path.join(tmp, "runtime"), rt_dst, [])
        check("runtime exe copied",
              os.path.isfile(os.path.join(rt_dst, "python3.14t.exe")))
        check("runtime site-packages copied",
              os.path.isfile(os.path.join(rt_dst, "Lib", "site-packages",
                                          "numpy", "__init__.py")))
        check("runtime copy still skips venv dirs",
              not os.path.isdir(os.path.join(rt_dst, ".venv-ext")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ── 3. 开发工具共用同一判定 ──
    print("── 3. dev tools share the predicate ──")
    import imgui_docgen  # noqa: E402
    import print_audit  # noqa: E402

    check("print_audit uses shared predicate",
          print_audit.is_vendor_dir is is_vendor_dir)
    check("imgui_docgen sees .venv-ext as vendor", imgui_docgen._is_vendor_dir(".venv-ext"))
    check("imgui_docgen keeps app dirs", not imgui_docgen._is_vendor_dir("Editor"))
    check("print_audit keeps its own skips", "wheels" in print_audit._SKIP_DIRS)

    # ── 4. 复发守卫: 测试不得裸扫 Application / Functions ──
    print("── 4. no unguarded tree walk in Test/ ──")
    # 明确豁免（一行理由）：扫的不是树，或已经用其它机制整枝排除。
    exempt = {
        "test_extension_coupling_inventory.py":
            "walks an explicit file list (C 类棘轮), not a tree",
        "test_utils_layout.py":
            "walks Utils/ and its staged copies, never Application/Functions",
        "test_virtual_panel.py":
            "walks MGE_EXTENSIONS_DATA sandbox, not the repo tree",
    }
    offenders: list[str] = []
    for path in iter_py(os.path.join(ROOT, "Test")):
        name = os.path.basename(path)
        if name in exempt or name == "test_vendor_dirs.py":
            continue
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if "os.walk(" not in text:
            continue
        if not re.search(r'["\'](?:Application|Functions)\b', text):
            continue
        if "is_vendor_dir" not in text and "iter_py" not in text:
            offenders.append(os.path.relpath(path, ROOT).replace("\\", "/"))
    check("every Application-tree walk guards vendor dirs", not offenders,
          "; ".join(offenders[:5]))

    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"RESULT: {'OK' if _RESULTS['fail'] == 0 else 'FAIL'} "
          f"({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
