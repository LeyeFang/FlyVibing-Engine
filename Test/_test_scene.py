"""
Common Test Scene — 深灰背景 + 三个白色立方体的统一测试场景。

提供:
  - create_three_cubes(renderer, positions=...)  — 创建 3 个立方体实体
  - register_grid(renderer)                       — 注册摄像机跟随网格
  - DEFAULT_CUBE_POSITIONS                        — 标准立方体位置

所有测试应通过本模块创建场景，确保视觉基准一致。
"""

from __future__ import annotations

from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Scene.BasicComponents import MeshRenderer
from Application.Editor.Gizmos.Grid import Grid
from Application.Editor.Gizmos.ViewGizmo import ViewGizmo
from Application.Editor.Gizmos.OutlinerID import OutlinerID


# ═══════════════════════════════════════════════════════════════
# 标准场景参数
# ═══════════════════════════════════════════════════════════════

DEFAULT_CUBE_POSITIONS: list[tuple[float, float, float]] = [
    (-2.0, 0.0, 0.0),
    ( 0.0, 0.0, 0.0),
    ( 2.0, 0.0, 0.0),
]
"""三个白色立方体的标准位置 — 沿 X 轴等距排列。"""


# ═══════════════════════════════════════════════════════════════
# 场景构建函数
# ═══════════════════════════════════════════════════════════════

def create_three_cubes(
    renderer,
    positions: list[tuple[float, float, float]] = None,
) -> list[int]:
    """创建三个白色立方体实体并注册到渲染器。

    Args:
        renderer: 渲染器实例 (需支持 register_entity)。
        positions: 立方体位置列表，默认 DEFAULT_CUBE_POSITIONS。

    Returns:
        entity_ids: 创建的实体 ID 列表。
    """
    if positions is None:
        positions = DEFAULT_CUBE_POSITIONS

    cube_mesh_id = ResourceManager.GetDefaultMesh('Cube')
    entity_ids = []

    for pos in positions:
        eid = SceneManager._current().AddEntity()
        entity_ids.append(eid)
        SceneManager._current().AddComponentToEntity(eid, MeshRenderer(mesh_id=cube_mesh_id))
        SceneManager._current().SetEntityTransform(eid, position_xyz=pos)

    return entity_ids


def register_grid(renderer) -> None:
    """注册摄像机跟随网格到渲染器。

    网格中心跟随 EditorCamera 注视点，半径 = 摄像机距离。
    0.8r~1r 边缘虚化至透明。

    Args:
        renderer: 渲染器实例 (需为 openGLRenderer 或其子类)。
    """
    Grid.register_to(renderer)
    print("[Scene] Grid registered (camera-following)")


def register_view_gizmo(renderer) -> None:
    """注册 ViewGizmo 到渲染器。

    ViewGizmo 立方体旋转方向由 Core.Math.ViewGizmo.compute_cube_model()
    内部的 SIGN_YAW = -1.0 处理，调用方直接传入 EditorCamera.yaw 即可，
    不需要额外取反。主线和所有测试共享同一约定。

    约定（任何测试使用 ViewGizmo 时必须遵守）:
      - compute_cube_model 的 yaw 参数 = EditorCamera.get_instance().yaw（原值）
      - 鼠标 X 轴正方向拖拽 → yaw 增大 → ViewGizmo 立方体绕 GL Y 轴（编辑器 Z 轴）
        逆时针旋转（从上往下看）
      - 不要对 yaw 做任何额外取反
    """
    ViewGizmo.register_to(renderer)
    print("[Scene] ViewGizmo registered")


def register_outliner_id(renderer) -> None:
    """注册 OutlinerID 轮廓高亮到渲染器。"""
    OutlinerID.register_to(renderer)
    print("[Scene] OutlinerID registered")


def unregister_view_gizmo(renderer) -> None:
    """从渲染器注销 ViewGizmo。"""
    ViewGizmo.unregister_from(renderer)


def unregister_outliner_id(renderer) -> None:
    """从渲染器注销 OutlinerID。"""
    OutlinerID.unregister_from(renderer)


# ═══════════════════════════════════════════════════════════════
# 一键场景
# ═══════════════════════════════════════════════════════════════

def setup_default_scene(
    renderer,
    *,
    with_grid: bool = False,
    with_gizmo: bool = False,
    with_outliner: bool = False,
    cube_positions: list = None,
) -> list[int]:
    """一键搭建标准测试场景：深灰背景 + 三个白色立方体 + 可选 overlay。

    所有测试应通过此函数创建场景，确保视觉基准完全一致。

    Args:
        renderer: 渲染器实例。
        with_grid: 是否注册摄像机跟随网格。
        with_gizmo: 是否注册 ViewGizmo。
        with_outliner: 是否注册 OutlinerID 轮廓高亮。
        cube_positions: 立方体位置，默认 DEFAULT_CUBE_POSITIONS。

    Returns:
        entity_ids: 创建的实体 ID 列表。
    """
    entity_ids = create_three_cubes(renderer, positions=cube_positions)

    if with_grid:
        register_grid(renderer)
    if with_gizmo:
        register_view_gizmo(renderer)
    if with_outliner:
        register_outliner_id(renderer)

    return entity_ids
