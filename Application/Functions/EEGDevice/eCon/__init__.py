"""
eCon — 念通科技（econEXG）脑电设备品牌目录（预留占位）。

状态: 预留 — 尚未接入 API。接入约定（与 Gtec 同构）:
  1. backend.py 实现 DeviceBackend（configure/start/stop/close/pump/info）;
  2. service.py 用 run_service('econ', mode, ...) 暴露服务进程（自有环境）;
  3. 引擎门面路由: cfg.device == "ECON" → 服务连接（MGE_ECON_SERVICE）;
  4. 验证: 参照 VirtualDevice 的进程机制测试（Test/Application/Functions/test_eeg_service.py）。

注意: pyproject 的 device extra 已含 `econexg[lsl,usb]`（预留依赖声明）。
"""

DEVICE_KEY = "ECON"                # 预留: 门面路由键（cfg.device）
SERVICE_ENDPOINT_ENV = "MGE_ECON_SERVICE"
SUPPORTED = False                  # 预留: 未接入

__all__ = ["DEVICE_KEY", "SERVICE_ENDPOINT_ENV", "SUPPORTED"]
