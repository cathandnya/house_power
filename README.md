# 家庭電力消費量モニター

Wi-SUN Bルートでスマートメーターから直接電力消費量を取得し、Webダッシュボードでリアルタイム表示。REST API / WebSocketで電力データを配信するサーバー/クライアント構成。

## 特徴

- **リアルタイム更新**: 約3秒間隔で電力値を取得
- **Webダッシュボード**: ブラウザでリアルタイム表示・グラフ
- **LINE通知**: 電力が閾値を超えたらLINE Notifyで通知
- **REST API**: 外部システムとの連携が容易
- **WebSocket**: リアルタイムデータ配信
- **Mockモード**: Wi-SUNアダプタなしで動作テスト可能
- **Nature Remo E liteと併用可能**

## アーキテクチャ

```
                                          ┌─ [Webブラウザ] ダッシュボード
[スマートメーター] <--Wi-SUN--> [サーバー] ─┼─ [REST API] 外部連携
         (920MHz)              (Pi Zero 2W)└─ [WebSocket] リアルタイム配信
```

## ハードウェア

### サーバー構成

| 部品 | 推奨品 | 価格 |
|------|--------|------|
| Raspberry Pi | **Pi Zero 2 W** | 約2,500円 |
| Wi-SUNアダプタ | ROHM BP35C2 または テセラ製 | 約12,000〜16,800円 |
| USBハブ（OTG） | microUSB OTG変換ケーブル | 約300円 |
| microSDカード | 8GB以上 | 約500円 |

**合計**: 約15,300〜20,100円

### Wi-SUNアダプタ選択肢

| 製品 | 価格 | 特徴 |
|------|------|------|
| ROHM BP35C2 | 約16,800円 | 参考情報豊富、安心 |
| テセラ製 | 約12,000円 | 安価 |

※ 両方ともUSB接続、SKコマンド互換。コードは共通で動作

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
| `/api/power` | GET | 現在の電力値（JSON） |
| `/api/history` | GET | 過去1時間の履歴 |
| `/api/status` | GET | サーバーステータス |
| `/api/settings` | GET | 通知設定の取得 |
| `/api/settings` | POST | 通知設定の更新 |

### WebSocket

| エンドポイント | 説明 |
|---------------|------|
| `/ws/power` | リアルタイム電力データ配信（3秒ごと） |

### レスポンス例

```json
{
  "instant_power": 2345,
  "instant_current_r": 12.3,
  "instant_current_t": 11.8,
  "timestamp": "2025-01-23T12:34:56.789"
}
```

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
