"""
eCon — 念通科技 econEXG 后端（预留占位; 尚未实现）。

接入步骤见 eCon/__init__.py 与 eCon/README.md。
接入时: 实现 DeviceBackend 协议 → service.py 挂 run_service → 门面路由 cfg.device="ECON"。
"""

from __future__ import annotations


class EConBackend:
    """预留: econEXG DeviceBackend 实现（接入 API 后填充）。"""

    is_stub = False

    def configure(self, cfg) -> None:
        raise NotImplementedError("eCon backend not implemented yet (预留)")

    def start(self, on_block, user_block_ms: float = 100.0) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def info(self) -> dict:
        return {"backend": "EConBackend (reserved)", "stub": False}
