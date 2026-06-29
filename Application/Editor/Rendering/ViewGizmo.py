"""
ViewGizmo — 视图方向立方体 (Fusion 360 风格)，绘制在渲染窗口右上角。

设计原则:
  - 正交投影 (无透视)，恒定屏幕空间大小
  - 立方体跟随摄像机轨道旋转，实时反映当前视图方向
  - 通过 overlay callback 机制注册到 Renderer，每帧回调计算 model 矩阵

坐标约定 (编辑器 ←→ GL):
  - 编辑器 X  =  GL  X   (+X 右)
  - 编辑器 Y  =  GL −Z   (−Z 前)
  - 编辑器 Z  =  GL  Y   (+Y 上)

六个面的 GL 几何法线 (与 OBJ 参考 Cube.obj 一致):
  - Front  (编辑器 -Y) :  GL normal = ( 0,  0, +1)
  - Back   (编辑器 +Y) :  GL normal = ( 0,  0, -1)
  - Right  (编辑器 +X) :  GL normal = ( 1,  0,  0)
  - Left   (编辑器 -X) :  GL normal = (-1,  0,  0)
  - Top    (编辑器 +Z) :  GL normal = ( 0,  1,  0)
  - Bottom (编辑器 -Z) :  GL normal = ( 0, -1,  0)

架构:
  - 零 GL 调用: 注册时仅传递 numpy 数据，GPU 资源由渲染器管理
  - 与 Grid 相同的解耦模式: EditorLayer → ViewGizmo.register_to(renderer)
"""

from __future__ import annotations
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from Application.Core.Renderer.Renderer import Renderer


# ════════════════════════════════════════════════════════════════
# 内联着色器
# ════════════════════════════════════════════════════════════════

_VIEWCUBE_VS: str = """#version 440 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aColor;
layout (location = 2) in vec3 aNormal;
layout (location = 3) in vec2 aTexCoord;
uniform mat4 uModel;
uniform mat4 uProj;
out vec3 vColor;
out vec3 vNormal;
out vec3 vLocalPos;
out vec2 vTexCoord;
void main() {
    gl_Position = uProj * uModel * vec4(aPos, 1.0);
    vColor = aColor;
    vNormal = normalize(mat3(uModel) * aNormal);
    vLocalPos = aPos;
    vTexCoord = aTexCoord;
}
"""

_VIEWCUBE_FS: str = """#version 440 core
in vec3 vColor;
in vec3 vNormal;
in vec3 vLocalPos;
in vec2 vTexCoord;
uniform sampler2D uLetterTex;
out vec4 fragColor;
void main() {
    // 法线朝向亮度
    float facing = vNormal.z * 0.15 + 0.85;
    vec3 litColor = vColor * facing;
    // 边缘检测
    float edgeDist;
    if (abs(vNormal.x) > 0.9) {
        edgeDist = min(0.5 - abs(vLocalPos.y), 0.5 - abs(vLocalPos.z));
    } else if (abs(vNormal.y) > 0.9) {
        edgeDist = min(0.5 - abs(vLocalPos.x), 0.5 - abs(vLocalPos.z));
    } else {
        edgeDist = min(0.5 - abs(vLocalPos.x), 0.5 - abs(vLocalPos.y));
    }
    edgeDist = max(edgeDist, 0.0);
    float edge = 1.0 - smoothstep(0.0, 0.04, edgeDist) * 0.40;
    // 采样字母纹理 (白色字母 on 透明背景)
    vec4 texColor = texture(uLetterTex, vTexCoord);
    // 字母 alpha 混合到面颜色上
    vec3 finalColor = mix(litColor, vec3(1.0), texColor.a * 0.9);
    fragColor = vec4(finalColor * edge, 1.0);
}
"""


# ════════════════════════════════════════════════════════════════
# ViewGizmo — 纯数据层 (零 GL, 与 Grid 对齐)
# ════════════════════════════════════════════════════════════════

class ViewGizmo:
    """视图方向立方体 — 6 独立面 overlay (纯数据, GL 由 Renderer 管理)。
    使用方式:
      ViewGizmo.register_to(renderer)     # OnAttach (注册 6 面 overlay)
      ViewGizmo.unregister_from(renderer) # OnDetach
      ViewGizmo.get_pick_data()           # → Renderer 用于 FBO 拾取
    """
    # ── 屏幕布局常量 ────────────────────────────────────────
    CUBE_SIZE_NDC: float = 0.10
    SCREEN_OFFSET_X: float = 0.82
    SCREEN_OFFSET_Y: float = 0.78
    # ── 六个面名称 (遍历顺序即渲染顺序) ──────────────────────
    FACE_NAMES: tuple[str, ...] = (
        'front', 'back',
        'left', 'right',
        'top', 'bottom',
    )
    # ── face_name → pick ID (编码到 B 通道, 1~6) ────────────
    FACE_PICK_IDS: dict[str, int] = {
        'front': 2, 'back': 1,
        'left': 3, 'right': 4,
        'top': 5, 'bottom': 6,
    }
    # ── face_name → GL 摄像机方向 (target → camera, EditorCamera.look_from_direction 用) ──
    FACE_LOOK_DIRECTIONS: dict[str, np.ndarray] = {
        'front':  np.array([ 0.0,  0.0,  1.0], dtype=np.float32),  # GL +Z
        'back':   np.array([ 0.0,  0.0, -1.0], dtype=np.float32),  # GL -Z
        'right':  np.array([ 1.0,  0.0,  0.0], dtype=np.float32),  # GL +X
        'left':   np.array([-1.0,  0.0,  0.0], dtype=np.float32),  # GL -X
        'top':    np.array([ 0.0,  1.0,  0.0], dtype=np.float32),  # GL +Y
        'bottom': np.array([ 0.0, -1.0,  0.0], dtype=np.float32),  # GL -Y
    }
    # ── 面颜色 ──────────────────────────────────────────────
    #       face    几何法线(GL)   编辑器方向   颜色
    FACE_COLORS: dict[str, tuple] = {
        'front':  (0.15, 0.85, 0.20),   # ( 0, 0, 1)  +Z  −Y  正绿
        'back':   (0.10, 0.70, 0.15),   # ( 0, 0,-1)  −Z  +Y  暗绿
        'right':  (0.90, 0.15, 0.12),   # (−1, 0, 0)  −X  −X  正红
        'left':   (0.72, 0.10, 0.08),   # ( 1, 0, 0)  +X  +X  暗红
        'top':    (0.08, 0.30, 0.80),   # ( 0, 1, 0)  +Y  +Z  暗蓝
        'bottom': (0.12, 0.45, 1.00),   # ( 0,-1, 0)  −Y  −Z  正蓝
    }
    # ── 每面 UV 变换 ────────────────────────────────────────
    #       面名      UV变换          该面显示的字母
    _FACE_UV_XFORM: dict[str, str] = {
        'front':  'mirror_v',
        'back':   'mirror_u',
        'right':  'ccw_mirror_u',
        'left':   'cw',
        'top':    'cw_mirror_u',
        'bottom': '',
    }
    # ── overlay key 前缀 ────────────────────────────────────
    OVERLAY_KEY_PREFIX: str = "editor_view_gizmo"
    # ════════════════════════════════════════════════════════════
    # 注册 / 注销 (纯数据, 零 GL)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def register_to(
        cls,
        renderer: 'Renderer'
    ) -> None:
        """注册 6 个面 overlay (纯数据, GPU 资源由 Renderer 管理)。"""
        from Application.Core.Renderer.Renderer import RenderResourceManger as RRM
        face_geometries = cls._build_face_geometries()
        tex_pixels = cls._build_letter_atlas()
        shared_cb = cls._compute_cube_model_cb
        for face_name in cls.FACE_NAMES:
            verts, indices = face_geometries[face_name]
            pick_id = cls.FACE_PICK_IDS.get(face_name, 0)
            print(face_name, pick_id)
            overlay = RRM.overlay_drawable_struct(
                key=f"{cls.OVERLAY_KEY_PREFIX}_{face_name}",
                vertices=verts,
                indices=indices,
                vs_src=_VIEWCUBE_VS,
                fs_src=_VIEWCUBE_FS,
                draw_mode='triangles',
                depth_test=False,
                blend=True,
                cull_face=True,
                ignore_scene_matrices=True,
                model_matrix_cb=shared_cb,
                texture_pixels=tex_pixels,
                texture_uniform='uLetterTex',
                vertex_stride=11 * 4,
                vertex_attrs=[
                    (0, 3, 0),    # aPos
                    (1, 3, 12),   # aColor
                    (2, 3, 24),   # aNormal
                    (3, 2, 36),   # aTexCoord
                ],
                pick_type=1,       # 1 = ViewGizmo face
                pick_id=pick_id,   # 1~6
            )
            renderer.register_overlay_drawable(overlay)
        print("[ViewGizmo] registered 6 face overlays")

    @classmethod
    def unregister_from(
        cls,
        renderer: 'Renderer'
    ) -> None:
        """注销 6 个面 overlay。"""
        for face_name in cls.FACE_NAMES:
            renderer.unregister_overlay_drawable(
                f"{cls.OVERLAY_KEY_PREFIX}_{face_name}"
            )
        print("[ViewGizmo] unregistered")

    # ════════════════════════════════════════════════════════════
    # 拾取数据导出 (供 Renderer 使用)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def get_pick_data(cls) -> dict:
        """返回 FBO 拾取所需的全部数据 (纯 numpy, 零 GL)。

        Returns:
            {
                'face_names':   FACE_NAMES,
                'pick_ids':     FACE_PICK_IDS,
                'geometries':   _build_face_geometries() 结果,
                'model_cb':     _compute_cube_model_cb,
            }
        """
        return {
            'face_names':  cls.FACE_NAMES,
            'pick_ids':    cls.FACE_PICK_IDS,
            'geometries':  cls._build_face_geometries(),
            'model_cb':    cls._compute_cube_model_cb,
        }

    # ════════════════════════════════════════════════════════════
    # Model matrix callback (6 faces shared, pure numpy)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _compute_cube_model_cb(cls, vp_w: int, vp_h: int) -> np.ndarray:
        """Compute the view cube model matrix (6 faces share one callback).

        Delegates to Core.Math.ViewGizmo.compute_cube_model().

        IMPORTANT: This returns a numpy ndarray (Type B matrix).
        GL upload MUST use GL_TRUE for both visual and pick passes.
        """
        from Application.Core.Math.ViewGizmo import compute_cube_model
        from Application.Editor.EditorCamera import EditorCamera
        cam = EditorCamera.get_instance()
        return compute_cube_model(vp_w, vp_h, cam.yaw, cam.pitch)

    # ════════════════════════════════════════════════════════════
    # 面几何生成 (纯 numpy, 每面独立)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _build_face_geometries(cls) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        """生成 6 个面的独立 (vertices, indices)。

        Returns:
            dict[face_name → (vertices(4×11), indices(6,))]
        """
        h = 0.5
        corners = {
            '---': np.array([-h, -h, -h], dtype=np.float32),
            '+--': np.array([+h, -h, -h], dtype=np.float32),
            '+-+': np.array([+h, -h, +h], dtype=np.float32),
            '--+': np.array([-h, -h, +h], dtype=np.float32),
            '-+-': np.array([-h, +h, -h], dtype=np.float32),
            '++-': np.array([+h, +h, -h], dtype=np.float32),
            '+++': np.array([+h, +h, +h], dtype=np.float32),
            '-++': np.array([-h, +h, +h], dtype=np.float32),
        }
        face_normals = {
            'front':  np.array([ 0.0,  0.0,  1.0], dtype=np.float32),
            'back':   np.array([ 0.0,  0.0, -1.0], dtype=np.float32),
            'right':  np.array([-1.0,  0.0,  0.0], dtype=np.float32),
            'left':   np.array([ 1.0,  0.0,  0.0], dtype=np.float32),
            'top':    np.array([ 0.0,  1.0,  0.0], dtype=np.float32),
            'bottom': np.array([ 0.0, -1.0,  0.0], dtype=np.float32),
        }
        face_uv_cells = {
            'front':  (0, 1), 'back':   (0, 0),
            'left':   (1, 1), 'right':  (1, 0),
            'top':    (2, 1), 'bottom': (2, 0),
        }

        def _rot90cw(u0, u1, v0, v1):
            return [(u0, v1), (u0, v0), (u1, v0), (u1, v1)]
        def _rot180(u0, u1, v0, v1):
            return [(u1, v1), (u0, v1), (u0, v0), (u1, v0)]
        def _rot90ccw(u0, u1, v0, v1):
            return [(u1, v0), (u1, v1), (u0, v1), (u0, v0)]
        def _mirror_u(uvs):
            return [(u1 + u0 - u, v) for u, v in uvs]
        def _mirror_v(uvs):
            return [(u, v1 + v0 - v) for u, v in uvs]

        face_defs = [
            ('front',  ['-++', '+++', '+-+', '--+']),
            ('back',   ['---', '+--', '++-', '-+-']),
            ('right',  ['---', '-+-', '-++', '--+']),
            ('left',   ['+++', '++-', '+--', '+-+']),
            ('top',    ['-++', '-+-', '++-', '+++']),
            ('bottom', ['+--', '---', '--+', '+-+']),
        ]
        result: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for face_name, corner_keys in face_defs:
            color = cls.FACE_COLORS.get(face_name, (0.5, 0.5, 0.5))
            normal = face_normals[face_name]
            col, row = face_uv_cells[face_name]
            u0, u1 = col / 3.0, (col + 1) / 3.0
            v0, v1 = 1.0 - (row + 1) / 2.0, 1.0 - row / 2.0
            xf = cls._FACE_UV_XFORM.get(face_name, 'base')
            if xf == 'cw':
                uv_corners = _rot90cw(u0, u1, v0, v1)
            elif xf == 'ccw':
                uv_corners = _rot90ccw(u0, u1, v0, v1)
            elif xf == '180':
                uv_corners = _rot180(u0, u1, v0, v1)
            elif xf == 'mirror_u':
                uv_corners = _mirror_u([(u0, v0), (u1, v0), (u1, v1), (u0, v1)])
            elif xf == 'mirror_v':
                uv_corners = _mirror_v([(u0, v0), (u1, v0), (u1, v1), (u0, v1)])
            elif xf == 'ccw_mirror_u':
                uv_corners = _mirror_u(_rot90ccw(u0, u1, v0, v1))
            elif xf == 'cw_mirror_u':
                uv_corners = _mirror_u(_rot90cw(u0, u1, v0, v1))
            elif xf == 'ccw_mirror_v':
                uv_corners = _mirror_v(_rot90ccw(u0, u1, v0, v1))
            elif xf == 'cw_mirror_v':
                uv_corners = _mirror_v(_rot90cw(u0, u1, v0, v1))
            elif xf == '180_mirror_u':
                uv_corners = _mirror_u(_rot180(u0, u1, v0, v1))
            else:
                uv_corners = [
                    (u0, v0),
                    (u1, v0),
                    (u1, v1),
                    (u0, v1)
                ]
            if face_name in ('front', 'back', 'left', 'right'):
                uv_corners = [
                    uv_corners[2],
                    uv_corners[3],
                    uv_corners[0],
                    uv_corners[1]
                ]
            verts = []
            for i, ck in enumerate(corner_keys):
                pos = corners[ck]
                u, v = uv_corners[i]
                verts.extend([
                    pos[0], pos[1], pos[2],
                    color[0], color[1], color[2],
                    normal[0], normal[1], normal[2],
                    u, v
                ])
            indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)
            result[face_name] = (
                np.array(verts, dtype=np.float32).reshape(4, 11),
                indices,
            )
        return result

    # ════════════════════════════════════════════════════════════
    # 字母纹理 atlas (纯 numpy 像素, 供渲染器上传)
    # ════════════════════════════════════════════════════════════

    # 5×7 点阵字体
    _LETTER_BITS: dict[str, list[int]] = {
        'F': [0b11111, 0b10000, 0b11110, 0b10000, 0b10000, 0b10000, 0b10000],
        'B': [0b11110, 0b10001, 0b10001, 0b11110, 0b10001, 0b10001, 0b11110],
        'L': [0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b11111],
        'R': [0b11110, 0b10001, 0b10001, 0b11110, 0b10100, 0b10010, 0b10001],
        'U': [0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110],
        'D': [0b11110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b11110],
    }

    @classmethod
    def _build_letter_atlas(cls) -> np.ndarray:
        """生成字母纹理 atlas 像素 (纯 numpy, 不上传 GL)。
        Returns:
            RGBA uint8 array (H, W, 4)
        """
        CELL_W, CELL_H = 24, 32
        GLYPH_W, GLYPH_H = 5, 7
        ATLAS_W = CELL_W * 3
        ATLAS_H = CELL_H * 2
        pixels = np.zeros((ATLAS_H, ATLAS_W, 4), dtype=np.uint8)
        positions = [
            ('F', 0, 0), ('B', 0, 1),
            ('L', 1, 0), ('R', 1, 1),
            ('U', 2, 0), ('D', 2, 1),
        ]
        for letter, col, row in positions:
            bits = cls._LETTER_BITS.get(letter)
            if bits is None:
                continue
            ox = col * CELL_W
            oy = row * CELL_H
            gx0 = ox + (CELL_W - GLYPH_W) // 2
            gy0 = oy + (CELL_H - GLYPH_H) // 2
            for gy in range(GLYPH_H):
                line = bits[gy]
                for gx in range(GLYPH_W):
                    if line & (1 << (GLYPH_W - 1 - gx)):
                        pixels[gy0 + gy, gx0 + gx] = [255, 255, 255, 255]
        return pixels
