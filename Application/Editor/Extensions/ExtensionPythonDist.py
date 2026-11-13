"""ExtensionPythonDist — 把扩展依赖**装进产物**（导出期执行，编辑器侧）。

契约由 `Application.Core.Extension.ExtensionRuntimeDeps` 解析；本模块只做"怎么放进去"。

两条落地方式（按 `runtime.mode` 分）:

| mode | 落地 | 触发 |
|---|---|---|
| `engine` | 包 → `<产物>/runtime/Lib/site-packages`（产物解释器**进程内**可用） | 节点代码 `import` 三方包 |
| `bundle` | 整个环境目录 → `<产物>/extensions/<id>/env/`（**只给子进程**） | 三方包与引擎版本/ABI 冲突 |

`engine` 模式的两条来源（按序，**全部离线**）:

1. wheelhouse 里现有的 wheel（`<引擎>/Resource/wheels` + 扩展自带 `wheels/`）
   → `pip install --no-index --no-deps --target <site-packages>`；
2. 引擎 venv 已安装的包目录（**开发期验证过的那个版本**）→ 直接复制包目录 + dist-info。

★ `--no-deps` 是必须的: `pip --target` 无视已安装包，会把 numpy 之类**再装一份**到
`--target` 里，覆盖产物基础镜像的版本（2026-11-14 实测: 装 h5py 会连带计划安装
numpy-2.5.1）。基础镜像由 `prepare_runtime.py` 保证，缺什么由 probe 报错。
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess

from Application.Core.Extension import ExtensionRuntimeDeps as deps


def _norm(name: str) -> str:
    """发行名/模块名归一化（`PyOpenGL-accelerate` ≈ `pyopengl_accelerate`）。"""
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")


def _wheel_dist_name(filename: str) -> str:
    """`h5py-3.16.0-cp314-cp314t-win_amd64.whl` → `h5py`。"""
    return _norm(filename.split("-", 1)[0])


def find_wheel(requirement: str, wheel_dirs) -> str:
    """在若干 wheelhouse 里找能满足该需求的 wheel（按文件名前缀匹配，版本交给 pip）。"""
    name = _norm(deps.requirement_name(requirement))
    if not name:
        return ""
    for directory in wheel_dirs or ():
        if not directory or not os.path.isdir(directory):
            continue
        for fname in sorted(os.listdir(directory)):
            if not fname.lower().endswith(".whl"):
                continue
            if _wheel_dist_name(fname) == name:
                return os.path.join(directory, fname)
    return ""


def probe_in_runtime(runtime_python: str, module: str, *, timeout: float = 30.0) -> tuple:
    """用**产物解释器**判断模块是否存在（不能在编辑器进程里判断 — 环境不同）。"""
    if not runtime_python or not os.path.isfile(runtime_python):
        return False, f"runtime interpreter missing: {runtime_python!r}"
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env.pop("PYTHONPATH", None)
    try:
        proc = subprocess.run(
            [runtime_python, "-c", f"import {module}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"cannot run runtime python: {exc}"
    if proc.returncode == 0:
        return True, "ok"
    lines = (proc.stderr or proc.stdout or "").strip().splitlines()
    detail = next((ln.strip() for ln in reversed(lines)
                   if "error" in ln.lower() or "fatal" in ln.lower()),
                  lines[-1].strip() if lines else f"exit {proc.returncode}")
    return False, detail


def _pip_install_wheel(runtime_python: str, site_packages: str, wheel: str) -> tuple:
    """离线安装单个 wheel（`--no-deps`，见模块文档的星号注）。"""
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env.pop("PYTHONPATH", None)
    cmd = [runtime_python, "-m", "pip", "install",
           "--no-index", "--no-deps", "--no-warn-script-location",
           "--disable-pip-version-check",
           "--find-links", os.path.dirname(wheel),
           "--target", site_packages, wheel]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300.0, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        tail = ((proc.stderr or proc.stdout or "").strip().splitlines() or [""])[-1]
        return False, tail or f"pip exit {proc.returncode}"
    return True, "installed from wheel"


def copy_installed_package(module: str, site_packages: str) -> tuple:
    """把**引擎 venv 里已安装的包目录**复制进产物（无 wheel 时的离线兜底）。

    优点: 版本 = 开发期实测过的版本；缺点: 绕过 wheel 的依赖元数据审计，
    所以调用方必须记录 `source="engine_venv"` 让清单可审计。
    """
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, AttributeError, ValueError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if spec is None:
        return False, f"{module} not importable in engine venv"
    locations = list(spec.submodule_search_locations or ())
    if locations:
        src = locations[0]
    elif spec.origin and spec.origin.endswith(".py"):
        src = spec.origin
    else:
        return False, f"{module}: no copyable location"
    if not os.path.exists(src):
        return False, f"{module}: location missing ({src})"
    try:
        if os.path.isdir(src):
            dst = os.path.join(site_packages, os.path.basename(src))
            shutil.copytree(src, dst, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            dst = os.path.join(site_packages, os.path.basename(src))
            shutil.copy2(src, dst)
    except OSError as exc:
        return False, f"copy failed: {exc}"
    # dist-info 一起带过去（pip 以外的东西靠它认版本）
    dist_name = _norm(deps.requirement_name(module) or module)
    try:
        import importlib.metadata as _md
        for dist in _md.distributions():
            meta_name = _norm(dist.metadata.get("Name", ""))
            if meta_name and (meta_name == dist_name or _norm(module) == meta_name):
                info_dir = str(dist._path)  # noqa: SLF001 — 标准库没有公开访问器
                if os.path.isdir(info_dir):
                    shutil.copytree(
                        info_dir,
                        os.path.join(site_packages, os.path.basename(info_dir)),
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "RECORD"),
                    )
                break
    except Exception:  # noqa: BLE001 — dist-info 缺失不影响运行
        pass
    return True, f"copied from engine venv ({src})"


def install_contract(contract, *, runtime_python: str, site_packages: str,
                     wheel_dirs, allow_venv_copy: bool = True) -> dict:
    """把一个 `engine` 契约装进产物 → 结果结构（写进导出清单）。"""
    result = {
        "id": contract.ext_id, "mode": contract.mode,
        "requires": list(contract.requires), "installed": [], "present": [],
        "failed": [], "skipped": False,
    }
    if contract.mode != "engine" or not contract.requires:
        result["skipped"] = True
        return result
    if not runtime_python or not os.path.isfile(runtime_python):
        result["failed"].append(
            {"requirement": "*", "reason": "runtime interpreter missing — include_player "
                                           "needs Resource/runtime"})
        return result
    if not os.path.isdir(site_packages):
        os.makedirs(site_packages, exist_ok=True)

    probes = list(contract.probe)
    for index, requirement in enumerate(contract.requires):
        name = deps.requirement_name(requirement)
        # 显式 probe 与 requires **等长**时按位置对应（`pyserial` → `serial` 这种
        # 名字推导不出来的别名必须这样写）；否则按发行名推导。
        module = probes[index] if len(probes) == len(contract.requires) else ""
        probe_module = module or (deps.import_names([requirement]) or [name])[0]
        ok, detail = probe_in_runtime(runtime_python, probe_module)
        if ok:
            result["present"].append({"requirement": requirement, "module": probe_module})
            continue
        wheel = find_wheel(requirement, wheel_dirs)
        if wheel:
            ok, why = _pip_install_wheel(runtime_python, site_packages, wheel)
            if ok:
                ok, why = probe_in_runtime(runtime_python, probe_module)
            result["installed" if ok else "failed"].append(
                {"requirement": requirement, "module": probe_module,
                 "source": "wheelhouse", "wheel": wheel, "detail": why})
            continue
        if allow_venv_copy:
            ok, why = copy_installed_package(probe_module, site_packages)
            if ok:
                ok, why = probe_in_runtime(runtime_python, probe_module)
            if ok:
                result["installed"].append(
                    {"requirement": requirement, "module": probe_module,
                     "source": "engine_venv", "detail": why})
                continue
        result["failed"].append(
            {"requirement": requirement, "module": probe_module,
             "reason": "no wheel in wheelhouse and not installed in the engine venv "
                       "— run Utils/Dev/collect_wheels.py or add the wheel to "
                       "<extension>/wheels/", "detail": detail})
    return result


def bundle_environment(contract, target_root: str) -> dict:
    """`bundle` 模式：整个环境目录 → `<产物>/extensions/<id>/env/`。

    只拷解释器目录本身（`.git`/`__pycache__` 之类跳过），返回 `{executable, files, bytes}`。
    子进程用哪个 exe 由 `_venv_exe` 的同一套规则决定，写进 `python_envs.json`。
    """
    from Application.Core.Extension.ExtensionPython import _venv_exe

    result = {"id": contract.ext_id, "source": contract.path,
              "executable": "", "dir": "", "files": 0, "bytes": 0, "error": ""}
    if not contract.path or not os.path.isdir(contract.path):
        result["error"] = f"bundle env dir not found: {contract.path!r}"
        return result
    dst = os.path.join(target_root, "extensions", contract.ext_id, "env")
    try:
        shutil.copytree(
            contract.path, dst, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".git", ".hg", ".svn", "*.egg-info"),
        )
    except OSError as exc:
        result["error"] = f"copy failed: {exc}"
        return result
    local_exe = _venv_exe(dst)
    # `_venv_exe` 对不存在的候选返回"最可能路径"；产物里要的是真实文件
    result["executable"] = local_exe if os.path.isfile(local_exe) else ""
    if not result["executable"]:
        result["error"] = (f"bundled env has no python executable "
                           f"(looked for {local_exe})")
    result["dir"] = dst
    for cur, _dirs, files in os.walk(dst):
        for fname in files:
            result["files"] += 1
            try:
                result["bytes"] += os.path.getsize(os.path.join(cur, fname))
            except OSError:
                pass
    return result


__all__ = [
    "find_wheel", "probe_in_runtime", "copy_installed_package",
    "install_contract", "bundle_environment",
]
