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

from web_push_notifier import WebPushNotifier, get_or_create_vapid_keys, create_web_push_notifier

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

# Web Push Notifier（main.pyで初期化）
web_push_notifier: Optional[WebPushNotifier] = None


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


async def check_and_notify(power: int):
    """閾値チェックしてWebPush通知"""
    if not _alert_enabled:
        return
    if power < _alert_threshold:
        return

    message = (
        f"電力使用量アラート\n"
        f"現在: {power:,}W\n"
        f"閾値: {_alert_threshold:,}W"
    )

    # WebPush通知
    if web_push_notifier is not None:
        await web_push_notifier.send(message, title="⚡ 電力アラート")


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
        "web_push_configured": web_push_notifier is not None,
        "web_push_subscription_count": web_push_notifier.get_subscription_count() if web_push_notifier else 0,
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


# --- Web Push API ---


class PushSubscription(BaseModel):
    endpoint: str
    keys: dict


@app.get("/api/push/vapid-public-key")
async def get_vapid_public_key():
    """VAPID公開鍵を取得"""
    try:
        public_key, _ = get_or_create_vapid_keys()
        return {"publicKey": public_key}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/push/subscribe")
async def subscribe_push(subscription: PushSubscription):
    """プッシュ通知を購読"""
    if web_push_notifier is None:
        return {"error": "Web Push not configured"}

    success = web_push_notifier.add_subscription(subscription.model_dump())
    return {
        "success": success,
        "subscription_count": web_push_notifier.get_subscription_count(),
    }


@app.post("/api/push/unsubscribe")
async def unsubscribe_push(subscription: PushSubscription):
    """プッシュ通知の購読を解除"""
    if web_push_notifier is None:
        return {"error": "Web Push not configured"}

    success = web_push_notifier.remove_subscription(subscription.endpoint)
    return {
        "success": success,
        "subscription_count": web_push_notifier.get_subscription_count(),
    }


@app.post("/api/push/test")
async def test_push():
    """テスト通知を送信"""
    if web_push_notifier is None:
        return {"error": "Web Push not configured"}

    count = await web_push_notifier.send(
        "テスト通知です。プッシュ通知が正しく設定されています。",
        title="テスト通知"
    )
    return {"success": count > 0, "sent_count": count}


@app.get("/api/push/status")
async def get_push_status():
    """プッシュ通知のステータスを取得"""
    if web_push_notifier is None:
        return {
            "configured": False,
            "subscription_count": 0,
        }

    return {
        "configured": True,
        "subscription_count": web_push_notifier.get_subscription_count(),
    }


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
