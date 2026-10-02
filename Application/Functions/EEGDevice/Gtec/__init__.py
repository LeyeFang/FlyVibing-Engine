"""
Gtec — g.tec g.HIamp 品牌目录（独立进程文件应用; 自有环境）。

目录契约（品牌文件夹约定）:
  - Gtec.py / GtecStub.py : 后端实现（DeviceBackend 协议; 真实 / 空跑）
  - service.py            : 品牌服务进程入口（外部启动; 自有环境运行）
  - README.md             : 环境 / 启动 / 契约说明

通信: 复用 EEGDevice.ServiceProtocol/ServiceHost — 与 VirtualDevice 同一机制;
引擎侧经 ServiceClient.connect_gtec() 连接（MGE_GTEC_SERVICE, 默认 127.0.0.1:47810）。
"""

from .Gtec import GtecHiampBackend, GtecUnavailable, probe_environment
from .GtecStub import GtecStubBackend

__all__ = [
    "GtecHiampBackend",
    "GtecUnavailable",
    "probe_environment",
    "GtecStubBackend",
]
