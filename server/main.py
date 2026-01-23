#!/usr/bin/env python3
"""
家庭電力モニター サーバー

Wi-SUN Bルートでスマートメーターから電力データを取得し、
REST API / WebSocket で配信する
"""

import argparse
import asyncio
import os
import signal
import sys
from datetime import datetime

import uvicorn

# ローカルモジュール
try:
    import config
except ImportError:
    print("Error: config.py が見つかりません")
    print("config.py.example をコピーして config.py を作成し、")
    print("BルートID/パスワードを設定してください")
    sys.exit(1)

from api import app, update_power_data, broadcast_power_data, set_mock_mode, check_and_notify
import api
from notifier import LineNotifier


def parse_args():
    """コマンドライン引数をパース"""
    parser = argparse.ArgumentParser(description="家庭電力モニター サーバー")
    parser.add_argument(
        "--mock",
        "-m",
        action="store_true",
        help="Mockモードで起動（Wi-SUNアダプタ不要）",
    )
    return parser.parse_args()


def is_mock_mode(args) -> bool:
    """Mockモードかどうかを判定（優先順位: コマンドライン > 環境変数 > config）"""
    # 1. コマンドライン引数
    if args.mock:
        return True

    # 2. 環境変数
    env_mock = os.environ.get("MOCK_MODE", "").lower()
    if env_mock in ("true", "1", "yes"):
        return True

    # 3. config.py
    if getattr(config, "MOCK_MODE", False):
        return True

    return False


def create_client(mock_mode: bool):
    """クライアントを作成"""
    if mock_mode:
        from mock_client import MockWiSUNClient

        return MockWiSUNClient()
    else:
        from wisun_client import WiSUNClient

        return WiSUNClient(
            port=config.SERIAL_PORT,
            broute_id=config.BROUTE_ID,
            broute_pwd=config.BROUTE_PASSWORD,
            baud_rate=config.BAUD_RATE,
        )


# グローバル変数
wisun_client = None
running = True


async def power_loop():
    """電力データ取得ループ（3秒ごと）"""
    global wisun_client, running

    while running:
        try:
            if wisun_client:
                data = wisun_client.get_power_data()

                # データ更新
                update_power_data(
                    power=data.get("instant_power"),
                    current_r=data.get("instant_current_r"),
                    current_t=data.get("instant_current_t"),
                )

                # WebSocketで配信
                await broadcast_power_data()

                # 閾値チェック・通知
                power = data.get("instant_power")
                if power is not None:
                    await check_and_notify(power)

                # ログ出力
                if power is not None:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Power: {power}W")

        except Exception as e:
            print(f"Error in power loop: {e}")

        await asyncio.sleep(config.POLL_INTERVAL)


async def main():
    """メイン関数"""
    global wisun_client, running

    # 引数パース
    args = parse_args()
    mock_mode = is_mock_mode(args)

    # api.pyにmockモードを設定
    set_mock_mode(mock_mode)

    # LINE Notifier初期化
    token = getattr(config, "LINE_NOTIFY_TOKEN", "")
    if token:
        cooldown = getattr(config, "NOTIFY_COOLDOWN_MINUTES", 5)
        api.notifier = LineNotifier(token=token, cooldown_minutes=cooldown)

    print("=" * 50)
    print("家庭電力モニター サーバー")
    if mock_mode:
        print("*** MOCK MODE ***")
    if token:
        print("LINE Notify: Enabled")
    else:
        print("LINE Notify: Disabled (no token)")
    print("=" * 50)

    # クライアント初期化
    if mock_mode:
        print("\nStarting in mock mode (no Wi-SUN adapter required)...")
    else:
        print(f"\nConnecting to Wi-SUN adapter ({config.SERIAL_PORT})...")

    wisun_client = create_client(mock_mode)

    # スマートメーターに接続
    if not wisun_client.connect():
        print("\nFailed to connect to smart meter")
        if not mock_mode:
            print("Please check:")
            print("  1. Wi-SUN adapter is connected")
            print("  2. B-route ID/password is correct")
            print("  3. Smart meter is in range")
            print("\nTip: Use --mock flag to run without hardware")
        sys.exit(1)

    print(f"\nStarting API server on http://{config.API_HOST}:{config.API_PORT}")
    print("Press Ctrl+C to stop\n")

    # 電力取得タスクを開始
    power_task = asyncio.create_task(power_loop())

    # APIサーバー起動
    server_config = uvicorn.Config(
        app, host=config.API_HOST, port=config.API_PORT, log_level="warning"
    )
    server = uvicorn.Server(server_config)

    try:
        await server.serve()
    except asyncio.CancelledError:
        pass
    finally:
        running = False
        power_task.cancel()

        if wisun_client:
            wisun_client.close()

        print("\nServer stopped")


def signal_handler(sig, frame):
    """シグナルハンドラ"""
    global running
    print("\nShutting down...")
    running = False
    sys.exit(0)


if __name__ == "__main__":
    # シグナルハンドラ設定
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # メイン実行
    asyncio.run(main())
