"""
Nature Remo 連携のユニットテスト
"""

import sys
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

# serverディレクトリをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

import api
from api import app, set_nature_remo_enabled
import nature_remo_controller as nrc
from nature_remo_controller import NatureRemoController


class FakeResponse:
    def __init__(self, status=200, json_data=None, text_data=""):
        self.status = status
        self._json_data = json_data or []
        self._text_data = text_data

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(self, post_status=200, get_status=200, json_data=None):
        self.post_status = post_status
        self.get_status = get_status
        self.json_data = json_data or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        return FakeResponse(status=self.post_status)

    def get(self, *args, **kwargs):
        return FakeResponse(status=self.get_status, json_data=self.json_data)


class FakeTimeout:
    def __init__(self, total=10):
        self.total = total


@pytest.fixture
def transport():
    return ASGITransport(app=app)


@pytest.mark.asyncio
async def test_execute_actions_success(monkeypatch):
    monkeypatch.setattr(nrc.aiohttp, "ClientSession", lambda *args, **kwargs: FakeSession())
    monkeypatch.setattr(nrc.aiohttp, "ClientTimeout", FakeTimeout)

    controller = NatureRemoController(
        access_token="token",
        cooldown_minutes=5,
        actions=[
            {
                "appliance_id": "appliance-1",
                "endpoint": "light",
                "params": {"button": "off"},
            }
        ],
    )

    ok = await controller.execute_actions(skip_cooldown=True)
    assert ok is True


@pytest.mark.asyncio
async def test_execute_actions_cooldown(monkeypatch):
    monkeypatch.setattr(nrc.aiohttp, "ClientSession", lambda *args, **kwargs: FakeSession())
    monkeypatch.setattr(nrc.aiohttp, "ClientTimeout", FakeTimeout)
    monkeypatch.setattr(nrc.time, "time", lambda: 1000)

    controller = NatureRemoController(
        access_token="token",
        cooldown_minutes=5,
        actions=[
            {
                "appliance_id": "appliance-1",
                "endpoint": "light",
                "params": {"button": "off"},
            }
        ],
    )

    first = await controller.execute_actions(skip_cooldown=False)
    second = await controller.execute_actions(skip_cooldown=False)
    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_get_appliances(monkeypatch):
    monkeypatch.setattr(
        nrc.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: FakeSession(json_data=[{"id": "appliance-1"}]),
    )
    monkeypatch.setattr(nrc.aiohttp, "ClientTimeout", FakeTimeout)

    controller = NatureRemoController(access_token="token")
    data = await controller.get_appliances()
    assert data == [{"id": "appliance-1"}]


@pytest.mark.asyncio
async def test_api_nature_remo_not_configured(transport):
    api.nature_remo_controller = None
    set_nature_remo_enabled(False)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/nature-remo/appliances")

    assert response.status_code == 200
    assert response.json()["error"] == "Nature Remo not configured"


@pytest.mark.asyncio
async def test_api_nature_remo_test_execute(transport):
    class DummyController:
        async def get_appliances(self):
            return [{"id": "appliance-1"}]

        async def execute_actions(self, skip_cooldown=False):
            return True

    api.nature_remo_controller = DummyController()
    set_nature_remo_enabled(True)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/nature-remo/test")

    assert response.status_code == 200
    assert response.json()["success"] is True
