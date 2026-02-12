"""
Wi-SUN Bルート通信クライアント

ROHM BP35C2 / テセラ製 Wi-SUN USBアダプタ対応
SKコマンドでスマートメーターと通信し、ECHONET Liteで電力値を取得
"""

import logging
import serial
import time
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
    EPC_CUMULATIVE_ENERGY = "E0" # 積算電力量（正方向）
    EPC_CUMULATIVE_ENERGY_REV = "E3"  # 積算電力量（逆方向・売電）
    EPC_CUMULATIVE_ENERGY_UNIT = "E1" # 積算電力量単位
    EPC_CUMULATIVE_ENERGY_FIXED = "EA" # 定時積算電力量（正方向）

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
        self.last_rssi: Optional[int] = None  # 最後に受信したRSSI (dBm)
        self.energy_unit: Optional[float] = None  # 積算電力量単位 (kWh)
        self.consecutive_timeouts: int = 0  # 連続タイムアウト回数
        self.max_timeouts_before_reconnect: int = 2  # 再接続までの許容回数
        self._needs_reconnect: bool = False  # 即座に再接続が必要かどうか
        self._reconnect_backoff: int = 0  # 再接続失敗後のバックオフ（ポーリング回数）

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
            logging.error(f"Serial open error: {e}")
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
            logging.warning(f"Cache load error: {e}")
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
            logging.warning(f"Cache save error: {e}")

    def connect(self) -> bool:
        """
        スマートメーターに接続

        Returns:
            接続成功したらTrue
        """
        if not self.open():
            return False

        # アダプタ応答確認（ヘルスチェック）
        ver_lines = self._send_command("SKVER", "OK", timeout=5)
        ver = next((l for l in ver_lines if l.startswith("EVER")), None)
        if ver:
            logging.info(f"Wi-SUN adapter firmware: {ver}")
        else:
            logging.error("Wi-SUN adapter not responding to SKVER")
            return False

        # BルートID設定
        logging.info("Setting B-route ID...")
        self._send_command(f"SKSETRBID {self.broute_id}", "OK")

        # パスワード設定
        logging.info("Setting password...")
        self._send_command(f"SKSETPWD C {self.broute_pwd}", "OK")

        # RSSI表示を有効化（SA2=1でERXUDPにRSSIが含まれる）
        self._send_command("SKSREG SA2 1", "OK")

        # キャッシュがあれば使う
        if self._load_cache() and self.scan_result:
            logging.info(f"Using cached connection info: CH={self.scan_result.channel}")

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
            logging.info("Scanning for smart meter...")
            self.scan_result = self._scan()
            if not self.scan_result:
                logging.error("Smart meter not found")
                return False

            logging.info(f"Found: CH={self.scan_result.channel}, PAN={self.scan_result.pan_id}")

            # チャンネル設定
            self._send_command(f"SKSREG S2 {self.scan_result.channel}", "OK")
            # PAN ID設定
            self._send_command(f"SKSREG S3 {self.scan_result.pan_id}", "OK")

            # IPv6アドレス取得
            self.ipv6_addr = self._get_ipv6_addr(self.scan_result.addr)

            # キャッシュ保存
            self._save_cache()

        if not self.ipv6_addr:
            logging.error("Failed to get IPv6 address")
            return False

        # PANA接続
        logging.info("Connecting (SKJOIN)...")
        result = self._send_command(f"SKJOIN {self.ipv6_addr}", "EVENT 25", timeout=30)

        # 接続成功確認
        for line in result:
            if "EVENT 25" in line:
                logging.info("Connected successfully!")
                # 接続後バッファクリア
                time.sleep(0.5)
                while self.ser and self.ser.in_waiting > 0:
                    self.ser.read(self.ser.in_waiting)
                return True
            if "EVENT 24" in line:
                logging.error("Connection failed (EVENT 24)")
                # キャッシュ削除
                if os.path.exists(self.cache_file):
                    os.remove(self.cache_file)
                return False

        logging.error("Connection timeout")
        return False

    def reconnect(self) -> bool:
        """
        再接続を試行

        Returns:
            再接続成功したらTrue
        """
        logging.warning("Attempting reconnection...")

        # まず SKTERM で明示的に切断を試行
        if self.ser and self.ser.is_open:
            try:
                logging.info("Sending SKTERM...")
                self.ser.write(b"SKTERM\r\n")
                time.sleep(1)
                # SKRESET でプロトコルスタックを初期化
                logging.info("Sending SKRESET...")
                self.ser.write(b"SKRESET\r\n")
                time.sleep(1)
                # バッファクリア
                while self.ser.in_waiting > 0:
                    self.ser.read(self.ser.in_waiting)
                # SKRESET後に認証情報を再設定
                logging.info("Re-setting B-route credentials...")
                self._send_command(f"SKSETRBID {self.broute_id}", "OK")
                self._send_command(f"SKSETPWD C {self.broute_pwd}", "OK")
                if self.scan_result:
                    self._send_command(f"SKSREG S2 {self.scan_result.channel}", "OK")
                    self._send_command(f"SKSREG S3 {self.scan_result.pan_id}", "OK")
            except Exception as e:
                logging.warning(f"SKTERM/SKRESET error: {e}")

        # 再接続（SKJOINのみ、スキャン不要）
        if self.ipv6_addr:
            logging.info("Reconnecting (SKJOIN)...")
            result = self._send_command(f"SKJOIN {self.ipv6_addr}", "EVENT 25", timeout=30)

            for line in result:
                if "EVENT 25" in line:
                    logging.info("Reconnected successfully!")
                    self.consecutive_timeouts = 0
                    # PANAセッション安定待ち＆バッファクリア
                    time.sleep(2)
                    while self.ser and self.ser.in_waiting > 0:
                        self.ser.read(self.ser.in_waiting)
                    return True
                if "EVENT 24" in line:
                    logging.error("Reconnection failed (EVENT 24)")
                    return False

            logging.error("Reconnection timeout")
            return False
        else:
            logging.error("No IPv6 address for reconnection")
            return False

    def _scan(self) -> Optional[ScanResult]:
        """アクティブスキャンでスマートメーターを探す"""
        # スキャン実行（Duration=7で約2分）
        # テセラ製ドングルは最後のパラメータ(0)が必要
        lines = self._send_command("SKSCAN 2 FFFFFFFF 7 0", "EVENT 22", timeout=120)

        # 結果パース
        channel = None
        pan_id = None
        addr = None
        lqi = None

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("Channel:"):
                channel = stripped.split(":")[1].strip()
            elif stripped.startswith("Pan ID:"):
                pan_id = stripped.split(":")[1].strip()
            elif stripped.startswith("Addr:"):
                addr = stripped.split(":")[1].strip()
            elif stripped.startswith("LQI:"):
                lqi = stripped.split(":")[1].strip()

        if channel and pan_id and addr:
            if lqi:
                logging.info(f"Scan LQI: {lqi} (signal quality)")
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
            logging.debug(f"_send_echonet: ser={self.ser is not None}, ipv6={self.ipv6_addr}")
            return None

        frame = self._build_echonet_frame(epc)
        frame_bytes = bytes.fromhex(frame)

        # SKSENDTO送信
        # 注意: テセラ製Wi-SUNモジュールでは、コマンドとデータを一度に送信
        # データの後にCRLFを付けない
        cmd = f"SKSENDTO 1 {self.ipv6_addr} 0E1A 1 0 {len(frame_bytes):04X} "
        logging.debug(f"_send_echonet: sending cmd for EPC={epc}")
        try:
            self.ser.write(cmd.encode() + frame_bytes)
        except Exception as e:
            logging.error(f"_send_echonet: write error: {e}")
            return None

        # 応答待ち（5秒タイムアウト）
        start_time = time.time()
        while time.time() - start_time < 5:
            if self.ser.in_waiting > 0:
                try:
                    line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                except Exception as e:
                    logging.error(f"_send_echonet: readline error: {e}")
                    return None

                if line:
                    logging.debug(f"_send_echonet: recv line={line[:80]}...")

                # EVENT 29: PANAセッション切断通知（ライフタイム期限切れ等）
                if line.startswith("EVENT 29"):
                    logging.error("PANA session disconnected (EVENT 29), triggering reconnect")
                    self._needs_reconnect = True
                    return None

                # EVENT 21: 送信結果 (EVENT 21 <IPv6> <SIDE> <RESULT>)
                # RESULT: 00=成功, 01=失敗, 02=IP再送回数オーバー
                if line.startswith("EVENT 21"):
                    parts = line.split(" ")
                    if len(parts) >= 4:
                        result_code = parts[-1]  # 最後の要素が結果コード
                        if result_code != "00":
                            logging.warning(f"Send failed: EVENT 21 result={result_code}, will reconnect on next poll")
                            self._needs_reconnect = True
                            return None  # 次回ポーリングで再接続

                if line.startswith("ERXUDP"):
                    # ERXUDP応答をパース
                    # SA2=1の場合: ERXUDP SENDER DEST RPORT LPORT SENDERLLA RSSI SECURED SIDE DATALEN DATA
                    # SA2=0の場合: ERXUDP SENDER DEST RPORT LPORT SENDERLLA SECURED SIDE DATALEN DATA
                    parts = line.split(" ")
                    logging.debug(f"ERXUDP parts({len(parts)}): {[p[:20] for p in parts]}")
                    if len(parts) >= 11:
                        # SA2=1: RSSIあり
                        rssi_raw = int(parts[6], 16)
                        self.last_rssi = rssi_raw - 107  # dBmに変換
                        logging.debug(f"RSSI: raw=0x{parts[6]} ({rssi_raw}) -> {self.last_rssi} dBm")
                        data = parts[10]
                        dest = parts[2]
                    elif len(parts) >= 10:
                        # SA2=0: RSSIなし
                        logging.debug(f"ERXUDP: SA2=0 mode (no RSSI), parts[6]={parts[6]}")
                        data = parts[9]
                        dest = parts[2]
                    else:
                        continue

                    # ユニキャスト宛のレスポンスのみ処理（マルチキャストFF02:はスキップ）
                    if dest.startswith("FF02:"):
                        continue
                    # ECHONET Liteヘッダチェック（1081で始まらないデータはスキップ）
                    if not data.startswith("1081"):
                        logging.debug(f"ERXUDP ignored: not ECHONET Lite (data={data[:20]}...)")
                        continue
                    # ECHONET Liteレスポンスをパース
                    result = self._parse_echonet_response(data, epc)
                    if result is not None:
                        self.consecutive_timeouts = 0  # 成功したらリセット
                        return result
                    else:
                        logging.debug(f"ERXUDP ignored: EPC mismatch (expected={epc}, data={data[:40]}...)")
            else:
                time.sleep(0.1)

        logging.warning(f"_send_echonet: timeout for EPC={epc}")
        self.consecutive_timeouts += 1
        logging.info(f"Consecutive timeouts: {self.consecutive_timeouts}/{self.max_timeouts_before_reconnect}")

        # 連続タイムアウトが閾値に達したら即座に再接続してリトライ
        if self.consecutive_timeouts >= self.max_timeouts_before_reconnect:
            logging.warning("Threshold reached, attempting immediate reconnect...")
            if self.reconnect():
                self.consecutive_timeouts = 0
                # リトライ前にバッファを再度クリア（遅延到着データ対策）
                if self.ser:
                    time.sleep(0.5)
                    while self.ser.in_waiting > 0:
                        discarded = self.ser.read(self.ser.in_waiting)
                        logging.debug(f"Discarded {len(discarded)} bytes before retry")
                # 再接続成功したら即座にリトライ
                logging.info("Retrying after reconnect...")
                return self._send_echonet(epc)
            else:
                logging.error("Immediate reconnect failed")
                self.consecutive_timeouts = 0

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
            logging.warning(f"Parse error: {e}")

        return None

    def get_instant_power(self) -> Optional[int]:
        """
        瞬時電力を取得

        Returns:
            瞬時電力（W）。取得失敗時はNone
        """
        logging.debug("get_instant_power: sending request...")
        edt = self._send_echonet(self.EPC_INSTANT_POWER)
        logging.debug(f"get_instant_power: edt={edt}")
        if edt and len(edt) == 8:
            # 符号付き32ビット整数
            value = int(edt, 16)
            if value >= 0x80000000:
                value -= 0x100000000
            return value
        return None

    def _get_energy_unit(self) -> Optional[float]:
        """
        積算電力量単位を取得

        Returns:
            単位（kWh）。例: 0.1, 0.01, 1.0 など
        """
        if self.energy_unit is not None:
            return self.energy_unit

        edt = self._send_echonet(self.EPC_CUMULATIVE_ENERGY_UNIT)
        if edt and len(edt) == 2:
            code = int(edt, 16)
            # 0x00=1kWh, 0x01=0.1kWh, 0x02=0.01kWh, 0x03=0.001kWh
            # 0x04=0.0001kWh, 0x0A=10kWh, 0x0B=100kWh, 0x0C=1000kWh, 0x0D=10000kWh
            unit_map = {
                0x00: 1.0,
                0x01: 0.1,
                0x02: 0.01,
                0x03: 0.001,
                0x04: 0.0001,
                0x0A: 10.0,
                0x0B: 100.0,
                0x0C: 1000.0,
                0x0D: 10000.0,
            }
            self.energy_unit = unit_map.get(code, 0.1)  # デフォルト0.1kWh
            return self.energy_unit
        return None

    def get_cumulative_energy(self) -> Optional[float]:
        """
        積算電力量（正方向）を取得

        Returns:
            積算電力量（kWh）。取得失敗時はNone
        """
        unit = self._get_energy_unit()
        if unit is None:
            unit = 0.1  # デフォルト

        edt = self._send_echonet(self.EPC_CUMULATIVE_ENERGY)
        if edt and len(edt) == 8:
            # 符号なし32ビット整数
            value = int(edt, 16)
            if value == 0xFFFFFFFE:  # オーバーフロー
                return None
            return value * unit
        return None

    def get_cumulative_energy_reverse(self) -> Optional[float]:
        """
        積算電力量（逆方向・売電）を取得

        Returns:
            積算電力量（kWh）。取得失敗時はNone
        """
        unit = self._get_energy_unit()
        if unit is None:
            unit = 0.1  # デフォルト

        edt = self._send_echonet(self.EPC_CUMULATIVE_ENERGY_REV)
        if edt and len(edt) == 8:
            # 符号なし32ビット整数
            value = int(edt, 16)
            if value == 0xFFFFFFFE:  # オーバーフロー
                return None
            return value * unit
        return None

    def get_fixed_cumulative_energy(self) -> Optional[dict]:
        """
        定時積算電力量（正方向）を取得
        30分ごとの積算値と計測日時

        Returns:
            {
                "timestamp": "YYYY-MM-DD HH:MM:SS",
                "energy": 積算電力量(kWh)
            }
            取得失敗時はNone
        """
        unit = self._get_energy_unit()
        if unit is None:
            unit = 0.1  # デフォルト

        edt = self._send_echonet(self.EPC_CUMULATIVE_ENERGY_FIXED)
        if edt and len(edt) == 22:  # 11バイト
            # 年(2バイト) + 月(1) + 日(1) + 時(1) + 分(1) + 秒(1) + 積算電力量(4バイト)
            year = int(edt[0:4], 16)
            month = int(edt[4:6], 16)
            day = int(edt[6:8], 16)
            hour = int(edt[8:10], 16)
            minute = int(edt[10:12], 16)
            second = int(edt[12:14], 16)
            energy_raw = int(edt[14:22], 16)

            if energy_raw == 0xFFFFFFFE:  # オーバーフロー
                return None

            return {
                "timestamp": f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}",
                "energy": energy_raw * unit
            }
        return None

    def get_power_data(self) -> dict:
        """
        電力データを取得

        Returns:
            {"instant_power": 瞬時電力(W)}
        """
        data = {"instant_power": None}

        # バックオフ中はスキップ
        if self._reconnect_backoff > 0:
            self._reconnect_backoff -= 1
            logging.info(f"Reconnect backoff: waiting {self._reconnect_backoff + 1} more polls")
            return data

        # EVENT 29（PANAセッション切断）または連続タイムアウトで再接続を試行
        if self._needs_reconnect or self.consecutive_timeouts >= self.max_timeouts_before_reconnect:
            if self._needs_reconnect:
                logging.warning("PANA session lost (EVENT 29), attempting reconnect...")
            else:
                logging.warning(f"Too many consecutive timeouts ({self.consecutive_timeouts}), attempting reconnect...")
            if self.reconnect():
                self.consecutive_timeouts = 0
                self._needs_reconnect = False
                self._reconnect_backoff = 0
            else:
                logging.error("Reconnection failed, backing off before retry")
                self.consecutive_timeouts = 0
                self._needs_reconnect = True  # 次回も再接続を試みる
                self._reconnect_backoff = 12  # 12ポーリング分待機（5秒x12=60秒）
                return data

        # 瞬時電力
        power = self.get_instant_power()
        if power is not None:
            data["instant_power"] = power

        return data

    def get_energy_data(self) -> dict:
        """
        積算電力量データを取得

        Returns:
            {
                "cumulative_energy": 積算電力量(kWh),
                "cumulative_energy_reverse": 逆方向積算電力量(kWh),
                "fixed_energy": {
                    "timestamp": "YYYY-MM-DD HH:MM:SS",
                    "energy": 定時積算電力量(kWh)
                },
                "energy_unit": 積算電力量単位(kWh)
            }
        """
        data = {
            "cumulative_energy": None,
            "cumulative_energy_reverse": None,
            "fixed_energy": None,
            "energy_unit": None
        }

        # 積算電力量（正方向）
        energy = self.get_cumulative_energy()
        if energy is not None:
            data["cumulative_energy"] = energy

        # 積算電力量（逆方向）
        energy_rev = self.get_cumulative_energy_reverse()
        if energy_rev is not None:
            data["cumulative_energy_reverse"] = energy_rev

        # 定時積算電力量
        fixed = self.get_fixed_cumulative_energy()
        if fixed is not None:
            data["fixed_energy"] = fixed

        # 単位
        data["energy_unit"] = self.energy_unit

        return data

    def get_connection_info(self) -> dict:
        """
        接続情報を取得

        Returns:
            {
                "channel": チャンネル番号,
                "pan_id": PAN ID,
                "mac_addr": MACアドレス,
                "ipv6_addr": IPv6アドレス,
                "rssi": 電波強度(dBm),
                "rssi_quality": 電波品質("excellent"/"good"/"fair"/"poor")
            }
        """
        info = {
            "channel": None,
            "pan_id": None,
            "mac_addr": None,
            "ipv6_addr": self.ipv6_addr,
            "rssi": self.last_rssi,
            "rssi_quality": None
        }

        if self.scan_result:
            info["channel"] = self.scan_result.channel
            info["pan_id"] = self.scan_result.pan_id
            info["mac_addr"] = self.scan_result.addr

        # RSSI品質判定
        if self.last_rssi is not None:
            if self.last_rssi >= -60:
                info["rssi_quality"] = "excellent"
            elif self.last_rssi >= -70:
                info["rssi_quality"] = "good"
            elif self.last_rssi >= -80:
                info["rssi_quality"] = "fair"
            else:
                info["rssi_quality"] = "poor"

        return info


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
            print(f"Power: {data['instant_power']}W")
            time.sleep(3)

        client.close()
    else:
        print("Connection failed")
