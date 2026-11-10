"""扩展解释器协议（ExtensionPython / manifest `python` / ctx.python）守卫。

锁定（extdev protocol §「依赖与解释器」）:
  1. manifest 简写（"engine" / {mode, path, probe}）归一化
  2. 解析优先级: env `FVE_EXT_PYTHON_<ID>` → manifest path → 引擎解释器
  3. venv 模式: 目录 → Scripts/python.exe（POSIX bin/python）
  4. `%EXT_DATA%` / `%EXT_DIR%` 变量展开（禁止写死机器路径）
  5. `env()` 把扩展目录 + 引擎根放进 PYTHONPATH
  6. `probe()` 真子进程 import（命中/缺失都如实返回，不污染引擎进程）
  7. `spawn()` 拉起的子进程由 `close()` 统一回收
  8. 官方示例扩展（SerialParallelDevice）声明 mode=engine + probe=serial

用法:
    .venv-py314t\\Scripts\\python.exe Test/Application/Core/test_extension_python.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
while ROOT and not os.path.exists(os.path.join(ROOT, "startup.bat")):
    parent = os.path.dirname(ROOT)
    if parent == ROOT:
        ROOT = ""
        break
    ROOT = parent
assert ROOT, "repo root not found"
for _p in (ROOT,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from Application.Core.Extension.ExtensionPython import ExtensionPython  # noqa: E402

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        _failures.append(name)


def _env(*, spec=None, ext_dir="", data_dir="", root=""):
    return ExtensionPython("probe_ext", extension_dir=ext_dir, data_dir=data_dir,
                           engine_root=root, spec=spec)


def main() -> int:
    print("-- 1. manifest 归一化 --")
    env = _env()
    check("缺省 = engine", env.mode == "engine" and env.executable == sys.executable)
    check("缺省来源 = engine", env.source == "engine", env.source)

    env = _env(spec="engine")
    check("字符串简写 = mode", env.mode == "engine" and env.source == "engine")

    print("-- 2. 解析优先级 --")
    fake_exe = os.path.join(ROOT, "Test", "_runs", "_fake_python.exe")
    env = _env(spec={"mode": "path", "path": fake_exe})
    check("manifest path 生效", env.executable == fake_exe and env.source == "manifest",
          f"{env.executable}/{env.source}")
    check("不存在的解释器被标出", env.exists() is False)
    check("explain 报 not found", any("not found" in p for p in env.explain()["problems"]),
          str(env.explain()["problems"]))

    os.environ["FVE_EXT_PYTHON_PROBE_EXT"] = sys.executable
    try:
        env = _env(spec={"mode": "path", "path": fake_exe})
        check("env 覆盖 manifest", env.executable == sys.executable and env.source == "env",
              f"{env.executable}/{env.source}")
    finally:
        os.environ.pop("FVE_EXT_PYTHON_PROBE_EXT", None)

    print("-- 3. venv 解析与变量展开 --")
    fake_venv = os.path.join(ROOT, "Test", "_runs", "_fake_venv")
    os.makedirs(os.path.join(fake_venv, "Scripts"), exist_ok=True)
    exe = os.path.join(fake_venv, "Scripts", "python.exe")
    open(exe, "w").close()
    env = _env(spec={"mode": "venv", "path": fake_venv})
    expected = exe if os.name == "nt" else os.path.join(fake_venv, "bin", "python")
    check("venv 目录 → 解释器", env.executable == expected, env.executable)
    check("venv 解释器存在", env.exists() is True)

    env = _env(spec={"mode": "venv", "path": "%EXT_DATA%"}, data_dir=fake_venv)
    check("%EXT_DATA% 展开", env.executable == expected, env.executable)

    print("-- 4. 子进程环境 --")
    env = _env(spec={"mode": "engine"}, ext_dir="C:/ext/dir", root="C:/engine/root")
    penv = env.env({"FVE_TEST_EXTRA": "1"})
    parts = penv.get("PYTHONPATH", "").split(os.pathsep)
    check("PYTHONPATH 含扩展目录", "C:/ext/dir" in parts, penv.get("PYTHONPATH", ""))
    check("PYTHONPATH 含引擎根", "C:/engine/root" in parts, penv.get("PYTHONPATH", ""))
    check("透传额外环境变量", penv.get("FVE_TEST_EXTRA") == "1")

    print("-- 5. probe（真子进程）--")
    env = _env(spec={"mode": "engine"})
    ok, detail = env.probe("json")
    check("stdlib 模块可导入", ok is True, detail)
    ok, detail = env.probe("no_such_module_fve_probe")
    check("缺失模块返回 False", ok is False, detail)
    check("explain(probe=True) 带结果",
          env.explain(probe=True)["probe"].get("no_such_module_fve_probe", {}).get("ok") is False)
    check("install_hint 可复制", "pip install" in env.install_hint(), env.install_hint())

    print("-- 6. spawn / close 回收 --")
    env = _env(spec={"mode": "engine"})
    info = env.spawn(args=["-c", "import time; time.sleep(30)"], log_name="fve_ext_probe.log")
    check("spawn 返回 pid/命令/日志", info["pid"] > 0 and info["cmd"][0] == sys.executable
          and os.path.isfile(info["log"]), str(info))
    time.sleep(0.4)
    check("子进程存活计数", env.children() == 1, str(env.children()))
    env.close()
    time.sleep(0.6)
    check("close 后子进程回收", env.children() == 0, str(env.children()))

    print("-- 7. 运行期覆盖（extension.python）--")
    state_dir = tempfile.mkdtemp(prefix="fve_ext_state_")
    os.environ["FVE_EXTENSIONS_STATE"] = os.path.join(state_dir, "extensions.json")
    os.environ["FVE_EXTENSIONS_DATA"] = tempfile.mkdtemp(prefix="fve_ext_data_")
    from Application.Editor.Extensions.ExtensionManager import ExtensionManager as M

    status = M.set_python_override("device", sys.executable)
    check("覆盖写入并立即生效",
          status["override"] == sys.executable and status["python"]["source"] == "override",
          f"{status.get('override')}/{status['python'].get('source')}")
    check("未装载也能解析出解释器",
          status["python"]["executable"] == sys.executable, status["python"].get("executable"))
    state = json.load(open(os.environ["FVE_EXTENSIONS_STATE"], encoding="utf-8"))
    check("状态文件 version 2", state.get("version") == 2, str(state.get("version")))
    check("覆盖落盘", state.get("python", {}).get("device") == sys.executable,
          str(state.get("python")))

    status = M.set_python_override("device", "")
    check("清除覆盖", status["override"] == "", status.get("override"))
    check("清除后回落声明",
          status["python"]["source"] in ("engine", "manifest"), status["python"].get("source"))

    print("-- 8. 官方示例扩展声明 --")
    manifest = os.path.join(ROOT, "Application", "Functions", "SerialParallelDevice",
                            "extension.json")
    data = json.load(open(manifest, encoding="utf-8"))
    py = data.get("python") or {}
    check("device 声明 python", bool(py), str(data.get("python")))
    check("device = engine 模式", str(py.get("mode")) == "engine", str(py))
    check("device 声明 serial 探针", "serial" in (py.get("probe") or []), str(py))

    print()
    if _failures:
        print(f"RESULT: FAILED ({len(_failures)}) — " + ", ".join(_failures))
        return 1
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
