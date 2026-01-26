# 家庭電力消費量モニター

Wi-SUN Bルートでスマートメーターから直接電力消費量を取得し、Webダッシュボードでリアルタイム表示。REST API / WebSocketで電力データを配信するサーバー/クライアント構成。

## 特徴

- **リアルタイム更新**: 5秒間隔で瞬時電力を取得
- **接続品質監視**: RSSI（電波強度）をリアルタイム表示
- **自動再接続**: 接続断を検知して自動復帰
- **Webダッシュボード**: ブラウザでリアルタイム表示・グラフ
- **Discord通知**: 電力が閾値を超えたらDiscordに通知
- **REST API**: 外部システムとの連携が容易
- **WebSocket**: リアルタイムデータ配信
- **Mockモード**: Wi-SUNアダプタなしで動作テスト可能
- **PWA対応**: スマホのホーム画面にアプリとして追加可能
- **ダークモード**: システム設定に連動

## アーキテクチャ

```
                                          ┌─ [Webブラウザ] ダッシュボード
[スマートメーター] <--Wi-SUN--> [サーバー] ─┼─ [REST API] 外部連携
         (920MHz)              (Pi Zero 2W)└─ [WebSocket] リアルタイム配信
```

## ハードウェア

### サーバー構成

- Raspberry Pi 等
- Wi-SUNアダプタ（ROHM BP35C2、テセラ・テクノロジー RL7023 等）

※ [テセラ製RL7023 Stick-D/IPS](https://amzn.to/4raXM0F)で動作確認済み
※ ROHM BP35C2もSKコマンド互換のため動作する可能性あり（未検証）

## セットアップ

### 1. Bルートサービス申請（必須）

電力会社に「電力メーター情報発信サービス（Bルートサービス）」を申請。
無料、申請から1〜2週間でID/パスワードが届く。

### 2. Raspberry Pi セットアップ

```bash
# リポジトリをクローン
git clone https://github.com/cathandnya/house_power.git
cd house_power/server

# 依存ライブラリのインストール
pip install -r requirements.txt

# USBアダプタ接続確認
ls /dev/ttyUSB*
# → /dev/ttyUSB0 が表示されればOK

# アクセス権限（必要に応じて）
sudo usermod -a -G dialout $USER
```

### 3. 設定

```bash
# 設定ファイルをコピー
cp config.py.example config.py

# config.py を編集
nano config.py
```

```python
# Wi-SUN Bルート認証（電力会社から届いたもの）
BROUTE_ID = "00000000000000000000000000000000"
BROUTE_PASSWORD = "XXXXXXXXXXXX"

# 更新間隔
POLL_INTERVAL = 5  # 瞬時電力の取得間隔（秒）

# 警告閾値（Discord通知用）
POWER_THRESHOLD = 4000  # W

# Discord通知（Webhook URL）
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/..."
```

### 4. 実行

```bash
python main.py
```

ブラウザで `http://<Raspberry PiのIP>:8000` にアクセス

### 5. 自動起動設定（オプション）

```bash
# サービスファイルを作成
sudo tee /etc/systemd/system/house-power.service << 'EOF'
[Unit]
Description=House Power Monitor Server
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/house_power/server/main.py
WorkingDirectory=/home/pi/house_power/server
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
EOF

# サービス有効化
sudo systemctl enable house-power
sudo systemctl start house-power
```

## Discord通知

電力が閾値を超えたときにDiscordへ通知を送信します。

### 設定方法

1. Discordでサーバーを作成（または既存サーバーを使用）
2. チャンネル設定 → 連携サービス → ウェブフック → 新しいウェブフック
3. 「ウェブフックURLをコピー」をクリック
4. `config.py` の `DISCORD_WEBHOOK_URL` にURLを設定
5. ダッシュボードの「テスト通知を送信」で動作確認

### 通知内容

```
⚡ 電力アラート
現在: 4,500W
閾値: 4,000W
```

クールダウン機能付きで、連続通知を防止します（デフォルト5分間隔）。

## 開発・テスト

### Mockモード

Wi-SUNアダプタなしでサーバーをテストできます。

```bash
python main.py --mock
```

時間帯に応じたリアルな電力データが生成されます。

### ユニットテスト

```bash
cd server
pytest tests/ -v
```

## ファイル構成

```
house_power/
├── server/
│   ├── main.py              # サーバーメイン
│   ├── config.py            # 設定（※.gitignore対象）
│   ├── config.py.example    # 設定サンプル
│   ├── wisun_client.py      # Wi-SUN/ECHONET Lite通信
│   ├── mock_client.py       # Mockクライアント（テスト用）
│   ├── api.py               # REST API / WebSocket
│   ├── discord_notifier.py  # Discord通知
│   ├── static/              # PWA用静的ファイル
│   │   ├── manifest.json
│   │   ├── sw.js
│   │   └── icon-*.png
│   ├── templates/
│   │   └── index.html       # Webダッシュボード
│   ├── tests/
│   │   └── test_api.py      # ユニットテスト
│   └── requirements.txt
├── .github/
│   └── workflows/
│       └── test.yml         # GitHub Actions CI
├── .gitignore
└── README.md
```

## API

### REST API

| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/` | GET | Webダッシュボード |
| `/api/power` | GET | 現在の電力値（瞬時電力） |
| `/api/connection` | GET | 接続情報（RSSI・チャンネル等） |
| `/api/history` | GET | 過去の履歴 |
| `/api/status` | GET | サーバーステータス |
| `/api/settings` | GET/POST | 通知設定の取得・更新 |
| `/api/notify/test` | POST | テスト通知送信 |
| `/api/notify/status` | GET | 通知ステータス |

### WebSocket

| エンドポイント | 説明 |
|---------------|------|
| `/ws/power` | リアルタイム電力データ配信（5秒ごと） |

### レスポンス例

#### `/api/power`
```json
{
  "instant_power": 1052,
  "timestamp": "2026-01-25T10:36:26.316186"
}
```

#### `/api/connection`
```json
{
  "channel": "31",
  "pan_id": "A91B",
  "mac_addr": "C0F94500408AA91B",
  "ipv6_addr": "FE80:0000:0000:0000:C2F9:4500:408A:A91B",
  "rssi": -57,
  "rssi_quality": "excellent"
}
```

## スマホアプリ化（PWA）

iPhone/Androidでホーム画面にアプリとして追加できます。

### iPhone (Safari)

1. Safariでダッシュボードにアクセス
2. 共有ボタン（□↑）をタップ
3. 「ホーム画面に追加」を選択
4. 「追加」をタップ

### Android (Chrome)

1. Chromeでダッシュボードにアクセス
2. メニュー（⋮）→「ホーム画面に追加」
3. 「追加」をタップ

追加後はアプリとして起動でき、ブラウザのUIなしで表示されます。

## トラブルシューティング

### USBアダプタが認識されない

```bash
# デバイス確認
lsusb
dmesg | tail -20
ls -la /dev/ttyUSB*
```

### スマートメーターに接続できない

- BルートID/パスワードが正しいか確認
- スマートメーターとの距離（推奨: 1〜10m）
- `wisun_cache.json` を削除して再接続

### Webダッシュボードにアクセスできない

```bash
# ポート確認
ss -tlnp | grep 8000

# ファイアウォール確認
sudo ufw status
```

### Discord通知が届かない

- Webhook URLが正しいか確認
- Discordサーバー/チャンネルが存在するか確認
- サーバーログでエラーを確認

## ライセンス

MIT License
