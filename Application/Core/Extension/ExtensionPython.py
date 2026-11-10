"""ExtensionPython — 扩展的 Python 解释器协议（manifest 声明 + `ctx.python` 门面）。

问题:
  扩展在编辑器进程内 import（`ExtensionManager` 用 importlib 加载），第三方依赖要么装进
  引擎 venv（污染、升级即失效），要么像设备类扩展那样自己 spawn 服务进程并在设备配置里手填
  `service_python` / `MGE_EEG_SERVICE_PYTHON`。后者能用，但没有统一协议：路径写死、
  换机器就断、错误信息不可操作、子进程没人回收。

协议（manifest，可选；缺省 = 引擎解释器）:
    "python": "engine"
    "python": {
        "mode": "engine" | "venv" | "path",
        "path": "%EXT_DATA%/venv",        // venv: 目录或 exe 都接受；path: exe
        "requirements": "requirements.txt",
        "probe": ["serial", "numpy"]      // 启动自检的 import 名（可选）
    }

解析优先级（一处实现，所有扩展共享）:
    用户覆盖（`extension.python` op / 状态文件）→ 环境变量 `FVE_EXT_PYTHON_<ID>` /
    `MGE_EXT_PYTHON_<ID>` → manifest `path` → 引擎解释器

门面（`ctx.python`，总是注入）:
    .executable                解析后的解释器路径
    .env(extra=None)           子进程环境（PYTHONPATH = 扩展目录 + 引擎根）
    .probe(name)               子进程 `import <name>` 自检 → (ok, detail)
    .spawn(module=..., args=...) 拉起子进程（日志落临时目录、卸载时统一回收）
    .explain()                 「为什么选了这个解释器」→ 直接进错误信息/extension.list

纪律:
  - 不自动 pip install（无网络副作用）；缺依赖时报可复制的安装命令；
  - 子进程一律走 `spawn`（宿主回收），扩展不要自己 `subprocess.Popen`；
  - 路径支持 `%EXT_DIR%` / `%EXT_DATA%` / `%ENGINE_ROOT%` 变量，禁止写死机器路径。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_MOD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_VARS = {
    "%EXT_DIR%": "extension_dir",
    "%EXT_DATA%": "data_dir",
    "%ENGINE_ROOT%": "engine_root",
}


def _normalise_spec(raw) -> dict:
    """manifest `python` 字段 → dict（字符串简写 = mode）。"""
    if raw in (None, "", {}):
        return {}
    if isinstance(raw, str):
        return {"mode": raw.strip().lower()}
    if isinstance(raw, dict):
        spec = dict(raw)
        spec["mode"] = str(spec.get("mode") or "engine").strip().lower()
        if isinstance(spec.get("probe"), str):
            spec["probe"] = [spec["probe"]]
        return spec
    raise ValueError("manifest python must be a string or an object")


def _expand(path: str, *, extension_dir: str, data_dir: str, engine_root: str) -> str:
    out = str(path or "")
    values = {"extension_dir": extension_dir, "data_dir": data_dir, "engine_root": engine_root}
    for token, key in _VARS.items():
        if token in out:
            out = out.replace(token, values[key] or "")
    return os.path.expandvars(os.path.expanduser(out))


def _venv_exe(path: str) -> str:
    """venv 目录 → 解释器路径（Windows Scripts / POSIX bin / conda 根）。"""
    p = Path(path)
    if p.suffix.lower() == ".exe" or (p.is_file() and p.name.startswith("python")):
        return str(p)
    candidates = [
        p / "Scripts" / "python.exe",
        p / "bin" / "python",
        p / "python.exe",
        p / "python",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    # 目录尚不存在时也给出最可能的路径（explain 会标 not found，方便用户修）
    return str(candidates[0] if os.name == "nt" else candidates[1])


class ExtensionPython:
    """一个扩展的 Python 环境（解析 + 自检 + 子进程托管）。"""

    def __init__(self, extension_id: str, *, extension_dir: str, data_dir: str,
                 engine_root: str, spec=None, override: str = "") -> None:
        self.id = str(extension_id)
        self.extension_dir = str(extension_dir or "")
        self.data_dir = str(data_dir or "")
        self.engine_root = str(engine_root or "")
        self.spec = _normalise_spec(spec)
        self.mode = str(self.spec.get("mode") or "engine").lower()
        if self.mode not in ("engine", "venv", "path"):
            self.mode = "engine"
            self.spec.setdefault("problems", []).append(f"unknown mode {self.spec.get('mode')!r}")
        self.requirements = str(self.spec.get("requirements") or "")
        self.probe_modules = [str(m) for m in (self.spec.get("probe") or []) if str(m).strip()]
        self._procs: list[subprocess.Popen] = []
        self._probes: dict[str, dict] = {}
        self._override = str(override or "").strip()
        self._exe, self.source = self._resolve()

    # ── 解析 ───────────────────────────────────────────────

    def _resolve(self) -> tuple[str, str]:
        """→ (executable, source)；source ∈ override / env / manifest / engine。"""
        if self._override:
            raw = _expand(self._override, extension_dir=self.extension_dir,
                          data_dir=self.data_dir, engine_root=self.engine_root)
            return self._norm_exe(raw), "override"
        env_key = "FVE_EXT_PYTHON_" + re.sub(r"[^A-Za-z0-9]", "_", self.id).upper()
        legacy_key = "MGE_EXT_PYTHON_" + re.sub(r"[^A-Za-z0-9]", "_", self.id).upper()
        for key in (env_key, legacy_key):
            raw = (os.environ.get(key) or "").strip()
            if raw:
                return self._norm_exe(raw), "env"
        declared = str(self.spec.get("path") or "").strip()
        if declared:
            raw = _expand(declared, extension_dir=self.extension_dir,
                          data_dir=self.data_dir, engine_root=self.engine_root)
            return self._norm_exe(raw), "manifest"
        return sys.executable, "engine"

    def _norm_exe(self, raw: str) -> str:
        if self.mode == "venv":
            return _venv_exe(raw)
        return raw

    @property
    def executable(self) -> str:
        return self._exe

    def apply_override(self, path: str) -> None:
        """运行期覆盖解释器（op `extension.python path=...`；空串 = 清除）。

        只影响「之后」的 probe/spawn；已拉起的子进程仍由 `close()` 统一回收。
        """
        self._override = str(path or "").strip()
        self._exe, self.source = self._resolve()
        self._probes.clear()

    def _same_as_engine(self) -> bool:
        try:
            return os.path.normcase(os.path.abspath(self._exe)) == \
                os.path.normcase(os.path.abspath(sys.executable))
        except (OSError, ValueError):
            return False

    def exists(self) -> bool:
        return bool(self._exe) and os.path.isfile(self._exe)

    # ── 子进程环境 ─────────────────────────────────────────

    def env(self, extra: dict | None = None) -> dict:
        """子进程环境：继承当前进程 + 扩展目录/引擎根进 PYTHONPATH。

        注意 `PYTHON_GIL`: 引擎按 free-threading 启动（`PYTHON_GIL=0`），但外部 venv 很可能是
        GIL 构建 —— 原样继承会让子进程在初始化阶段直接 Fatal（实测系统 Python 3.14:
        "Disabling the GIL is not supported by this build"），import 自检因此永远失败。
        所以只在「子进程就是引擎解释器」时保留，其它解释器一律去掉（让它的构建自己决定）。
        """
        env = os.environ.copy()
        if not self._same_as_engine():
            env.pop("PYTHON_GIL", None)
        parts = [p for p in (self.extension_dir, self.engine_root) if p]
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(parts + ([existing] if existing else []))
        env.setdefault("PYTHONNOUSERSITE", "1")
        if extra:
            env.update({str(k): str(v) for k, v in extra.items()})
        return env

    # ── 自检 ───────────────────────────────────────────────

    def probe(self, module: str) -> tuple[bool, str]:
        """子进程 `import <module>`；不污染引擎进程，结果缓存。"""
        name = str(module or "").strip()
        if not name:
            return False, "empty module name"
        if name in self._probes:
            item = self._probes[name]
            return bool(item.get("ok")), str(item.get("detail", ""))
        if not _MOD_NAME.match(name):
            return False, f"invalid module name {name!r}"
        cmd = [self._exe, "-c", f"import {name}"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  timeout=20.0, env=self.env())
        except (OSError, subprocess.SubprocessError) as e:
            detail = f"cannot run {self._exe!r}: {e}"
            self._probes[name] = {"ok": False, "detail": detail}
            return False, detail
        if proc.returncode == 0:
            detail = "ok"
            self._probes[name] = {"ok": True, "detail": detail}
            return True, detail
        lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        # 取最有信息量的一行（ModuleNotFoundError / Error / fatal），否则末行
        detail = next((ln.strip() for ln in reversed(lines)
                       if "error" in ln.lower() or "fatal" in ln.lower()),
                      lines[-1].strip() if lines else "")
        detail = detail or f"exit {proc.returncode}"
        self._probes[name] = {"ok": False, "detail": detail}
        return False, detail

    # ── 子进程托管 ─────────────────────────────────────────

    def spawn(self, module: str = "", args: list[str] | None = None,
              cwd: str | None = None, env: dict | None = None,
              log_name: str = "") -> dict:
        """拉起子进程（扩展服务/工具），返回 `{pid, cmd, log}`；卸载时统一回收。"""
        cmd = [self._exe]
        if module:
            cmd += ["-m", str(module)]
        cmd += [str(a) for a in (args or [])]
        workdir = str(cwd or self.engine_root or self.extension_dir or os.getcwd())
        name = log_name or f"fve_ext_{self.id}_{len(self._procs) + 1}.log"
        log_path = os.path.join(tempfile.gettempdir(), name)
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with open(log_path, "ab") as log:
            proc = subprocess.Popen(cmd, cwd=workdir, env=self.env(env),
                                    stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT,
                                    creationflags=creationflags)
        self._procs.append(proc)
        return {"pid": proc.pid, "cmd": cmd, "log": log_path}

    def children(self) -> int:
        return len([p for p in self._procs if p.poll() is None])

    def close(self) -> None:
        """卸载：终止本扩展拉起的全部子进程（先 terminate，3s 后 kill）。"""
        for proc in self._procs:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            except OSError:
                pass
        self._procs.clear()

    # ── 诊断 ───────────────────────────────────────────────

    def explain(self, probe: bool = False) -> dict:
        """当前选择 + 证据（extension.list / 错误信息直接用这个结构）。"""
        problems: list[str] = []
        if not self.exists():
            problems.append(
                f"python not found: {self._exe!r} (mode={self.mode}, source={self.source})")
        results: dict = dict(self._probes)
        if probe:
            for name in self.probe_modules:
                ok, detail = self.probe(name)
                results[name] = {"ok": ok, "detail": detail}
        missing = [n for n, r in results.items() if not r.get("ok")]
        if missing:
            problems.append(f"missing modules: {', '.join(missing)}")
        return {
            "mode": self.mode,
            "source": self.source,
            "override": self._override,
            "executable": self._exe,
            "exists": self.exists(),
            "requirements": self.requirements,
            "declared": dict(self.spec),
            "probe": results,
            "problems": problems,
            "children": self.children(),
        }

    def install_hint(self) -> str:
        """缺依赖时的可复制命令（不自动执行）。"""
        if not self.requirements:
            return f'"{self._exe}" -m pip install <package>'
        req = _expand(self.requirements, extension_dir=self.extension_dir,
                      data_dir=self.data_dir, engine_root=self.engine_root)
        return f'"{self._exe}" -m pip install -r "{req}"'


__all__ = ["ExtensionPython"]
