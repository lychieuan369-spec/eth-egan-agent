#!/usr/bin/env python3
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import subprocess
import json
import requests
from datetime import datetime, timezone
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8639655584:AAGKmEwGKEufCYwItf3v4c7G_P5acacAwQA")
CHAT_ID = os.environ.get("CHAT_ID", "8842938928")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

TIMEFRAMES = [
    ("4h", "4H"),
    ("1h", "1H"),
]

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    resp = requests.post(url, json=payload, timeout=10)
    return resp.ok

def get_signal(timeframe: str) -> dict:
    result = subprocess.run(
        ["python", os.path.join(SCRIPT_DIR, "analyze_eth.py"),
         "--symbol", "ETHUSDT",
         "--timeframe", timeframe,
         "--mode", "json"],
        capture_output=True, text=True, encoding='utf-8',
        cwd=SCRIPT_DIR
    )
    if result.returncode not in (0, 255):
        raise RuntimeError(result.stderr)
    # Strip any non-JSON lines before the opening brace
    stdout = result.stdout
    brace_idx = stdout.find("{")
    if brace_idx == -1:
        raise RuntimeError(f"No JSON in output: {stdout}")
    return json.loads(stdout[brace_idx:])

def format_message(sig: dict, tf_label: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    signal_emoji = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "⚪"}
    trend_emoji = {"UPTREND": "📈", "DOWNTREND": "📉", "CONSOLIDATION": "➡️"}
    div_map = {"bullish": "✅ Bullish div", "bearish": "✅ Bearish div", "none": "❌ No div"}

    emoji = signal_emoji[sig["signal"]]
    lines = [
        f"{emoji} <b>Ξ ETHUSDT {tf_label} — {sig['signal']} ({sig['strength']})</b>",
        f"🕐 {now}",
        f"",
        f"💰 Giá ETH: <b>${sig['price']:,.2f}</b>",
        f"📊 RSI(14): {sig['rsi']}",
        f"📈 EMA(9)/RSI: {sig['ema9_rsi']}",
        f"📉 WMA(45)/RSI: {sig['wma45_rsi']}",
        f"Trend: {trend_emoji[sig['trend']]} {sig['trend']}",
        f"Divergence: {div_map[sig['divergence']]}",
    ]

    c = sig["conditions"]
    if sig["signal"] == "BUY":
        lines += [
            f"",
            f"<b>Điều kiện BUY:</b>",
            f"{'✅' if c['buy']['rsi_zone'] else '❌'} RSI oversold ({sig['rsi']})",
            f"{'✅' if c['buy']['ema_cross'] else '❌'} EMA cắt lên WMA",
            f"{'✅' if c['buy']['divergence'] else '❌'} Bullish divergence",
            f"",
            f"📌 <b>Kế hoạch ETH:</b>",
            f"Entry:  ${sig['entry']:,.2f}",
            f"SL:     ${sig['stop_loss_buy']:,.2f} (-2.5%)",
            f"TP1:    ${sig['tp1_buy']:,.2f} (+2.5%)",
            f"TP2:    ${sig['tp2_buy']:,.2f} (+5%)",
        ]
    elif sig["signal"] == "SELL":
        lines += [
            f"",
            f"<b>Điều kiện SELL:</b>",
            f"{'✅' if c['sell']['rsi_zone'] else '❌'} RSI overbought ({sig['rsi']})",
            f"{'✅' if c['sell']['ema_cross'] else '❌'} EMA cắt xuống WMA",
            f"{'✅' if c['sell']['divergence'] else '❌'} Bearish divergence",
            f"",
            f"📌 <b>Kế hoạch ETH:</b>",
            f"Entry:  ${sig['entry']:,.2f}",
            f"SL:     ${sig['stop_loss_sell']:,.2f} (+2.5%)",
            f"TP1:    ${sig['tp1_sell']:,.2f} (-2.5%)",
            f"TP2:    ${sig['tp2_sell']:,.2f} (-5%)",
        ]

    return "\n".join(lines)

def main():
    any_signal = False
    for tf, tf_label in TIMEFRAMES:
        try:
            sig = get_signal(tf)
            if sig["signal"] != "NEUTRAL":
                msg = format_message(sig, tf_label)
                ok = send_telegram(msg)
                status = "✅ sent" if ok else "❌ failed"
                print(f"[ETH {tf_label}] {sig['signal']} signal → Telegram {status}")
                any_signal = True
            else:
                print(f"[ETH {tf_label}] No signal. RSI={sig['rsi']}, Trend={sig['trend']}")
        except Exception as e:
            print(f"[ETH {tf_label}] Error: {e}")

    if not any_signal:
        print("No ETH signals on any timeframe.")

if __name__ == "__main__":
    main()
