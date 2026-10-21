"""
COM 发送器 — 每隔 N 秒向串口发送 float/int 值。

用法:
    python -m Test.Device.com11_sender [--port COM12] [--baud 115200] [--byte]

默认参数已针对 ESP32 CH340:
    --port COM12, --baud 115200, float32 格式
"""

import argparse
import struct
import sys
import time


def main():
    parser = argparse.ArgumentParser(description="COM sender for ESP32 testing")
    parser.add_argument("--port", default="COM3", help="serial port (default COM12)")
    parser.add_argument("--baud", type=int, default=9600, help="baud rate (default 115200)")
    parser.add_argument("--byte", action="store_true", help="send single uint8 byte instead of float32")
    parser.add_argument("--value", type=float, default=15.0, help="value to send (default 11.0)")
    parser.add_argument("--interval", type=float, default=5.0, help="interval in seconds (default 5)")
    args = parser.parse_args()

    try:
        import serial
    except ImportError:
        print("[ERR] pyserial not installed, run: pip install pyserial")
        sys.exit(1)

    fmt_label = "uint8" if args.byte else "float32"
    if args.byte:
        payload = struct.pack("<B", max(1, min(255, int(args.value))))
    else:
        payload = struct.pack("<f", float(args.value))

    print(f"[SENDER] Opening {args.port} @ {args.baud} baud, fmt={fmt_label}")
    try:
        ser = serial.Serial(args.port, args.baud, timeout=1, write_timeout=1)
    except Exception as e:
        print(f"[ERR] Cannot open {args.port}: {e}")
        sys.exit(1)

    print(f"[SENDER] Connected: {ser.name}")
    print(f"[SENDER] Every {args.interval:.0f}s sending {args.value} -> {payload.hex(' ')} ({len(payload)}B)")
    print(f"[SENDER] Press Ctrl+C to stop\n")

    count = 0
    try:
        while True:
            n = ser.write(payload)
            count += 1
            print(f"  [{count:3d}] -> {n}B: {payload.hex(' ')}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print(f"\n[SENDER] Stopped — sent {count} times")
    finally:
        ser.close()
        print("[SENDER] Closed")


if __name__ == "__main__":
    main()
