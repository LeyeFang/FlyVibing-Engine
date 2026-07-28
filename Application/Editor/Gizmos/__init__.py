"""
Editor/Gizmos — 编辑器专用组件可视化模块（纯数据生成，零图形API依赖）。

包含:
  - Grid                  : X-Y 平面参考网格 + 主轴
  - ViewGizmo             : 视图方向立方体 (6 面 overlay)
  - OutlinerID            : 实体轮廓高亮 (FBO + stencil)
  - TransformGizmo        : 变换 Gizmo 入口 (G/R/S 切换模式)
  - PositionGizmo         : 平移手柄 (G 键) — 三轴箭头 + 三平面
  - RotationGizmo         : 旋转手柄 (R 键) — 三轴旋转环
  - ScaleGizmo            : 缩放手柄 (S 键) — 轴圆 + 均匀缩放圆
"""

