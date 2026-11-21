"""VendorDirs — 树遍历时**不进入**的第三方 / 工具生成目录名。

背景（2026-11-17，社区扩展反馈）:
  本地扩展把实机用的虚拟环境放进自己的源码目录（实测名字形如 `.venv-<ext>`）后，
  凡是"按目录名跳过"的地方都只认**精确名**（`.venv` / `venv` / `env`），
  于是这个虚拟环境被当成扩展源码处理，同时踩了三处：

  | 位置 | 症状 |
  |---|---|
  | 扩展评审 `_scan_py_files`（工具仓） | C12「写死解释器路径」对 cffi / numpy 自己的 .py 报错 |
  | 导出 `_copy_tree_for_export`（引擎） | 219 MB / 5,434 个文件的虚拟环境被打进游戏层 |
  | `print_audit` / `imgui_docgen`（开发工具） | 第三方 print、`imgui.*` 调用被统计成"我们的代码" |

  结论：判定必须**单一来源**、且按**前缀**识别虚拟环境（`.venv*` / `venv*`），
  否则每加一个新遍历点就复现一次。任何 `os.walk` 触及 `Application/` 的代码
  都应该用本模块，而不是各自维护名字列表。

用法:
    from Application.Core.FileSystem.VendorDirs import is_vendor_dir
    dirs[:] = [d for d in dirs if not is_vendor_dir(d)]

**两种语义，别混用（2026-11-17 事故）**
  - `is_vendor_dir`  —— **扫描源码**：`site-packages` 是第三方代码，要跳过。
  - `is_copy_skip_dir` —— **复制产物树**：`site-packages` 就是内容本身（运行时镜像
    `Resource/runtime/Lib/site-packages`）。用错这个会把整个 Python 环境从成品里剔掉
    —— 实测 `_copy_tree_for_export(Resource/runtime, …)` 只剩 exe，numpy 全丢。

线程安全 / 依赖: 纯字符串判定，无 IO、无第三方依赖（开发工具也能安全导入）。
"""

from __future__ import annotations

#: 精确匹配的目录名（第三方代码 / 版本控制 / 工具缓存）。
VENDOR_DIR_NAMES = frozenset({
    # 虚拟环境（非前缀形式；`.venv` / `venv` 也在此列，便于文档与守卫直接比对）
    ".venv", "venv", "env", "site-packages", "node_modules",
    # 版本控制
    ".git", ".hg", ".svn",
    # 工具缓存 / IDE
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".tox", ".nox", ".idea", ".vscode", ".vs",
})

#: 前缀匹配 —— 虚拟环境几乎总是叫 `venv` / `.venv` / `venv-<ext>` / `.venv-<ext>`。
#: 用前缀而不是白名单: 扩展作者自建环境的名字不可预测（实测 `.venv-<ext>`）。
VENDOR_DIR_PREFIXES = (".venv", "venv")

#: 复制产物树时**必须保留**的名字 —— 它们对"扫描"是第三方，对"复制"是内容。
COPY_KEEP_DIR_NAMES = frozenset({"site-packages"})

#: 复制产物树时要跳过的名字 = vendor 去掉上面那批。
COPY_SKIP_DIR_NAMES = VENDOR_DIR_NAMES - COPY_KEEP_DIR_NAMES


def is_vendor_dir(name: str) -> bool:
    """目录名是否属于"第三方 / 工具生成"（**扫描源码**时应整枝跳过）。

    只判断**单层名字**，不接收路径 —— 调用方在 `os.walk` 里对 `dirs` 逐项判即可。
    `name` 为空 / 非字符串时返回 False（不误伤）。
    """
    if not name or not isinstance(name, str):
        return False
    if name in VENDOR_DIR_NAMES:
        return True
    low = name.lower()
    return any(low.startswith(prefix) for prefix in VENDOR_DIR_PREFIXES)


def is_copy_skip_dir(name: str) -> bool:
    """目录名是否应在**复制产物树**时跳过（`site-packages` 不跳）。

    与 `is_vendor_dir` 的唯一差别是保留 `site-packages`：运行时镜像的依赖就在里面。
    """
    if not name or not isinstance(name, str):
        return False
    if name in COPY_SKIP_DIR_NAMES:
        return True
    low = name.lower()
    return any(low.startswith(prefix) for prefix in VENDOR_DIR_PREFIXES)


__all__ = ["VENDOR_DIR_NAMES", "VENDOR_DIR_PREFIXES", "COPY_KEEP_DIR_NAMES",
           "COPY_SKIP_DIR_NAMES", "is_vendor_dir", "is_copy_skip_dir"]
