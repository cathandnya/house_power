"""
LINE Notify 通知モジュール

電力閾値超過時にLINEで通知を送信
"""

import httpx
from datetime import datetime, timedelta
from typing import Optional


class LineNotifier:
    """LINE Notify クライアント"""

    def __init__(self, token: str, cooldown_minutes: int = 5):
        """
        Args:
            token: LINE Notifyのアクセストークン
            cooldown_minutes: 通知のクールダウン時間（分）
        """
        self.token = token
        self.cooldown = timedelta(minutes=cooldown_minutes)
        self.last_notified: Optional[datetime] = None

    def can_notify(self) -> bool:
        """クールダウン中でなければTrue"""
        if not self.last_notified:
            return True
        return datetime.now() - self.last_notified > self.cooldown

    async def send(self, message: str) -> bool:
        """
        LINE Notifyで通知を送信

        Args:
            message: 送信するメッセージ

        Returns:
            送信成功ならTrue
        """
        if not self.token:
            return False

        if not self.can_notify():
            return False

        url = "https://notify-api.line.me/api/notify"
        headers = {"Authorization": f"Bearer {self.token}"}
        data = {"message": message}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, data=data)
                if response.status_code == 200:
                    self.last_notified = datetime.now()
                    print(f"LINE Notify: Sent notification")
                    return True
                else:
                    print(f"LINE Notify: Failed ({response.status_code})")
                    return False
        except Exception as e:
            print(f"LINE Notify: Error - {e}")
            return False

    def reset_cooldown(self):
        """クールダウンをリセット（テスト用）"""
        self.last_notified = None
