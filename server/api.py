"""
REST API / WebSocket サーバー

電力データをJSON APIとWebSocketで配信
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional
import asyncio
import json

from discord_notifier import DiscordNotifier
from nature_remo_controller import NatureRemoController

# アプリケーション
app = FastAPI(title="House Power Monitor API")

# 静的ファイル（PWA用）
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=static_path), name="static")

# 最新データ
current_data: dict = {
    "instant_power": None,
    "timestamp": None,
}

# 接続情報
connection_info: dict = {
    "channel": None,
    "pan_id": None,
    "mac_addr": None,
    "ipv6_addr": None,
    "rssi": None,
    "rssi_quality": None,
}

# 履歴データ
history: deque = deque(maxlen=100)

# WebSocket接続管理
connected_clients: list[WebSocket] = []

# Mockモードフラグ
_mock_mode: bool = False

# アラート設定
_alert_threshold: int = 4000  # デフォルト閾値 (W)
_alert_enabled: bool = True

# 契約アンペア（使用量バー計算用）
_contract_amperage: int = 40  # デフォルト40A

# Discord Notifier（main.pyで初期化）
discord_notifier: Optional[DiscordNotifier] = None

# Nature Remo（main.pyで初期化）
_nature_remo_enabled: bool = False
nature_remo_controller: Optional[NatureRemoController] = None


def set_mock_mode(mock: bool):
    """mockモードを設定"""
    global _mock_mode
    _mock_mode = mock


def set_alert_threshold(threshold: int):
    """閾値を設定"""
    global _alert_threshold
    _alert_threshold = threshold


def set_alert_enabled(enabled: bool):
    """アラート有効/無効を設定"""
    global _alert_enabled
    _alert_enabled = enabled


def set_contract_amperage(amperage: int):
    """契約アンペアを設定"""
    global _contract_amperage
    _contract_amperage = amperage


def set_nature_remo_enabled(enabled: bool):
    """Nature Remo有効/無効を設定"""
    global _nature_remo_enabled
    _nature_remo_enabled = enabled


async def check_and_notify(power: int):
    """閾値チェックしてDiscord通知"""
    if not _alert_enabled:
        return
    if power < _alert_threshold:
        return

    message = (
        f"現在: **{power:,}W**\n"
        f"閾値: {_alert_threshold:,}W"
    )

    # Discord通知
    if discord_notifier is not None:
        await discord_notifier.send(message, title="⚡ 電力アラート")

    # Nature Remo制御
    if _nature_remo_enabled and nature_remo_controller is not None:
        await nature_remo_controller.execute_actions()


def update_power_data(power: int | None):
    """電力データを更新"""
    current_data["instant_power"] = power
    current_data["timestamp"] = datetime.now().isoformat()

    # 履歴に追加
    history.append(current_data.copy())


async def broadcast_power_data():
    """全WebSocketクライアントにデータを送信"""
    if not connected_clients:
        return

    data = json.dumps(current_data)
    disconnected = []

    for client in connected_clients:
        try:
            await client.send_text(data)
        except Exception:
            disconnected.append(client)

    # 切断されたクライアントを削除
    for client in disconnected:
        connected_clients.remove(client)


# --- REST API ---


@app.get("/api/power")
async def get_power():
    """現在の電力値を取得"""
    return current_data


@app.get("/api/history")
async def get_history(limit: int = 0):
    """
    履歴データを取得

    Args:
        limit: 取得件数（0=全件）
    """
    if limit > 0:
        return list(history)[-limit:]
    return list(history)


@app.get("/api/status")
async def get_status():
    """サーバーステータス"""
    return {
        "status": "running",
        "mock_mode": _mock_mode,
        "history_count": len(history),
        "connected_clients": len(connected_clients),
        "last_update": current_data.get("timestamp"),
    }


@app.get("/api/connection")
async def get_connection():
    """接続情報を取得"""
    return connection_info


def update_connection_info(info: dict):
    """接続情報を更新"""
    global connection_info
    connection_info.update(info)


# --- 設定API ---


class SettingsUpdate(BaseModel):
    threshold: Optional[int] = None
    enabled: Optional[bool] = None


@app.get("/api/settings")
async def get_settings():
    """通知設定を取得"""
    return {
        "alert_threshold": _alert_threshold,
        "alert_enabled": _alert_enabled,
        "contract_amperage": _contract_amperage,
        "discord_configured": discord_notifier is not None,
        "nature_remo_enabled": _nature_remo_enabled,
        "nature_remo_configured": nature_remo_controller is not None,
    }


@app.post("/api/settings")
async def update_settings(settings: SettingsUpdate):
    """通知設定を更新"""
    global _alert_threshold, _alert_enabled

    if settings.threshold is not None:
        _alert_threshold = settings.threshold
    if settings.enabled is not None:
        _alert_enabled = settings.enabled

    return await get_settings()


# --- Discord通知API ---


@app.post("/api/notify/test")
async def test_notify():
    """テスト通知を送信"""
    if discord_notifier is None:
        return {"error": "Discord not configured"}

    success = await discord_notifier.send(
        "テスト通知です。Discord通知が正しく設定されています。",
        title="テスト通知",
        skip_cooldown=True
    )
    return {"success": success}


@app.get("/api/notify/status")
async def get_notify_status():
    """通知のステータスを取得"""
    return {
        "discord_configured": discord_notifier is not None,
        "nature_remo_enabled": _nature_remo_enabled,
        "nature_remo_configured": nature_remo_controller is not None,
    }


# --- Nature Remo API ---


@app.get("/api/nature-remo/appliances")
async def get_nature_remo_appliances():
    """Nature Remo 家電一覧を取得"""
    if nature_remo_controller is None:
        return {"error": "Nature Remo not configured"}

    appliances = await nature_remo_controller.get_appliances()
    return appliances


@app.post("/api/nature-remo/test")
async def test_nature_remo():
    """Nature Remo テスト実行"""
    if nature_remo_controller is None:
        return {"error": "Nature Remo not configured"}

    success = await nature_remo_controller.execute_actions(skip_cooldown=True)
    return {"success": success}


# --- WebSocket ---


@app.websocket("/ws/power")
async def websocket_power(websocket: WebSocket):
    """WebSocket: リアルタイム電力データ配信"""
    await websocket.accept()
    connected_clients.append(websocket)

    try:
        # 接続直後に現在値を送信
        await websocket.send_json(current_data)

        # 切断まで待機
        while True:
            # クライアントからのメッセージを待つ（ping/pongなど）
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # タイムアウトでもOK、接続は維持
                pass
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in connected_clients:
            connected_clients.remove(websocket)


# --- ダッシュボード ---


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Webダッシュボード"""
    template_path = Path(__file__).parent / "templates" / "index.html"
    if template_path.exists():
        return FileResponse(template_path)
    else:
        return HTMLResponse(
            "<h1>Dashboard not found</h1><p>templates/index.html が見つかりません</p>"
        )
