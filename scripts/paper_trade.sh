#!/bin/bash
# Runs one paper trading cycle. Silent if no trades placed; outputs summary if trades placed.
cd ~/prediction-bot
set -a; source .env; set +a
source venv/bin/activate
OUTPUT=$(python -m src.main paper --bankroll 120 --daily-cap 50 2>&1)
# Only surface output if at least one trade was placed
if echo "$OUTPUT" | grep -q "Placed [1-9]"; then
    echo "=== prediction-bot paper trade cycle $(date -u '+%Y-%m-%d %H:%M UTC') ==="
    echo "$OUTPUT"
fi
