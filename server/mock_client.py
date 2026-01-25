"""
Mock Wi-SUN クライアント

Wi-SUNアダプタなしでテスト可能なモックデータ生成
"""

import random
from datetime import datetime
from typing import Optional


class MockWiSUNClient:
    """Mock Wi-SUN クライアント（テスト用）"""

    def __init__(
        self,
        port: str = "",
        broute_id: str = "",
        broute_pwd: str = "",
        baud_rate: int = 115200,
        cache_file: Optional[str] = None,
    ):
        """
        WiSUNClientと同じシグネチャを持つが、引数は無視される
        """
        self._connected = False

    def connect(self) -> bool:
        """接続（常に成功）"""
        print("Mock mode: Simulating smart meter connection...")
        self._connected = True
        print("Mock mode: Connected successfully!")
        return True

    def close(self):
        """切断"""
        self._connected = False
        print("Mock mode: Disconnected")

    def get_power_data(self) -> dict:
        """
        Mockの電力データを生成

        色変化がわかりやすいよう広い範囲でランダム変動
        60A契約(6000W)の場合: 緑<2000W, 青<4000W, 黄<6000W, 赤>6000W
        """
        power = random.randint(500, 5500)

        return {
            "instant_power": power,
        }

    def get_connection_info(self) -> dict:
        """
        Mock接続情報を返す
        """
        # RSSIはランダムに変動（-50〜-80 dBm）
        rssi = random.randint(-80, -50)

        if rssi >= -60:
            rssi_quality = "excellent"
        elif rssi >= -70:
            rssi_quality = "good"
        elif rssi >= -80:
            rssi_quality = "fair"
        else:
            rssi_quality = "poor"

        return {
            "channel": "33",
            "pan_id": "MOCK",
            "mac_addr": "MOCK00000001",
            "ipv6_addr": "FE80:0000:0000:0000:MOCK:MOCK:MOCK:0001",
            "rssi": rssi,
            "rssi_quality": rssi_quality,
        }

    def get_energy_data(self) -> dict:
        """
        Mock積算電力量データを返す
        """
        now = datetime.now()

        # 定時積算電力量の時刻（30分単位に丸める）
        fixed_minute = (now.minute // 30) * 30
        fixed_time = now.replace(minute=fixed_minute, second=0, microsecond=0)

        # 月初からの日数に基づいてベースの積算量を計算（1日約20kWh想定）
        day_of_month = now.day
        base_energy = day_of_month * 20.0 + random.uniform(0, 5)

        # 逆方向（売電）は太陽光がある想定で少なめ（1日約5kWh）
        base_energy_rev = day_of_month * 5.0 + random.uniform(0, 2)

        return {
            "cumulative_energy": round(base_energy, 1),
            "cumulative_energy_reverse": round(base_energy_rev, 1),
            "fixed_energy": {
                "timestamp": fixed_time.strftime("%Y-%m-%d %H:%M:%S"),
                "energy": round(base_energy - random.uniform(0, 1), 1)
            },
            "energy_unit": 0.1
        }
