"""
Editor Outliner (ID Buffer) — Blender 风格的实体 ID + 屏幕空间边缘检测轮廓高亮。

设计理念:
  不使用 stencil buffer。改用 MRT (Multiple Render Target) 渲染两个 attachment:
    Attachment 0: 颜色 (RGBA8)
    Attachment 1: 实体 ID (R32UINT)
  然后通过 screen-space edge detection (Roberts cross) 检测 ID 不连续像素作为轮廓。

架构:
  本文件仅包含纯业务逻辑 — 选择状态管理 + 配置参数。
  所有 GPU 渲染细节委托给 Core/Renderer/ 中的 PostProcess 管线。
  Editor 层完全不感知 OpenGL / ZenGL。

使用方式:
  OutlinerID.register_to(renderer)     # 自动适配 OpenGL / ZenGL 后端
  OutlinerID.unregister_from(renderer)
  OutlinerID.set_selected_entities(selected_set)
  OutlinerID.configure(xray=True, outline_width=2, outline_color=(1,0.6,0.2))
"""

from __future__ import annotations


# ============================================================================
# 参数常量
# ============================================================================

OUTLINE_COLOR: tuple = (0.878, 0.416, 0.153)      # Blender 橙色
OUTLINE_WIDTH: int = 3                                  # 边缘检测半径 (像素)
OUTLINE_XRAY: bool = True                             # 默认穿透模式


# ============================================================================
# OutlinerID — 纯业务逻辑 (零图形 API 依赖)
# ============================================================================

class OutlinerID:
    """选中实体轮廓高亮 — 业务编排层。

    职责:
      - 持有选择状态和配置参数
      - 委托 PostProcess (Core/Renderer/) 执行 GPU 渲染
      - 不 import 任何图形 API (OpenGL / ZenGL / zengl / imgui 等)

    线程安全:
      - 主线程: set_selected_entities() / clear() / configure()
      - 渲染线程: PostProcess._sync_selection() 在 _render_post_process 中同步
    """

    _renderer = None

    _color: tuple = OUTLINE_COLOR
    _width: int = OUTLINE_WIDTH
    _xray: bool = OUTLINE_XRAY

    # ========================================================================
    # 注册 / 注销
    # ========================================================================

    @classmethod
    def register_to(cls, renderer) -> None:
        """注册 outliner — 委托 Renderer 初始化 PostProcess GPU 资源。

        调用时机: EditorLayer.OnAttach() (渲染线程，GL 上下文有效)。

        Args:
            renderer: openGLRenderer 或 ZenGLRenderer 类
        """
        from Application.Core.Renderer.PostProcess import HighlightEffectConfig

        cls._renderer = renderer
        config = HighlightEffectConfig(
            color=cls._color,
            width=cls._width,
            xray=cls._xray,
        )
        renderer.register_highlight_effect(config)

    @classmethod
    def unregister_from(cls, renderer) -> None:
        """注销 outliner — 释放 PostProcess GPU 资源。"""
        renderer.unregister_highlight_effect()
        cls._renderer = None

    # ========================================================================
    # 主线程 API (零 GL 调用)
    # ========================================================================

    @classmethod
    def set_selected_entities(cls, entity_ids: set[int]) -> None:
        """更新选中的实体 ID 集合 (主线程安全)。

        实际生效在下一帧 PostProcess._render_post_process 中的 _sync_selection()。

        Args:
            entity_ids: 被选中的实体 ID 集合
        """
        if cls._renderer is not None:
            cls._renderer.update_highlight_selection(entity_ids)

    @classmethod
    def clear(cls) -> None:
        """清除所有选中 (主线程安全)。"""
        if cls._renderer is not None:
            cls._renderer.update_highlight_selection(set())

    @classmethod
    def configure(
        cls,
        color: tuple[float, float, float] = None,
        outline_width: int = None,
        xray: bool = None,
    ) -> None:
        """更新轮廓渲染参数 (主线程安全)。

        参数变更立即推送到 Renderer，不重建 GPU 资源。

        Args:
            color:         轮廓颜色 (r, g, b)
            outline_width: 边缘检测采样半径 (像素)
            xray:          穿透模式 (True=轮廓始终可见)
        """
        if color is not None:
            cls._color = tuple(color)
        if outline_width is not None:
            cls._width = max(1, int(outline_width))
        if xray is not None:
            cls._xray = bool(xray)
        if cls._renderer is not None:
            cls._renderer.update_highlight_config(
                color=color,
                width=outline_width,
                xray=xray,
            )

    # ========================================================================
    # 兼容性 — 保留 _sync() 空实现 (EditorLayer 可能引用)
    # ========================================================================

    @classmethod
    def _sync(cls) -> None:
        """渲染线程同步 (已废弃)。

        选择状态同步现在由 PostProcess._sync_selection() 在
        _render_post_process 中自动执行。保留此方法以兼容可能的旧调用方。
        """
        pass
