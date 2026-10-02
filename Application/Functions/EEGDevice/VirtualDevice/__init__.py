"""
VirtualDevice — 虚拟信号发生器品牌目录（进程化数据源; 使用引擎本体环境）。

目录契约:
  - SigGen.py   : SigGenConfig + VirtualSigGenBackend（DeviceBackend 协议）
  - service.py  : 服务进程入口（与 Gtec 同一通信协议; 引擎自动拉起, pump 模式）
  - README.md   : 说明

环境: 与其他品牌不同 — **直接使用引擎本体环境**（无额外依赖）,
      作为进程机制（协议 / 生命周期 / 数据流）的验证平台。
"""

from .SigGen import SigGenConfig, VirtualSigGenBackend

__all__ = ["SigGenConfig", "VirtualSigGenBackend"]
