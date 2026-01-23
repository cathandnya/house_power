"""
Wi-SUN Bルート通信クライアント

ROHM BP35C2 / テセラ製 Wi-SUN USBアダプタ対応
SKコマンドでスマートメーターと通信し、ECHONET Liteで電力値を取得
"""

import serial
import time
import re
import json
import os
from typing import Optional
from dataclasses import dataclass


@dataclass
class ScanResult:
    """スキャン結果"""
    channel: str
    pan_id: str
    addr: str


class WiSUNClient:
    """Wi-SUN Bルート通信クライアント"""

    # ECHONET Lite定数
    ECHONET_LITE_HEADER = "1081"  # EHD
    ECHONET_LITE_TID = "0001"    # トランザクションID
    SEOJ = "05FF01"              # 送信元（コントローラー）
    DEOJ = "028801"              # 宛先（低圧スマート電力量メーター）

    # EPC（ECHONET Liteプロパティコード）
    EPC_INSTANT_POWER = "E7"     # 瞬時電力計測値
    EPC_INSTANT_CURRENT = "E8"   # 瞬時電流計測値
    EPC_CUMULATIVE_ENERGY = "E0" # 積算電力量

    def __init__(self, port: str, broute_id: str, broute_pwd: str,
                 baud_rate: int = 115200, cache_file: Optional[str] = None):
        """
        初期化

        Args:
            port: シリアルポート（例: /dev/ttyUSB0）
            broute_id: BルートID（32文字）
            broute_pwd: Bルートパスワード（12文字）
            baud_rate: ボーレート（デフォルト: 115200）
            cache_file: 接続情報キャッシュファイルパス
        """
        self.port = port
        self.broute_id = broute_id
        self.broute_pwd = broute_pwd
        self.baud_rate = baud_rate
        self.cache_file = cache_file or "wisun_cache.json"

        self.ser: Optional[serial.Serial] = None
        self.ipv6_addr: Optional[str] = None
        self.scan_result: Optional[ScanResult] = None

    def open(self) -> bool:
        """シリアルポートを開く"""
        try:
            self.ser = serial.Serial(
                self.port,
                self.baud_rate,
                timeout=2
            )
            time.sleep(0.5)
            return True
        except serial.SerialException as e:
            print(f"Serial open error: {e}")
            return False

    def close(self):
        """シリアルポートを閉じる"""
        if self.ser and self.ser.is_open:
            self.ser.close()

    def _send_command(self, cmd: str, wait_for: Optional[str] = None,
                      timeout: float = 10.0) -> list[str]:
        """
        SKコマンドを送信して応答を受信

        Args:
            cmd: 送信するコマンド
            wait_for: この文字列を含む行が来るまで待つ
            timeout: タイムアウト秒数

        Returns:
            受信した行のリスト
        """
        if not self.ser:
            return []

        # 送信
        self.ser.write((cmd + "\r\n").encode())

        # 受信
        lines = []
        start_time = time.time()

        while True:
            if time.time() - start_time > timeout:
                break

            if self.ser.in_waiting > 0:
                line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    lines.append(line)
                    if wait_for and wait_for in line:
                        break
            else:
                time.sleep(0.1)

        return lines

    def _load_cache(self) -> bool:
        """キャッシュから接続情報を読み込む"""
        if not os.path.exists(self.cache_file):
            return False

        try:
            with open(self.cache_file, 'r') as f:
                data = json.load(f)
                self.scan_result = ScanResult(
                    channel=data['channel'],
                    pan_id=data['pan_id'],
                    addr=data['addr']
                )
                self.ipv6_addr = data.get('ipv6_addr')
                return True
        except Exception as e:
            print(f"Cache load error: {e}")
            return False

    def _save_cache(self):
        """接続情報をキャッシュに保存"""
        if not self.scan_result:
            return

        try:
            data = {
                'channel': self.scan_result.channel,
                'pan_id': self.scan_result.pan_id,
                'addr': self.scan_result.addr,
                'ipv6_addr': self.ipv6_addr
            }
            with open(self.cache_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Cache save error: {e}")

    def connect(self) -> bool:
        """
        スマートメーターに接続

        Returns:
            接続成功したらTrue
        """
        if not self.open():
            return False

        # BルートID設定
        print("Setting B-route ID...")
        self._send_command(f"SKSETRBID {self.broute_id}", "OK")

        # パスワード設定
        print("Setting password...")
        self._send_command(f"SKSETPWD C {self.broute_pwd}", "OK")

        # キャッシュがあれば使う
        if self._load_cache() and self.scan_result:
            print(f"Using cached connection info: CH={self.scan_result.channel}")

            # チャンネル設定
            self._send_command(f"SKSREG S2 {self.scan_result.channel}", "OK")
            # PAN ID設定
            self._send_command(f"SKSREG S3 {self.scan_result.pan_id}", "OK")

            # IPv6アドレスがなければ取得
            if not self.ipv6_addr:
                self.ipv6_addr = self._get_ipv6_addr(self.scan_result.addr)
                self._save_cache()
        else:
            # スキャン実行
            print("Scanning for smart meter...")
            self.scan_result = self._scan()
            if not self.scan_result:
                print("Smart meter not found")
                return False

            print(f"Found: CH={self.scan_result.channel}, PAN={self.scan_result.pan_id}")

            # チャンネル設定
            self._send_command(f"SKSREG S2 {self.scan_result.channel}", "OK")
            # PAN ID設定
            self._send_command(f"SKSREG S3 {self.scan_result.pan_id}", "OK")

            # IPv6アドレス取得
            self.ipv6_addr = self._get_ipv6_addr(self.scan_result.addr)

            # キャッシュ保存
            self._save_cache()

        if not self.ipv6_addr:
            print("Failed to get IPv6 address")
            return False

        # PANA接続
        print("Connecting (SKJOIN)...")
        result = self._send_command(f"SKJOIN {self.ipv6_addr}", "EVENT 25", timeout=30)

        # 接続成功確認
        for line in result:
            if "EVENT 25" in line:
                print("Connected successfully!")
                return True
            if "EVENT 24" in line:
                print("Connection failed (EVENT 24)")
                # キャッシュ削除
                if os.path.exists(self.cache_file):
                    os.remove(self.cache_file)
                return False

        print("Connection timeout")
        return False

    def _scan(self) -> Optional[ScanResult]:
        """アクティブスキャンでスマートメーターを探す"""
        # スキャン実行（Duration=6で約1分）
        lines = self._send_command("SKSCAN 2 FFFFFFFF 6", "EVENT 22", timeout=60)

        # 結果パース
        channel = None
        pan_id = None
        addr = None

        for line in lines:
            if line.startswith("  Channel:"):
                channel = line.split(":")[1].strip()
            elif line.startswith("  Pan ID:"):
                pan_id = line.split(":")[1].strip()
            elif line.startswith("  Addr:"):
                addr = line.split(":")[1].strip()

        if channel and pan_id and addr:
            return ScanResult(channel=channel, pan_id=pan_id, addr=addr)

        return None

    def _get_ipv6_addr(self, mac_addr: str) -> Optional[str]:
        """MACアドレスからIPv6リンクローカルアドレスを取得"""
        lines = self._send_command(f"SKLL64 {mac_addr}", timeout=5)

        for line in lines:
            if line.startswith("FE80:"):
                return line.strip()

        return None

    def _build_echonet_frame(self, epc: str, edt: str = "") -> str:
        """ECHONET Liteフレームを構築"""
        esv = "62" if edt == "" else "61"  # Get or SetC
        opc = "01"  # 処理プロパティ数
        pdc = format(len(edt) // 2, '02X')  # EDTバイト数

        frame = (
            self.ECHONET_LITE_HEADER +
            self.ECHONET_LITE_TID +
            self.SEOJ +
            self.DEOJ +
            esv +
            opc +
            epc +
            pdc +
            edt
        )

        return frame

    def _send_echonet(self, epc: str) -> Optional[str]:
        """ECHONET Lite電文を送信してEDTを取得"""
        if not self.ser or not self.ipv6_addr:
            return None

        frame = self._build_echonet_frame(epc)
        frame_bytes = bytes.fromhex(frame)

        # SKSENDTO送信
        cmd = f"SKSENDTO 1 {self.ipv6_addr} 0E1A 1 {len(frame_bytes):04X} "
        self.ser.write(cmd.encode())
        self.ser.write(frame_bytes)
        self.ser.write(b"\r\n")

        # 応答待ち
        start_time = time.time()
        while time.time() - start_time < 10:
            if self.ser.in_waiting > 0:
                line = self.ser.readline().decode('utf-8', errors='ignore').strip()

                if line.startswith("ERXUDP"):
                    # ERXUDP応答をパース
                    parts = line.split(" ")
                    if len(parts) >= 9:
                        data = parts[8]
                        # ECHONET Liteレスポンスをパース
                        return self._parse_echonet_response(data, epc)
            else:
                time.sleep(0.1)

        return None

    def _parse_echonet_response(self, data: str, expected_epc: str) -> Optional[str]:
        """ECHONET Liteレスポンスをパースしてプロパティ値を取得"""
        try:
            # 最低限の長さチェック
            if len(data) < 24:
                return None

            # ヘッダチェック (1081)
            if data[0:4] != "1081":
                return None

            # ESVチェック（72=Get_Res, 71=Set_Res）
            esv = data[20:22]
            if esv not in ["72", "71", "52"]:
                return None

            # OPC（プロパティ数）
            opc = int(data[22:24], 16)

            # プロパティをパース
            pos = 24
            for _ in range(opc):
                epc = data[pos:pos+2]
                pdc = int(data[pos+2:pos+4], 16)
                edt = data[pos+4:pos+4+pdc*2]

                if epc.upper() == expected_epc.upper():
                    return edt

                pos += 4 + pdc * 2

        except Exception as e:
            print(f"Parse error: {e}")

        return None

    def get_instant_power(self) -> Optional[int]:
        """
        瞬時電力を取得

        Returns:
            瞬時電力（W）。取得失敗時はNone
        """
        edt = self._send_echonet(self.EPC_INSTANT_POWER)
        if edt and len(edt) == 8:
            # 符号付き32ビット整数
            value = int(edt, 16)
            if value >= 0x80000000:
                value -= 0x100000000
            return value
        return None

    def get_instant_current(self) -> Optional[tuple[float, float]]:
        """
        瞬時電流を取得

        Returns:
            (R相電流, T相電流) のタプル（A）。取得失敗時はNone
        """
        edt = self._send_echonet(self.EPC_INSTANT_CURRENT)
        if edt and len(edt) == 8:
            # R相: 符号付き16ビット整数（0.1A単位）
            r_raw = int(edt[0:4], 16)
            if r_raw >= 0x8000:
                r_raw -= 0x10000
            r_current = r_raw / 10.0

            # T相: 符号付き16ビット整数（0.1A単位）
            t_raw = int(edt[4:8], 16)
            if t_raw >= 0x8000:
                t_raw -= 0x10000
            t_current = t_raw / 10.0

            return (r_current, t_current)
        return None

    def get_power_data(self) -> dict:
        """
        電力データを取得

        Returns:
            {
                "instant_power": 瞬時電力(W),
                "instant_current_r": R相電流(A),
                "instant_current_t": T相電流(A)
            }
        """
        data = {
            "instant_power": None,
            "instant_current_r": None,
            "instant_current_t": None
        }

        # 瞬時電力
        power = self.get_instant_power()
        if power is not None:
            data["instant_power"] = power

        # 瞬時電流
        current = self.get_instant_current()
        if current is not None:
            data["instant_current_r"] = current[0]
            data["instant_current_t"] = current[1]

        return data


# テスト用
if __name__ == "__main__":
    import config

    client = WiSUNClient(
        port=config.SERIAL_PORT,
        broute_id=config.BROUTE_ID,
        broute_pwd=config.BROUTE_PASSWORD
    )

    if client.connect():
        print("\n--- Getting power data ---")
        for i in range(10):
            data = client.get_power_data()
            print(f"Power: {data['instant_power']}W, "
                  f"R: {data['instant_current_r']}A, "
                  f"T: {data['instant_current_t']}A")
            time.sleep(3)

        client.close()
    else:
        print("Connection failed")
