"""
RHI 架构验证测试 — 等价于当前主线 EntryPoint.py 的功能，
但渲染器走 CommandQueue 异步命令模式。

设计:
  - TestEditorHost: 覆写 _create_renderer() → RHI 变体 openGLRenderer
  - EditorLayer / DebugLayer: 直接用主线版本（已迁移到 EditorHost）
  - 所有渲染命令通过 CommandQueue 投递，StartFrame 时消费

运行:
  python Test/RHI/test_rhi_host.py
"""

from __future__ import annotations
import sys
import os

# ════════════════════════════════════════════════════════════════
# 1. 路径设置
# ════════════════════════════════════════════════════════════════

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


# ════════════════════════════════════════════════════════════════
# 2. 薄子类 — RHI 渲染器
# ════════════════════════════════════════════════════════════════

from Application.Editor.EditorHost import EditorHost


class TestRHIEditorHost(EditorHost):
    """RHI 变体 EditorHost — 渲染器走命令队列。"""

    @classmethod
    def _create_renderer(cls):
        """使用 RHI 变体 openGLRenderer (OnEvent→enqueue, StartFrame→execute)。"""
        from Test.RHI.Engine.OpenGLRenderer import OpenGLRenderer
        cls.window.MakeContextCurrent()
        EditorHost.editor_renderer = OpenGLRenderer.Create()
        return EditorHost.editor_renderer


# ════════════════════════════════════════════════════════════════
# 3. 启动
# ════════════════════════════════════════════════════════════════

def main():
    print(f"Python {sys.version_info[:2]}")
    print("=" * 50)
    print("RHI CommandQueue 架构验证测试")
    print("=" * 50)

    from Application.Editor.EditorPlugin import EditorPlugin

    # ── 初始化 (RHI 渲染器) ──
    TestRHIEditorHost.init(window_type='GLFW', renderer_type='OpenGL')

    # ── 加载插件 — 用主线 EditorLayer + DebugLayer (已迁移到 EditorHost) ──
    TestRHIEditorHost.load_plugin(EditorPlugin())

    # ── 运行 ──
    TestRHIEditorHost.run()


if __name__ == '__main__':
    main()
