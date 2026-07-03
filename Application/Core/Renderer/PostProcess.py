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
        cls._RenderEntities(view, proj)
        cls._render_post_process(view, proj)   ← 由本 Mixin 提供
        cls._render_all_overlays(view, proj)
    """

    # ── 后处理效果注册表 (当前仅 Highlight) ──
    _highlight_config: HighlightEffectConfig = None

    # ── 线程安全: 双缓冲选择状态 ──
    _pending_selected_ids: set[int] = None
    _active_selected_ids: set[int] = set()

    # ════════════════════════════════════════════════════════
    # 公开 API (Editor 层调用)
    # ════════════════════════════════════════════════════════

    @classmethod
    def register_highlight_effect(cls, config: HighlightEffectConfig) -> None:
        """注册轮廓高亮后处理效果 — 编译 shader、创建 FBO/VAO。

        调用时机: EditorLayer.OnAttach() → OutlinerID.register_to(renderer)
        前提: 已在渲染线程，GL 上下文有效。

        Args:
            config: 初始配置 (颜色/宽度/穿透模式)
        """
        cls._highlight_config = config
        cls._init_highlight(config)

    @classmethod
    def unregister_highlight_effect(cls) -> None:
        """注销轮廓高亮效果，释放全部 GPU 资源。"""
        cls._release_highlight()
        cls._highlight_config = None
        cls._pending_selected_ids = None
        cls._active_selected_ids = set()

    @classmethod
    def update_highlight_selection(cls, selected_ids: set[int]) -> None:
        """主线程安全: 更新待选实体 ID 集合。

        实际生效在下一帧 _render_post_process 中的 _sync_selection()。

        Args:
            selected_ids: 被选中的实体 ID 集合 (可为空)
        """
        cls._pending_selected_ids = set(selected_ids) if selected_ids else set()

    @classmethod
    def update_highlight_config(
        cls,
        color: tuple[float, float, float] = None,
        width: int = None,
        xray: bool = None,
    ) -> None:
        """更新轮廓渲染参数 — 不重建 GPU 资源。

        Args:
            color: 轮廓颜色 (r, g, b)
            width: 边缘检测采样半径 (像素)
            xray: 穿透模式
        """
        if cls._highlight_config is None:
            return
        if color is not None:
            cls._highlight_config.color = tuple(color)
        if width is not None:
            cls._highlight_config.width = max(1, int(width))
        if xray is not None:
            cls._highlight_config.xray = bool(xray)
        cls._update_highlight_params()

    # ════════════════════════════════════════════════════════
    # 管线入口 (Renderer 每帧调用)
    # ════════════════════════════════════════════════════════

    @classmethod
    def _render_post_process(cls, view: np.ndarray, proj: np.ndarray) -> None:
        """后处理管线入口 — 由 Renderer._do_start_frame() 在 Entities 之后调用。

        执行顺序:
          1. 同步选择状态 (_pending → _active)
          2. 渲染已注册的后处理效果 (当前仅 Highlight)
        """
        cls._sync_selection()
        if cls._highlight_config is not None:
            cls._render_highlight(view, proj)

    @classmethod
    def _sync_selection(cls) -> None:
        """渲染线程: 原子交换选择状态 (pending → active)。"""
        if cls._pending_selected_ids is not None:
            cls._highlight_config.selected_ids = cls._pending_selected_ids
            cls._active_selected_ids = cls._pending_selected_ids
            cls._pending_selected_ids = None

    # ════════════════════════════════════════════════════════
    # 子类必须实现
    # ════════════════════════════════════════════════════════

    @classmethod
    def _init_highlight(cls, config: HighlightEffectConfig) -> None:
        """初始化 GPU 资源 — 编译 shader、创建 FBO/VAO/全屏四边形。

        子类实现 (OpenGLPostProcess / ZenGLPostProcess)。
        """
        raise NotImplementedError

    @classmethod
    def _render_highlight(cls, view: np.ndarray, proj: np.ndarray) -> None:
        """执行 highlight 后处理渲染 — MRT → 边缘检测 → 合成。

        子类实现 (OpenGLPostProcess / ZenGLPostProcess)。
        """
        raise NotImplementedError

    @classmethod
    def _release_highlight(cls) -> None:
        """释放 highlight 相关 GPU 资源。

        子类实现 (OpenGLPostProcess / ZenGLPostProcess)。
        """
        raise NotImplementedError

    @classmethod
    def _update_highlight_params(cls) -> None:
        """更新可变渲染参数 (颜色/宽度等)，不重建 GPU 资源。

        子类可选覆写。默认空操作 — 参数在每帧 _render_highlight 中读取。
        """
        pass
