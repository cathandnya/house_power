"""
スキャンリトライスクリプト

間隔を空けてスキャンを繰り返す（10分, 20分, 40分...）
成功したら停止する
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT = str(Path(__file__).parent / "scan_test.py")
PYTHON = sys.executable
LOG_FILE = Path(__file__).parent / "logs" / "scan_retry.log"

# 初回の待ち時間（秒）と倍率
INITIAL_DELAY = 600  # 10分
MULTIPLIER = 2


def log(msg):
    """コンソールとファイルに出力"""
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def main():
    LOG_FILE.parent.mkdir(exist_ok=True)
    log(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] Scan retry started")

    attempt = 0
    while True:
        delay = INITIAL_DELAY * (MULTIPLIER ** attempt)
        log(f"\n{'='*60}")
        log(f"[{datetime.now():%H:%M:%S}] Attempt {attempt + 1}")
        log(f"{'='*60}")

        result = subprocess.run(
            [PYTHON, SCRIPT],
            cwd=str(Path(__file__).parent),
            capture_output=True,
            text=True,
        )

        # 子プロセスの出力をコンソールとログに書き出し
        if result.stdout:
            for line in result.stdout.rstrip().split("\n"):
                log(line)
        if result.stderr:
            for line in result.stderr.rstrip().split("\n"):
                log(f"[STDERR] {line}")

        if result.returncode == 0:
            log(f"\n[{datetime.now():%H:%M:%S}] Smart meter found! Stopping.")
            return

        minutes = delay // 60
        log(f"\n[{datetime.now():%H:%M:%S}] Next scan in {minutes} minutes...")
        try:
            time.sleep(delay)
        except KeyboardInterrupt:
            log("\nInterrupted by user")
            return

        attempt += 1


if __name__ == "__main__":
    main()
