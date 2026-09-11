"""USB の抜き差しでシリアルデバイスが入れ替わったときに復旧できるかのテスト。

実際に起きた障害:
  by-id のリンク先が ttyUSB0 → ttyUSB1 に変わったあとも、プロセスは起動時に
  開いた ttyUSB0 の fd を掴んだままで、以後 42 分間 Errno 5 を出し続けた。
  PANA セッションの張り直し (SKTERM/SKRESET) は既存ハンドルへの書き込みなので
  復旧しない。デバイスを開き直す必要がある。
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from wisun_client import WiSUNClient  # noqa: E402


def make_client():
    return WiSUNClient(port="/dev/serial/by-id/dummy", broute_id="X", broute_pwd="Y",
                       cache_file="/tmp/wisun_cache_test.json")


class DeadSerial:
    """デバイスが消えたあとのハンドル。書き込みも読み出しも Errno 5 を出す。"""
    is_open = True

    def write(self, _data):
        raise OSError(5, "Input/output error")

    @property
    def in_waiting(self):
        raise OSError(5, "Input/output error")

    def readline(self):
        raise OSError(5, "Input/output error")

    def close(self):
        pass


def test_write_error_requests_reopen():
    """書き込みエラーで開き直しが要求されること（以前は何も起きなかった）。"""
    c = make_client()
    c.ser = DeadSerial()
    c.ipv6_addr = "FE80::1"

    assert c._send_echonet("E7") is None
    assert c._needs_reopen is True, "デバイス消失を検知できていない"
    assert c._needs_reconnect is True


def test_send_command_survives_dead_device():
    """_send_command が例外を投げず、開き直しを要求すること。

    以前は write が保護されておらず、connect() の途中で例外が伝播していた。
    """
    c = make_client()
    c.ser = DeadSerial()

    assert c._send_command("SKVER", "OK") == []
    assert c._needs_reopen is True


def test_reconnect_reopens_instead_of_skterm():
    """デバイス消失時、SKTERM を書かずに開き直して connect() すること。"""
    c = make_client()
    dead = DeadSerial()
    c.ser = dead
    c._needs_reopen = True

    with patch.object(WiSUNClient, "connect", return_value=True) as connect:
        assert c.reconnect() is True

    connect.assert_called_once()
    assert c._needs_reopen is False


def test_reconnect_failure_keeps_reopen_flag():
    """開き直しに失敗したら、次回も開き直しから試すこと。"""
    c = make_client()
    c.ser = DeadSerial()
    c._needs_reopen = True

    with patch.object(WiSUNClient, "connect", return_value=False):
        assert c.reconnect() is False

    assert c._needs_reopen is True, "フラグが落ちると以後 SKTERM 経路に入ってしまう"


def test_get_power_data_triggers_reopen():
    """_needs_reopen だけが立っている状態でも再接続が走ること。

    以前の条件は _needs_reconnect と連続タイムアウトだけを見ていた。
    """
    c = make_client()
    c.ser = DeadSerial()
    c._needs_reopen = True

    with patch.object(WiSUNClient, "reconnect", return_value=True) as reconnect, \
         patch.object(WiSUNClient, "get_instant_power", return_value=1234):
        data = c.get_power_data()

    reconnect.assert_called_once()
    assert data["instant_power"] == 1234


def test_healthy_path_does_not_reopen():
    """正常時は開き直さないこと。"""
    c = make_client()
    ser = MagicMock()
    ser.is_open = True
    c.ser = ser
    c._needs_reopen = False
    c._needs_reconnect = False
    c.consecutive_timeouts = 0

    with patch.object(WiSUNClient, "reconnect") as reconnect, \
         patch.object(WiSUNClient, "get_instant_power", return_value=100):
        c.get_power_data()

    reconnect.assert_not_called()
