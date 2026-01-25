"""
Discord Webhook通知クライアント

Discord Webhookを使用して通知を送信するモジュール
"""

import logging
import time
from typing import Optional

import aiohttp


class DiscordNotifier:
    """Discord Webhookで通知を送信するクライアント"""

    def __init__(
        self,
        webhook_url: str,
        cooldown_minutes: int = 5,
    ):
        """
        Args:
            webhook_url: Discord Webhook URL
            cooldown_minutes: 通知間隔（分）
        """
        self.webhook_url = webhook_url
        self.cooldown_seconds = cooldown_minutes * 60
        self._last_notification_time: float = 0

    async def send(
        self,
        message: str,
        title: str = "電力モニター",
        skip_cooldown: bool = False,
    ) -> bool:
        """
        Discord Webhookで通知を送信

        Args:
            message: 通知本文
            title: 通知タイトル
            skip_cooldown: クールダウンをスキップするか（テスト通知用）

        Returns:
            送信成功時True
        """
        # クールダウンチェック
        now = time.time()
        if not skip_cooldown and now - self._last_notification_time < self.cooldown_seconds:
            remaining = int(
                self.cooldown_seconds - (now - self._last_notification_time)
            )
            logging.debug(f"Discord cooldown: {remaining}s remaining")
            return False

        if not skip_cooldown:
            self._last_notification_time = now

        # Discord Embed形式で送信
        payload = {
            "embeds": [
                {
                    "title": title,
                    "description": message,
                    "color": 0xFF6600,  # オレンジ色
                }
            ]
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status == 204:
                        logging.info("Discord notification sent")
                        return True
                    else:
                        logging.warning(
                            f"Discord webhook failed: {response.status}"
                        )
                        return False
        except Exception as e:
            logging.error(f"Discord webhook error: {e}")
            return False


def create_discord_notifier(
    webhook_url: Optional[str] = None,
    cooldown_minutes: int = 5,
) -> Optional[DiscordNotifier]:
    """
    DiscordNotifierインスタンスを作成

    Args:
        webhook_url: Discord Webhook URL（Noneの場合はconfigから取得）
        cooldown_minutes: 通知間隔（分）

    Returns:
        DiscordNotifier インスタンス、または作成失敗時None
    """
    if webhook_url is None:
        try:
            import config
            webhook_url = getattr(config, "DISCORD_WEBHOOK_URL", "")
        except ImportError:
            return None

    if not webhook_url:
        logging.info("Discord webhook URL not configured")
        return None

    return DiscordNotifier(
        webhook_url=webhook_url,
        cooldown_minutes=cooldown_minutes,
    )
