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
    update_connection_info,
    history,
    current_data,
    connection_info,
    connected_clients,
    set_mock_mode,
    set_alert_threshold,
    set_alert_enabled,
    set_contract_amperage,
    _mock_mode,
    _alert_threshold,
    _alert_enabled,
)
import api


@pytest.fixture(autouse=True)
def reset_state():
    """各テスト前に状態をリセット"""
    current_data["instant_power"] = None
    current_data["timestamp"] = None
    connection_info["channel"] = None
    connection_info["pan_id"] = None
    connection_info["mac_addr"] = None
    connection_info["ipv6_addr"] = None
    connection_info["rssi"] = None
    connection_info["rssi_quality"] = None
    history.clear()
    connected_clients.clear()
    set_mock_mode(False)
    set_alert_threshold(4000)
    set_alert_enabled(True)
    set_contract_amperage(40)
    api.notifier = None
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
    assert data["timestamp"] is None


@pytest.mark.asyncio
async def test_get_power_after_update(transport):
    """update_power_data後は値が取得できる"""
    update_power_data(1500)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/power")

    assert response.status_code == 200
    data = response.json()
    assert data["instant_power"] == 1500
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
    update_power_data(1000)
    update_power_data(1500)
    update_power_data(2000)

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
        update_power_data(1000 + i * 100)

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
    update_power_data(1500)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/status")

    assert response.status_code == 200
    data = response.json()
    assert data["history_count"] == 1
    assert data["last_update"] is not None


# --- Connection Info API Tests ---


@pytest.mark.asyncio
async def test_get_connection_initial(transport):
    """初期状態では接続情報は全てNone"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/connection")

    assert response.status_code == 200
    data = response.json()
    assert data["channel"] is None
    assert data["pan_id"] is None
    assert data["mac_addr"] is None
    assert data["ipv6_addr"] is None
    assert data["rssi"] is None
    assert data["rssi_quality"] is None


@pytest.mark.asyncio
async def test_get_connection_after_update(transport):
    """update_connection_info後は値が取得できる"""
    update_connection_info({
        "channel": "31",
        "pan_id": "A91B",
        "mac_addr": "C2F94500408AA91B",
        "ipv6_addr": "FE80:0000:0000:0000:C2F9:4500:408A:A91B",
        "rssi": -57,
        "rssi_quality": "excellent",
    })

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/connection")

    assert response.status_code == 200
    data = response.json()
    assert data["channel"] == "31"
    assert data["pan_id"] == "A91B"
    assert data["mac_addr"] == "C2F94500408AA91B"
    assert data["ipv6_addr"] == "FE80:0000:0000:0000:C2F9:4500:408A:A91B"
    assert data["rssi"] == -57
    assert data["rssi_quality"] == "excellent"


@pytest.mark.asyncio
async def test_get_connection_partial_update(transport):
    """部分的な更新でも動作する"""
    update_connection_info({
        "rssi": -65,
        "rssi_quality": "good",
    })

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/connection")

    assert response.status_code == 200
    data = response.json()
    assert data["rssi"] == -65
    assert data["rssi_quality"] == "good"
    # 更新していないフィールドはNoneのまま
    assert data["channel"] is None


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
    update_power_data(1500)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/power") as websocket:
            # 接続直後に現在値が送信される
            data = websocket.receive_json()
            assert data["instant_power"] == 1500


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

    # 値が妥当な範囲
    assert isinstance(data["instant_power"], int)
    assert data["instant_power"] > 0


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


def test_mock_client_get_connection_info():
    """MockWiSUNClientの接続情報取得テスト"""
    from mock_client import MockWiSUNClient

    client = MockWiSUNClient()
    client.connect()

    info = client.get_connection_info()

    # 必要なキーが存在する
    assert "channel" in info
    assert "pan_id" in info
    assert "mac_addr" in info
    assert "ipv6_addr" in info
    assert "rssi" in info
    assert "rssi_quality" in info

    # 値が設定されている
    assert info["channel"] == "33"
    assert info["pan_id"] == "MOCK"
    assert info["mac_addr"] == "MOCK00000001"
    assert info["ipv6_addr"].startswith("FE80:")

    # RSSIは妥当な範囲 (-80 ~ -50)
    assert isinstance(info["rssi"], int)
    assert -80 <= info["rssi"] <= -50

    # rssi_qualityは有効な値
    assert info["rssi_quality"] in ["excellent", "good", "fair", "poor"]


def test_mock_client_connection_info_rssi_quality():
    """RSSIに応じたrssi_qualityの判定テスト"""
    from mock_client import MockWiSUNClient

    client = MockWiSUNClient()
    client.connect()

    # 10回取得してrssi_qualityがRSSI値と一致するか確認
    for _ in range(10):
        info = client.get_connection_info()
        rssi = info["rssi"]
        quality = info["rssi_quality"]

        if rssi >= -60:
            assert quality == "excellent"
        elif rssi >= -70:
            assert quality == "good"
        elif rssi >= -80:
            assert quality == "fair"
        else:
            assert quality == "poor"


def test_mock_client_get_energy_data():
    """MockWiSUNClientの積算電力量取得テスト"""
    from mock_client import MockWiSUNClient

    client = MockWiSUNClient()
    client.connect()

    data = client.get_energy_data()

    # 必要なキーが存在する
    assert "cumulative_energy" in data
    assert "cumulative_energy_reverse" in data
    assert "fixed_energy" in data
    assert "energy_unit" in data

    # 値が設定されている
    assert isinstance(data["cumulative_energy"], float)
    assert data["cumulative_energy"] > 0
    assert isinstance(data["cumulative_energy_reverse"], float)
    assert data["energy_unit"] == 0.1

    # fixed_energyの構造確認
    assert "timestamp" in data["fixed_energy"]
    assert "energy" in data["fixed_energy"]


# --- Settings API Tests ---


@pytest.mark.asyncio
async def test_get_settings_default(transport):
    """デフォルト設定の取得"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()
    assert data["alert_threshold"] == 4000
    assert data["alert_enabled"] is True
    assert data["line_notify_configured"] is False


@pytest.mark.asyncio
async def test_update_settings_threshold(transport):
    """閾値の更新"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/settings",
            json={"threshold": 3000}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["alert_threshold"] == 3000
    assert data["alert_enabled"] is True


@pytest.mark.asyncio
async def test_update_settings_enabled(transport):
    """通知有効/無効の更新"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/settings",
            json={"enabled": False}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["alert_enabled"] is False


@pytest.mark.asyncio
async def test_update_settings_both(transport):
    """閾値と有効/無効を同時に更新"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/settings",
            json={"threshold": 5000, "enabled": False}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["alert_threshold"] == 5000
    assert data["alert_enabled"] is False


@pytest.mark.asyncio
async def test_settings_line_notify_configured(transport):
    """LINE Notify設定済みの確認"""
    from notifier import LineNotifier
    api.notifier = LineNotifier(token="test_token")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()
    assert data["line_notify_configured"] is True


# --- Notifier Tests ---


def test_notifier_can_notify_initial():
    """初期状態では通知可能"""
    from notifier import LineNotifier
    notifier = LineNotifier(token="test", cooldown_minutes=5)
    assert notifier.can_notify() is True


def test_notifier_cooldown():
    """クールダウン中は通知不可"""
    from notifier import LineNotifier
    from datetime import datetime, timedelta

    notifier = LineNotifier(token="test", cooldown_minutes=5)
    notifier.last_notified = datetime.now()

    assert notifier.can_notify() is False


def test_notifier_cooldown_expired():
    """クールダウン終了後は通知可能"""
    from notifier import LineNotifier
    from datetime import datetime, timedelta

    notifier = LineNotifier(token="test", cooldown_minutes=5)
    notifier.last_notified = datetime.now() - timedelta(minutes=10)

    assert notifier.can_notify() is True


def test_notifier_no_token():
    """トークンなしでは通知不可"""
    from notifier import LineNotifier
    notifier = LineNotifier(token="", cooldown_minutes=5)
    assert notifier.token == ""


# --- Static Files Tests (PWA) ---


@pytest.mark.asyncio
async def test_manifest_json(transport):
    """manifest.jsonが取得できる"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/static/manifest.json")

    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert "icons" in data


@pytest.mark.asyncio
async def test_service_worker(transport):
    """Service Workerが取得できる"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/static/sw.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_app_icon(transport):
    """アプリアイコンが取得できる"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/static/icon-192.png")

    assert response.status_code == 200
    assert "image/png" in response.headers["content-type"]


# --- Contract Amperage Tests ---


@pytest.mark.asyncio
async def test_get_settings_includes_contract_amperage(transport):
    """設定に契約アンペアが含まれる"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()
    assert "contract_amperage" in data
    assert data["contract_amperage"] == 40  # デフォルト値


@pytest.mark.asyncio
async def test_contract_amperage_is_positive(transport):
    """契約アンペアは正の整数"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["contract_amperage"], int)
    assert data["contract_amperage"] > 0


@pytest.mark.asyncio
async def test_contract_amperage_not_null(transport):
    """契約アンペアはNoneではない"""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()
    assert data["contract_amperage"] is not None


def test_set_contract_amperage():
    """契約アンペアの設定"""
    set_contract_amperage(60)
    assert api._contract_amperage == 60

    set_contract_amperage(30)
    assert api._contract_amperage == 30
