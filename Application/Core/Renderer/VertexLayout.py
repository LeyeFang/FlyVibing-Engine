"""
VertexLayout — 跨渲染后端的顶点格式描述符。

设计原则:
  - 不可变 (frozen dataclass), 线程安全
  - 零图形 API 依赖 — 存纯粹的数据描述
  - 所有标准布局定义在 STD_LAYOUT 类中, 作为唯一真理来源
  - 提供 to_zengl_format() / to_gl() 等辅助方法, 渲染器各取所需

使用方式:
  from Application.Core.Renderer.VertexLayout import VertexLayout, STD_LAYOUT

  # 标准布局
  mesh.layout = STD_LAYOUT.ENTITY_POS_UV_NORMAL

  # 自定义 overlay 布局
  gizmo_layout = VertexLayout(
      attributes=(
          (0, 3, 0),    # location=0, 3 floats (position), byte_offset=0
          (1, 3, 12),   # location=1, 3 floats (color),    byte_offset=12
      ),
      stride=24
  )
"""

from __future__ import annotations
from dataclasses import dataclass
import re
import warnings


@dataclass(frozen=True)
class VertexLayout:
    """跨后端顶点格式描述符。

    Attributes:
        attributes: ((location, component_count, byte_offset), ...)
                    按 byte_offset 升序排列。
                    location=0 必须是 position。
        stride:     每顶点总字节数。

    不变式:
        - attributes 不为空
        - stride >= 最后一个 attribute 的 offset + component_count * 4
        - 所有 offset 是 4 的整数倍
    """

    attributes: tuple  # ((loc, count, offset), ...)
    stride: int

    def __post_init__(self):
        if not self.attributes:
            raise ValueError("VertexLayout.attributes 不能为空")
        if self.stride <= 0:
            raise ValueError(f"VertexLayout.stride 必须 > 0, 得到 {self.stride}")

    # ══════════════════════════════════════════════════
    # 后端适配方法
    # ══════════════════════════════════════════════════

    def to_zengl_format(self) -> str:
        """生成 ZenGL 的 zengl.bind() 格式字符串。

        例如 ENTITY_POS_UV_NORMAL → '3f 2f 3f'
        """
        attrs = sorted(self.attributes, key=lambda a: a[2])
        return ' '.join(f'{c}f' for _, c, _ in attrs)

    def to_zengl_locations(self) -> list[int]:
        """生成 ZenGL 的 zengl.bind() locations 参数。

        例如 ENTITY_POS_UV_NORMAL → [0, 1, 2]
        """
        attrs = sorted(self.attributes, key=lambda a: a[2])
        return [loc for loc, _, _ in attrs]

    def to_gl_attribs(self) -> list[tuple[int, int, int, int]]:
        """生成 OpenGL glVertexAttribPointer 参数列表。

        Returns:
            [(location, component_count, stride, byte_offset), ...]
        """
        return [
            (loc, count, self.stride, offset)
            for loc, count, offset in self.attributes
        ]

    def get_position_attr(self) -> tuple[int, int, int]:
        """获取 location=0 的属性 (position).

        Returns:
            (location, component_count, byte_offset) — 不存在时返回 (0, 3, 0)
        """
        for loc, count, offset in self.attributes:
            if loc == 0:
                return (loc, count, offset)
        return (0, 3, 0)

    # ══════════════════════════════════════════════════
    # Shader 一致性检查
    # ══════════════════════════════════════════════════

    _SHADER_ATTR_RE: re.Pattern = re.compile(
        r'layout\s*\(\s*location\s*=\s*(\d+)\s*\)\s+in\s+\w+\s+(\w+)\s*;'
    )

    def get_active_locations(self, vs_src: str) -> list[int]:
        """返回与 shader 实际声明位置匹配的 locations (未匹配的填 -1)。

        shader 中声明但未在 main() 中使用的 attribute 视为 inactive，
        对应的 location 返回 -1。layout 中有但 shader 未声明的也返回 -1。

        这用于 ZenGL 的 zengl.bind() — ZenGL 要求 locations 与 linked
        program 的 active attributes 严格一致。
        """
        if not vs_src:
            return self.to_zengl_locations()

        # ── 解析 shader 声明的 attribute: location → name ──
        shader_attrs: dict[int, str] = {}
        for m in VertexLayout._SHADER_ATTR_RE.finditer(vs_src):
            shader_attrs[int(m.group(1))] = m.group(2)

        # ── 哪些在 main() 中被实际使用 ──
        _body = vs_src
        _mm = re.search(r'void\s+main\s*\(', _body)
        if _mm:
            _body = _body[_mm.end():]
        used_names = {name for name in shader_attrs.values() if name in _body}

        result = []
        for loc in self.to_zengl_locations():
            if loc in shader_attrs and shader_attrs[loc] in used_names:
                result.append(loc)
            else:
                result.append(-1)
        return result

    @staticmethod
    def check_shader_consistency(
        layout: 'VertexLayout',
        vs_src: str,
        context: str = '',
    ) -> None:
        """检查 VertexLayout 与 shader 源码的顶点属性一致性。

        规则:
          1. layout 中的每个 attribute 必须在 shader 中声明且被使用
          2. shader 中声明且使用的 attribute 必须在 layout 中定义

        不一致时发出 UserWarning, 不抛异常 — 引擎允许运行但提示开发者修复。

        Args:
            layout: 顶点格式描述符
            vs_src: 顶点着色器 GLSL 源码
            context: 上下文标识 (如 "entity shader 'Basic'"), 用于 warning 消息
        """
        if layout is None or not vs_src:
            return

        # ── 解析 shader 中的 attribute 声明 ──
        shader_attrs: dict[int, str] = {}  # location → name
        for m in VertexLayout._SHADER_ATTR_RE.finditer(vs_src):
            shader_attrs[int(m.group(1))] = m.group(2)

        # ── 解析 shader 中实际使用的 attribute (main 函数体内被引用) ──
        _body = vs_src
        _mm = re.search(r'void\s+main\s*\(', _body)
        if _mm:
            _body = _body[_mm.end():]
        used_names: set[str] = {name for name in shader_attrs.values() if name in _body}

        ctx = f" [{context}]" if context else ""

        # ── 检查 1: layout 中有, shader 中未声明 → Warning ──
        layout_locs = {loc for loc, _, _ in layout.attributes}
        for loc in sorted(layout_locs):
            if loc not in shader_attrs:
                warnings.warn(
                    f"VertexLayout{ctx}: location {loc} 在 VBO 数据中存在, "
                    f"但 shader 未声明该 attribute — 数据被浪费",
                    UserWarning, stacklevel=2,
                )
            elif shader_attrs[loc] not in used_names:
                warnings.warn(
                    f"VertexLayout{ctx}: attribute '{shader_attrs[loc]}' (location {loc}) "
                    f"在 shader 中声明但 main() 内未使用 — GLSL 编译器会优化掉",
                    UserWarning, stacklevel=2,
                )

        # ── 检查 2: shader 中用到了但 layout 中没有 → Warning ──
        for loc in sorted(shader_attrs):
            if loc not in layout_locs and shader_attrs[loc] in used_names:
                warnings.warn(
                    f"VertexLayout{ctx}: shader 使用了 attribute "
                    f"'{shader_attrs[loc]}' (location {loc}), "
                    f"但 VertexLayout 未定义 — 该 attribute 不会被绑定",
                    UserWarning, stacklevel=2,
                )


# ══════════════════════════════════════════════════
# 标准布局常量 — 引擎唯一真理来源
# ══════════════════════════════════════════════════


class STD_LAYOUT:
    """引擎所有标准顶点布局常量。

    添加新布局:
      1. 在此处添加常量
      2. 更新 RENDERER_DATA_SPEC.md 的布局表格
    """

    # ── Entity 网格: pos(3f) + uv(2f) + normal(3f) ──
    # 每顶点 8 floats = 32 bytes
    #   [px, py, pz,  u, v,  nx, ny, nz]
    #    |-- 0-11 --| |12-19| |-- 20-31 --|
    ENTITY_POS_UV_NORMAL: VertexLayout = VertexLayout(
        attributes=(
            (0, 3, 0),   # aPos      — location 0, vec3, byte offset 0
            (1, 2, 12),  # aTexCoord — location 1, vec2, byte offset 12
            (2, 3, 20),  # aNormal   — location 2, vec3, byte offset 20
        ),
        stride=32,
    )

    # ── 纯位置: pos(3f) ──
    # Grid / 坐标轴 / 简单 overlay
    # 每顶点 3 floats = 12 bytes
    POSITION_ONLY: VertexLayout = VertexLayout(
        attributes=((0, 3, 0),),
        stride=12,
    )

    # ── ViewGizmo 面: pos(3f) + color(3f) + normal(3f) + texcoord(2f) ──
    # 每顶点 11 floats = 44 bytes
    VIEW_GIZMO: VertexLayout = VertexLayout(
        attributes=(
            (0, 3, 0),   # aPos
            (1, 3, 12),  # aColor
            (2, 3, 24),  # aNormal
            (3, 2, 36),  # aTexCoord
        ),
        stride=44,
    )

    # ── TransformGizmo: pos(3f) + color(3f) ──
    # 每顶点 6 floats = 24 bytes
    TRANSFORM_GIZMO: VertexLayout = VertexLayout(
        attributes=(
            (0, 3, 0),   # aPos
            (1, 3, 12),  # aColor
        ),
        stride=24,
    )

    # ── 全屏 quad (PostProcess): pos(2f) ──
    # 每顶点 2 floats = 8 bytes
    SCREEN_QUAD: VertexLayout = VertexLayout(
        attributes=((0, 2, 0),),
        stride=8,
    )
