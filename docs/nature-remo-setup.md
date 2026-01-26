# Nature Remo 連携セットアップ

消費電力が閾値を超えたときに、Nature Remo Cloud API を使って家電を自動制御します。

## 1. アクセストークンの取得

1. https://home.nature.global にアクセス
2. Nature アカウントでログイン
3. 「Generate access token」をクリックしてトークンを発行
4. 表示されたトークンをコピー（一度しか表示されないので注意）
5. `server/config.py` に設定

```python
NATURE_REMO_ACCESS_TOKEN = "YOUR_ACCESS_TOKEN"
NATURE_REMO_ENABLED = True
```

## 2. 家電ID（appliance_id）の確認

### スクリプトで確認（推奨）

```bash
cd server
python list_appliances.py
```

家電一覧と、config.py への設定例が表示されます。

表示された `id` を `appliance_id` として使用します。

## 3. エンドポイントとパラメータ

### エアコン (`endpoint: "aircon_settings"`)

| params | 説明 |
|--------|------|
| `{"button": "power-off"}` | 電源OFF |
| `{"button": ""}` | 電源ON（前回の設定で起動） |
| `{"operation_mode": "cool", "temperature": "26"}` | 冷房26度 |
| `{"temperature": "24"}` | 温度のみ変更 |

`operation_mode` の値: `cool`, `warm`, `dry`, `blow`, `auto`

### 照明 (`endpoint: "light"`)

| params | 説明 |
|--------|------|
| `{"button": "off"}` | OFF |
| `{"button": "on"}` | ON |
| `{"button": "on-100"}` | 100%点灯 |
| `{"button": "on-favorite"}` | お気に入り |

### テレビ (`endpoint: "tv"`)

| params | 説明 |
|--------|------|
| `{"button": "power"}` | 電源トグル |
| `{"button": "vol-up"}` | 音量上げ |
| `{"button": "vol-down"}` | 音量下げ |

### シグナル (`endpoint: "signal"`)

学習済みの赤外線信号を送信します。`signal_id` の指定が必要です。

```python
{
    "appliance_id": "xxx",
    "endpoint": "signal",
    "signal_id": "signal-id-here",
    "params": {}
}
```

## 4. 設定例

```python
# === Nature Remo 連携 ===
NATURE_REMO_ACCESS_TOKEN = "YOUR_ACCESS_TOKEN"
NATURE_REMO_ENABLED = True
NATURE_REMO_COOLDOWN_MINUTES = 5

NATURE_REMO_ACTIONS = [
    # エアコンOFF
    {
        "appliance_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "endpoint": "aircon_settings",
        "params": {"button": "power-off"},
    },
    # 照明OFF
    {
        "appliance_id": "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy",
        "endpoint": "light",
        "params": {"button": "off"},
    },
]
```

## 5. テスト実行

設定したアクションを手動でテスト実行できます（クールダウンをスキップ）。

```bash
curl -X POST http://localhost:8000/api/nature-remo/test
```

成功時：

```json
{"success": true}
```

## 注意事項

- **レート制限**: Nature Remo API は 5分間で30リクエストまで
- **クールダウン**: 連続実行を防ぐため、デフォルト5分間は再実行されません
- **トークン管理**: `config.py` は `.gitignore` に含まれています。トークンを公開しないよう注意してください
