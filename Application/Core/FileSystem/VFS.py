"""
VFS — 虚拟文件系统（引擎文件 I/O 的唯一入口）。

设计原则：
  - 所有文件读写必须经过 VFS，禁止直接 open() / os.path
  - 支持多挂载点（磁盘目录 + 未来 .pak 压缩包）
  - 项目根目录作为默认挂载点，自动解析相对路径
  - 文本读写默认 UTF-8，二进制读写原样传递

挂载优先级：
  1. 显式挂载的磁盘目录（按 mount 顺序）
  2. 项目根目录（_project_root）
  3. 引擎内置资源目录（_engine_root）

使用方式：
  from Application.Core.FileSystem import VFS

  # 初始化（Engine.init() 时调用一次）
  VFS.init(project_root="D:/MyProject")

  # 读取场景 JSON
  data = VFS.read_json("Scenes/Main.scene")

  # 写入 Prefab
  VFS.write_json("Prefabs/Tank.prefab", prefab_dict)
"""

from __future__ import annotations

import json
import os
from typing import Optional

from .PathUtils import PathUtils


class VFS:
    """虚拟文件系统 — 所有方法均为 @classmethod。

    生命周期：
      VFS.init(project_root)   → 引擎启动时调用一次
      VFS.mount(path)          → 注册额外挂载点
      VFS.read_text(...)       → 日常 I/O
      VFS.shutdown()           → 引擎关闭时清理
    """

    # ── 挂载点 ──────────────────────────────────────────────
    _project_root: str = ""        # 项目根目录（必须）
    _mounts: list[str] = []        # 额外挂载点（按优先级排列）

    @classmethod
    def init(cls, project_root: str) -> None:
        """初始化 VFS — 必须在任何 I/O 操作前调用。

        Args:
            project_root: 项目根目录（.project 文件所在目录）
        """
        cls._project_root = PathUtils.normalize(os.path.abspath(project_root))
        cls._mounts.clear()
        # 把项目根也作为一个挂载点
        cls._mounts.append(cls._project_root)

    @classmethod
    def shutdown(cls) -> None:
        """清理 VFS 状态。"""
        cls._project_root = ""
        cls._mounts.clear()

    # ════════════════════════════════════════════════════════════
    # 挂载点管理
    # ════════════════════════════════════════════════════════════

    @classmethod
    def mount(cls, path: str) -> None:
        """注册额外挂载点 — 用于资源搜索路径。

        挂载后，VFS.resolve() 会按优先级搜索文件：
          1. 项目根目录
          2. 后挂载的目录（后挂优先）

        Args:
            path: 要挂载的目录路径（绝对路径或相对项目根）
        """
        abs_path = cls._to_absolute(path)
        if abs_path and PathUtils.is_dir(abs_path):
            # 后挂载的优先级更高 → 插到列表前面
            cls._mounts.insert(0, abs_path)

    @classmethod
    def unmount(cls, path: str) -> None:
        """取消挂载。"""
        abs_path = PathUtils.normalize(os.path.abspath(path))
        if abs_path in cls._mounts:
            cls._mounts.remove(abs_path)

    @classmethod
    def get_project_root(cls) -> str:
        """返回项目根目录。"""
        return cls._project_root

    # ════════════════════════════════════════════════════════════
    # 路径解析
    # ════════════════════════════════════════════════════════════

    @classmethod
    def resolve(cls, path: str) -> Optional[str]:
        """将相对路径解析为绝对路径（搜索所有挂载点）。

        绝对路径直接返回（不做沙箱校验）。

        Args:
            path: 相对路径（如 "Scenes/Main.scene"）或绝对路径

        Returns:
            找到的第一个存在的文件路径，未找到返回 None
        """
        # 绝对路径 → 直接返回（不做校验）
        if PathUtils.is_absolute(path):
            return PathUtils.normalize(path) if PathUtils.exists(path) else None

        # 相对路径 → 遍历挂载点
        for mount in cls._mounts:
            candidate = PathUtils.join(mount, path)
            if PathUtils.exists(candidate):
                return candidate

        return None

    @classmethod
    def resolve_or_raise(cls, path: str) -> str:
        """resolve() 的严格版本 — 找不到抛 FileNotFoundError。"""
        result = cls.resolve(path)
        if result is None:
            raise FileNotFoundError(
                f"VFS: 找不到文件 '{path}' — 已搜索挂载点: {cls._mounts}"
            )
        return result

    # ════════════════════════════════════════════════════════════
    # 读文本
    # ════════════════════════════════════════════════════════════

    @classmethod
    def read_text(cls, path: str, encoding: str = "utf-8") -> str:
        """读取文本文件。

        Args:
            path: 相对或绝对路径
            encoding: 文件编码，默认 utf-8

        Returns:
            文件内容字符串

        Raises:
            FileNotFoundError: 文件不存在
        """
        abs_path = cls.resolve_or_raise(path)
        with open(abs_path, "r", encoding=encoding) as f:
            return f.read()

    @classmethod
    def read_json(cls, path: str) -> dict | list:
        """读取 JSON 文件 → Python 对象。

        Args:
            path: JSON 文件路径

        Returns:
            dict 或 list

        Raises:
            FileNotFoundError: 文件不存在
            json.JSONDecodeError: JSON 格式错误
        """
        text = cls.read_text(path)
        return json.loads(text)

    # ════════════════════════════════════════════════════════════
    # 读二进制
    # ════════════════════════════════════════════════════════════

    @classmethod
    def read_bytes(cls, path: str) -> bytes:
        """读取二进制文件。

        Args:
            path: 相对或绝对路径

        Returns:
            文件二进制内容

        Raises:
            FileNotFoundError: 文件不存在
        """
        abs_path = cls.resolve_or_raise(path)
        with open(abs_path, "rb") as f:
            return f.read()

    # ════════════════════════════════════════════════════════════
    # 写
    # ════════════════════════════════════════════════════════════

    @classmethod
    def write_text(
        cls,
        path: str,
        content: str,
        encoding: str = "utf-8",
    ) -> None:
        """写入文本文件（自动创建目录）。

        Args:
            path: 相对路径（基于项目根）或绝对路径
            content: 要写入的文本
            encoding: 编码
        """
        abs_path = cls._to_absolute(path)
        PathUtils.ensure_dir(abs_path)
        with open(abs_path, "w", encoding=encoding) as f:
            f.write(content)

    @classmethod
    def write_json(
        cls,
        path: str,
        data: dict | list,
        indent: int = 2,
    ) -> None:
        """将 Python 对象写入 JSON 文件。

        Args:
            path: 文件路径
            data: 要序列化的 dict/list
            indent: JSON 缩进空格数
        """
        text = json.dumps(data, indent=indent, ensure_ascii=False)
        cls.write_text(path, text)

    @classmethod
    def write_bytes(cls, path: str, data: bytes) -> None:
        """写入二进制文件。"""
        abs_path = cls._to_absolute(path)
        PathUtils.ensure_dir(abs_path)
        with open(abs_path, "wb") as f:
            f.write(data)

    # ════════════════════════════════════════════════════════════
    # 文件查询
    # ════════════════════════════════════════════════════════════

    @classmethod
    def exists(cls, path: str) -> bool:
        """文件是否存在（搜索所有挂载点）。"""
        return cls.resolve(path) is not None

    @classmethod
    def list_dir(
        cls,
        directory: str,
        full_path: bool = False,
    ) -> list[str]:
        """列出目录内容。"""
        abs_dir = cls._to_absolute(directory)
        return PathUtils.list_dir(abs_dir, full_path=full_path)

    @classmethod
    def glob(
        cls,
        directory: str,
        pattern: str = "*",
        recursive: bool = False,
        full_path: bool = True,
    ) -> list[str]:
        """通配符搜索文件。"""
        abs_dir = cls._to_absolute(directory)
        return PathUtils.glob(abs_dir, pattern, recursive=recursive, full_path=full_path)

    # ════════════════════════════════════════════════════════════
    # 内部工具
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _to_absolute(cls, path: str) -> str:
        """将路径转为绝对路径（基于项目根）。

        - 绝对路径 → 原样返回
        - 相对路径 → 拼接 project_root
        """
        if PathUtils.is_absolute(path):
            return PathUtils.normalize(path)
        if not cls._project_root:
            raise RuntimeError("VFS 未初始化 — 请先调用 VFS.init(project_root)")
        return PathUtils.join(cls._project_root, path)
