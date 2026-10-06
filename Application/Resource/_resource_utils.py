"""着色器文件解析 — 读取 .vert/.frag 源码 + .spv 二进制，提取 uniform 元信息。"""

import re
import os


# ★ 渲染器保留 uniform — 由渲染管线每帧统一注入，不进材质 uniforms_data
#   (材质若持有这些名字，逐实体上传会覆盖渲染器注入值 — 协议: Doc/Dev/shader_protocol.md)
_RESERVED_UNIFORMS = frozenset({
    "uAmbient",      # 场景环境光 (vec3)
    "uCameraPos",    # 相机世界坐标 (vec3) — 高光用
    "uLightCount",   # 方向光数量 (int)
    "uLightDir",     # 方向光方向数组 (vec3[4]) — 光线传播方向
    "uLightColor",   # 方向光颜色×强度 数组 (vec3[4])
})


def parse_shader_files(
    vert_path: str,
    frag_path: str,
    vert_spv_path: str = "",
    frag_spv_path: str = ""
) -> tuple:
    """
    读取独立的 .vert + .frag 着色器文件，提取 uniform 元信息，
    并可选加载预编译的 SPIR-V 二进制。

    Args:
        vert_path    : 顶点着色器 GLSL 源码路径
        frag_path    : 片段着色器 GLSL 源码路径
        vert_spv_path: 顶点着色器 SPIR-V 二进制路径 (可选)
        frag_spv_path: 片段着色器 SPIR-V 二进制路径 (可选)

    Returns:
        (vs_src, fs_src, vs_spv, fs_spv, uniforms_dict)
    """
    with open(vert_path, 'r', encoding='utf-8') as f:
        vs_src = f.read()
    with open(frag_path, 'r', encoding='utf-8') as f:
        fs_src = f.read()

    vs_spv = b""
    fs_spv = b""
    if vert_spv_path and os.path.exists(vert_spv_path):
        with open(vert_spv_path, 'rb') as f:
            vs_spv = f.read()
    if frag_spv_path and os.path.exists(frag_spv_path):
        with open(frag_spv_path, 'rb') as f:
            fs_spv = f.read()

    # 提取 uniform 元信息 (普通 uniform + sampler + push_constant block)
    uniforms = {}
    # ① 普通 uniform: layout(...) uniform type name [= init]; 
    uniform_pattern = re.compile(
        r'(?:layout\s*\([^)]*\)\s*)?uniform\s+'
        r'(\w+)\s+'
        r'(\w+)\s*'
        r'(?:\[[^\]]*\])?\s*'
        r'(?:=[^;]*)?\s*;',
        re.MULTILINE
    )
    # ② push_constant block 成员: layout(push_constant) uniform Name { type member; ... }
    push_block_pattern = re.compile(
        r'layout\s*\(\s*push_constant\s*\)\s*uniform\s+\w+\s*\{'
        r'([^}]+)\}',
        re.MULTILINE
    )
    push_member_pattern = re.compile(
        r'(\w+)\s+(\w+)\s*;'
    )

    for src, tag in [(vs_src, "vertex"), (fs_src, "fragment")]:
        # 普通 uniform
        for match in uniform_pattern.finditer(src):
            u_type, u_name = match.group(1), match.group(2)
            if u_name in _RESERVED_UNIFORMS:
                continue  # 渲染器每帧注入的保留 uniform — 不进材质
            uniforms[u_name] = u_type
        # push_constant block 成员
        for block_match in push_block_pattern.finditer(src):
            block_body = block_match.group(1)
            for m in push_member_pattern.finditer(block_body):
                u_type, u_name = m.group(1), m.group(2)
                if u_name in uniforms and uniforms[u_name] != u_type:
                    print(f"警告: uniform '{u_name}' 类型不一致 ({uniforms[u_name]} vs {u_type})")
                uniforms[u_name] = u_type

    return vs_src, fs_src, vs_spv, fs_spv, uniforms


def parse_shader_file(
    filepath: str
) -> tuple:
    """兼容旧版 .shader 格式 (保留)。"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"文件未找到: {filepath}")

    pattern = r'(#version\s+\d+\s+\w+.*?)(?=#version\s+\d+\s+\w+|\Z)'
    blocks = re.findall(pattern, content, re.DOTALL)
    if not blocks:
        raise ValueError("没有找到任何以 #version 开头的着色器代码块")

    vertex_src = None
    fragment_src = None
    uniforms = {}
    uniform_pattern = re.compile(
        r'(?:layout\s*\([^)]*\)\s*)?uniform\s+'
        r'(\w+)\s+'
        r'(\w+)\s*'
        r'(?:\[[^\]]*\])?\s*;',
        re.MULTILINE
    )

    for block in blocks:
        block = block.strip()
        is_frag = bool(re.search(r'\bout\s+vec4\s+\w+\s*;', block) or 'FragColor' in block)
        is_vert = bool('gl_Position' in block or re.search(r'layout\s*\(\s*location\s*=\s*\d+\s*\)\s+in\s+vec3', block))

        if is_frag:
            fragment_src = block
            target = "fragment"
        elif is_vert:
            vertex_src = block
            target = "vertex"
        else:
            continue

        for match in uniform_pattern.finditer(block):
            u_type, u_name = match.group(1), match.group(2)
            uniforms[u_name] = u_type

    return vertex_src, fragment_src, uniforms
