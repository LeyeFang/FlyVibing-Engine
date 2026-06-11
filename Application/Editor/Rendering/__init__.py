"""
Editor/Rendering — 编辑器专用渲染模块。

包含:
  - Grid                  : X-Y 平面参考网格 + 主轴
  - ViewGizmo             : 视图方向立方体 (6 面 overlay)
  - Outliner              : 实体轮廓高亮 (FBO + stencil)
  - OpenGLEditorRenderer  : 编辑器渲染桥梁 (统一管理上述资源)
"""

