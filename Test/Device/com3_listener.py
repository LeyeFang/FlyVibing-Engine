"""
COM3 监听器 — 持续监听串口，解码 SerialSend (bytes 格式) 发来的 float32 数据。

用法:
    python -m Test.Device.com3_listener
    或直接:  python Test/Device/com3_listener.py

约定: 波特率 9600，数据格式 float32 小端 (4 字节)。
"""

import struct
import sys
import time


def main():
    port = "COM3"
    baud = 9600

    try:
        import serial
    except ImportError:
        print("[ERR] pyserial 未安装，请执行: pip install pyserial")
        sys.exit(1)

    print(f"[COM3] 打开 {port} @ {baud} baud ...")
    try:
        ser = serial.Serial(port, baud, timeout=0.5)
    except Exception as e:
        print(f"[ERR] 无法打开 {port}: {e}")
        sys.exit(1)

    print(f"[COM3] 监听中，按 Ctrl+C 退出 ...\n")
    buf = b""
    count = 0

    try:
        start_time = time.time()
        while True:
            try:
                chunk = ser.read(max(1, ser.in_waiting or 1))
            except Exception as e:
                print(f"[COM3] 读取异常: {e}")
                time.sleep(0.5)
                continue

            if not chunk:
                continue

            buf += chunk
            # 每 4 字节解一个 float32
            while len(buf) >= 4:
                raw = buf[:4]
                buf = buf[4:]
                try:
                    val = struct.unpack("<f", raw)[0]
                except struct.error:
                    # 字节不对齐，丢弃 1 字节重试
                    buf = raw[1:] + buf
                    continue
                count += 1
                t = time.time() - start_time
                print(f"  [{count:03d}] t={t:.3f}  value={val}")

    except KeyboardInterrupt:
        print(f"\n[COM3] 停止。共收到 {count} 条数据。")
    finally:
        ser.close()
        print("[COM3] 串口已关闭。")


if __name__ == "__main__":
    main()
