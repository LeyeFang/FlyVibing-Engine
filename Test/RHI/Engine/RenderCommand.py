"""
RenderCommand — 渲染命令基类 + 具体命令。

命令分为两类:
  - 被动命令 (reactive):  由主线程事件触发，渲染线程执行。如 resize / camera update
  - 主动命令 (proactive):  由 Layer.OnUpdate 生成，渲染线程执行。如 DrawMesh (未来)

当前实现: 4 种被动命令，覆盖 openGLRenderer.OnEvent 的全部事件类型。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class RenderCommand(ABC):
    """渲染命令基类 — 所有命令必须实现 execute()。"""

    @abstractmethod
    def execute(self) -> None:
        """在渲染线程中执行此命令。"""
        ...


@dataclass
class ResizeCommand(RenderCommand):
    """窗口尺寸变更命令。"""
    width: int
    height: int

    def execute(self) -> None:
        """更新视口和投影矩阵。"""
        # TODO: 从备份恢复完整实现


@dataclass
class CameraUpdateCommand(RenderCommand):
    """摄像机参数更新命令。"""
    view_matrix: Any = None
    proj_matrix: Any = None

    def execute(self) -> None:
        """更新渲染器缓存的摄像机矩阵。"""
        # TODO: 从备份恢复完整实现


@dataclass
class EntityRegistrationCommand(RenderCommand):
    """实体注册/更新命令 — MeshRenderer 组件变更时触发。"""
    entity_id: int = 0
    mesh_id: Any = None

    def execute(self) -> None:
        """注册或更新渲染实体。"""
        # TODO: 从备份恢复完整实现


@dataclass
class PickMouseMoveCommand(RenderCommand):
    """鼠标移动命令 — 用于拾取系统的 hover 状态更新。"""
    pos_x: float = 0.0
    pos_y: float = 0.0

    def execute(self) -> None:
        """更新拾取系统的鼠标位置。"""
        # TODO: 从备份恢复完整实现


# ════════════════════════════════════════════════════════════════
# TODO: 以上所有 execute() 方法体需要从备份恢复
# ════════════════════════════════════════════════════════════════
