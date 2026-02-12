"""
Wi-SUNスキャンテストスクリプト

スマートメーターのスキャン(SKSCAN)だけを実行し、
生の応答をすべて表示する。デバッグ用。
"""

import sys
import serial
import time
import config


def send_cmd(ser, cmd, wait_for=None, timeout=10):
    """コマンド送信（応答を全て表示）"""
    print(f"<< {cmd}")
    ser.write((cmd + '\r\n').encode())
    lines = []
    start = time.time()
    while time.time() - start < timeout:
        if ser.in_waiting > 0:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                elapsed = time.time() - start
                print(f"  [{elapsed:5.1f}s] >> {line}")
                lines.append(line)
                if wait_for and wait_for in line:
                    break
        else:
            time.sleep(0.1)
    return lines


def main():
    print(f"Serial port: {config.SERIAL_PORT}")
    print(f"Baud rate: {config.BAUD_RATE}")

    ser = serial.Serial(config.SERIAL_PORT, config.BAUD_RATE, timeout=2)
    time.sleep(0.5)

    try:
        # 認証情報設定
        print("\n[1] Setting B-route credentials...")
        send_cmd(ser, f'SKSETRBID {config.BROUTE_ID}', 'OK')
        send_cmd(ser, f'SKSETPWD C {config.BROUTE_PASSWORD}', 'OK')

        # スキャン実行 (Duration=7, 約30秒)
        print("\n[2] Starting scan (SKSCAN 2 FFFFFFFF 7 0)...")
        print("    Waiting for EVENT 22 (scan complete)...\n")
        lines = send_cmd(ser, 'SKSCAN 2 FFFFFFFF 7 0', 'EVENT 22', timeout=120)

        # 結果パース
        print("\n[3] Parsing results...")
        channel = None
        pan_id = None
        addr = None

        for line in lines:
            if line.strip().startswith("Channel:"):
                channel = line.split(":")[1].strip()
            elif line.strip().startswith("Pan ID:"):
                pan_id = line.split(":")[1].strip()
            elif line.strip().startswith("Addr:"):
                addr = line.split(":")[1].strip()

        if channel and pan_id and addr:
            print(f"\n*** Smart meter FOUND! ***")
            print(f"  Channel: {channel}")
            print(f"  Pan ID:  {pan_id}")
            print(f"  Addr:    {addr}")
            return 0
        else:
            print(f"\n*** Smart meter NOT FOUND ***")
            print(f"  Received {len(lines)} lines but no scan result data")
            return 1

    finally:
        ser.close()
        print("\nSerial port closed.")


if __name__ == "__main__":
    sys.exit(main())
