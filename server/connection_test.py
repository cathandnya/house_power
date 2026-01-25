"""
Wi-SUN接続テストスクリプト

前回取得した接続情報（Channel, Pan ID, IPv6アドレス）を使って
スキャンをスキップし、直接PANA接続と電力データ取得をテストする

※ wisun_cache.jsonに保存された接続情報を使用します
"""

import json
import serial
import time
from pathlib import Path
import config

# キャッシュファイルから接続情報を読み込む
CACHE_FILE = Path(__file__).parent / "wisun_cache.json"


def load_cache():
    """キャッシュから接続情報を読み込む"""
    if not CACHE_FILE.exists():
        print(f"ERROR: Cache file not found: {CACHE_FILE}")
        print("Run the main server first to scan and cache connection info.")
        return None

    with open(CACHE_FILE, "r") as f:
        cache = json.load(f)

    required = ["channel", "pan_id", "ipv6_addr"]
    for key in required:
        if key not in cache:
            print(f"ERROR: Missing '{key}' in cache file")
            return None

    return cache


def send_cmd(ser, cmd, wait_for=None, timeout=10):
    """コマンド送信"""
    ser.write((cmd + '\r\n').encode())
    lines = []
    start = time.time()
    while time.time() - start < timeout:
        if ser.in_waiting > 0:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                print(f"  > {line}")
                lines.append(line)
                if wait_for and wait_for in line:
                    break
        else:
            time.sleep(0.1)
    return lines


def main():
    # キャッシュから接続情報を読み込む
    cache = load_cache()
    if cache is None:
        return

    channel = cache["channel"]
    pan_id = cache["pan_id"]
    ipv6_addr = cache["ipv6_addr"]

    print(f"Loaded from cache: channel={channel}, pan_id={pan_id}")
    print(f"IPv6: {ipv6_addr}")

    print(f"\nOpening serial port: {config.SERIAL_PORT}")
    ser = serial.Serial(config.SERIAL_PORT, config.BAUD_RATE, timeout=2)
    time.sleep(0.5)

    try:
        # 認証情報設定
        print("\n[1] Setting B-route credentials...")
        send_cmd(ser, f'SKSETRBID {config.BROUTE_ID}', 'OK')
        send_cmd(ser, f'SKSETPWD C {config.BROUTE_PASSWORD}', 'OK')

        # チャンネル・PAN ID設定
        print(f"\n[2] Setting channel={channel}, PAN ID={pan_id}...")
        send_cmd(ser, f'SKSREG S2 {channel}', 'OK')
        send_cmd(ser, f'SKSREG S3 {pan_id}', 'OK')

        # PANA接続
        print(f"\n[3] Connecting to {ipv6_addr}...")
        ser.write(f'SKJOIN {ipv6_addr}\r\n'.encode())

        connected = False
        start = time.time()
        while time.time() - start < 60:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    print(f"  > {line}")
                if 'EVENT 25' in line:
                    connected = True
                    print("\n*** PANA Connection SUCCESS! ***")
                    break
                if 'EVENT 24' in line:
                    print("\n*** PANA Connection FAILED ***")
                    break
            else:
                time.sleep(0.1)

        if not connected:
            print("Connection timeout or failed")
            return

        # 接続後少し待つ
        time.sleep(1)

        # バッファクリア
        while ser.in_waiting > 0:
            ser.read(ser.in_waiting)

        # 瞬時電力を複数回取得
        print("\n[4] Requesting instant power from smart meter (DEOJ=028801, EPC=E7)...")

        for i in range(3):
            print(f"\n--- Request {i+1} ---")
            # バッファクリア
            while ser.in_waiting > 0:
                ser.read(ser.in_waiting)

            # ECHONET Lite frame:
            # EHD=1081, TID=0001, SEOJ=05FF01, DEOJ=028801, ESV=62(Get), OPC=01, EPC=E7, PDC=00
            frame = bytes.fromhex('1081000105FF0102880162' + '01' + 'E7' + '00')

            # SKSENDTOコマンド
            cmd = f'SKSENDTO 1 {ipv6_addr} 0E1A 1 0 {len(frame):04X} '
            ser.write(cmd.encode() + frame)

            # 応答待ち
            start = time.time()
            while time.time() - start < 10:
                if ser.in_waiting > 0:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        if line.startswith('ERXUDP'):
                            parts = line.split(' ')
                            if len(parts) >= 10:
                                data = parts[9]
                                parse_echonet_response(data)
                                break
                else:
                    time.sleep(0.1)

            time.sleep(2)  # 次のリクエストまで待つ

        return

        # SKSENDTOコマンド
        # ハンドル=1, IPv6, ポート=0E1A, SEC=1, SIDE=0, DATALEN, DATA
        cmd = f'SKSENDTO 1 {ipv6_addr} 0E1A 1 0 {len(frame):04X} '
        print(f"  Sending: {cmd}[{len(frame)} bytes binary]")
        ser.write(cmd.encode() + frame)
        # テセラ製モジュール: データの後にCRLFは送信しない

        # 応答待ち
        start = time.time()
        while time.time() - start < 15:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    elapsed = time.time() - start
                    print(f"  [{elapsed:.1f}s] {line}")

                    if line.startswith('ERXUDP'):
                        parts = line.split(' ')
                        if len(parts) >= 9:
                            # ERXUDP形式: SENDER DEST RPORT LPORT MACADDR SEC SIDE DATALEN DATA
                            # データは最後のフィールド（インデックス9）
                            data = parts[9] if len(parts) > 9 else parts[8]
                            print(f"\n  ECHONET Lite Data: {data}")
                            parse_echonet_response(data)
            else:
                time.sleep(0.1)

    finally:
        ser.close()
        print("\nSerial port closed.")


def parse_echonet_response(data):
    """ECHONET Liteレスポンスをパース"""
    if len(data) < 24:
        print(f"  Data too short: {len(data)} chars")
        return

    ehd = data[0:4]
    tid = data[4:8]
    seoj = data[8:14]
    deoj = data[14:20]
    esv = data[20:22]
    opc = data[22:24]

    print(f"  EHD={ehd}, TID={tid}")
    print(f"  SEOJ={seoj}, DEOJ={deoj}")
    print(f"  ESV={esv}, OPC={opc}")

    # ESVの意味
    esv_names = {
        "62": "Get (request)",
        "72": "Get_Res (response)",
        "52": "Get_SNA (error)",
        "61": "SetC (request)",
        "71": "SetC_Res (response)",
        "51": "SetC_SNA (error)",
    }
    print(f"  ESV meaning: {esv_names.get(esv, 'Unknown')}")

    if esv == "72":
        # 正常レスポンス
        opc_count = int(opc, 16)
        pos = 24
        for i in range(opc_count):
            epc = data[pos:pos+2]
            pdc = int(data[pos+2:pos+4], 16)
            edt = data[pos+4:pos+4+pdc*2]
            print(f"  Property[{i}]: EPC={epc}, PDC={pdc}, EDT={edt}")

            if epc.upper() == 'E7' and pdc == 4:
                power = int(edt, 16)
                if power >= 0x80000000:
                    power -= 0x100000000
                print(f"\n  *** Instant Power: {power} W ***")

            pos += 4 + pdc * 2
    elif esv == "52":
        print("  ERROR: Get request failed (Get_SNA)")


if __name__ == "__main__":
    main()
