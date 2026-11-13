"""OptionalExtensions — 引擎与**可选扩展**之间的唯一接缝。

规则（2026-11-14，外部扩展报告 O9）
----------------------------------
`Application/Core/**` 与 `Application/Runtime/**` **不得**直接
`from Application.Functions.<扩展> import ...`。

原因不是洁癖，是产物形态：导出器按**场景实际用到的节点类型**决定带哪些扩展目录
（`ProjectManager._resolve_export_extensions`）。一个纯核心场景（`OnFrameUpdate` /
`EntitySpawn` / `ext.<某个>.*` 之类不涉及设备 I/O）的产物里
`Application/Functions/<那个扩展>/` 根本不存在。此时任何硬 import 都是
`ModuleNotFoundError` → **成品连窗口都起不来**，而错误发生在引擎自己的启动路径上，
扩展作者既看不见也无法规避。

实测（2026-11-14）: 纯核心场景 `EmptyGame` 导出的成品启动即崩:

    ModuleNotFoundError: No module named 'Application.Functions.SerialParallelDevice'

### 语义（三条，别混）

| 情形 | 结果 |
|---|---|
| 扩展**目录不存在**（本次没有随包分发） | 返回 `absent`，打一行 info，**不抛** —— 这是正常形态 |
| 扩展存在，调用**成功** | 返回 `ok` |
| 扩展存在，调用**失败**（端口/服务/依赖） | `required=True` → **抛**；`required=False` → 告警 |

第三条的方向是刻意的：设备 I/O 起不来却继续跑实验 = 静默丢刺激。所以"存在但坏掉"
是硬错误；"根本不存在"不是错误。

这与 `SerialParallelDevice.extension.on_engine_start()` 的契约一致
（"失败不吞"），区别只是**调用方**从扩展换成了引擎的接缝模块 —— 于是引擎不再需要
认识任何具体扩展的名字来启动，只需在这里登记一次。

### 使用

```python
from Application.Core.Extension.OptionalExtensions import start_io, stop_io, call

start_io("runtime")          # 起不来真实故障时抛；产物没有该扩展时静默跳过
stop_io("runtime")           # 释放租约（关闭路径，失败只告警）
call("VirtualDevice", "close_all")   # 兜底清理（缺席/失败都只告警）
```

为什么住在 `Core/Extension/` 而不是 `Runtime/`：`Core/NodeGraph/validation/dry_run`
也要用它（干跑清理设备会话），放在 Runtime 会形成 Core → Runtime 反向依赖。
"""

from __future__ import annotations

import importlib
import importlib.util
import os

#: 运行时可选集成的登记表（扩展目录名 / 一句话用途）。
#: 新增一项 = 引擎自愿支持该扩展；不登记也不会崩，只是不主动集成。
INTEGRATIONS = {
    "SerialParallelDevice": "device I/O (serial / parallel writes)",
    "VirtualDevice": "virtual EEG device sessions (cleanup safety net)",
    "BCIAlgorithm": "epoch datasets (cleanup safety net)",
}

_FUNCS_PARENT = "Application.Functions"

#: 本文件位于 `<Application>/Core/Extension/OptionalExtensions.py` → 三级向上 = `<Application>`
#: （不依赖 `Application.__file__`：命名空间包下它是 None）
_APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _extension_dir(name: str) -> str:
    """扩展目录的绝对路径（与导出器的判定单位一致 = 目录）。"""
    name = str(name or "")
    if not name:
        return ""
    return os.path.join(_APP_DIR, "Functions", name)


def available(name: str) -> bool:
    """该扩展在**本进程可见的安装**里是否存在（不 import 扩展代码）。

    主判据是**目录存在**（与导出器同一个单位：导出器删/留的就是目录）；
    兜底再用 `find_spec`，兜住以 zip/egg 形态安装的非目录布局。
    """
    name = str(name or "")
    if not name:
        return False
    directory = _extension_dir(name)
    if directory and os.path.isdir(directory):
        return True
    try:
        return importlib.util.find_spec(f"{_FUNCS_PARENT}.{name}") is not None
    except (ImportError, AttributeError, ValueError):
        return False


def module(name: str):
    """导入可选扩展并返回模块对象；**不存在时返回 None**（不抛）。

    给需要多个函数的调用点用（例: 干跑清理要 `list_sessions`/`kill_device`/
    `destroy_pool` 一起用）。单个函数请用 `call()` —— 它把"缺席/失败"的差别
    已经包好了。
    """
    if not available(name):
        return None
    try:
        return importlib.import_module(f"{_FUNCS_PARENT}.{name}")
    except Exception as exc:  # noqa: BLE001 — 目录在但 import 炸（缺依赖等）
        print(f"[Runtime] WARNING: optional integration {name} failed to import: "
              f"{type(exc).__name__}: {exc}")
        return None


def call(name: str, func: str, *args, required: bool = False, **kwargs):
    """调用可选扩展里的一个函数 → `(ok, detail)`。

    Args:
        required: 扩展**存在**但调用失败时是否上抛。缺席永远不上抛。
    """
    if not available(name):
        return False, "absent"
    try:
        module = importlib.import_module(f"{_FUNCS_PARENT}.{name}")
    except Exception as exc:  # noqa: BLE001 — 目录在但 import 炸（缺依赖等）
        if required:
            raise
        print(f"[Runtime] WARNING: optional integration {name} failed to import: "
              f"{type(exc).__name__}: {exc}")
        return False, f"{type(exc).__name__}: {exc}"
    fn = getattr(module, func, None)
    if not callable(fn):
        detail = f"{name}.{func} is not callable"
        if required:
            raise AttributeError(detail)
        print(f"[Runtime] WARNING: optional integration {detail}")
        return False, detail
    try:
        fn(*args, **kwargs)
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        if required:
            raise
        print(f"[Runtime] WARNING: optional integration {name}.{func} failed: "
              f"{type(exc).__name__}: {exc}")
        return False, f"{type(exc).__name__}: {exc}"


def start_io(owner: str = "runtime") -> bool:
    """启动设备 I/O 层（串口/并口发送线程）。返回是否真的启动了。

    产物不含该扩展 → 返回 False 并打一行 info（正常：纯核心 / 纯采集场景）。
    含该扩展但起不来 → **抛**（继续跑 = 静默丢刺激）。
    """
    name = "SerialParallelDevice"
    ok, detail = call(name, "start", owner, required=True)
    if ok:
        return True
    if detail == "absent":
        print(f"[Runtime] {name} not in this build — {INTEGRATIONS[name]} disabled "
              f"(scene uses no {name} nodes; expected for extension-free products)")
    return False


def stop_io(owner: str = "runtime") -> None:
    """释放设备 I/O 租约（关闭路径：缺席/失败都只告警，绝不阻断退出）。"""
    call("SerialParallelDevice", "stop", owner)


def stop_all_io() -> None:
    """进程退出时释放**全部** I/O 租约（含编辑器残留；同样不阻断退出）。"""
    call("SerialParallelDevice", "stop_all")


def status() -> dict:
    """诊断快照（`extension.list` / 日志 / 测试用）。"""
    return {
        "integrations": {
            name: {"available": available(name), "purpose": purpose}
            for name, purpose in sorted(INTEGRATIONS.items())
        }
    }


__all__ = [
    "INTEGRATIONS", "available", "module", "call",
    "start_io", "stop_io", "stop_all_io", "status",
]
