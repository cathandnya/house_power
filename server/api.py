"""
REST API / WebSocket サーバー

電力データをJSON APIとWebSocketで配信
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from collections import deque
from datetime import datetime
from pathlib import Path
import asyncio
import json

# アプリケーション
app = FastAPI(title="House Power Monitor API")

# 最新データ
current_data: dict = {
    "instant_power": None,
    "instant_current_r": None,
    "instant_current_t": None,
    "timestamp": None
}

# 履歴データ（過去1時間分、3秒間隔 = 1200件）
history: deque = deque(maxlen=1200)

# WebSocket接続管理
connected_clients: list[WebSocket] = []

# Mockモードフラグ
_mock_mode: bool = False


def set_mock_mode(mock: bool):
    """mockモードを設定"""
    global _mock_mode
    _mock_mode = mock


def update_power_data(power: int | None, current_r: float | None, current_t: float | None):
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
        return HTMLResponse("<h1>Dashboard not found</h1><p>templates/index.html が見つかりません</p>")
