# 家庭電力消費量モニター

Wi-SUN Bルートでスマートメーターから直接電力消費量を取得し、Webダッシュボードでリアルタイム表示。REST API / WebSocketで電力データを配信するサーバー/クライアント構成。

## 特徴

- **リアルタイム更新**: 5秒間隔で瞬時電力・電流を取得
- **積算電力量**: 30分ごとに買電・売電の積算値を取得
- **接続品質監視**: RSSI（電波強度）をリアルタイム表示
- **Webダッシュボード**: ブラウザでリアルタイム表示・グラフ
- **LINE通知**: 電力が閾値を超えたらLINE Notifyで通知
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

- Raspberry Pi（Pi Zero 2 W 推奨）
- Wi-SUNアダプタ（ROHM BP35C2 または テセラ製）
- microUSB OTG変換ケーブル
- microSDカード（8GB以上）

※ Wi-SUNアダプタは両方ともUSB接続、SKコマンド互換。コードは共通で動作

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
ENERGY_POLL_INTERVAL = 1800  # 積算電力量の取得間隔（秒）

# LINE Notify（オプション）
LINE_NOTIFY_TOKEN = "your_token_here"
```

### 4. LINE Notify設定（オプション）

電力が閾値を超えたときにLINEで通知を受け取れます。

1. https://notify-bot.line.me/ にアクセス
2. LINEアカウントでログイン
3. 「トークンを発行する」をクリック
4. トークン名（例: 電力モニター）を入力し、通知先を選択
5. 発行されたトークンを `config.py` の `LINE_NOTIFY_TOKEN` に設定

閾値はWebダッシュボードの「通知設定」から変更できます。

### 5. 実行

```bash
python main.py
```

ブラウザで `http://<Raspberry PiのIP>:8000` にアクセス

### 6. 自動起動設定（オプション）

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
│   ├── notifier.py          # LINE Notify通知
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
| `/api/power` | GET | 現在の電力値（瞬時電力・電流） |
| `/api/energy` | GET | 積算電力量（買電・売電） |
| `/api/connection` | GET | 接続情報（RSSI・チャンネル等） |
| `/api/history` | GET | 過去1時間の履歴 |
| `/api/status` | GET | サーバーステータス |
| `/api/settings` | GET/POST | 通知設定の取得・更新 |

### WebSocket

| エンドポイント | 説明 |
|---------------|------|
| `/ws/power` | リアルタイム電力データ配信（5秒ごと） |

### レスポンス例

#### `/api/power`
```json
{
  "instant_power": 1052,
  "instant_current_r": 6.0,
  "instant_current_t": 5.0,
  "timestamp": "2026-01-25T10:36:26.316186"
}
```

#### `/api/energy`
```json
{
  "cumulative_energy": 5890.6,
  "cumulative_energy_reverse": 0.6,
  "fixed_energy": {
    "timestamp": "2026-01-25 10:30:00",
    "energy": 5890.5
  },
  "energy_unit": 0.1,
  "timestamp": "2026-01-25T10:35:46.060267"
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

## ライセンス

MIT License
