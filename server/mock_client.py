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
        リアルな電力データを生成

        生成パターン:
        - 時間帯による変動（朝・昼・夕方・深夜）
        - ランダムなノイズ
        - たまに発生する高負荷スパイク
        """
        now = datetime.now()
        hour = now.hour

        # 時間帯別ベース電力
        if 6 <= hour < 9:  # 朝（起床・朝食準備）
            base = 1500
        elif 9 <= hour < 12:  # 午前（軽い活動）
            base = 800
        elif 12 <= hour < 14:  # 昼（昼食準備）
            base = 1200
        elif 14 <= hour < 18:  # 午後
            base = 600
        elif 18 <= hour < 22:  # 夜（夕食・入浴・エアコンなど）
            base = 2000
        elif 22 <= hour < 24:  # 深夜前
            base = 1000
        else:  # 深夜（待機電力中心）
            base = 300

        # 季節変動（簡易: 月による調整）
        month = now.month
        if month in [7, 8]:  # 夏（エアコン）
            base = int(base * 1.3)
        elif month in [1, 2, 12]:  # 冬（暖房）
            base = int(base * 1.4)

        # ランダムノイズ（±20%）
        noise = random.uniform(-0.2, 0.2)
        power = int(base * (1 + noise))

        # 10%の確率で高負荷スパイク（電子レンジ、ドライヤーなど）
        if random.random() < 0.1:
            spike = random.choice([800, 1000, 1200, 1500])  # 追加負荷
            power += spike

        # 電流計算（単相3線式: R相・T相に分散）
        # 電力 = 電圧(100V) × 電流 として簡易計算
        total_current = power / 100.0
        # R相とT相に不均等に分散（60:40 ~ 40:60）
        r_ratio = random.uniform(0.4, 0.6)
        current_r = round(total_current * r_ratio, 1)
        current_t = round(total_current * (1 - r_ratio), 1)

        return {
            "instant_power": power,
            "instant_current_r": current_r,
            "instant_current_t": current_t,
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
