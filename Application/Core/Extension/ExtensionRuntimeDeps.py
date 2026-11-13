"""ExtensionRuntimeDeps — 扩展**依赖契约**（manifest `python.runtime`）的唯一实现。

为什么需要（2026-11-14，范式侧 + 设备类扩展联合 issue）
------------------------------------------------------
扩展的 Python 依赖原本只描述"**编辑器里**用哪个解释器"（`python.mode/path/probe`），
没有任何字段描述"**导出成品里**这些包怎么办"。结果是：

* 依赖装在引擎 venv → PIE 正常；成品用的是另一份 `Resource/runtime` 镜像（由
  `Utils/Dev/prepare_runtime.py` 按**手写清单** `requirements.runtime.txt` 烘焙），
  扩展的包从来不在里面 → 成品 `ModuleNotFoundError`。设备类扩展的 hdf5 落盘就是这样：
  能开、能录，**到写文件那一刻**才报 `h5py is not installed`。
* 依赖装在自己 venv → 成品连那个解释器都没有，子进程服务起不来。

所以依赖语言必须有**第二条轴**。本模块是这条轴的唯一解析/校验实现，被三处共用：

| 使用方 | 时机 | 作用 |
|---|---|---|
| `ProjectManager` 导出 | 交付前 | 校验契约 + 把 `requires` 装进产物 / 把整个环境拷进产物 |
| `PlayerBootstrap` 启动 | 产物运行时 | 按契约 probe，缺包**大声报**而不是静默空跑 |
| `Utils/Dev/check_extension_python.py` | 开发期 | 离线自查（CI / 扩展作者本地） |

## 语言（固定，全部键都在这一个对象里）

```json
"python": {
  "mode": "engine" | "venv" | "path",     // 开发期：扩展代码在编辑器里跑哪个解释器
  "path": "%EXT_DATA%/venv",              // venv/path 必填
  "requirements": "requirements.txt",      // 开发期安装清单（给 install_hint 用）
  "probe": ["numpy", "h5py"],              // 开发期自检（可选）

  "runtime": {                             // ★ 产物侧契约（导出时强制校验）
    "mode": "engine" | "bundle" | "none",
    "requires": ["h5py>=3.16"],            // engine: 要装进产物运行时的包
    "probe": ["h5py"],                     // import 名（缺省 = 由 requires 推导）
    "optional": false,                     // true = 缺失只降级告警，不阻断
    "path": "venv",                        // bundle: 环境目录（相对扩展目录 / %EXT_DATA%）
    "env": {"PYTHONPATH": "..."},           // bundle: 子进程附加环境（可选）
    "note": "为什么需要"                    // 自由文本，进清单，方便审计
  }
}
```

### 两个 mode 的语义差别（**不要混**）

| runtime.mode | 含义 | 何时用 | 代价 |
|---|---|---|---|
| `engine` | 包**装进产物基础镜像**的 `runtime/Lib/site-packages`，节点在**进程内**直接 import | 默认。依赖版本与引擎兼容 | 产物 +几 MB |
| `bundle` | 整个解释器环境**拷进** `<产物>/extensions/<id>/env/`，只给**子进程**用 | 三方包与引擎版本冲突（numpy/ABI 钉死） | 产物 +几百 MB（不可避免） |
| `none` | 显式声明"无第三方依赖" | 纯内置库扩展 | 无 |

`bundle` **不能**让进程内节点用上那个环境 —— 节点求值在引擎进程里，只有一个解释器。
需要隔离版本的扩展必须把重活放到 `ctx.python.spawn` 的子进程，节点只做 IPC。

### 强制点（违反即导出失败）

1. `runtime` 必须是对象，**未知键报错**（拼错 `requires` 不会被静默忽略）；
2. `mode` ∈ {engine, bundle, none}；`bundle` 必须有可解析的 `path`；
3. `requires` 是 PEP 508 字符串列表，名字合法；
4. `probe` 是 import 名列表；
5. **凡是随产物分发、且声明了 `python` 或 `nodes` 能力的扩展，必须显式给 `runtime`**
   —— 沉默地"没有依赖声明"正是本次 bug 的形态，不再接受。
"""

from __future__ import annotations

import importlib.util
import os
import re
from dataclasses import dataclass, field

#: manifest 里本契约所在的键路径（错误信息里直接引用）
SPEC_PATH = "python.runtime"

#: 契约版本（结构变更时 +1；导出清单会写出来，便于以后兼容旧产物）
SPEC_VERSION = 1

DEV_MODES = ("engine", "venv", "path")
RUNTIME_MODES = ("engine", "bundle", "none")

#: 只允许这些键（其余一律报错 — 拼写错误必须被发现）
KNOWN_KEYS = frozenset({"mode", "requires", "probe", "optional", "path", "env", "note"})

_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
#: PEP 508 名字部分（后续的 extras / 版本约束不在这里解析，交给 pip）
_REQ_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")

_VARS = {
    "%EXT_DIR%": "extension_dir",
    "%EXT_DATA%": "data_dir",
    "%ENGINE_ROOT%": "engine_root",
}


# ════════════════════════════════════════════════════════════════
# 契约
# ════════════════════════════════════════════════════════════════

@dataclass
class RuntimeContract:
    """一个扩展的产物侧依赖契约（已解析、已校验）。"""

    ext_id: str = ""
    declared: bool = False          # manifest 是否**显式**写了 `runtime` 段
    mode: str = "none"              # engine | bundle | none
    requires: list = field(default_factory=list)   # PEP 508 字符串
    probe: list = field(default_factory=list)      # import 名（显式优先）
    optional: bool = False
    path: str = ""                  # bundle: 已展开的环境绝对路径
    env: dict = field(default_factory=dict)
    note: str = ""
    problems: list = field(default_factory=list)   # 校验问题（非空 = 契约非法）

    # ── 派生 ────────────────────────────────────────────────

    @property
    def imports(self) -> list:
        """需要 `import` 成功的模块名（显式 `probe` 优先，否则由 require 名推导）。"""
        if self.probe:
            return list(self.probe)
        return import_names(self.requires)

    @property
    def distributable(self) -> bool:
        return self.mode in ("engine", "bundle")

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict:
        """导出清单 / `extension.list` 用的稳定结构。"""
        return {
            "version": SPEC_VERSION,
            "id": self.ext_id,
            "declared": bool(self.declared),
            "mode": self.mode,
            "requires": list(self.requires),
            "probe": list(self.imports),
            "optional": bool(self.optional),
            "path": self.path,
            "env": dict(self.env),
            "note": self.note,
            "problems": list(self.problems),
        }

    def summary(self) -> str:
        """一行人类可读（日志/CLI）。"""
        if self.mode == "none":
            return "runtime=none (no third-party deps)"
        if self.mode == "bundle":
            return f"runtime=bundle ({self.path})"
        return f"runtime=engine requires={self.requires or '[]'}"


# ════════════════════════════════════════════════════════════════
# 解析 / 校验
# ════════════════════════════════════════════════════════════════

def requirement_name(requirement: str) -> str:
    """`h5py>=3.16` → `h5py`（extras / 版本约束丢弃）。"""
    match = _REQ_NAME_RE.match(str(requirement or ""))
    return match.group(1) if match else ""


def import_names(requirements) -> list:
    """需求列表 → import 名列表（`pyserial` → `serial` 这类**别名无法推导**，
    需要时请显式写 `runtime.probe`）。"""
    out: list = []
    for requirement in requirements or ():
        name = requirement_name(requirement)
        if not name:
            continue
        module = name.replace("-", "_").replace(".", "_")
        if module not in out:
            out.append(module)
    return out


def _expand(path: str, *, extension_dir: str, data_dir: str, engine_root: str) -> str:
    """`%EXT_DIR%` / `%EXT_DATA%` / `%ENGINE_ROOT%` + 环境变量 + `~` 展开。"""
    out = str(path or "")
    values = {"extension_dir": extension_dir, "data_dir": data_dir,
              "engine_root": engine_root}
    for token, key in _VARS.items():
        if token in out:
            out = out.replace(token, values[key] or "")
    return os.path.expandvars(os.path.expanduser(out))


def _as_list(raw, *, what: str, problems: list) -> list:
    if raw in (None, ""):
        return []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, (list, tuple)):
        out = []
        for item in raw:
            if not isinstance(item, str) or not item.strip():
                problems.append(f"{what} 含非字符串项: {item!r}")
                continue
            out.append(item.strip())
        return out
    problems.append(f"{what} 必须是字符串或字符串列表（得到 {type(raw).__name__}）")
    return []


def parse(manifest: dict, *, ext_id: str = "", ext_dir: str = "",
          data_dir: str = "", engine_root: str = "") -> RuntimeContract:
    """manifest → `RuntimeContract`（从不抛异常；问题进 `problems`）。"""
    manifest = manifest if isinstance(manifest, dict) else {}
    contract = RuntimeContract(ext_id=str(ext_id or manifest.get("id") or ""))
    python = manifest.get("python")
    raw = None
    dev_mode = "engine"
    if isinstance(python, str):
        dev_mode = python.strip().lower() or "engine"
    elif isinstance(python, dict):
        dev_mode = str(python.get("mode") or "engine").strip().lower() or "engine"
        if "runtime" in python:
            raw = python.get("runtime")
    elif python not in (None, ""):
        contract.problems.append(
            f"python 必须是字符串或对象（得到 {type(python).__name__}）")
        return contract
    if dev_mode not in DEV_MODES:
        contract.problems.append(f"python.mode={dev_mode!r} 非法（{'/'.join(DEV_MODES)}）")
        dev_mode = "engine"

    if raw is None:
        # 未声明：按开发期解释器推断（engine → 一样用引擎环境；venv/path → 整个打包）。
        # declared=False 让导出方能把"没写"和"写了 none"区分开。
        contract.mode = "engine" if dev_mode == "engine" else "bundle"
        contract.path = _bundle_path({}, python if isinstance(python, dict) else {},
                                     ext_dir=ext_dir, data_dir=data_dir,
                                     engine_root=engine_root)
        return contract

    contract.declared = True
    if not isinstance(raw, dict):
        contract.problems.append(
            f"{SPEC_PATH} 必须是对象（得到 {type(raw).__name__}）")
        return contract

    unknown = sorted(set(raw) - KNOWN_KEYS)
    if unknown:
        contract.problems.append(
            f"{SPEC_PATH} 含未知键 {unknown}（允许: {sorted(KNOWN_KEYS)}）")

    mode = str(raw.get("mode") or ("engine" if dev_mode == "engine" else "bundle"))
    mode = mode.strip().lower()
    if mode not in RUNTIME_MODES:
        contract.problems.append(
            f"{SPEC_PATH}.mode={mode!r} 非法（{'/'.join(RUNTIME_MODES)}）")
        mode = "none"
    contract.mode = mode

    contract.requires = _as_list(raw.get("requires"),
                                 what=f"{SPEC_PATH}.requires", problems=contract.problems)
    for requirement in contract.requires:
        if not _REQ_NAME_RE.match(requirement):
            contract.problems.append(
                f"{SPEC_PATH}.requires 项非法（不是 PEP 508 需求串）: {requirement!r}")

    contract.probe = _as_list(raw.get("probe"),
                              what=f"{SPEC_PATH}.probe", problems=contract.problems)
    for module in contract.probe:
        if not _MODULE_RE.match(module):
            contract.problems.append(
                f"{SPEC_PATH}.probe 项非法（不是 import 名）: {module!r}")

    optional = raw.get("optional", False)
    if not isinstance(optional, bool):
        contract.problems.append(f"{SPEC_PATH}.optional 必须是 true/false")
        optional = bool(optional)
    contract.optional = optional

    env = raw.get("env") or {}
    if not isinstance(env, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        contract.problems.append(f"{SPEC_PATH}.env 必须是 {{str: str}}")
        env = {}
    contract.env = {str(k): str(v) for k, v in env.items()}

    contract.note = str(raw.get("note") or "")

    if contract.mode == "bundle":
        contract.path = _bundle_path(raw, python if isinstance(python, dict) else {},
                                     ext_dir=ext_dir, data_dir=data_dir,
                                     engine_root=engine_root)
        if not contract.path:
            contract.problems.append(
                f"{SPEC_PATH}.mode=bundle 需要 path（环境目录，或外层 python.path）")
    elif contract.mode == "none":
        if contract.requires:
            contract.problems.append(
                f"{SPEC_PATH}.mode=none 不应带 requires（要装包请用 mode=engine）")
    elif contract.mode == "engine":
        # engine 模式没有 requires 也可以（= 无三方依赖），但显式写 none 更清楚
        pass

    return contract


def _bundle_path(runtime: dict, python: dict, *, ext_dir: str, data_dir: str,
                 engine_root: str) -> str:
    """bundle 模式的环境目录：`runtime.path` 优先，回退外层 `python.path`。"""
    raw = str(runtime.get("path") or python.get("path") or "").strip()
    if not raw:
        return ""
    expanded = _expand(raw, extension_dir=ext_dir, data_dir=data_dir,
                       engine_root=engine_root)
    if not os.path.isabs(expanded):
        expanded = os.path.join(ext_dir, expanded)
    return os.path.abspath(expanded)


# ════════════════════════════════════════════════════════════════
# 导出侧强制校验
# ════════════════════════════════════════════════════════════════

def export_problems(contract: RuntimeContract, *, ships_code: bool = True) -> list:
    """导出前的**强制**校验问题（空 = 通过）。

    Args:
        ships_code: 该扩展是否随产物分发（场景用到它的节点/能力）。
            只有这类扩展才必须给出契约 —— 没被用到的扩展不受影响。
    """
    problems = list(contract.problems)
    if not ships_code:
        return problems
    if not contract.declared:
        problems.append(
            f"扩展 '{contract.ext_id}' 随产物分发，但 manifest 没有 {SPEC_PATH} 段。"
            f" 必须显式声明（无三方依赖也要写 {{\"mode\": \"none\"}}）——"
            f" 导出的成品用独立运行时镜像，未声明的依赖在成品里必然缺失。")
        return problems
    if contract.mode == "bundle" and contract.path:
        if not os.path.isdir(contract.path):
            problems.append(
                f"{SPEC_PATH}.mode=bundle 的环境目录不存在: {contract.path}")
    return problems


def snippet_for(ext_id: str = "<id>") -> str:
    """给扩展作者的"抄这个"片段（错误信息/通告里直接引用）。"""
    return (
        '"python": {\n'
        '    "mode": "engine",\n'
        '    "runtime": {\n'
        '      "mode": "engine",\n'
        '      "requires": ["yourpkg>=1.0"],\n'
        '      "probe": ["yourpkg"],\n'
        '      "note": "why the product needs it"\n'
        '    }\n'
        '  }'
    )


# ════════════════════════════════════════════════════════════════
# 运行时 probe（产物里用；纯标准库）
# ════════════════════════════════════════════════════════════════

def probe_module(name: str) -> tuple:
    """当前进程能否 import `name` → `(ok, detail)`（不真正 import 子模块）。"""
    module = str(name or "").strip()
    if not module:
        return False, "empty module name"
    if not _MODULE_RE.match(module):
        return False, f"invalid module name {module!r}"
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, AttributeError, ValueError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if spec is None:
        return False, f"not found: {module}"
    return True, "ok"


def probe_imports(names) -> dict:
    """`{name: {ok, detail}}`（顺序稳定）。"""
    return {str(n): dict(zip(("ok", "detail"), probe_module(n))) for n in (names or ())}


def missing_imports(names) -> list:
    return [n for n in (names or ()) if not probe_module(n)[0]]


def load_product_contracts(root: str) -> dict:
    """读产物里的 `<root>/extensions/python_contracts.json` → `{ext_id: dict}`。

    导出器总会写这个文件（空契约也写），所以"没有文件"= 旧产物，返回空 dict。
    """
    import json

    path = os.path.join(str(root or ""), "extensions", "python_contracts.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    contracts = data.get("extensions") if isinstance(data, dict) else None
    if not isinstance(contracts, dict):
        return {}
    return {str(k): v for k, v in contracts.items() if isinstance(v, dict)}


def apply_env_overrides(root: str) -> list:
    """按 `<root>/extensions/python_envs.json` 设置 `FVE_EXT_PYTHON_<ID>`。

    产物里没有扩展管理器（没有 `ctx.python`），但**子进程服务**仍然需要知道自己
    该用哪个解释器。导出器把 bundle 出去的环境路径写进这个文件，这里在
    `PlayerBootstrap` 启动最早处注入环境变量 —— 于是扩展代码只要遵守协议
    （读 `FVE_EXT_PYTHON_<ID>` / `ctx.python`），在成品与编辑器里行为一致。

    Returns: 已设置的 `[(ext_id, executable)]`。
    """
    import json

    path = os.path.join(str(root or ""), "extensions", "python_envs.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    envs = data.get("extensions") if isinstance(data, dict) else None
    if not isinstance(envs, dict):
        return []
    applied: list = []
    for ext_id, info in envs.items():
        exe = str((info or {}).get("executable") or "") if isinstance(info, dict) else ""
        if not exe or not os.path.isfile(exe):
            continue
        key = "FVE_EXT_PYTHON_" + re.sub(r"[^A-Za-z0-9]", "_", str(ext_id)).upper()
        os.environ[key] = exe
        applied.append((str(ext_id), exe))
    return applied


__all__ = [
    "SPEC_PATH", "SPEC_VERSION", "DEV_MODES", "RUNTIME_MODES", "KNOWN_KEYS",
    "RuntimeContract", "parse", "export_problems", "snippet_for",
    "requirement_name", "import_names", "probe_module", "probe_imports",
    "missing_imports", "load_product_contracts", "apply_env_overrides",
]
