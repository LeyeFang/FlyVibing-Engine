"""Media — 动态媒体库（M1: GIF/图像; 协议 Doc/Dev/media_protocol.md）。

- MediaSystem: 播放时钟 + 动态纹理（节点 ShowMedia 驱动 — 无独立循环）;
- 组件 MediaPlayer（Application/Core/Scene/BasicComponents.py）= 可序列化参数载体。
"""

from .MediaSystem import MediaClip, advance, load_media, reset, snapshot

__all__ = ["MediaClip", "advance", "load_media", "reset", "snapshot"]
