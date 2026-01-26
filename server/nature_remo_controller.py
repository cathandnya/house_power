"""
Nature Remo Cloud API 制御
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import aiohttp


class NatureRemoController:
    """Nature Remo Cloud API を使って家電を制御するクライアント"""

    BASE_URL = "https://api.nature.global/1"

    def __init__(
        self,
        access_token: str,
        cooldown_minutes: int = 5,
        actions: Optional[list] = None,
    ):
        self.access_token = access_token
        self.cooldown_seconds = cooldown_minutes * 60
        self.actions = actions or []
        self._last_action_time: float = 0

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _build_url(self, appliance_id: str, endpoint: str, signal_id: Optional[str] = None) -> Optional[str]:
        if endpoint.startswith("http"):
            return endpoint
        if endpoint.startswith("/"):
            return f"{self.BASE_URL}{endpoint}"
        if endpoint in ("aircon_settings", "light", "tv"):
            return f"{self.BASE_URL}/appliances/{appliance_id}/{endpoint}"
        if endpoint == "signal" and signal_id:
            return f"{self.BASE_URL}/signals/{signal_id}/send"
        return None

    async def execute_actions(self, skip_cooldown: bool = False) -> bool:
        """
        登録されたアクションを順番に実行

        Args:
            skip_cooldown: クールダウンをスキップするか（テスト用）

        Returns:
            すべて成功時 True
        """
        if not self.access_token:
            logging.info("Nature Remo access token not configured")
            return False
        if not self.actions:
            logging.info("Nature Remo actions not configured")
            return False

        now = time.time()
        if not skip_cooldown and now - self._last_action_time < self.cooldown_seconds:
            remaining = int(self.cooldown_seconds - (now - self._last_action_time))
            logging.debug(f"Nature Remo cooldown: {remaining}s remaining")
            return False

        if not skip_cooldown:
            self._last_action_time = now

        all_success = True
        async with aiohttp.ClientSession() as session:
            for action in self.actions:
                ok = await self._execute_action(session, action)
                if not ok:
                    all_success = False

        return all_success

    async def _execute_action(self, session: aiohttp.ClientSession, action: dict) -> bool:
        appliance_id = action.get("appliance_id")
        endpoint = action.get("endpoint")
        signal_id = action.get("signal_id")
        params = action.get("params", {})

        if not appliance_id or not endpoint:
            logging.warning("Nature Remo action missing appliance_id/endpoint")
            return False

        url = self._build_url(appliance_id, endpoint, signal_id)
        if not url:
            logging.warning(f"Nature Remo unsupported endpoint: {endpoint}")
            return False

        try:
            async with session.post(
                url,
                headers=self._headers(),
                data=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status in (200, 201, 204):
                    logging.info(
                        f"Nature Remo action executed: {appliance_id} {endpoint}"
                    )
                    return True

                body = await response.text()
                logging.warning(
                    "Nature Remo action failed: %s %s status=%s body=%s",
                    appliance_id,
                    endpoint,
                    response.status,
                    body,
                )
                return False
        except Exception as e:
            logging.error(f"Nature Remo action error: {e}")
            return False

    async def get_appliances(self) -> list:
        """家電一覧を取得"""
        if not self.access_token:
            return []

        url = f"{self.BASE_URL}/appliances"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status != 200:
                        logging.warning(
                            f"Nature Remo get_appliances failed: {response.status}"
                        )
                        return []
                    return await response.json()
        except Exception as e:
            logging.error(f"Nature Remo get_appliances error: {e}")
            return []


def create_nature_remo_controller(
    access_token: Optional[str] = None,
    enabled: Optional[bool] = None,
    cooldown_minutes: int = 5,
    actions: Optional[list] = None,
) -> Optional[NatureRemoController]:
    """
    NatureRemoControllerインスタンスを作成

    Args:
        access_token: Nature Remo Access Token（Noneの場合はconfigから取得）
        enabled: 有効/無効（Noneの場合はconfigから取得）
        cooldown_minutes: クールダウン（分）
        actions: 実行アクション

    Returns:
        NatureRemoController インスタンス、または作成失敗時 None
    """
    if access_token is None or enabled is None or actions is None:
        try:
            import config

            if access_token is None:
                access_token = getattr(config, "NATURE_REMO_ACCESS_TOKEN", "")
            if enabled is None:
                enabled = getattr(config, "NATURE_REMO_ENABLED", False)
            if cooldown_minutes is None:
                cooldown_minutes = getattr(config, "NATURE_REMO_COOLDOWN_MINUTES", 5)
            if actions is None:
                actions = getattr(config, "NATURE_REMO_ACTIONS", [])
        except ImportError:
            return None

    if not enabled:
        logging.info("Nature Remo is disabled")
        return None
    if not access_token:
        logging.info("Nature Remo access token not configured")
        return None

    return NatureRemoController(
        access_token=access_token,
        cooldown_minutes=cooldown_minutes,
        actions=actions or [],
    )
