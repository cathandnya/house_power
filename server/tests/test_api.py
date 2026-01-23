"""
API ユニットテスト

REST API と WebSocket のテスト
"""

import pytest
from httpx import AsyncClient, ASGITransport

import sys
from pathlib import Path

# serverディレクトリをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from api import (
    app,
    update_power_data,
    history,
    current_data,
    connected_clients,
    set_mock_mode,
    _mock_mode,
)


@pytest.fixture(autouse=True)
def reset_state():
    """各テスト前に状態をリセット"""
    current_data["instant_power"] = None
    current_data["instant_current_r"] = None
    current_data["instant_current_t"] = None
    current_data["timestamp"] = None
    history.clear()
    connected_clients.clear()
    set_mock_mode(False)
    yield


@pytest.fixture
def transport():
    """ASGITransportを作成"""
    return ASGITransport(app=app)


# --- REST API Tests ---


@pytest.mark.asyncio
async def test_get_power_initial(transport):
    """初期状態では全てNone"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/power")

    assert response.status_code == 200
    data = response.json()
    assert data["instant_power"] is None
    assert data["instant_current_r"] is None
    assert data["instant_current_t"] is None
    assert data["timestamp"] is None


@pytest.mark.asyncio
async def test_get_power_after_update(transport):
    """update_power_data後は値が取得できる"""
    update_power_data(1500, 8.5, 7.2)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/power")

    assert response.status_code == 200
    data = response.json()
    assert data["instant_power"] == 1500
    assert data["instant_current_r"] == 8.5
    assert data["instant_current_t"] == 7.2
    assert data["timestamp"] is not None


@pytest.mark.asyncio
async def test_get_history_empty(transport):
    """履歴が空の場合は空リストを返す"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/history")

    assert response.status_code == 200
    data = response.json()
    assert data == []


@pytest.mark.asyncio
async def test_get_history_with_data(transport):
    """履歴データの取得"""
    # 3件のデータを追加
    update_power_data(1000, 5.0, 5.0)
    update_power_data(1500, 7.5, 7.5)
    update_power_data(2000, 10.0, 10.0)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/history")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    assert data[0]["instant_power"] == 1000
    assert data[1]["instant_power"] == 1500
    assert data[2]["instant_power"] == 2000


@pytest.mark.asyncio
async def test_get_history_with_limit(transport):
    """limitパラメータで件数制限"""
    # 5件のデータを追加
    for i in range(5):
        update_power_data(1000 + i * 100, 5.0, 5.0)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/history?limit=3")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    # 最新の3件が取得される
    assert data[0]["instant_power"] == 1200
    assert data[1]["instant_power"] == 1300
    assert data[2]["instant_power"] == 1400


@pytest.mark.asyncio
async def test_get_status(transport):
    """ステータス情報の確認"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/status")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert data["mock_mode"] is False
    assert data["history_count"] == 0
    assert data["connected_clients"] == 0
    assert data["last_update"] is None


@pytest.mark.asyncio
async def test_get_status_with_mock_mode(transport):
    """mockモードがステータスに反映される"""
    set_mock_mode(True)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/status")

    assert response.status_code == 200
    data = response.json()
    assert data["mock_mode"] is True


@pytest.mark.asyncio
async def test_get_status_with_data(transport):
    """データ追加後のステータス"""
    update_power_data(1500, 8.5, 7.2)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/status")

    assert response.status_code == 200
    data = response.json()
    assert data["history_count"] == 1
    assert data["last_update"] is not None


@pytest.mark.asyncio
async def test_dashboard(transport):
    """ダッシュボードHTMLレスポンス"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


# --- WebSocket Tests ---


@pytest.mark.asyncio
async def test_websocket_connection():
    """WebSocket接続と初期データ受信"""
    from starlette.testclient import TestClient

    # 初期データを設定
    update_power_data(1500, 8.5, 7.2)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/power") as websocket:
            # 接続直後に現在値が送信される
            data = websocket.receive_json()
            assert data["instant_power"] == 1500
            assert data["instant_current_r"] == 8.5
            assert data["instant_current_t"] == 7.2


# --- MockWiSUNClient Tests ---


def test_mock_client_connect():
    """MockWiSUNClientの接続テスト"""
    from mock_client import MockWiSUNClient

    client = MockWiSUNClient()
    assert client.connect() is True


def test_mock_client_get_power_data():
    """MockWiSUNClientのデータ生成テスト"""
    from mock_client import MockWiSUNClient

    client = MockWiSUNClient()
    client.connect()

    data = client.get_power_data()

    # 必要なキーが存在する
    assert "instant_power" in data
    assert "instant_current_r" in data
    assert "instant_current_t" in data

    # 値が妥当な範囲
    assert isinstance(data["instant_power"], int)
    assert data["instant_power"] > 0
    assert isinstance(data["instant_current_r"], float)
    assert isinstance(data["instant_current_t"], float)


def test_mock_client_power_variation():
    """MockWiSUNClientが変動するデータを生成することを確認"""
    from mock_client import MockWiSUNClient

    client = MockWiSUNClient()
    client.connect()

    # 10回データを取得して、全て同じ値ではないことを確認
    powers = [client.get_power_data()["instant_power"] for _ in range(10)]
    unique_powers = set(powers)

    # ランダムノイズがあるので、10回中少なくとも2つは異なる値になるはず
    assert len(unique_powers) > 1
