"""Shader uniform 的声明式描述（GLSL `//!` 注解）—— 默认值 / GUI / 校验的唯一来源。

为什么要这层（2026-11 之前的状态）：
  - uniform 名字与类型：GLSL 正则解析 (`_resource_utils.parse_shader_files`)；
  - 默认值：材质按**类型**填白/0，真正的业务默认值硬编码在 ResourceManager（`uShininess=32`）
    或靠 shader 里 `0 = 用默认` 的哨兵约定；
  - GUI 形态：ScenePanel 按 shader **名字**分支（`if shader_name == 'Basic': 颜色盘`）；
  - 归属：三份互不相干的名单（解析排除 / 上传跳过 / 建材质特判）。

现在：shader 自己声明"这个 uniform 是什么"，其余消费方都读它：

    //! ui: color4 | label=mat.uColor | group=Surface | default=1,1,1,1
    uniform vec4 uColor = vec4(1.0);

注解语法（`//!` 前缀，机读；普通 `//` 注释保持自由）：

    //! ui:<kind> | label=<i18n 键> | group=<分组> | range=<min>..<max> | step=<n>
    //!   | default=<v[,v...]> | unit=<Hz|rad|deg> | choices=<v>:<标签键>[,<v>:<标签键>...]
    //!   | owner=<content|engine|runtime> | readonly | doc=<一行说明>

  - 位置：`uniform` 声明**上一行**，或**同一行** `;` 之后（两者都支持，同行优先）；
  - `kind` 省略时按 GLSL 类型推断（`vec4` → `vec4`，不会自动当颜色 —— 想要色盘就写 `color4`）；
  - 无注解 → 全部推断 + `editable=True` + 无范围 = **2026-11 之前的行为**（老 shader 一行不改）；
  - `default=` 是真正的默认值；`= 0.0` 的 GLSL 初始化只是语言要求，不再被当成哨兵；
  - `owner=engine|runtime` 的 uniform（`model` / `time` …）不进材质 —— 谁写入由声明说清。

协议: `Doc/Dev/shader_protocol.md` §6.1（工具仓 `docs_content/dev/shader_protocol.md`）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# GLSL 类型 → 缺省 kind（无注解时的降级推断）
_GLSL_KIND = {
    "float": "float",
    "double": "float",
    "int": "int",
    "uint": "int",
    "bool": "bool",
    "vec2": "vec2",
    "vec3": "vec3",
    "vec4": "vec4",
    "mat2": "readonly",
    "mat3": "readonly",
    "mat4": "readonly",
    "sampler2D": "readonly",
    "samplerCube": "readonly",
}

# kind → 分量数（向量类）
_VEC_SIZE = {"vec2": 2, "vec3": 3, "vec4": 4, "color3": 3, "color4": 4}

# kind 别名（写注解时的宽容度）
_KIND_ALIASES = {
    "number": "float",
    "slider": "float",
    "color": "color4",
    "colour": "color4",
    "rgba": "color4",
    "rgb": "color3",
    "toggle": "bool",
    "check": "bool",
    "select": "enum",
    "dropdown": "enum",
    "read-only": "readonly",
    "array": "array",
}

KINDS = ("float", "int", "bool", "color3", "color4", "vec2", "vec3", "vec4",
         "enum", "readonly", "array")

_OWNERS = ("content", "engine", "runtime")

# 数字解析用（default / range / step / choices 共用）
_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def infer_kind(glsl_type: str) -> str:
    """GLSL 类型 → kind（无注解降级）。未知类型按只读处理（不静默当成可写）。"""
    return _GLSL_KIND.get(str(glsl_type or "").strip(), "readonly")


def _split_float_tuple(raw: str) -> tuple | None:
    parts = [p.strip() for p in str(raw).split(",")]
    try:
        vals = tuple(float(p) for p in parts if p != "")
    except ValueError:
        return None
    return vals or None


def parse_annotation(body: str) -> dict:
    """`//!` 之后的正文 → 原始选项字典；无法识别的 token 静默忽略（注解不该让引擎崩）。

    返回键: ui / label / group / unit / owner / doc / range (min,max) / step /
            default (原始字符串) / choices (原始字符串) / readonly (bool)
    """
    out: dict = {}
    first = True
    for raw in str(body or "").split("|"):
        tok = raw.strip()
        if not tok:
            continue
        m = re.match(r"^ui\s*:\s*([\w\-]+)\s*$", tok)
        if m and first:
            out["ui"] = m.group(1).lower()
            first = False
            continue
        first = False
        if tok.lower() in ("readonly", "read-only"):
            out["readonly"] = True
            continue
        if "=" not in tok:
            continue
        key, _, val = tok.partition("=")
        key, val = key.strip().lower(), val.strip()
        if key == "range":
            m = re.match(rf"^({_NUM})\s*\.\.\s*({_NUM})$", val)
            if m:
                out["range"] = (float(m.group(1)), float(m.group(2)))
        elif key == "step":
            try:
                out["step"] = float(val)
            except ValueError:
                pass
        elif key in ("default", "choices", "label", "group", "unit", "owner", "doc"):
            out[key] = val
    return out


@dataclass(frozen=True)
class UniformSpec:
    """一个 uniform 的完整说明。字段语义见模块 docstring。"""

    name: str
    glsl_type: str
    kind: str = "readonly"
    label: str = ""
    group: str = ""
    unit: str = ""
    default: tuple | None = None
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    choices: tuple = ()          # ((int 值, 标签键), ...)
    owner: str = "content"       # content | engine | runtime
    editable: bool = True
    doc: str = ""

    # ── 派生语义 ──────────────────────────────────────────────
    @property
    def writable(self) -> bool:
        """能不能被 GUI / MCP 写（只读 kind 与 engine/runtime 归属都不能）。"""
        return bool(self.editable) and self.owner == "content" and self.kind != "readonly"

    @property
    def in_material(self) -> bool:
        """是否应进材质 `uniforms_data`（engine/runtime 归属由渲染器/引擎注入）。"""
        return self.owner == "content"

    def default_value(self):
        """注解默认值 → numpy 值；未声明返回 None（调用方回落到类型默认）。"""
        if self.default is None:
            return None
        try:
            import numpy as np
        except Exception:  # pragma: no cover — numpy 是硬依赖
            return None
        raw = self.default
        if self.kind in ("float",):
            return np.float32(raw[0]) if raw else np.float32(0)
        if self.kind in ("int", "enum"):
            return np.int32(int(round(raw[0]))) if raw else np.int32(0)
        if self.kind == "bool":
            return np.int32(1 if (raw and raw[0]) else 0)
        if self.kind in _VEC_SIZE:
            size = _VEC_SIZE[self.kind]
            vals = list(raw or ())
            if size == 4 and len(vals) == 3:
                vals.append(1.0)        # color3 风格默认 + 不透明
            vals = (vals + [0.0] * size)[:size]
            return np.array(vals, dtype=np.float32)
        return None

    def matches_default(self, value, eps: float = 1e-6) -> bool:
        """当前值是否等于注解默认值（面板据此显示"已改"标记/复位按钮）。"""
        ref = self.default_value()
        if ref is None:
            return True
        try:
            import numpy as np
            a = np.asarray(value, dtype=np.float64)
            b = np.asarray(ref, dtype=np.float64)
            return bool(a.shape == b.shape and np.allclose(a, b, atol=eps))
        except Exception:
            return True

    def to_dict(self) -> dict:
        """JSON 友好形态（编辑器 UI / MCP `schema.get` 共用）。"""
        return {
            "name": self.name,
            "glsl_type": self.glsl_type,
            "kind": self.kind,
            "label": self.label or self.name,
            "group": self.group,
            "unit": self.unit,
            "default": list(self.default) if self.default is not None else None,
            "min": self.minimum,
            "max": self.maximum,
            "step": self.step,
            "choices": [list(c) for c in self.choices],
            "owner": self.owner,
            "editable": self.writable,
            "doc": self.doc,
        }


def _parse_choices(raw: str) -> tuple:
    """`0:mat.phong,1:mat.blinn` → ((0, 'mat.phong'), (1, 'mat.blinn'))。"""
    out = []
    for part in str(raw or "").split(","):
        if ":" not in part:
            continue
        val, _, label = part.partition(":")
        try:
            out.append((int(round(float(val.strip()))), label.strip()))
        except ValueError:
            continue
    return tuple(out)


def build_spec(name: str, glsl_type: str, body: str | None = None,
               is_array: bool = False, reserved: bool = False) -> UniformSpec:
    """由声明 + 可选注解正文构造 spec（**唯一**构造入口）。"""
    opts = parse_annotation(body or "")
    raw_kind = str(opts.get("ui", "") or "").lower()
    kind = _KIND_ALIASES.get(raw_kind, raw_kind)
    if kind not in KINDS:
        kind = infer_kind(glsl_type)
    if is_array and not body:
        kind = "array"          # 无注解的数组：只读展示（避免按 vec3 误上传）
    owner = str(opts.get("owner", "content") or "content").lower()
    if owner not in _OWNERS:
        owner = "content"
    if reserved:
        owner = "engine"
    rng = opts.get("range")
    choices = _parse_choices(opts.get("choices", ""))
    editable = kind not in ("readonly", "array") and not opts.get("readonly")
    return UniformSpec(
        name=name,
        glsl_type=str(glsl_type or ""),
        kind=kind,
        label=str(opts.get("label", "") or ""),
        group=str(opts.get("group", "") or ""),
        unit=str(opts.get("unit", "") or ""),
        default=_split_float_tuple(opts.get("default", "")) if "default" in opts else None,
        minimum=rng[0] if rng else None,
        maximum=rng[1] if rng else None,
        step=opts.get("step"),
        choices=choices,
        owner=owner,
        editable=editable,
        doc=str(opts.get("doc", "") or ""),
    )


def _legacy_default(glsl_type: str):
    """无注解 / 无 default 时的类型默认值 —— 与 2026-11 之前完全一致。

    返回 None 表示"该类型不进材质"（int / sampler / 数组 / 未知）——同样是旧行为。
    """
    import numpy as np
    t = str(glsl_type or "")
    if t == "mat4":
        return np.zeros((4, 4), dtype=np.float32)
    if t == "vec4":
        return np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32)
    if t == "vec3":
        return np.array([1.0, 1.0, 1.0], dtype=np.float32)
    if t in ("float",):
        return np.float32(0)
    if t in ("double",):
        return np.float64(0)
    return None


def build_default_uniforms(uniforms_name_type: dict, uniform_specs: dict | None = None) -> dict:
    """按 (名字→类型) + spec 生成材质初始 `uniforms_data`（**唯一**默认值实现）。

    优先 spec.default（shader 里声明的那一份），否则回落类型默认。
    `owner=engine|runtime` 的 uniform 一律不进材质。
    """
    specs = uniform_specs or {}
    out: dict = {}
    for name, gtype in (uniforms_name_type or {}).items():
        spec = specs.get(name)
        if spec is not None:
            if not spec.in_material:
                continue
            val = spec.default_value()
            if val is not None:
                out[name] = val
                continue
        val = _legacy_default(gtype)
        if val is not None:
            out[name] = val
    return out
