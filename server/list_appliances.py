#!/usr/bin/env python3
"""
Nature Remo 家電一覧取得スクリプト

config.py の NATURE_REMO_ACCESS_TOKEN を使って家電一覧を取得し、
設定に必要な appliance_id を表示します。

Usage:
    python list_appliances.py
"""

import asyncio
import sys

try:
    import config
except ImportError:
    print("エラー: config.py が見つかりません")
    sys.exit(1)

from nature_remo_controller import NatureRemoController


async def main():
    token = getattr(config, "NATURE_REMO_ACCESS_TOKEN", "")
    if not token:
        print("エラー: config.py に NATURE_REMO_ACCESS_TOKEN が設定されていません")
        print()
        print("設定方法:")
        print("  1. https://home.nature.global にアクセス")
        print("  2. 「Generate access token」でトークンを発行")
        print("  3. config.py に以下を追加:")
        print('     NATURE_REMO_ACCESS_TOKEN = "your-token-here"')
        sys.exit(1)

    controller = NatureRemoController(access_token=token)
    appliances = await controller.get_appliances()

    if not appliances:
        print("家電が見つかりませんでした")
        sys.exit(1)

    print("=" * 60)
    print("Nature Remo 家電一覧")
    print("=" * 60)
    print()

    for app in appliances:
        app_id = app.get("id", "")
        nickname = app.get("nickname", "(名前なし)")
        app_type = app.get("type", "")

        # エンドポイントを判定
        if app_type == "AC":
            endpoint = "aircon_settings"
        elif app_type == "LIGHT":
            endpoint = "light"
        elif app_type == "TV":
            endpoint = "tv"
        else:
            endpoint = "signal"

        print(f"【{nickname}】")
        print(f"  type: {app_type}")
        print(f"  appliance_id: {app_id}")
        print(f"  endpoint: {endpoint}")
        print()

    print("=" * 60)
    print("config.py への設定例:")
    print("=" * 60)
    print()
    print("NATURE_REMO_ACTIONS = [")
    for app in appliances:
        app_id = app.get("id", "")
        nickname = app.get("nickname", "")
        app_type = app.get("type", "")

        if app_type == "AC":
            print(f"    # {nickname}")
            print("    {")
            print(f'        "appliance_id": "{app_id}",')
            print('        "endpoint": "aircon_settings",')
            print('        "params": {"button": "power-off"},')
            print("    },")
        elif app_type == "LIGHT":
            print(f"    # {nickname}")
            print("    {")
            print(f'        "appliance_id": "{app_id}",')
            print('        "endpoint": "light",')
            print('        "params": {"button": "off"},')
            print("    },")
        elif app_type == "TV":
            print(f"    # {nickname}")
            print("    {")
            print(f'        "appliance_id": "{app_id}",')
            print('        "endpoint": "tv",')
            print('        "params": {"button": "power"},')
            print("    },")
    print("]")


if __name__ == "__main__":
    asyncio.run(main())
