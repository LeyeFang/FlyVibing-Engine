"""DataPaths — 写文件节点的**统一落点**解析（1.2）。

## 为什么需要这个模块

2026-11-11 范式侧 issue（`ISSUE_20261111_export_file_io_gaps.md`）暴露的四个缺口
其实是同一个症状：**引擎没有"输出根"这个概念**。

- `TextFileWrite` 的相对路径按 **CWD** 解析 → 成品里凭空长出 `Test/TestProject/...`
  深目录，装到只读位置还会直接失败；
- `init` 类扩展把**开发机绝对路径**写进场景 prop → 换机器就写不进去（或写到别人的
  同名目录）；
- 成品自带 `output/`（`game.json` 的 `output_dir`）却**没有任何写入走它**。

## 语义

| `relative_to` | 相对路径解析到 | 谁会用 |
|---|---|---|
| `output`（**默认**） | `<成品>/output` · PIE `<工程>/output` · 编辑器 `<引擎>/output` | 数据、日志、seed —— 一切产物 |
| `project` | 工程根（成品里 = 成品根） | 需要跟工程一起走的配置 |
| `cwd` | 进程工作目录（**旧行为**，为兼容保留） | 明确知道自己要 CWD 的场景 |

**绝对路径永远原样使用**（这是显式覆盖，不是默认；导出器会用路径审计告警）。
`MGE_OUTPUT_DIR` 环境变量可整体改道（部署/多用户机器上很有用）。

## 宏（macro）— 跨形态的"命名根"

相对路径解决"常见情况"，宏解决"**说清楚是哪个根**"。语法用 `<Name>`：

- `<` `>` 在 Windows 上**是非法文件名字符** → 磁盘上不可能存在同名的真实目录，
  所以"文件夹名恰好和宏一样"这种歧义从根上不存在（这正是选它的理由，而不是
  `$(Name)` 那种合法文件名格式）；
- 大小写不敏感（`<gameroot>` 与 `<GameRoot>` 等价）；
- **在保存时绝不展开** —— `.scene` 里存的永远是宏字面量。展开只发生在求值/写盘那一刻。

| 宏 | 别名 | 含义 | 编辑器 | PIE | 成品 |
|---|---|---|---|---|---|
| `<EngineRoot>` | `<EditorRoot>` | 引擎根（含 `Application/`） | 引擎仓 | 引擎仓 | 成品根 |
| `<ProjectRoot>` | — | `.myproj` 所在目录 | 工程目录 | 工程目录 | 成品根 |
| `<GameRoot>` | — | 游戏自己的根（`game.json` 所在） | 工程目录 | 工程目录 | 成品根 |
| `<OutputRoot>` | — | 运行数据根 | `<ProjectRoot>/output` | `<ProjectRoot>/output` | `<GameRoot>/output` |
| `<Cwd>` | — | 进程工作目录 | 逃生口，**不要**用它做默认 | | |

> `GameRoot` 与 `ProjectRoot` 目前总是同值（成品里 myproj 与 game.json 并存，
> PIE 里游戏读的就是工程）。分成两个名字是为了**语义**："我要游戏自己的根" 与
> "我要工程的根" 不是同一句话，将来若两者分离，用 `<GameRoot>` 的图自动正确。

用法示例：

```
<GameRoot>./output/logs/run.txt     → <成品>/output/logs/run.txt
<ProjectRoot>/assets/seed.json      → <工程>/assets/seed.json
seed/x.txt  + relative_to=output    → <output 根>/seed/x.txt   （等价简写）
```

求值链只有一条：**先展开宏 → 再判绝对/相对** → 相对则拼 `relative_to` 基准。
未知宏**抛 `PathMacroError`**（不静默降级到某个根 —— 写错地方比写失败难查）。

## 边界

- 本模块属 Core，**不得** import Editor；
- 纯函数 + 一次 `Engine` 查询；无状态、无缓存（目录可能在运行期被移动）；
- 扩展应调用 `resolve_write_path()` 而不是自己拼 `os.getcwd()`。

守卫: `Test/Application/Core/test_data_paths.py`。
"""

from __future__ import annotations

import os
import re

__all__ = [
    "DEFAULT_RELATIVE_TO",
    "RELATIVE_TO_CHOICES",
    "MACRO_PATTERN",
    "MACRO_NAMES",
    "PathMacroError",
    "data_roots",
    "base_for",
    "contains_macro",
    "expand_macros",
    "resolve_write_path",
    "looks_absolute_path",
]

#: 默认解析基准 —— 写文件默认落在输出根（旧行为是 CWD，属于事故来源）。
DEFAULT_RELATIVE_TO = "output"

#: 可选基准（UI 下拉与校验共用同一份顺序）。
RELATIVE_TO_CHOICES = ("output", "project", "cwd")

#: 宏语法 `<Name>`。
#:
#: 为什么不用 `$(Name)` / `%Name%`：
#:   - `$()`、`%…%` 在 Windows 上是**合法文件名字符** → 磁盘上真可能出现同名目录，
#:     "这是宏还是文件夹"就变成需要猜测的问题；
#:   - `<` `>` 在 Windows 上非法 → 同名目录物理上不可能存在，歧义从根上消失；
#:   - `%Name%` 还会与 Windows 环境变量展开语义混淆（我们不做环境变量展开）。
MACRO_PATTERN = re.compile(r"<([A-Za-z][A-Za-z0-9_]*)>")

#: 宏名（小写）→ `data_roots()` 的键。别名指向同一个键。
MACRO_ROOTS: dict[str, str] = {
    "engineroot": "engine",
    "editorroot": "engine",     # 别名：团队既有语言，语义等同引擎根
    "projectroot": "project",
    "gameroot": "game",
    "outputroot": "output",
    "cwd": "cwd",
}

#: 供 UI / 文档 / 诊断使用的规范宏名（大小写按展示惯例）。
MACRO_NAMES: tuple[str, ...] = (
    "EngineRoot", "ProjectRoot", "GameRoot", "OutputRoot", "Cwd",
)


class PathMacroError(ValueError):
    """路径里有无法解析的宏（未知名字 / 该形态下没有这个根）。"""


def _abspath(path: str) -> str:
    return os.path.abspath(os.path.expanduser(str(path)))


def _engine_dir() -> str:
    """本文件所在引擎根：`<root>/Application/Core/FileSystem/DataPaths.py`。

    成品里 `Application/` 是冻结副本，所以这里得到的**就是成品根** ——
    同一个表达式在编辑器/PIE/成品三种形态下都正确。
    """
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _all_engine_classes():
    """`Engine` + 全部子类（递归）—— 根可能挂在任一子类的 state 上。"""
    from Application.Core.Engine import Engine

    seen: list = []
    stack = [Engine]
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.append(cls)
        stack.extend(cls.__subclasses__())
    return seen


def _engine_roots() -> dict:
    """向当前进程里的 Engine **族**询问路径根。

    2026-11-13 修正（扩展侧 O7）: `set_data_roots` 是 classmethod，宿主把根写在
    `EditorHost` / `GameRuntime` 的 per-class state 上；而本模块只能 import
    `Engine` 基类 —— 直接 `Engine.data_roots()` 读的是**基类自己那份（永远空）**，
    于是编辑器里 `<ProjectRoot>` / `<OutputRoot>` 退化成引擎根，与 PIE/成品不一致。

    现在的规则: 扫 `Engine` + 全部子类，取**最后声明**的那份（含"清空"的声明 ——
    工程关闭后不应该继续沿用上一个工程的根）。
    """
    best: dict = {}
    best_seq = -1
    try:
        classes = _all_engine_classes()
    except Exception:      # noqa: BLE001 — 无引擎上下文（单测/工具）不是错误
        return {}
    for cls in classes:
        try:
            seq = int(cls.roots_stamp())
        except Exception:      # noqa: BLE001
            continue
        if seq < best_seq or seq == 0:
            continue
        try:
            roots = dict(cls.data_roots() or {})
        except Exception:      # noqa: BLE001
            continue
        best, best_seq = roots, seq
    return best


def data_roots(engine=None) -> dict:
    """返回各根的绝对路径。

    Keys: `engine` / `project` / `game` / `output` / `cwd`
    （`game` 目前恒等于 `project` —— 成品与 PIE 里两者同目录）。
    """
    roots = {}
    if engine is not None:
        try:
            roots = engine.data_roots() or {}
        except Exception:      # noqa: BLE001
            roots = {}
    if not roots:
        roots = _engine_roots()

    cwd = _abspath(roots.get("cwd") or os.getcwd())
    engine_root = _abspath(roots.get("engine") or _engine_dir())
    project = _abspath(roots.get("project") or engine_root)
    game = _abspath(roots.get("game") or project)
    env_output = os.environ.get("MGE_OUTPUT_DIR", "").strip()
    output = roots.get("output") or env_output or os.path.join(project, "output")
    return {
        "engine": engine_root,
        "project": project,
        "game": game,
        "output": _abspath(output),
        "cwd": cwd,
    }


def contains_macro(text) -> bool:
    """路径里是否含宏（不含则完全走旧逻辑）。"""
    return bool(MACRO_PATTERN.search(str(text or "")))


def expand_macros(text: str, roots: dict | None = None) -> str:
    """把 `<Name>` 宏替换成对应根的绝对路径。

    Raises:
        PathMacroError: 名字未知（含拼错）。

    注意：
      - 这里**只做替换**，不做规范化也不判绝对/相对 —— 那是 `resolve_write_path` 的事；
      - 宏替换结果若不是紧跟分隔符就补一个，避免 `<GameRoot>output` 拼成
        `C:\\productoutput` 这种静默错误。
    """
    raw = str(text or "")
    if not MACRO_PATTERN.search(raw):
        return raw
    # 调用方给的根可能只有部分键（引擎只会注入 project/output；编辑器里
    # engine_root 常常是空的）→ 用派生值补齐，**空值不算"配置过"**。
    # 否则 `<EngineRoot>` 会在编辑器里报错、在成品里正常，行为不一致。
    effective = dict(data_roots())
    for key, value in (roots or {}).items():
        if str(value or "").strip():
            effective[key] = value
    r = effective

    def _sub(match: re.Match) -> str:
        name = match.group(1)
        key = MACRO_ROOTS.get(name.strip().lower())
        if key is None:
            raise PathMacroError(
                f"unknown path macro <{name}> (known: "
                + ", ".join(f"<{n}>" for n in MACRO_NAMES) + ")"
            )
        value = str(r.get(key) or "").strip()
        if not value:
            raise PathMacroError(
                f"path macro <{name}> is not available in this run form"
                f" (no '{key}' root configured)")
        # 宏之后紧跟非分隔符 → 补一个：`<GameRoot>output` 否则会拼成
        # `C:\productoutput` 这种**静默**错误（不报错但写到别处）。
        tail = raw[match.end():match.end() + 1]
        if tail and tail not in ("/", "\\"):
            value = value.rstrip("\\/") + os.sep
        return value

    return MACRO_PATTERN.sub(_sub, raw)


def base_for(relative_to: str, roots: dict | None = None) -> str:
    """把 `relative_to` 名字解析成绝对目录。未知值退回默认（output）。"""
    key = str(relative_to or "").strip().lower()
    if key not in RELATIVE_TO_CHOICES:
        key = DEFAULT_RELATIVE_TO
    r = roots or data_roots()
    return r.get(key) or r[DEFAULT_RELATIVE_TO]


def resolve_write_path(
    raw: str,
    *,
    relative_to: str = DEFAULT_RELATIVE_TO,
    default_name: str = "",
    roots: dict | None = None,
) -> str:
    """把节点里的路径字符串解析成**绝对路径**。

    求值链：**展开宏 → 判绝对/相对 → 相对则拼 `relative_to` 基准**。

    Args:
        raw:           节点 prop / 上游引脚给的路径（可为空 / 宏 / 相对 / 绝对）。
        relative_to:   相对（且无宏）时以哪个根为基准（见模块文档）。
        default_name:  `raw` 为空时使用的文件名（空 = 直接用基准目录）。
        roots:         显式传入的根（测试用；省略则查 Engine / 环境变量）。

    Raises:
        PathMacroError: `raw` 里有未知宏（**不静默降级**）。

    Returns:
        绝对路径。**不创建任何目录**（创建是调用方的副作用，dry-run 必须跳过）。
    """
    text = str(raw or "").strip()
    r = roots or data_roots()
    if not text:
        base = base_for(relative_to, r)
        return os.path.join(base, default_name) if default_name else base
    expanded = os.path.expanduser(expand_macros(text, r))
    if looks_absolute_path(expanded):
        return os.path.normpath(expanded)
    # 也规范化 —— 否则 `a/b` 会被拼成 `C:\\out\\a/b`（混分隔符，日志里很难看）
    return os.path.normpath(os.path.join(base_for(relative_to, r), expanded))


def looks_absolute_path(value) -> bool:
    """跨平台判断"看起来是绝对路径"（导出器路径审计复用）。

    比 `os.path.isabs` 宽：在 Windows 上也要能识别 `/home/x`（mac/linux 写法的
    场景文件），在 POSIX 上也要识别 `C:\\x`（从 Windows 导出的场景）。
    """
    text = str(value or "").strip()
    if not text:
        return False
    if text.startswith("\\\\"):          # UNC
        return True
    if text.startswith("builtin://"):    # 资源引用不是路径
        return False
    if len(text) >= 2 and text[1] == ":" and text[0].isalpha():
        return True                       # Windows 盘符
    return text.startswith("/") or text.startswith("\\")
