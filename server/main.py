#!/usr/bin/env python3
"""
家庭電力モニター サーバー

Wi-SUN Bルートでスマートメーターから電力データを取得し、
REST API / WebSocket で配信する
"""

import argparse
import asyncio
import logging
import logging.handlers
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

    # ログファイル名（追記モード）
    log_file = log_dir / "server.log"

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

    # ファイルハンドラ（ローテーション: 1MB x 5世代）
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
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

from api import app, update_power_data, broadcast_power_data, set_mock_mode, check_and_notify, update_connection_info, set_contract_amperage, set_nature_remo_enabled
import api
from discord_notifier import create_discord_notifier
from nature_remo_controller import create_nature_remo_controller


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

    # Discord Notifier初期化
    cooldown = getattr(config, "NOTIFY_COOLDOWN_MINUTES", 5)
    api.discord_notifier = create_discord_notifier(cooldown_minutes=cooldown)

    # Nature Remo初期化
    nature_remo_enabled = getattr(config, "NATURE_REMO_ENABLED", False)
    set_nature_remo_enabled(nature_remo_enabled)
    api.nature_remo_controller = create_nature_remo_controller(
        access_token=getattr(config, "NATURE_REMO_ACCESS_TOKEN", ""),
        enabled=nature_remo_enabled,
        cooldown_minutes=getattr(config, "NATURE_REMO_COOLDOWN_MINUTES", 5),
        actions=getattr(config, "NATURE_REMO_ACTIONS", []),
    )

    logging.info("=" * 50)
    logging.info("家庭電力モニター サーバー")
    if mock_mode:
        logging.info("*** MOCK MODE ***")
    if api.discord_notifier:
        logging.info("Discord: Enabled")
    else:
        logging.info("Discord: Disabled (no webhook URL)")
    if nature_remo_enabled and api.nature_remo_controller:
        logging.info("Nature Remo: Enabled")
    elif nature_remo_enabled:
        logging.info("Nature Remo: Disabled (no access token)")
    else:
        logging.info("Nature Remo: Disabled")
    logging.info(f"Log file: {log_file}")
    logging.info("=" * 50)

    # クライアント初期化
    if mock_mode:
        logging.info("Starting in mock mode (no Wi-SUN adapter required)...")
    else:
        logging.info(f"Connecting to Wi-SUN adapter ({config.SERIAL_PORT})...")

    wisun_client = create_client(mock_mode)

    # スマートメーターに接続（リトライあり）
    # スキャンはアダプタ側の処理でメーターに負荷なし → 短間隔で多数リトライ
    max_retries = 20
    retry_delay = 10  # 秒

    for attempt in range(max_retries):
        if wisun_client.connect():
            break

        logging.error(f"Failed to connect to smart meter (attempt {attempt + 1}/{max_retries})")

        if attempt < max_retries - 1:
            logging.info(f"Retrying in {retry_delay} seconds...")
            await asyncio.sleep(retry_delay)
            # クライアント再作成
            wisun_client.close()
            wisun_client = create_client(mock_mode)
            if not mock_mode:
                logging.info(f"Connecting to Wi-SUN adapter ({config.SERIAL_PORT})...")
    else:
        # 全リトライ失敗
        logging.error("All connection attempts failed")
        if not mock_mode:
            logging.error("Please check:")
            logging.error("  1. Wi-SUN adapter is connected")
            logging.error("  2. B-route ID/password is correct")
            logging.error("  3. Smart meter is in range")
            logging.error("Tip: Use --mock flag to run without hardware")
        # 急速な再起動ループを防ぐため待機
        logging.info("Waiting 10 minutes before exit to prevent rapid restart loop...")
        await asyncio.sleep(600)
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
