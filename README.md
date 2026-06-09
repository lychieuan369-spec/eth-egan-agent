# ETH Egan Agent

Ethereum price signal agent using RSI(14) + EMA(9) + WMA(45) — Egan Le methodology.

## How it works

- Fetches ETHUSDT OHLCV from Binance public API
- Calculates RSI(14), EMA(9) on RSI, WMA(45) on RSI
- Detects bullish/bearish divergences
- Generates BUY/SELL/NEUTRAL signals with strength (STRONG/MODERATE/WEAK)
- Sends Telegram alert when a non-neutral signal fires

## Risk parameters (ETH — higher volatility than BTC)

| Level | Value |
|-------|-------|
| Stop Loss | ±2.5% |
| TP1 | ±2.5% (1:1 R:R) |
| TP2 | ±5% (swing) |

## Files

- `analyze_eth.py` — core signal engine (ETHUSDT)
- `telegram_alert_eth.py` — runs analysis, sends Telegram alert
- `.github/workflows/eth-alert.yml` — GitHub Actions cron (every hour)
- `requirements.txt` — requests, numpy, pandas

## Setup

1. Add GitHub repository secrets:
   - `BOT_TOKEN` — Telegram bot token
   - `CHAT_ID` — Telegram chat/channel ID

2. Push to GitHub — the workflow runs automatically every hour.

## Local usage

```bash
pip install -r requirements.txt

# Live signal
python analyze_eth.py

# JSON output
python analyze_eth.py --mode json

# Backtest
python analyze_eth.py --mode backtest

# Run Telegram alert manually
BOT_TOKEN=xxx CHAT_ID=yyy python telegram_alert_eth.py
```
