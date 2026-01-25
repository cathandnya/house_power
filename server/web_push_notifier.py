"""
Web Push通知クライアント

PWAプッシュ通知を送信するためのモジュール
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from pywebpush import webpush, WebPushException

import config


class WebPushNotifier:
    """Web Push通知を送信するクライアント"""

    def __init__(
        self,
        vapid_public_key: str,
        vapid_private_key: str,
        vapid_claims_email: str = "mailto:admin@example.com",
        subscriptions_file: Optional[str] = None,
        cooldown_minutes: int = 5,
    ):
        """
        Args:
            vapid_public_key: VAPID公開鍵（Base64 URL-safe）
            vapid_private_key: VAPID秘密鍵（Base64 URL-safe）
            vapid_claims_email: VAPID claims用のメールアドレス
            subscriptions_file: 購読情報保存ファイル（デフォルト: push_subscriptions.json）
            cooldown_minutes: 通知間隔（分）
        """
        self.vapid_public_key = vapid_public_key
        self.vapid_private_key = vapid_private_key
        self.vapid_claims = {"sub": vapid_claims_email}
        self.subscriptions_file = Path(
            subscriptions_file or "push_subscriptions.json"
        )
        self.cooldown_seconds = cooldown_minutes * 60
        self._last_notification_time: float = 0
        self._subscriptions: list[dict] = []
        self._load_subscriptions()

    def _load_subscriptions(self):
        """購読情報をファイルから読み込む"""
        if self.subscriptions_file.exists():
            try:
                with open(self.subscriptions_file, "r") as f:
                    self._subscriptions = json.load(f)
                logging.info(f"Loaded {len(self._subscriptions)} push subscriptions")
            except Exception as e:
                logging.error(f"Failed to load subscriptions: {e}")
                self._subscriptions = []
        else:
            self._subscriptions = []

    def _save_subscriptions(self):
        """購読情報をファイルに保存"""
        try:
            with open(self.subscriptions_file, "w") as f:
                json.dump(self._subscriptions, f, indent=2)
        except Exception as e:
            logging.error(f"Failed to save subscriptions: {e}")

    def add_subscription(self, subscription: dict) -> bool:
        """
        購読を追加

        Args:
            subscription: PushSubscription オブジェクト（endpoint, keys含む）

        Returns:
            追加成功時True
        """
        endpoint = subscription.get("endpoint")
        if not endpoint:
            return False

        # 既存の購読を更新または追加
        for i, sub in enumerate(self._subscriptions):
            if sub.get("endpoint") == endpoint:
                self._subscriptions[i] = subscription
                self._save_subscriptions()
                logging.info(f"Updated push subscription: {endpoint[:50]}...")
                return True

        self._subscriptions.append(subscription)
        self._save_subscriptions()
        logging.info(f"Added push subscription: {endpoint[:50]}...")
        return True

    def remove_subscription(self, endpoint: str) -> bool:
        """
        購読を削除

        Args:
            endpoint: 削除する購読のエンドポイントURL

        Returns:
            削除成功時True
        """
        original_count = len(self._subscriptions)
        self._subscriptions = [
            sub for sub in self._subscriptions if sub.get("endpoint") != endpoint
        ]

        if len(self._subscriptions) < original_count:
            self._save_subscriptions()
            logging.info(f"Removed push subscription: {endpoint[:50]}...")
            return True
        return False

    def get_subscription_count(self) -> int:
        """購読数を取得"""
        return len(self._subscriptions)

    async def send(self, message: str, title: str = "電力モニター") -> int:
        """
        全購読者に通知を送信

        Args:
            message: 通知本文
            title: 通知タイトル

        Returns:
            送信成功数
        """
        # クールダウンチェック
        now = time.time()
        if now - self._last_notification_time < self.cooldown_seconds:
            remaining = int(
                self.cooldown_seconds - (now - self._last_notification_time)
            )
            logging.debug(f"WebPush cooldown: {remaining}s remaining")
            return 0

        if not self._subscriptions:
            logging.debug("No push subscriptions")
            return 0

        self._last_notification_time = now

        payload = json.dumps({
            "title": title,
            "body": message,
            "icon": "/static/icons/icon-192.png",
            "badge": "/static/icons/icon-72.png",
            "tag": "power-alert",
            "requireInteraction": True,
        })

        success_count = 0
        failed_endpoints = []

        for subscription in self._subscriptions:
            try:
                webpush(
                    subscription_info=subscription,
                    data=payload,
                    vapid_private_key=self.vapid_private_key,
                    vapid_claims=self.vapid_claims,
                )
                success_count += 1
                logging.debug(f"Push sent to {subscription.get('endpoint', '')[:50]}...")
            except WebPushException as e:
                logging.warning(f"WebPush failed: {e}")
                # 410 Gone または 404 の場合は購読を削除
                if e.response and e.response.status_code in (404, 410):
                    failed_endpoints.append(subscription.get("endpoint"))
            except Exception as e:
                logging.error(f"WebPush error: {e}")

        # 無効な購読を削除
        for endpoint in failed_endpoints:
            self.remove_subscription(endpoint)

        logging.info(f"WebPush sent to {success_count}/{len(self._subscriptions)} subscribers")
        return success_count


def get_or_create_vapid_keys() -> tuple[str, str]:
    """
    VAPID鍵を取得または生成

    Returns:
        (public_key, private_key) のタプル
    """
    # config.pyに設定がある場合はそれを使用
    if config.VAPID_PUBLIC_KEY and config.VAPID_PRIVATE_KEY:
        return config.VAPID_PUBLIC_KEY, config.VAPID_PRIVATE_KEY

    # vapid_keys.jsonから読み込み
    keys_file = Path(__file__).parent / "vapid_keys.json"
    if keys_file.exists():
        try:
            with open(keys_file, "r") as f:
                keys = json.load(f)
                return keys["public_key"], keys["private_key"]
        except Exception as e:
            logging.error(f"Failed to load VAPID keys: {e}")

    # 新規生成（py_vapidを使用）
    from py_vapid import Vapid

    vapid = Vapid()
    vapid.generate_keys()

    # py_vapidの形式で鍵を取得
    import base64
    from cryptography.hazmat.primitives import serialization

    # 公開鍵: uncompressed point形式 -> Base64 URL-safe
    public_key_bytes = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public_key_b64 = base64.urlsafe_b64encode(public_key_bytes).decode("utf-8").rstrip("=")

    # 秘密鍵: PEM形式で保存（pywebpushはPEM形式を受け付ける）
    private_key_pem = vapid.private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    # ファイルに保存
    try:
        with open(keys_file, "w") as f:
            json.dump({
                "public_key": public_key_b64,
                "private_key": private_key_pem,
            }, f, indent=2)
        logging.info(f"Generated new VAPID keys and saved to {keys_file}")
    except Exception as e:
        logging.error(f"Failed to save VAPID keys: {e}")

    return public_key_b64, private_key_pem


def create_web_push_notifier() -> Optional[WebPushNotifier]:
    """
    WebPushNotifierインスタンスを作成

    Returns:
        WebPushNotifier インスタンス、または作成失敗時None
    """
    try:
        public_key, private_key = get_or_create_vapid_keys()
        return WebPushNotifier(
            vapid_public_key=public_key,
            vapid_private_key=private_key,
            vapid_claims_email=config.VAPID_CLAIMS_EMAIL,
            cooldown_minutes=config.NOTIFY_COOLDOWN_MINUTES,
        )
    except Exception as e:
        logging.error(f"Failed to create WebPushNotifier: {e}")
        return None
