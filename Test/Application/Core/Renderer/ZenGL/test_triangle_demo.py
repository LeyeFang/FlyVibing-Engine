"""
ZenGL 基础渲染流程 Demo — 三角形绘制与全管线遍历
═══════════════════════════════════════════════════════════════════════════════

本 Demo 按阶段演示 ZenGL 的核心渲染流程，每个阶段对应引擎中的一个功能点:

  Stage 1: 纯 GPU 三角形 (gl_VertexID, 无缓冲区)  → 等价于全屏后处理 / Compute-like 绘制
  Stage 2: 缓冲区三角形 (ctx.buffer + zengl.bind)  → 等价于 Mesh 顶点数据上传
  Stage 3: 索引三角形 (index_buffer)               → 等价于 Mesh 索引绘制
  Stage 4: Uniform Buffer (MVP 矩阵)               → 等价于 Camera + Model 矩阵传递
  Stage 5: Framebuffer → Blit                     → 等价于 FBO 离屏渲染 + 屏幕输出
  Stage 6: Image.read() (readPixels)               → 等价于 GPU Picking / 截图

操作:
  按数字键 1-6  → 切换 Stage
  ESC           → 退出

依赖:
  pip install zengl glfw numpy

运行:
  python Test/Application/Core/Renderer/ZenGL/test_triangle_demo.py   (项目根目录)
"""

from __future__ import annotations

# ════════════════════════════════════════════════════════════════
# TODO: 此文件内容丢失，需要从备份恢复完整实现
# ════════════════════════════════════════════════════════════════
# 原始文件包含:
#   - 路径设置 (_path_setup)
#   - GLFW 窗口初始化
#   - 6 个 Stage 的完整 ZenGL 渲染实现
#   - 主循环 (键盘切换 stage)
