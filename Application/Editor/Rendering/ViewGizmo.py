"""
ViewGizmo — 摄像机无关的视图方向立方体 (Fusion 360 风格)。

设计原则:
  - 立方体绘制在渲染窗口右上角，占据恒定的屏幕空间
  - 无透视投影 (正交投影)，仅 rotation 参与 model 矩阵
  - 六个面分别代表: 前(Front/编辑器+Y)、后(Back/编辑器-Y)、
    左(Left/编辑器-X)、右(Right/编辑器+X)、
    顶(Top/编辑器+Z)、底(Bottom/编辑器-Z)
  - 立方体跟随世界坐标系旋转 — 当编辑器摄像机轨道旋转时，
    立方体同步旋转以反映当前视图方向
  - 鼠标拖拽立方体 → 可以切换摄像机视图 (未来功能)

坐标约定:
  - 编辑器 X 轴 = GL  X 轴  (+X 方向)
  - 编辑器 Y 轴 = GL -Z 轴  (-Z 方向)
  - 编辑器 Z 轴 = GL  Y 轴  (+Y 方向)

面方向 (编辑器 → GL):
  - Front  (编辑器 +Y): GL normal = ( 0,  0, -1)
  - Back   (编辑器 -Y): GL normal = ( 0,  0,  1)
  - Right  (编辑器 +X): GL normal = ( 1,  0,  0)
  - Left   (编辑器 -X): GL normal = (-1,  0,  0)
  - Top    (编辑器 +Z): GL normal = ( 0,  1,  0)
  - Bottom (编辑器 -Z): GL normal = ( 0, -1,  0)

架构:
  - 使用 overlay callback 机制 (非 overlay_drawable), 因为需要独立的
    正交投影矩阵和 view 矩阵
  - 自己管理 GPU 资源: shader / VAO / VBO / EBO
  - 对齐 Grid 的解耦模式: EditorLayer → ViewGizmo.register_to(renderer)
"""

from __future__ import annotations
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from Application.Core.Renderer.Renderer import Renderer


# ════════════════════════════════════════════════════════════════
# 内联着色器
# ════════════════════════════════════════════════════════════════

_VIEWCUBE_VS: str = """#version 330 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aColor;
layout (location = 2) in vec3 aNormal;
layout (location = 3) in vec2 aTexCoord;
uniform mat4 uModel;
out vec3 vColor;
out vec3 vNormal;
out vec3 vLocalPos;
out vec2 vTexCoord;
void main() {
    vec4 worldPos = uModel * vec4(aPos, 1.0);
    gl_Position = worldPos;
    vColor = aColor;
    vNormal = normalize(mat3(uModel) * aNormal);
    vLocalPos = aPos;
    vTexCoord = aTexCoord;
}
"""

_VIEWCUBE_FS: str = """#version 330 core
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
# ViewGizmo
# ════════════════════════════════════════════════════════════════

class ViewGizmo:
    """视图方向立方体 — 摄像机无关的屏幕角落定向指示器。

    使用方式:
      ViewGizmo.register_to(renderer)   # OnAttach
      ViewGizmo.unregister_from(renderer)  # OnDetach
    """

    # ── 屏幕布局 ──────────────────────────────────────────────
    CUBE_SIZE_NDC: float = 0.10        # 立方体在 NDC 中的半边长
    SCREEN_OFFSET_X: float = 0.82      # 右上角 NDC X 偏移
    SCREEN_OFFSET_Y: float = 0.78      # 右上角 NDC Y 偏移

    # ── 面颜色 (编辑器坐标系) ─────────────────────────────────
    # 正红/正绿/正蓝 — 分别对应左右/前后/上下视图
    FACE_COLORS: dict[str, tuple] = {
        'front':  (0.15, 0.85, 0.20),   # 前: 正绿  (前后 = 绿)
        'back':   (0.10, 0.70, 0.15),   # 后: 暗绿
        'right':  (0.90, 0.15, 0.12),   # 右: 正红  (左右 = 红)
        'left':   (0.72, 0.10, 0.08),   # 左: 暗红
        'top':    (0.12, 0.45, 1.00),   # 顶: 正蓝  (上下 = 蓝)
        'bottom': (0.08, 0.30, 0.80),   # 底: 暗蓝
    }

    # ── 每面字母 UV 变换 (硬编码, 已验证) ──────────────────────
    _FACE_UV_XFORM: dict[str, str] = {
        'front':  'cw',            # F
        'back':   'ccw_mirror_u',  # B
        'left':   'ccw_mirror_u',  # L
        'right':  'ccw_mirror_u',  # R
        'top':    'cw_mirror_u',   # U
        'bottom': 'mirror_u',      # D
    }

    # ── overlay 注册 key ──────────────────────────────────────
    OVERLAY_KEY: str = "editor_view_gizmo"

    # ════════════════════════════════════════════════════════════
    # 公共 API (零 GL 调用)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def register_to(cls, renderer: 'Renderer') -> None:
        """向渲染器注册视图立方体 (纯数据, 零 GL 调用)。

        Args:
            renderer: 渲染器实例
        """
        from Application.Core.Renderer.Renderer import RenderResourceManger as RRM

        vertices, indices = cls._build_cube_geometry()
        tex_pixels = cls._build_letter_atlas()

        overlay = RRM.overlay_drawable_struct(
            key=cls.OVERLAY_KEY,
            vertices=vertices,
            indices=indices,
            vs_src=_VIEWCUBE_VS,
            fs_src=_VIEWCUBE_FS,
            draw_mode='triangles',
            depth_test=False,
            blend=True,
            cull_face=True,
            ignore_scene_matrices=True,
            model_matrix_cb=cls._compute_cube_model_cb,
            texture_pixels=tex_pixels,
            texture_uniform='uLetterTex',
            vertex_stride=11 * 4,
            vertex_attrs=[
                (0, 3, 0),    # aPos
                (1, 3, 12),   # aColor
                (2, 3, 24),   # aNormal
                (3, 2, 36),   # aTexCoord
            ],
        )
        renderer.register_overlay_drawable(overlay)
        print("[ViewGizmo] registered (zero GL) — view cube at top-right")

    @classmethod
    def unregister_from(cls, renderer: 'Renderer') -> None:
        """从渲染器取消注册。"""
        renderer.unregister_overlay_drawable(cls.OVERLAY_KEY)
        print("[ViewGizmo] unregistered")

    # ════════════════════════════════════════════════════════════
    # Model 矩阵回调 (纯 numpy, 零 GL, 由渲染器每帧调用)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _compute_cube_model_cb(cls, vp_w: int, vp_h: int) -> np.ndarray:
        """计算视图立方体的 model 矩阵 (渲染器每帧回调)。

        Args:
            vp_w, vp_h: 视口宽高 (像素)

        Returns:
            4×4 float32 model 矩阵
        """
        from Application.Editor.EditorCamera import EditorCamera
        cam = EditorCamera.get_instance()
        view_mat = cam.get_view_matrix()

        R_cube = view_mat[:3, :3].copy()
        R_cube[2, :] *= -1  # NDC 视线方向矫正
        R_cube[1, :] *= -1  # 编辑器 Z 轴旋转方向

        rot_mat = np.identity(4, dtype=np.float32)
        rot_mat[:3, :3] = R_cube

        aspect = vp_w / max(vp_h, 1)
        s = cls.CUBE_SIZE_NDC
        scale_mat = np.diag([s / aspect, s, s, 1.0]).astype(np.float32)

        trans_mat = np.identity(4, dtype=np.float32)
        trans_mat[0, 3] = cls.SCREEN_OFFSET_X
        trans_mat[1, 3] = cls.SCREEN_OFFSET_Y

        return (trans_mat @ rot_mat @ scale_mat).astype(np.float32)

    # ════════════════════════════════════════════════════════════
    # 立方体几何生成 (纯 numpy)
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _build_cube_geometry(cls) -> tuple[np.ndarray, np.ndarray]:
        """生成立方体的顶点和索引。

        6 个面，每面 4 个顶点 (位置+颜色+法线+UV)，共 24 顶点，36 索引。

        字母纹理 atlas: 3列×2行 (F/B/L/R/U/D)
        每面 UV 映射到对应字母区域。

        Returns:
            (vertices, indices): vertices shape (24, 11), indices shape (36,)
        """
        # 单位立方体 (边长 1, 中心在原点)
        h = 0.5  # half-size
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
            'front':  np.array([ 0.0,  0.0, -1.0], dtype=np.float32),
            'back':   np.array([ 0.0,  0.0,  1.0], dtype=np.float32),
            'right':  np.array([ 1.0,  0.0,  0.0], dtype=np.float32),
            'left':   np.array([-1.0,  0.0,  0.0], dtype=np.float32),
            'top':    np.array([ 0.0,  1.0,  0.0], dtype=np.float32),
            'bottom': np.array([ 0.0, -1.0,  0.0], dtype=np.float32),
        }

        # UV atlas 布局: 3列×2行, 每个字母占据 1/3 宽 × 1/2 高
        # 列: 0=F, 1=L, 2=U  (行0);  0=B, 1=R, 2=D (行1)
        face_uv_cells = {
            'front':  (0, 0),   # F
            'back':   (0, 1),   # B
            'left':   (1, 0),   # L
            'right':  (1, 1),   # R
            'top':    (2, 0),   # U
            'bottom': (2, 1),   # D
        }

        # ── 每面 UV 角点顺序 (配合字母阅读方向) ──
        # base: [bl=(u0,v0), br=(u1,v0), tr=(u1,v1), tl=(u0,v1)]
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
            ('front',  ['---', '-+-', '++-', '+--']),
            ('back',   ['+-+', '+++', '-++', '--+']),
            ('right',  ['+--', '++-', '+++', '+-+']),
            ('left',   ['--+', '-++', '-+-', '---']),
            ('top',    ['-+-', '-++', '+++', '++-']),
            ('bottom', ['---', '+--', '+-+', '--+']),
        ]

        verts = []
        idx_list = []
        vi = 0

        for face_name, corner_keys in face_defs:
            color = cls.FACE_COLORS.get(face_name, (0.5, 0.5, 0.5))
            normal = face_normals[face_name]
            col, row = face_uv_cells[face_name]
            u0, u1 = col / 3.0, (col + 1) / 3.0
            v0, v1 = 1.0 - (row + 1) / 2.0, 1.0 - row / 2.0  # GL 纹理原点在左下

            # 硬编码 UV 变换 (前后/左右/上下均已对正)
            xf = cls._FACE_UV_XFORM.get(face_name, 'base')
            if xf == 'cw':
                uv_corners = _rot90cw(u0, u1, v0, v1)
            elif xf == 'ccw':
                uv_corners = _rot90ccw(u0, u1, v0, v1)
            elif xf == '180':
                uv_corners = _rot180(u0, u1, v0, v1)
            elif xf == 'mirror_u':
                uv_corners = _mirror_u([(u0, v0), (u1, v0), (u1, v1), (u0, v1)])
            elif xf == 'ccw_mirror_u':
                uv_corners = _mirror_u(_rot90ccw(u0, u1, v0, v1))
            elif xf == 'cw_mirror_u':
                uv_corners = _mirror_u(_rot90cw(u0, u1, v0, v1))
            else:
                uv_corners = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]

            for i, ck in enumerate(corner_keys):
                pos = corners[ck]
                u, v = uv_corners[i]
                verts.extend([pos[0], pos[1], pos[2],
                              color[0], color[1], color[2],
                              normal[0], normal[1], normal[2],
                              u, v])
            idx_list.extend([vi, vi + 1, vi + 2,
                             vi, vi + 2, vi + 3])
            vi += 4

        return (
            np.array(verts, dtype=np.float32).reshape(-1, 11),
            np.array(idx_list, dtype=np.uint32),
        )

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
