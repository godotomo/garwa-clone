#!/data/data/com.termux/files/usr/bin/bash
# jobbot/daily_autopilot.sh - Jalankan autopilot harian + log.
#
# Dipanggil oleh cronie (crontab) tiap hari. Jalankan satu siklus autopilot
# penuh (scrape -> proposal -> deliverable -> report Telegram + email),
# lalu catat output ke file log.
set -u

ROOT="/data/data/com.termux/files/home/garwa-coder-v2"
LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/autopilot_$(date +%Y-%m-%d).log"

mkdir -p "$LOG_DIR"

cd "$ROOT" || exit 1

echo "==============================================" >> "$LOG_FILE"
echo "AUTOPILOT START $(date '+%Y-%m-%d %H:%M:%S %Z')" >> "$LOG_FILE"
echo "==============================================" >> "$LOG_FILE"

# Jalankan autopilot: 3 deliverable, kirim laporan Telegram + email.
python -m jobbot.cli autopilot \
    --max-deliverables 3 \
    --report-email \
    >> "$LOG_FILE" 2>&1

echo "----------------------------------------------" >> "$LOG_FILE"
echo "AUTOPILOT END   $(date '+%Y-%m-%d %H:%M:%S %Z')" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
