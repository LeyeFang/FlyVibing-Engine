import re


def parse_shader_file(
    filepath: str
) -> tuple:
    """
    从 .shader 文件中读取内容，分离出顶点着色器和片段着色器的源代码，
    并提取所有 uniform 变量的名称和类型。

    参数:
        filepath (str): .shader 文件的路径。

    返回:
        tuple: (vertex_src, fragment_src, uniforms_dict)
            - vertex_src (str): 顶点着色器源码，若无则为 None
            - fragment_src (str): 片段着色器源码，若无则为 None
            - uniforms_dict (dict): 形如 {"uniform_name": "type"} 的字典，
              包含两个着色器中定义的所有 uniform（同名时以片段着色器中的为准，并给出警告）

    异常:
        FileNotFoundError: 文件不存在。
        ValueError: 文件内容无法解析（没有找到任何有效着色器块，或无法确定类型）。
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"文件未找到: {filepath}")
    # 1. 按 #version 分割代码块
    pattern = r'(#version\s+\d+\s+\w+.*?)(?=#version\s+\d+\s+\w+|\Z)'
    blocks = re.findall(pattern, content, re.DOTALL)
    if not blocks:
        raise ValueError("没有找到任何以 #version 开头的着色器代码块")
    vertex_src = None
    fragment_src = None
    uniforms = {}
    # 用于提取 uniform 的正则（支持 layout(...) 限定符，数组，行尾分号）
    uniform_pattern = re.compile(
        r'(?:layout\s*\([^)]*\)\s*)?uniform\s+'
        r'(\w+)\s+'                 # 类型 (1)
        r'(\w+)\s*'                 # 名称 (2)
        r'(?:\[[^\]]*\])?\s*;',     # 可选数组维度 + 分号
        re.MULTILINE
    )
    for block in blocks:
        block = block.strip()
        # 识别顶点/片段着色器
        is_frag = bool(re.search(r'\bout\s+vec4\s+\w+\s*;', block) or 'FragColor' in block)
        is_vert = bool('gl_Position' in block or re.search(r'layout\s*\(\s*location\s*=\s*\d+\s*\)\s+in\s+vec3', block))
        if is_frag:
            fragment_src = block
            target = "fragment"
        elif is_vert:
            vertex_src = block
            target = "vertex"
        else:
            print(f"警告: 无法识别着色器类型，已跳过块:\n{block[:100]}...")
            continue
        # 提取当前块中的 uniform
        for match in uniform_pattern.finditer(block):
            uniform_type = match.group(1)
            uniform_name = match.group(2)
            if uniform_name in uniforms:
                print(f"警告: uniform '{uniform_name}' 在 {target} 着色器中重复定义（之前可能在其他块中已定义），将覆盖为当前类型 {uniform_type}")
            uniforms[uniform_name] = uniform_type
    if vertex_src is None and fragment_src is None:
        raise ValueError("未能提取到有效的顶点或片段着色器代码")
    return vertex_src, fragment_src, uniforms
