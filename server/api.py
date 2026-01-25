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

from notifier import LineNotifier

# アプリケーション
app = FastAPI(title="House Power Monitor API")

# 静的ファイル（PWA用）
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=static_path), name="static")

# 最新データ
current_data: dict = {
    "instant_power": None,
    "instant_current_r": None,
    "instant_current_t": None,
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

# 積算電力量データ
energy_data: dict = {
    "cumulative_energy": None,
    "cumulative_energy_reverse": None,
    "fixed_energy": None,
    "energy_unit": None,
    "timestamp": None,
}

# 履歴データ（過去1時間分、3秒間隔 = 1200件）
history: deque = deque(maxlen=1200)

# WebSocket接続管理
connected_clients: list[WebSocket] = []

# Mockモードフラグ
_mock_mode: bool = False

# アラート設定
_alert_threshold: int = 4000  # デフォルト閾値 (W)
_alert_enabled: bool = True

# LINE Notifier（main.pyで初期化）
notifier: Optional[LineNotifier] = None


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


async def check_and_notify(power: int):
    """閾値チェックして通知"""
    if not _alert_enabled:
        return
    if notifier is None:
        return
    if power >= _alert_threshold:
        await notifier.send(
            f"\n⚡ 電力使用量アラート\n"
            f"現在: {power:,}W\n"
            f"閾値: {_alert_threshold:,}W"
        )


def update_power_data(
    power: int | None, current_r: float | None, current_t: float | None
):
    """電力データを更新"""
    current_data["instant_power"] = power
    current_data["instant_current_r"] = current_r
    current_data["instant_current_t"] = current_t
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


@app.get("/api/energy")
async def get_energy():
    """積算電力量を取得"""
    return energy_data


def update_energy_data(data: dict):
    """積算電力量を更新"""
    global energy_data
    energy_data.update(data)
    energy_data["timestamp"] = datetime.now().isoformat()


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
        "line_notify_configured": notifier is not None and bool(notifier.token),
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
