"""
eCon 服务进程入口（预留）— 接入 econEXG 后参照 Gtec/service.py 填充。

参考运行形态（接入后）:
    python -m Application.Functions.EEGDevice.eCon.service --port 47820
"""

from __future__ import annotations


def main() -> int:
    raise SystemExit(
        "eCon service is reserved (念通科技 econEXG API not integrated yet). "
        "See Application/Functions/EEGDevice/eCon/README.md"
    )


if __name__ == "__main__":
    raise SystemExit(main())
