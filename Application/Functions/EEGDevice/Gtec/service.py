"""
Gtec 服务进程入口 — g.tec g.HIamp（独立进程文件应用; 自有环境运行）。

启动（在其自有环境中, 仓库根目录为 cwd）:
    python -m Application.Functions.EEGDevice.Gtec.service --port 47810

引擎侧连接: MGE_GTEC_SERVICE=host:port（默认 127.0.0.1:47810）。
数据模式: push — start 后采集线程逐块推送; 保存仍在引擎侧（StopGtecRecord 落盘逻辑不变）。
"""

from __future__ import annotations

from ..Device import GtecConfig
from ..ServiceHost import run_service
from .Gtec import GtecHiampBackend


def _create_backend():
    # pygds 在 configure() 内懒导入（真实采集需 GDS 服务 + 空闲设备）
    return GtecHiampBackend()


def _cfg_from_fields(fields):
    return GtecConfig.from_props(fields)


def main() -> int:
    return run_service("gtec", "push", _create_backend, _cfg_from_fields)


if __name__ == "__main__":
    raise SystemExit(main())
