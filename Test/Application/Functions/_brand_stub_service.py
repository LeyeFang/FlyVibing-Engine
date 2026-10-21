"""
Test-only brand stub service — 服务协议无头回环（自动拉起链路验收用）。

与外部品牌服务同形（独立进程 + 协议 + SigGen 数据后端）; hello 自报 brand="external"，
与 ServiceBackend.connect_brand 的品牌标签一致，用于验证:
  service_module 透传 → 引擎自动拉起 → hello 握手 → init/pump 数据往返。

引擎将自动拉起（勿用于生产）; 调试可手动运行:
    python -m Test.Application.Functions._brand_stub_service --port 0
"""

from __future__ import annotations

from Application.Functions.VirtualDevice.ServiceHost import run_service
from Application.Functions.VirtualDevice.SigGen import SigGenConfig, VirtualSigGenBackend

BRAND = "external"


def _create_backend() -> VirtualSigGenBackend:
    return VirtualSigGenBackend(dry_run=False)


def _cfg_from_fields(fields):
    """引擎侧字段 → SigGen 配置。

    品牌场景: 引擎发来的是 DeviceConfig 字段（无 "channels", 带 template）——
    按模板解析通道数（"64ch" → 64），使数据列数与引擎会话环形缓冲一致
    （RingBuffer.push 对通道数不匹配的块静默丢弃）。
    """
    props = dict(fields)
    if not props.get("channels"):
        digits = "".join(ch for ch in str(props.get("template", "")) if ch.isdigit())
        if digits:
            props["channels"] = int(digits)
    return SigGenConfig.from_props(props)


def main() -> int:
    return run_service(BRAND, "pump", _create_backend, _cfg_from_fields)


if __name__ == "__main__":
    raise SystemExit(main())
