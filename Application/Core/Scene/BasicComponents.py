from dataclasses import dataclass as component
from enum import Enum

from Application.Resource.ResourceManager import ResourceManager
from Application.Core.Scene.DataContract import DataclassContract, register_contract


@component
class Component(DataclassContract):
    pass


@component
class ObjectInfo(DataclassContract):
    name: str
    obj_id: int


@component
class Transform(DataclassContract):
    # ── 世界空间 (World / Global) — 由 local + parent 链动态推导，不应直接设置 ──
    position_x: float = 0
    position_y: float = 0
    position_z: float = 0
    rotation_x: float = 0
    rotation_y: float = 0
    rotation_z: float = 0
    scale_x: float = 1
    scale_y: float = 1
    scale_z: float = 1

    # ── 本地空间 (Local, 相对于父实体) — ★ 唯一信源 (source of truth) ──
    local_pos_x: float = 0
    local_pos_y: float = 0
    local_pos_z: float = 0
    local_rot_x: float = 0
    local_rot_y: float = 0
    local_rot_z: float = 0
    local_scl_x: float = 1
    local_scl_y: float = 1
    local_scl_z: float = 1

    def __post_init__(self) -> None:
        """确保 local 字段有默认值 (esper 创建实体时可能跳过 dataclass 默认值)。"""
        # 不做 world→local 复制 — 根实体调用方通过 SetEntityTransform 显式写入两边



@component
class MeshRenderer(DataclassContract):
    mesh_id: int = 1
    material_id: int = 0
    visible: bool = True

    def __post_init__(self) -> None:
        """dataclass 生成 __init__ 后自动调用 — 绑定默认 Material。"""
        if self.material_id == 0:
            self.material_id = ResourceManager.GetDefaultMaterial()


class ProjectionType(Enum):
    PERSPECTIVE = "perspective"
    ORTHOGRAPHIC = "orthographic"


@component
class MediaPlayer(DataclassContract):
    """媒体播放器 — 动态纹理载体 (协议: Doc/Dev/media_protocol.md)。

    - source : 媒体文件路径 (CWD 相对/绝对; M1=GIF, 视频后续)
    - 播放参数可经 Inspector/节点/MCP 编辑 (component.set type=MediaPlayer);
    - 播放时钟/帧号等运行期状态在 MediaSystem (不序列化 — 不进场景文件);
      编辑器侧编辑只是模板 — PIE/运行时由节点 ShowMedia 驱动播放。
    """
    source: str = ""
    playing: bool = True
    loop: bool = True
    speed: float = 1.0
    fit: str = "stretch"   # stretch / contain / cover (M1 仅 stretch; 见协议)


@component
class Light(DataclassContract):
    """光源 — 平面光 / 点光 双类型 (协议: Doc/Dev/shader_protocol.md §7)。

    light_type:
      - "directional" (平面光/方向光): 照射方向 = Transform 局部 -Z 前向的世界方向,
        与实体位置无关 (位置仅决定图标位置); 经 uLightDir[]/uLightColor[] 注入。
      - "point" (点光): 光源位于实体世界坐标; 按 range 衰减
        att = (1 - d/range)² (d ≥ range → 0); 经 uPointPos[]/uPointColor[]/uPointRange[] 注入。

    - 每类至多 4 盏 (按世界查询顺序; 超出忽略); 颜色 × 强度由渲染器每帧合并注入;
    - 仅在使用 Lighting 约定 shader 的材质上可见 — Basic/SSVEP 不受影响;
    - 无阴影 (roadmap P2); 默认场景含一盏平面光 "Sun" (DefaultLight.prefab)。
    """
    light_type: str = "directional"        # "directional" (平面光) | "point" (点光)
    color_r: float = 1.0
    color_g: float = 1.0
    color_b: float = 1.0
    intensity: float = 1.0
    range: float = 10.0                    # 点光衰减半径 (平面光忽略)


# 向后兼容别名 (旧 import 路径; 新代码统一用 Light; 旧场景文件 "DirectionalLight" 由加载器迁移)
DirectionalLight = Light


@component
class TextDisplay(DataclassContract):
    """文字显示 — 文本→动态纹理光栅化载体 (协议: Doc/Dev/text_protocol.md)。

    两种形态 (bg_color alpha 决定):
      - 有色画布: bg_color alpha = 1 (文字画在实心背景上, 如标签/题板);
      - 浮空文字: bg_color alpha = 0 (画布透明, 仅字形可见 — 依赖
        Material.blend="alpha" 标准混叠, 见的 P1 混合交付)。

    生命周期:
      - 编辑器内编辑即预览 (无时钟维度, 与媒体"编辑器=模板"有意偏差);
      - PIE 中由 SetText 节点驱动 (组件=状态载体 / 节点=控制面);
      - 画布尺寸 auto: 随内容自动变化 (内部同尺寸热更 / 换尺寸换纹理, 无感)。
    """
    text: str = "Text"
    font: str = "segoeui"                    # Resource/Fonts 名称 或字体文件路径 (中文需 CJK 字体)
    size: int = 64                            # 字号 (像素)
    bold: bool = False                        # 合成加粗 (描边扩展 — 无需字体变体)
    italic: bool = False                      # 合成斜体 (斜切变换)
    color: tuple = (1.0, 1.0, 1.0, 1.0)       # 文字 RGBA (0..1)
    bg_color: tuple = (0.0, 0.0, 0.0, 0.0)    # 画布底色 RGBA — alpha=0 = 浮空文字
    align: str = "center"                     # left / center / right
    line_spacing: float = 1.15
    padding: int = 8                          # 画布内边距 (像素)
    wrap_width: int = 0                       # >0 = 按像素宽度自动折行
    world_height: float = 1.0                 # auto_scale 时的画布世界高度 (引擎单位)
    auto_scale: bool = True                   # 自动把载体 quad 缩放为画布纵横比


@component
class Camera(DataclassContract):
    # 投影类型（默认透视投影）
    projection_type: ProjectionType = ProjectionType.PERSPECTIVE
    # 透视投影参数（角度制）
    fov: float = 45.0
    aspect_ratio: float = 16.0 / 9.0
    # 正交投影参数（世界单位半高）
    ortho_size: float = 5.0
    # 通用裁剪平面
    near_plane: float = 0.1
    far_plane: float = 1000.0
    # 视图辅助参数（用于计算视图矩阵，但实际位置/旋转来自 Transform）
    # 默认观察方向：局部坐标系中的前方（通常为 +Z 或 -Z，这里按 OpenGL 习惯设 -Z）
    local_forward: tuple = (0.0, 0.0, -1.0)
    up_vector: tuple = (0.0, 1.0, 0.0)
    # 可选：是否为主摄像机（若场景中有多个摄像机，用于标识默认）
    is_primary: bool = False


# ── 注册到 Serializable 注册表 ──
register_contract("Transform", Transform)
register_contract("MeshRenderer", MeshRenderer)
register_contract("Camera", Camera)
register_contract("MediaPlayer", MediaPlayer)
register_contract("Light", Light)
register_contract("TextDisplay", TextDisplay)
register_contract("Component", Component)
register_contract("ObjectInfo", ObjectInfo)
