#!/usr/bin/env python3
"""
家庭電力モニター サーバー

Wi-SUN Bルートでスマートメーターから電力データを取得し、
REST API / WebSocket で配信する
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

import uvicorn


def setup_logging():
    """ロギング設定（コンソール + ファイル）"""
    # ログディレクトリ
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)

    # ログファイル名（起動時にクリア）
    log_file = log_dir / "server.log"

    # 起動時にログファイルをクリア
    if log_file.exists():
        log_file.unlink()

    # ルートロガー設定
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # 既存のハンドラをクリア（重複防止）
    logger.handlers.clear()

    # フォーマッター
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # コンソールハンドラ
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # ファイルハンドラ
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger, log_file

# ローカルモジュール
try:
    import config
except ImportError:
    print("Error: config.py が見つかりません")
    print("config.py.example をコピーして config.py を作成し、")
    print("BルートID/パスワードを設定してください")
    sys.exit(1)

from api import app, update_power_data, broadcast_power_data, set_mock_mode, check_and_notify, update_connection_info, set_contract_amperage
import api
from web_push_notifier import create_web_push_notifier


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
                power = data.get("instant_power")

                # 接続情報更新（電力値に関わらず更新）
                if hasattr(wisun_client, 'get_connection_info'):
                    update_connection_info(wisun_client.get_connection_info())

                # 電力値が有効な場合のみ更新・配信
                if power is not None:
                    update_power_data(power)
                    await broadcast_power_data()
                    await check_and_notify(power)
                    logging.info(f"Power: {power}W")
                else:
                    logging.warning("Power data is None")

        except Exception as e:
            logging.error(f"Error in power loop: {e}", exc_info=True)

        await asyncio.sleep(config.POLL_INTERVAL)


# 積算電力量ループ（無効化：リクエスト削減のため）
# async def energy_loop():
#     """積算電力量取得ループ"""
#     global wisun_client, running
#
#     # 取得間隔（デフォルト1800秒=30分）
#     interval = getattr(config, "ENERGY_POLL_INTERVAL", 1800)
#
#     # 初回は少し待ってから開始
#     await asyncio.sleep(10)
#
#     while running:
#         try:
#             if wisun_client and hasattr(wisun_client, 'get_energy_data'):
#                 energy = wisun_client.get_energy_data()
#                 update_energy_data(energy)
#
#                 # ログ出力
#                 if energy.get("cumulative_energy") is not None:
#                     logging.info(f"Energy: {energy['cumulative_energy']:.1f}kWh")
#
#         except Exception as e:
#             logging.error(f"Error in energy loop: {e}", exc_info=True)
#
#         await asyncio.sleep(interval)


async def main():
    """メイン関数"""
    global wisun_client, running

    # ロギング初期化
    logger, log_file = setup_logging()

    # 引数パース
    args = parse_args()
    mock_mode = is_mock_mode(args)

    # api.pyにmockモードを設定
    set_mock_mode(mock_mode)

    # 契約アンペア初期化
    contract_amp = getattr(config, "CONTRACT_AMPERAGE", 40)
    set_contract_amperage(contract_amp)

    # Web Push Notifier初期化
    api.web_push_notifier = create_web_push_notifier()

    logging.info("=" * 50)
    logging.info("家庭電力モニター サーバー")
    if mock_mode:
        logging.info("*** MOCK MODE ***")
    if api.web_push_notifier:
        logging.info("Web Push: Enabled")
    else:
        logging.info("Web Push: Disabled")
    logging.info(f"Log file: {log_file}")
    logging.info("=" * 50)

    # クライアント初期化
    if mock_mode:
        logging.info("Starting in mock mode (no Wi-SUN adapter required)...")
    else:
        logging.info(f"Connecting to Wi-SUN adapter ({config.SERIAL_PORT})...")

    wisun_client = create_client(mock_mode)

    # スマートメーターに接続
    if not wisun_client.connect():
        logging.error("Failed to connect to smart meter")
        if not mock_mode:
            logging.error("Please check:")
            logging.error("  1. Wi-SUN adapter is connected")
            logging.error("  2. B-route ID/password is correct")
            logging.error("  3. Smart meter is in range")
            logging.error("Tip: Use --mock flag to run without hardware")
        sys.exit(1)

    logging.info(f"Starting API server on http://{config.API_HOST}:{config.API_PORT}")
    logging.info("Press Ctrl+C to stop")

    # 電力取得タスクを開始
    power_task = asyncio.create_task(power_loop())
    # energy_task = asyncio.create_task(energy_loop())  # 無効化

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
        # energy_task.cancel()  # 無効化

        if wisun_client:
            wisun_client.close()

        print("\nServer stopped")


def signal_handler(sig, frame):
    """シグナルハンドラ"""
    global running
    logging.info("Shutting down...")
    running = False
    sys.exit(0)


if __name__ == "__main__":
    # シグナルハンドラ設定
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # メイン実行
    asyncio.run(main())
