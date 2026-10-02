"""
VirtualDevice 服务进程入口 — 虚拟信号发生器（引擎本体环境运行）。

引擎正常流程会自动拉起本服务（无需手工启动）; 调试/验证可手工运行:
    python -m Application.Functions.EEGDevice.VirtualDevice.service --port 0

数据模式: pump — 块由 pump 命令同步生成并随响应返回（与进程内语义完全一致, 确定性）。
"""

from __future__ import annotations

from ..ServiceHost import run_service
from .SigGen import SigGenConfig, VirtualSigGenBackend


def _create_backend():
    # 服务模式 = 真实落盘通路（落盘在引擎侧执行; 服务只负责数据）
    return VirtualSigGenBackend(dry_run=False)


def _cfg_from_fields(fields):
    return SigGenConfig.from_props(fields)


def main() -> int:
    return run_service("virtual", "pump", _create_backend, _cfg_from_fields)


if __name__ == "__main__":
    raise SystemExit(main())
