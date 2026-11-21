"""测试共用的目录遍历工具 — 统一"哪些目录不该进"的判定。

为什么有它（2026-11-17）:
  本地扩展把实机 venv 放进自己的源码目录（`.venv-<ext>`）后，凡是手写
  `os.walk("Application")` 的测试都会去解析第三方源码：

    Application/Editor + Application/Functions 全扫 → 2,195 文件 / 13.3s
    跳过第三方目录后                              →   145 文件 / 0.7s

  `test_imgui_stack_pairing` 因此从 0.8s 涨到 33.6s（它扫两遍）。判定本身
  已经单源化在 `Application/Core/FileSystem/VendorDirs`，本模块只是把它
  接到测试侧，并提供 `iter_py()` 统一"只迭代 .py、跳过第三方目录"。

用法:
    from Test.Helpers.tree import iter_py, is_vendor_dir
    for path in iter_py(os.path.join(ROOT, "Application")):
        ...
"""

from __future__ import annotations

import os
import sys
from typing import Iterable, Iterator

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from Application.Core.FileSystem.VendorDirs import (  # type: ignore
        VENDOR_DIR_NAMES,
        is_vendor_dir,
    )
except Exception:  # noqa: BLE001 — 极少数裸环境（引擎包不可导入）退化为最小判定
    VENDOR_DIR_NAMES = frozenset({"__pycache__", "site-packages", "node_modules", ".git"})

    def is_vendor_dir(name: str) -> bool:  # type: ignore[misc]
        low = str(name or "").lower()
        return (low in VENDOR_DIR_NAMES or low.startswith(".venv")
                or low.startswith("venv"))


#: 测试自己的默认跳过项（运行产物目录，与第三方目录互补）。
TEST_SKIP_DIRS = frozenset({"_runs", "_archive", "dist", "build"})


def iter_dirs(root: str, extra_skip: Iterable[str] = ()) -> Iterator[tuple[str, list[str]]]:
    """遍历目录，返回 (当前目录, 保留的子目录名)；已剔除第三方/产物目录。"""
    extra = set(extra_skip)
    for base, dirs, _files in os.walk(root):
        dirs[:] = [d for d in dirs
                   if d not in extra and d not in TEST_SKIP_DIRS and not is_vendor_dir(d)]
        yield base, dirs


def iter_py(root: str, extra_skip: Iterable[str] = ()) -> Iterator[str]:
    """迭代 root 下所有 .py（跳过第三方目录、`__pycache__`、测试产物）。"""
    for base, _dirs in iter_dirs(root, extra_skip):
        for name in sorted(os.listdir(base)):
            if name.endswith(".py") and os.path.isfile(os.path.join(base, name)):
                yield os.path.join(base, name)


__all__ = ["VENDOR_DIR_NAMES", "is_vendor_dir", "TEST_SKIP_DIRS", "iter_dirs", "iter_py"]
