"""Extension 静态审查器 v0 — 扩展开发者的规范自查工具（无需引擎运行）。

用法:
    python Utils/User/ExtensionKit/review_extension.py <extension_dir> [<dir>...]
    python Utils/User/ExtensionKit/review_extension.py --all    # 扫仓库内全部 Functions/*/

检查项（对照 Doc/ExtDev/extension_dev_protocol.md）:

  [manifest]
    M1 extension.json 存在且为合法 JSON
    M2 id 合法（^[a-z][a-z0-9_]*$）
    M3 api_version 与宿主兼容（前缀 "1"）
    M4 entry 格式合法且文件存在（无 entry = planned/partial 允许）
    M5 capabilities 取值合法（ops/ui/nodes/threads/jobs/settings/device）
    M6 description 非空（菜单 tooltip）

  [code]（entry 存在时静态扫描）
    C1 capabilities 含 ui → entry 类继承 UIExtensionBase（语言层强制）
    C2 capabilities 含 ui → 实现 on_ui_event
    C3 register_window 调用声明 close_policy（窗口 X 语义显式化 — §7）
    C4 ops 注册名不得自带 "ext." 前缀（前缀由宿主强制）
    C5 无 monkey-patch 迹象（顶层引擎赋值启发式）
    C6 Application.* import 在常用白名单内
    C7 imgui 文本字形安全（字体图集外字符显示为 '?' — 与主应用 test_ui_text_safety 同源规则）
    C8 imgui 窗口栈配对纪律：begin_child 不得被条件门控（全裁剪 0x0 时返回 False）
    C9 combo/tab_item 反向规则：end_combo/end_tab_item 仅在 begin 返回 True 时调用
    C10 无顶层 imgui 上下文/窗口/GL 创建（纯导入允许 — M0 口径）
    C11 不触碰宿主全局 imgui 状态（create/destroy_context、set_ini_filename、io/style 赋值 —
        含 get_io()/get_style() 链式与别名写法）

  [files]
    F2 TODO.md 存在（状态档案）

退出码: 0 = 无 FAIL（WARN 不失败）; 1 = 存在 FAIL; 2 = 用法错误。
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys

_CAPABILITIES = {"ops", "ui", "nodes", "threads", "jobs", "settings", "device", "graph"}
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_IMPORT_RE = re.compile(
    r"^\s*from\s+(Application[\w\.]*)\s+import|^\s*import\s+(Application[\w\.]*)", re.M)
_IMPORT_ALLOW = (
    "Application.Core.Extension",
    "Application.Functions",
    "Application.Core.Events",
    "Application.Core.ThreadRegistry",
    # 跨机器设备身份（协议 device_io_protocol §12）— 官方示例扩展依赖的公共设施
    "Application.Core.DeviceRegistry",
)
_MONKEY_RE = re.compile(r"^Application\w*(?:\.\w+)*\s*=", re.M)
_UI_BASE_RE = re.compile(r"class\s+\w+\s*\([^)]*UIExtensionBase")

# 字形安全集（与主应用 Test/Application/Editor/test_ui_text_safety.py 同源；字体图集 = 
# ASCII + Latin-1 + General Punctuation 子集 + FontAwesome 私有区）
_SAFE_RANGES = [
    (0x0020, 0x007E),
    (0x00A0, 0x00FF),
    (0x2013, 0x2014),
    (0x2018, 0x201D),
    (0x2022, 0x2022),
    (0x2026, 0x2026),
    (0xF000, 0xFFFF),
]


def unsafe_chars(text: str) -> list:
    """返回 imgui 字体图集外字符（去重排序 → 渲染为 '?' 的隐患）；换行/制表符放行。"""
    bad = set()
    for ch in text:
        if ch in "\n\t":
            continue
        cp = ord(ch)
        if not any(a <= cp <= b for a, b in _SAFE_RANGES):
            bad.add(ch)
    return sorted(bad)


# ── imgui 窗口栈纪律（C8/C9/C10 — 与 Doc/Dev/ui_protocol.md §2.13 同源规则） ──
_BEGIN_CHILD = ("begin_child",)
_BEGIN_SCOPED = ("begin_combo", "begin_tab_item", "begin_menu", "begin_popup")
_END_SCOPED = ("end_combo", "end_tab_item", "end_menu", "end_popup")
_CTX_CREATE = ("create_context", "glfw_init", "glfw_init_for_opengl", "opengl2_init",
               "opengl3_init", "new_frame", "end_frame", "render", "run",
               "manually_render", "manually_show_gui")


def _imgui_call(node: ast.AST) -> tuple:
    """`imgui.xxx(...)` / `hello_imgui.xxx(...)` → (base 名, 属性名); 其它 → ("", "")。"""
    if not isinstance(node, ast.Call):
        return "", ""
    f = node.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f.value.id, f.attr
    return "", ""


def gated_begin_child(tree: ast.AST) -> list:
    """把 `begin_child` 当条件用的位置 → ["L<行> …"]。

    反模式: `if imgui.begin_child(...): … imgui.end_child()` —— 宿主窗口被完全裁剪
    （最小化 0x0）时返回 False → 漏 `end_child` → 窗口栈失衡 → 之后任意 `end()` 断言。
    """
    out: list[str] = []
    for node in ast.walk(tree):
        test = None
        if isinstance(node, (ast.If, ast.While)):
            test = node.test
        elif isinstance(node, ast.IfExp):
            test = node.test
        if test is None:
            continue
        for sub in ast.walk(test):
            _base, attr = _imgui_call(sub)
            if attr in _BEGIN_CHILD:
                out.append(f"L{node.lineno} {attr}() 被当作条件")
    return out


def unguarded_scoped_ends(tree: ast.AST) -> list:
    """函数内不在任何 `if` 体内的 `end_combo/end_tab_item` 等 → ["L<行> …"]（反向规则）。"""
    out: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        guarded: set = set()
        for sub in ast.walk(fn):
            if isinstance(sub, ast.If):
                for stmt in sub.body:
                    for c in ast.walk(stmt):
                        if isinstance(c, ast.Call) and _imgui_call(c)[1] in _END_SCOPED:
                            guarded.add(id(c))
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Call):
                _base, attr = _imgui_call(sub)
                if attr in _END_SCOPED and id(sub) not in guarded:
                    out.append(f"L{sub.lineno} {attr}() 不在任何 if 体内")
    return out


def toplevel_context_calls(tree: ast.Module) -> list:
    """模块顶层（**不含**函数/类体内）的 imgui 上下文/窗口/GL 创建 → ["L<行> …"]。

    注意: `ast.walk` 会钻进函数体 — 必须逐层剪掉函数/类作用域, 否则窗口回调里的
    `imgui.new_frame()` 之类会被误判（实测踩过）。
    """
    out: list[str] = []
    scope_cut = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
    stack: list = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, scope_cut):       # 在"取出时"剪枝（压入时剪不掉自身）
            continue
        base, attr = _imgui_call(node)
        if base in ("imgui", "hello_imgui") and attr in _CTX_CREATE:
            out.append(f"L{node.lineno} {base}.{attr}()")
        stack.extend(ast.iter_child_nodes(node))
    return out


# C11: 扩展不得触碰宿主全局 imgui 状态（会污染整个编辑器与其它扩展）
_GLOBAL_FORBIDDEN_CALLS = ("create_context", "destroy_context", "set_ini_filename")
_GLOBAL_FORBIDDEN_IO_ATTRS = ("get_io", "get_style")


def _is_io_source(node: ast.AST) -> bool:
    """`imgui.get_io()` / `imgui.get_style()` 调用（全局 io/style 来源）。"""
    return isinstance(node, ast.Call) and _imgui_call(node)[1] in _GLOBAL_FORBIDDEN_IO_ATTRS


def global_imgui_state_writes(tree: ast.AST) -> list:
    """扩展对宿主全局 imgui 状态的写入 → ["L<行> …"]（C11）。

    禁止: `create_context` / `destroy_context` / `set_ini_filename`（任意位置, 含
          `imgui.get_io().set_ini_filename(...)` 链式写法与 `io = imgui.get_io()`
          别名写法）; `imgui.get_io().x = …` / `imgui.get_style().x = …` 赋值。
    允许: 窗口内 `push_style_color / push_style_var`（局部作用域, 由宿主窗口包裹）;
          纯导入与只读查询（`io.display_size` 之类）。
    """
    out: list[str] = []
    nodes = list(ast.walk(tree))

    # 第一遍: 收集指向 get_io()/get_style() 返回对象的变量名（别名流）
    io_aliases: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Assign) and _is_io_source(node.value):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    io_aliases.add(tgt.id)

    def _flag(lineno: int, what: str) -> None:
        out.append(f"L{lineno} {what}")

    # 第二遍: 检出禁用调用与全局状态赋值
    for node in nodes:
        if isinstance(node, ast.Call):
            _base, attr = _imgui_call(node)
            if attr in _GLOBAL_FORBIDDEN_CALLS:                 # imgui.create_context() …
                _flag(node.lineno, f"{attr}()")
                continue
            fn = node.func
            if isinstance(fn, ast.Attribute):
                if _is_io_source(fn.value):                     # imgui.get_io().set_ini_filename(…)
                    _flag(node.lineno, f"get_io()/get_style().{fn.attr}()")
                    continue
                if isinstance(fn.value, ast.Name) and fn.value.id in io_aliases:
                    _flag(node.lineno, f"{fn.value.id}.{fn.attr}()")   # io = get_io(); io.font_…(…)
                    continue
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for tgt in targets:
                if not isinstance(tgt, ast.Attribute):
                    continue
                if _is_io_source(tgt.value):                    # imgui.get_io().x = …
                    _flag(node.lineno, f"get_io()/get_style().{tgt.attr} = ...")
                elif isinstance(tgt.value, ast.Name) and tgt.value.id in io_aliases:
                    _flag(node.lineno, f"{tgt.value.id}.{tgt.attr} = ...")
    return out


class Report:
    """单扩展审查报告（可导入使用 — 测试/CI）。"""

    def __init__(self, ext_dir: str) -> None:
        self.dir = ext_dir
        self.lines: list[str] = []
        self.passes = 0
        self.warns = 0
        self.fails = 0

    def _add(self, level: str, code: str, msg: str) -> None:
        self.lines.append(f"  [{level:4}] {code:2} {msg}")
        if level == "PASS":
            self.passes += 1
        elif level == "WARN":
            self.warns += 1
        else:
            self.fails += 1

    def ok(self, code: str, msg: str = "") -> None:
        self._add("PASS", code, msg)

    def warn(self, code: str, msg: str) -> None:
        self._add("WARN", code, msg)

    def fail(self, code: str, msg: str) -> None:
        self._add("FAIL", code, msg)


def review_extension(ext_dir: str) -> Report:
    """审查单个扩展目录（纯静态 — 不 import 扩展代码）。"""
    rep = Report(ext_dir)
    manifest_path = os.path.join(ext_dir, "extension.json")
    if not os.path.isfile(manifest_path):
        rep.fail("M1", "extension.json 缺失")
        return rep
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        rep.ok("M1", "extension.json 合法")
    except Exception as e:  # noqa: BLE001
        rep.fail("M1", f"extension.json 解析失败: {e}")
        return rep

    ext_id = str(manifest.get("id", ""))
    if _ID_RE.match(ext_id):
        rep.ok("M2", f"id='{ext_id}' 合法")
    else:
        rep.fail("M2", f"id='{ext_id}' 非法（要求 ^[a-z][a-z0-9_]*$）")

    api = str(manifest.get("api_version", ""))
    if api.split(".")[0] == "1":
        rep.ok("M3", f"api_version='{api}'")
    else:
        rep.fail("M3", f"api_version='{api}' 与宿主不兼容（当前需要 1.x）")

    caps = manifest.get("capabilities") or []
    bad_caps = [c for c in caps if c not in _CAPABILITIES]
    if bad_caps:
        rep.fail("M5", f"capabilities 含非法值: {bad_caps}")
    else:
        rep.ok("M5", f"capabilities={caps if caps else '(未声明)'}")

    if str(manifest.get("description", "")).strip():
        rep.ok("M6", "description 非空")
    else:
        rep.warn("M6", "description 为空（Extensions 菜单 tooltip 建议填写）")

    entry = str(manifest.get("entry", ""))
    entry_file = entry.split(":")[0] if entry else ""
    if not entry:
        rep.ok("M4", "无 entry（planned/partial 允许; 提供后可启用）")
        _review_files(rep, ext_dir)
        return rep
    entry_path = os.path.join(ext_dir, entry_file)
    if not os.path.isfile(entry_path):
        rep.fail("M4", f"entry 文件不存在: {entry_file}")
        return rep
    rep.ok("M4", f"entry={entry}")

    # ── 代码静态检查 ────────────────────────────────────────────
    try:
        with open(entry_path, encoding="utf-8") as fh:
            src = fh.read()
    except Exception as e:  # noqa: BLE001
        rep.fail("C0", f"entry 读取失败: {e}")
        return rep

    if "ui" in caps:
        if _UI_BASE_RE.search(src):
            rep.ok("C1", "entry 类继承 UIExtensionBase")
        else:
            rep.fail("C1", "capabilities 含 ui → entry 类必须继承 UIExtensionBase（语言层强制）")
        if "def on_ui_event" in src:
            rep.ok("C2", "实现 on_ui_event")
        else:
            rep.fail("C2", "capabilities 含 ui → 必须实现 on_ui_event（窗口生命周期完备性）")

    if "register_window(" in src:
        if "close_policy" in src:
            rep.ok("C3", "register_window 声明 close_policy")
        else:
            rep.warn("C3", "register_window 未声明 close_policy（窗口 X 语义未显式化 — dev protocol §7）")

    if re.search(r"\.register\(\s*['\"]ext\.", src):
        rep.fail("C4", "ops 注册名不得自带 'ext.' 前缀（宿主自动加 ext.<id>.）")
    else:
        rep.ok("C4", "ops 注册名无 ext. 前缀")

    monkey = _MONKEY_RE.findall(src)
    if monkey:
        rep.warn("C5", f"疑似顶层引擎赋值（monkey-patch 黑名单, 人工复核）: {monkey[:3]}")
    else:
        rep.ok("C5", "无 monkey-patch 迹象")

    offenders = []
    for m in _IMPORT_RE.finditer(src):
        mod = m.group(1) or m.group(2)
        if mod and not any(mod.startswith(prefix) for prefix in _IMPORT_ALLOW):
            offenders.append(mod)
    if offenders:
        rep.warn("C6", f"import Application.* 超出常用白名单（人工复核）: {sorted(set(offenders))}")
    else:
        rep.ok("C6", "Application.* import 均在白名单")

    # C7: imgui 文本字形安全（图集外字符 → '?'）
    try:
        entry_tree = ast.parse(src)
        bad_texts = []
        for node in ast.walk(entry_tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            base = node.func.value
            if not (isinstance(base, ast.Name) and base.id == "imgui"):
                continue
            for arg in node.args:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        bad = unsafe_chars(sub.value)
                        if bad:
                            bad_texts.append(f"L{sub.lineno} {bad} in {sub.value[:48]!r}")
        if bad_texts:
            extra = f" (+{len(bad_texts) - 2} more)" if len(bad_texts) > 2 else ""
            rep.fail("C7", "imgui 文本含图集外字符（显示为 '?'）: " + "; ".join(bad_texts[:2]) + extra)
        else:
            rep.ok("C7", "imgui 文本字形安全")
    except SyntaxError as e:  # noqa: BLE001
        rep.warn("C7", f"entry 语法错误, 跳过字形检查: {e}")

    # C8/C9/C10: imgui 窗口栈纪律（协议 §7.7 + ui_protocol §2.13 同源规则）
    try:
        tree8 = ast.parse(src)
    except SyntaxError as e:  # noqa: BLE001
        rep.warn("C8", f"entry 语法错误, 跳过窗口栈检查: {e}")
        tree8 = None
    if tree8 is not None:
        gated = gated_begin_child(tree8)
        if gated:
            rep.fail("C8", "begin_child 被条件门控（全裁剪 0x0 返回 False → 漏 end_child 会腐蚀"
                           "窗口栈, 之后任意 end 断言杀渲染循环; 用 try/finally 无条件配对）: "
                     + "; ".join(gated[:2]))
        else:
            rep.ok("C8", "窗口栈配对纪律（begin_child 未被条件门控）")
        loose = unguarded_scoped_ends(tree8)
        if loose:
            rep.warn("C9", "end_combo/end_tab_item 疑似无条件调用（应仅 begin 返回 True 时 end）: "
                     + "; ".join(loose[:2]))
        else:
            rep.ok("C9", "combo/tab_item 反向规则 OK")
        top = toplevel_context_calls(tree8)
        if top:
            rep.fail("C10", "顶层创建 imgui 上下文/窗口/GL（应放在窗口回调/运行时内）: "
                     + "; ".join(top[:2]))
        else:
            rep.ok("C10", "无顶层 imgui 上下文/窗口/GL 创建（纯导入允许）")

        global_writes = global_imgui_state_writes(tree8)
        if global_writes:
            rep.fail("C11", "触碰宿主全局 imgui 状态（会污染编辑器与其它扩展; 窗口内 "
                            "push_style_* 才可以）: " + "; ".join(global_writes[:2]))
        else:
            rep.ok("C11", "无全局 imgui 状态写入")

    _review_files(rep, ext_dir)
    return rep


def _review_files(rep: Report, ext_dir: str) -> None:
    if os.path.isfile(os.path.join(ext_dir, "TODO.md")):
        rep.ok("F2", "TODO.md 存在（状态档案）")
    else:
        rep.warn("F2", "建议提供 TODO.md（状态档案 — 开发规范 §3）")


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args:
        print(__doc__)
        return 2
    if args == ["--all"]:
        root = os.path.abspath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "Functions"))
        if not os.path.isdir(root):
            print(f"Functions 目录不存在: {root}")
            return 2
        dirs = []
        for dirpath, _dirnames, filenames in os.walk(root):
            if "extension.json" in filenames:
                dirs.append(dirpath)
        dirs.sort()
    else:
        dirs = [os.path.abspath(a) for a in args]

    total_fail = 0
    for ext_dir in dirs:
        rep = review_extension(ext_dir)
        name = os.path.basename(ext_dir.rstrip("/\\"))
        print(f"== review: {name}  ({ext_dir}) ==")
        for line in rep.lines:
            print(line)
        print(f"   -> {rep.passes} pass / {rep.warns} warn / {rep.fails} fail")
        print()
        total_fail += rep.fails

    print(f"SUMMARY: {len(dirs)} extension(s), fails={total_fail} — "
          + ("OK" if total_fail == 0 else "FAIL"))
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
