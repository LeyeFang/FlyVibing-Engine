"""
FileSystem — 引擎文件系统抽象层。

职责：
  - 虚拟文件系统 (VFS)：统一磁盘文件和压缩包访问
  - 路径工具 (PathUtils)：跨平台路径规范化、安全校验
  - 文件变更监听 (FileWatcher)：热重载支持（未来扩展）
  - 压缩包读取 (ArchiveReader)：.pak / .zip 挂载（未来扩展）

层级定位：
  Application/Core/FileSystem/  ← 引擎最底层的平台抽象
    ↑ 被依赖
  Application/Resource/ResourceManager  ← 通过 VFS 加载资产
  Application/Core/Scene/Scene          ← 通过 VFS 保存/加载场景
  Application/Core/Project/             ← 通过 VFS 解析项目路径
"""

from .VFS import VFS
from .PathUtils import PathUtils

__all__ = [
    "VFS",
    "PathUtils",
]
