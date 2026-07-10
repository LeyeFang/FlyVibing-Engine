"""
PostProcess — 屏幕空间后处理管线抽象基类。

设计原则:
  - Renderer 不知道 Editor 的存在，只知道有"后处理效果"
  - Editor (OutlinerID) 不 import 任何图形 API，只提供纯数据
  - 每个后端实现自己的 PostProcess Mixin (OpenGLPostProcess / ZenGLPostProcess)

后处理效果:
  - HighlightEffect: 实体轮廓高亮 (ID buffer + 边缘检测 + 合成)
  - (未来) Bloom, SSAO, ColorGrading ...

管线位置:
  Entities → **PostProcess** → Overlays

线程安全:
  - _pending_selected_ids: 主线程写入 (update_highlight_selection)
  - _render_post_process: 渲染线程消费，内部 sync pending → active
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable
import numpy as np


# ════════════════════════════════════════════════════════════════
# 后处理效果配置 (纯数据载体, 零图形 API 依赖)
# ════════════════════════════════════════════════════════════════

@dataclass
class HighlightEffectConfig:
    """轮廓高亮效果配置 — Editor 层填写，Renderer 后端据此创建 GPU 资源。

    类比 overlay_drawable_struct: 都是 Editor → Renderer 的数据桥梁。
    区别在于 PostProcess 是多 Pass 管线，不是单个 draw call。

    Attributes:
        selected_ids : 被选中实体 ID 集合 (渲染线程读取 _active 副本)
        color        : 轮廓颜色 (r, g, b)
        width        : 轮廓宽度 (边缘检测采样半径，像素)
        xray         : 穿透模式 (True=轮廓始终可见，False=被遮挡时不可见)
    """
    selected_ids: set[int] = field(default_factory=set)
    color: tuple = (0.878, 0.416, 0.153)   # Blender 橙色
    width: int = 3
    xray: bool = True


# ════════════════════════════════════════════════════════════════
# PostProcess — Mixin 基类
# ════════════════════════════════════════════════════════════════

class PostProcess:
    """后处理管线 Mixin 基类。

    子类 (OpenGLPostProcess / ZenGLPostProcess) 必须实现:
      - _init_highlight(config)
      - _render_highlight(view, proj)
      - _release_highlight()
      - _update_highlight_params()  (optional, 默认空操作)

    管线调用:
      Renderer._do_start_frame() 中:
        ...
        self._RenderEntities(view, proj)
        self._render_post_process(view, proj)
        self._render_all_overlays(view, proj)
    """

    def __init__(self) -> None:
        super().__init__()
        self._highlight_config: 'HighlightEffectConfig | None' = None
        self._pending_selected_ids: 'set[int] | None' = None
        self._active_selected_ids: set[int] = set()

    # ════════════════════════════════════════════════════════
    # 公开 API (Editor 层调用)
    # ════════════════════════════════════════════════════════

    def register_highlight_effect(self, config: HighlightEffectConfig) -> None:
        """注册轮廓高亮后处理效果 — 编译 shader、创建 FBO/VAO。"""
        self._highlight_config = config
        self._init_highlight(config)

    def unregister_highlight_effect(self) -> None:
        """注销轮廓高亮效果，释放全部 GPU 资源。"""
        self._release_highlight()
        self._highlight_config = None
        self._pending_selected_ids = None
        self._active_selected_ids = set()

    def update_highlight_selection(self, selected_ids: set[int]) -> None:
        """主线程安全: 更新待选实体 ID 集合。"""
        self._pending_selected_ids = set(selected_ids) if selected_ids else set()

    def update_highlight_config(
        self,
        color: tuple[float, float, float] = None,
        width: int = None,
        xray: bool = None,
    ) -> None:
        """更新轮廓渲染参数 — 不重建 GPU 资源。"""
        if self._highlight_config is None:
            return
        if color is not None:
            self._highlight_config.color = tuple(color)
        if width is not None:
            self._highlight_config.width = max(1, int(width))
        if xray is not None:
            self._highlight_config.xray = bool(xray)
        self._update_highlight_params()

    # ════════════════════════════════════════════════════════
    # 管线入口 (Renderer 每帧调用)
    # ════════════════════════════════════════════════════════

    def _render_post_process(self, view: np.ndarray, proj: np.ndarray) -> None:
        """后处理管线入口。"""
        self._sync_selection()
        if self._highlight_config is not None:
            self._render_highlight(view, proj)

    def _sync_selection(self) -> None:
        """渲染线程: 原子交换选择状态 (pending → active)。"""
        if self._pending_selected_ids is not None:
            self._highlight_config.selected_ids = self._pending_selected_ids
            self._active_selected_ids = self._pending_selected_ids
            self._pending_selected_ids = None

    # ════════════════════════════════════════════════════════
    # 子类必须实现
    # ════════════════════════════════════════════════════════

    def _init_highlight(self, config: HighlightEffectConfig) -> None:
        """初始化 GPU 资源。子类实现。"""
        ...

    def _release_highlight(self) -> None:
        """释放 GPU 资源。子类实现。"""
        ...

    def _render_highlight(self, view: np.ndarray, proj: np.ndarray) -> None:
        """渲染轮廓高亮。子类实现。"""
        ...

    def _update_highlight_params(self) -> None:
        """更新参数 (不重建资源)。子类可选实现。"""
        pass
