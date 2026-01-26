// 家庭電力モニター Scriptable Widget
// 設定: サーバーのURLを入力してください
const SERVER_URL = "http://YOUR_SERVER_IP:8000"

// ウィジェットサイズの判定
const widgetSize = config.widgetFamily || "small"

// データ取得
async function fetchPowerData() {
  try {
    const req = new Request(`${SERVER_URL}/api/power`)
    req.timeoutInterval = 10
    const data = await req.loadJSON()
    return data
  } catch (e) {
    return null
  }
}

// 設定取得
async function fetchSettings() {
  try {
    const req = new Request(`${SERVER_URL}/api/settings`)
    req.timeoutInterval = 10
    const data = await req.loadJSON()
    return data
  } catch (e) {
    return { alert_threshold: 4000, contract_amperage: 40 }
  }
}

// 色を取得（契約アンペアの1/4ごと）
function getColor(percent) {
  if (percent >= 75) return new Color("#ef4444") // 赤
  if (percent >= 50) return new Color("#eab308") // 黄
  if (percent >= 25) return new Color("#3b82f6") // 青
  return new Color("#22c55e") // 緑
}

// ウィジェット作成
async function createWidget() {
  const widget = new ListWidget()
  widget.backgroundColor = new Color("#1a1a1a")

  const powerData = await fetchPowerData()
  const settings = await fetchSettings()

  if (!powerData || powerData.instant_power === null) {
    // データ取得失敗
    const errorText = widget.addText("⚡ ---")
    errorText.font = Font.boldSystemFont(24)
    errorText.textColor = Color.gray()
    errorText.centerAlignText()

    widget.addSpacer(4)

    const statusText = widget.addText("接続できません")
    statusText.font = Font.systemFont(12)
    statusText.textColor = Color.gray()
    statusText.centerAlignText()

    return widget
  }

  const power = powerData.instant_power
  const maxPower = settings.contract_amperage * 100
  const percent = (power / maxPower) * 100
  const color = getColor(percent)

  // 電力値
  const powerText = widget.addText(`${power.toLocaleString()}`)
  powerText.font = Font.boldSystemFont(widgetSize === "small" ? 32 : 42)
  powerText.textColor = color
  powerText.centerAlignText()

  // 単位
  const unitText = widget.addText("W")
  unitText.font = Font.systemFont(16)
  unitText.textColor = Color.gray()
  unitText.centerAlignText()

  widget.addSpacer(8)

  // パーセント表示
  const percentText = widget.addText(`${Math.round(percent)}%`)
  percentText.font = Font.mediumSystemFont(14)
  percentText.textColor = color
  percentText.centerAlignText()

  widget.addSpacer(4)

  // 更新時刻
  if (powerData.timestamp) {
    const date = new Date(powerData.timestamp)
    const timeStr = date.toLocaleTimeString("ja-JP", {
      hour: "2-digit",
      minute: "2-digit"
    })
    const timeText = widget.addText(timeStr)
    timeText.font = Font.systemFont(10)
    timeText.textColor = Color.gray()
    timeText.centerAlignText()
  }

  return widget
}

// 実行
const widget = await createWidget()

if (config.runsInWidget) {
  Script.setWidget(widget)
} else {
  // アプリ内プレビュー
  widget.presentSmall()
}

Script.complete()
