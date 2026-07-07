"""
PathUtils — 跨平台路径工具（纯函数，零依赖）。

不依赖任何引擎状态，仅封装 os.path / pathlib 的常用操作，
并补充引擎特有的安全校验逻辑。
"""

from __future__ import annotations

import os
import pathlib
from typing import Optional


class PathUtils:
    """跨平台路径工具 — 所有方法均为 @staticmethod。"""

    # ════════════════════════════════════════════════════════════
    # 规范化
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def normalize(path: str) -> str:
        """统一路径格式 — 正斜杠 / 小写盘符 / 去除末尾分隔符。

        Examples:
            PathUtils.normalize("D:\\Foo\\Bar")   → "D:/Foo/Bar"
            PathUtils.normalize("../data///")      → "../data"
        """
        p = os.path.normpath(path)
        p = p.replace("\\", "/")
        # 去除末尾 /
        if len(p) > 1 and p.endswith("/"):
            p = p[:-1]
        return p

    @staticmethod
    def is_absolute(path: str) -> bool:
        """是否为绝对路径（跨平台）。"""
        return os.path.isabs(path)

    # ════════════════════════════════════════════════════════════
    # 拼接 & 相对
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def join(base: str, *parts: str) -> str:
        """路径拼接 → 自动规范化。

        Examples:
            PathUtils.join("D:/Project", "Assets", "tex.png") → "D:/Project/Assets/tex.png"
        """
        return PathUtils.normalize(os.path.join(base, *parts))

    @staticmethod
    def relative_to(path: str, base: str) -> str:
        """计算相对路径 — 始终返回正斜杠格式。

        Raises:
            ValueError: path 不在 base 之下
        """
        p = pathlib.PurePosixPath(PathUtils.normalize(path))
        b = pathlib.PurePosixPath(PathUtils.normalize(base))
        return str(p.relative_to(b)).replace("\\", "/")

    @staticmethod
    def stem(path: str) -> str:
        """返回文件名（不含扩展名）。"""
        return os.path.splitext(os.path.basename(path))[0]

    @staticmethod
    def basename(path: str) -> str:
        """返回文件名（含扩展名）。"""
        return os.path.basename(path)

    @staticmethod
    def dirname(path: str) -> str:
        """返回目录部分（规范化）。"""
        return PathUtils.normalize(os.path.dirname(path))

    @staticmethod
    def extension(path: str) -> str:
        """返回扩展名（小写，含点）。

        Examples:
            PathUtils.extension("model.glb")    → ".glb"
            PathUtils.extension("shader.vert")  → ".vert"
        """
        return os.path.splitext(path)[1].lower()

    @staticmethod
    def split_extension(path: str) -> tuple[str, str]:
        """分离扩展名 — 处理双扩展名（如 .vert.spv）。

        Returns:
            (stem_with_first_ext, second_ext)
            "Basic.vert.spv" → ("Basic.vert", ".spv")
            "model.obj"      → ("model", ".obj")
        """
        name = os.path.basename(path)
        parts = name.rsplit(".", 2)
        if len(parts) == 3:
            return (parts[0] + "." + parts[1], "." + parts[2].lower())
        elif len(parts) == 2:
            return (parts[0], "." + parts[1].lower())
        return (name, "")

    # ════════════════════════════════════════════════════════════
    # 安全校验
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def is_child_of(path: str, parent: str) -> bool:
        """检查 path 是否在 parent 目录之下（防 .. 逃逸）。

        用于校验用户输入的文件路径不会逃出项目沙箱。

        Examples:
            PathUtils.is_child_of("D:/Proj/Assets/tex.png", "D:/Proj")      → True
            PathUtils.is_child_of("D:/Proj/../secret", "D:/Proj")            → False
        """
        try:
            PathUtils.relative_to(path, parent)
            return True
        except ValueError:
            return False

    @staticmethod
    def ensure_dir(filepath: str) -> None:
        """确保文件所在目录存在（递归创建）。"""
        d = os.path.dirname(filepath)
        if d:
            os.makedirs(d, exist_ok=True)

    # ════════════════════════════════════════════════════════════
    # 文件信息
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def exists(path: str) -> bool:
        """文件或目录是否存在。"""
        return os.path.exists(path)

    @staticmethod
    def is_file(path: str) -> bool:
        return os.path.isfile(path)

    @staticmethod
    def is_dir(path: str) -> bool:
        return os.path.isdir(path)

    @staticmethod
    def file_size(path: str) -> int:
        """文件大小（字节），不存在返回 0。"""
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    @staticmethod
    def list_dir(path: str, full_path: bool = False) -> list[str]:
        """列出目录内容（非递归）。

        Args:
            path: 目录路径
            full_path: True 返回绝对路径，False 仅返回文件名
        """
        if not os.path.isdir(path):
            return []
        items = os.listdir(path)
        if full_path:
            items = [PathUtils.join(path, f) for f in items]
        return items

    @staticmethod
    def glob(
        directory: str,
        pattern: str = "*",
        recursive: bool = False,
        full_path: bool = True,
    ) -> list[str]:
        """通配符搜索文件。

        Args:
            directory: 搜索根目录
            pattern: glob 模式，如 "*.scene"、"**/*.png"
            recursive: 是否递归搜索子目录
            full_path: True 返回绝对路径

        Returns:
            匹配的文件路径列表（规范化）

        Examples:
            PathUtils.glob("D:/Proj/Scenes", "*.scene")       → 场景文件列表
            PathUtils.glob("D:/Proj/Assets", "**/*.png", recursive=True)
        """
        if not os.path.isdir(directory):
            return []
        p = pathlib.Path(directory)
        if recursive:
            matches = list(p.rglob(pattern))
        else:
            matches = list(p.glob(pattern))
        result = [
            PathUtils.normalize(str(m.absolute()))
            for m in sorted(matches)
            if m.is_file()
        ]
        if not full_path:
            base = PathUtils.normalize(directory)
            result = [
                PathUtils.relative_to(r, base)
                for r in result
            ]
        return result
