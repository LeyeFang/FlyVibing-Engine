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

## 边界

- 本模块属 Core，**不得** import Editor；
- 纯函数 + 一次 `Engine` 查询；无状态、无缓存（目录可能在运行期被移动）；
- 扩展应调用 `resolve_write_path()` 而不是自己拼 `os.getcwd()`。

守卫: `Test/Application/Core/test_data_paths.py`。
"""

from __future__ import annotations

import os

__all__ = [
    "DEFAULT_RELATIVE_TO",
    "RELATIVE_TO_CHOICES",
    "data_roots",
    "base_for",
    "resolve_write_path",
    "looks_absolute_path",
]

#: 默认解析基准 —— 写文件默认落在输出根（旧行为是 CWD，属于事故来源）。
DEFAULT_RELATIVE_TO = "output"

#: 可选基准（UI 下拉与校验共用同一份顺序）。
RELATIVE_TO_CHOICES = ("output", "project", "cwd")


def _abspath(path: str) -> str:
    return os.path.abspath(os.path.expanduser(str(path)))


def _engine_roots() -> dict:
    """向当前 Engine 询问已配置的根（无 Engine / 未初始化 → 空）。"""
    try:
        from Application.Core.Engine import Engine
        return Engine.data_roots()
    except Exception:      # noqa: BLE001 — 无引擎上下文（单测/工具）不是错误
        return {}


def data_roots(engine=None) -> dict:
    """返回三个根的绝对路径：`{"output", "project", "cwd"}`。

    解析顺序（output）: Engine 已设置的值 → `MGE_OUTPUT_DIR` → `<project>/output`
    → `<cwd>/output`。
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
    project = _abspath(roots.get("project") or cwd)
    env_output = os.environ.get("MGE_OUTPUT_DIR", "").strip()
    output = roots.get("output") or env_output or os.path.join(project, "output")
    return {
        "output": _abspath(output),
        "project": project,
        "cwd": cwd,
    }


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

    Args:
        raw:           节点 prop / 上游引脚给的路径（可为空 / 相对 / 绝对）。
        relative_to:   相对时以哪个根为基准（见模块文档）。
        default_name:  `raw` 为空时使用的文件名（空 = 直接用基准目录）。
        roots:         显式传入的根（测试用；省略则查 Engine / 环境变量）。

    Returns:
        绝对路径。**不创建任何目录**（创建是调用方的副作用，dry-run 必须跳过）。
    """
    text = str(raw or "").strip()
    if not text:
        base = base_for(relative_to, roots)
        return os.path.join(base, default_name) if default_name else base
    expanded = os.path.expanduser(text)
    if looks_absolute_path(expanded):
        return os.path.normpath(expanded)
    return os.path.join(base_for(relative_to, roots), expanded)


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
