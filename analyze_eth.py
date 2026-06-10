#!/usr/bin/env python3
"""
Ethereum Egan Trader - RSI(14) + EMA(9) + WMA(45) signal analyzer
Methodology: Vietnamese trading community (Egan Lê style)
"""

import argparse
import json
import sys
import io
from datetime import datetime, timezone
import requests
import numpy as np
import pandas as pd

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Binance public API ──────────────────────────────────────────────────────
BINANCE_URL = "https://api.binance.com/api/v3/klines"

TIMEFRAME_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"
}

def fetch_ohlcv(symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    resp = requests.get(BINANCE_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    df = pd.DataFrame(data, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore"
    ])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df = df.set_index("open_time")
    return df

# ── Indicators ──────────────────────────────────────────────────────────────
def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def calc_wma(series: pd.Series, period: int) -> pd.Series:
    weights = np.arange(1, period + 1, dtype=float)
    def wma_window(x):
        if len(x) < period:
            return np.nan
        return np.dot(x[-period:], weights) / weights.sum()
    return series.rolling(window=period).apply(wma_window, raw=True)

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["rsi"] = calc_rsi(df["close"], 14)
    df["ema9_rsi"] = calc_ema(df["rsi"], 9)
    df["wma45_rsi"] = calc_wma(df["rsi"], 45)
    return df.dropna(subset=["rsi", "ema9_rsi", "wma45_rsi"])

# ── Divergence detection ────────────────────────────────────────────────────
def find_pivots(series: pd.Series, left: int = 5, right: int = 5):
    """Return indices of pivot highs and lows."""
    highs, lows = [], []
    for i in range(left, len(series) - right):
        window = series.iloc[i - left: i + right + 1]
        if series.iloc[i] == window.max():
            highs.append(i)
        if series.iloc[i] == window.min():
            lows.append(i)
    return highs, lows

def detect_divergence(df: pd.DataFrame, lookback: int = 50) -> str:
    """
    Returns: 'bullish', 'bearish', or 'none'
    Bullish: price lower low + RSI higher low (at oversold zone)
    Bearish: price higher high + RSI lower high (at overbought zone)
    """
    sub = df.tail(lookback).copy()
    sub = sub.reset_index(drop=True)

    price_highs, price_lows = find_pivots(sub["close"])
    rsi_highs, rsi_lows = find_pivots(sub["rsi"])

    # Bullish divergence check
    if len(price_lows) >= 2 and len(rsi_lows) >= 2:
        pl1, pl2 = price_lows[-2], price_lows[-1]
        rl1, rl2 = rsi_lows[-2], rsi_lows[-1]
        if (sub["close"].iloc[pl2] < sub["close"].iloc[pl1] and
                sub["rsi"].iloc[rl2] > sub["rsi"].iloc[rl1] and
                sub["rsi"].iloc[rl2] < 35):
            return "bullish"

    # Bearish divergence check
    if len(price_highs) >= 2 and len(rsi_highs) >= 2:
        ph1, ph2 = price_highs[-2], price_highs[-1]
        rh1, rh2 = rsi_highs[-2], rsi_highs[-1]
        if (sub["close"].iloc[ph2] > sub["close"].iloc[ph1] and
                sub["rsi"].iloc[rh2] < sub["rsi"].iloc[rh1] and
                sub["rsi"].iloc[rh2] > 65):
            return "bearish"

    return "none"

# ── Signal logic ────────────────────────────────────────────────────────────
def get_signal(df: pd.DataFrame) -> dict:
    last = df.iloc[-1]
    prev = df.iloc[-2]

    rsi = last["rsi"]
    ema9 = last["ema9_rsi"]
    wma45 = last["wma45_rsi"]

    # Crossover detection
    ema_cross_up = (prev["ema9_rsi"] < prev["wma45_rsi"]) and (ema9 >= wma45)
    ema_cross_down = (prev["ema9_rsi"] > prev["wma45_rsi"]) and (ema9 <= wma45)

    # Trend reading
    if rsi > wma45 and ema9 > wma45:
        trend = "UPTREND"
    elif rsi < wma45 and ema9 < wma45:
        trend = "DOWNTREND"
    else:
        trend = "CONSOLIDATION"

    divergence = detect_divergence(df)

    # BUY conditions
    buy_rsi = rsi <= 25
    buy_cross = ema_cross_up or (ema9 > wma45 and rsi < 35)
    buy_div = divergence == "bullish"

    # SELL conditions
    sell_rsi = rsi >= 75
    sell_cross = ema_cross_down or (ema9 < wma45 and rsi > 65)
    sell_div = divergence == "bearish"

    buy_score = sum([buy_rsi, buy_cross, buy_div])
    sell_score = sum([sell_rsi, sell_cross, sell_div])

    moderate_buy_ok = rsi <= 35 and trend == "UPTREND"
    moderate_sell_ok = rsi >= 65 and trend == "DOWNTREND"

    if buy_score == 3:
        signal = "BUY"
        strength = "STRONG"
    elif buy_score == 2 and moderate_buy_ok:
        signal = "BUY"
        strength = "MODERATE"
    elif sell_score == 3:
        signal = "SELL"
        strength = "STRONG"
    elif sell_score == 2 and moderate_sell_ok:
        signal = "SELL"
        strength = "MODERATE"
    else:
        signal = "NEUTRAL"
        strength = "WEAK"

    price = last["close"]

    # ETH is more volatile than BTC — SL ±2.5%, TP1 ±2.5%, TP2 ±5%
    return {
        "signal": signal,
        "strength": strength,
        "price": price,
        "rsi": round(rsi, 2),
        "ema9_rsi": round(ema9, 2),
        "wma45_rsi": round(wma45, 2),
        "trend": trend,
        "divergence": divergence,
        "conditions": {
            "buy": {"rsi_zone": buy_rsi, "ema_cross": buy_cross, "divergence": buy_div},
            "sell": {"rsi_zone": sell_rsi, "ema_cross": sell_cross, "divergence": sell_div}
        },
        "entry": price,
        "stop_loss_buy": round(price * 0.975, 2),
        "stop_loss_sell": round(price * 1.025, 2),
        "tp1_buy": round(price * 1.025, 2),
        "tp2_buy": round(price * 1.05, 2),
        "tp1_sell": round(price * 0.975, 2),
        "tp2_sell": round(price * 0.95, 2),
    }

# ── Futures signal ──────────────────────────────────────────────────────────
def get_futures_signal(df: pd.DataFrame) -> dict:
    import numpy as np
    sig = get_signal(df)
    entry = sig["price"]
    # ETH more volatile — use 2.5% as proxy ATR unit
    atr = entry * 0.025

    if sig["signal"] == "BUY" and sig["strength"] == "STRONG":
        direction = "LONG"
        sl = entry - 1.5 * atr
        tp = entry + 3.0 * atr
    elif sig["signal"] == "SELL" and sig["strength"] == "STRONG":
        direction = "SHORT"
        sl = entry + 1.5 * atr
        tp = entry - 3.0 * atr
    else:
        direction = "NEUTRAL"
        sl = entry
        tp = entry

    return {
        "direction": direction,
        "entry": round(entry, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "atr": round(atr, 2),
    }

# ── Backtest ────────────────────────────────────────────────────────────────
def run_backtest(df: pd.DataFrame) -> dict:
    trades = []
    in_trade = None

    for i in range(50, len(df) - 1):
        sub = df.iloc[:i+1]
        last = sub.iloc[-1]
        prev = sub.iloc[-2]

        rsi = last["rsi"]
        ema9 = last["ema9_rsi"]
        wma45 = last["wma45_rsi"]
        ema_cross_up = (prev["ema9_rsi"] < prev["wma45_rsi"]) and (ema9 >= wma45)
        ema_cross_down = (prev["ema9_rsi"] > prev["wma45_rsi"]) and (ema9 <= wma45)

        if in_trade is None:
            if rsi <= 25 and ema_cross_up:
                in_trade = {"type": "BUY", "entry": last["close"], "idx": i, "entry_time": str(df.index[i])}
            elif rsi >= 75 and ema_cross_down:
                in_trade = {"type": "SELL", "entry": last["close"], "idx": i, "entry_time": str(df.index[i])}
        else:
            close_price = last["close"]
            if in_trade["type"] == "BUY" and (rsi >= 70 or ema_cross_down):
                pnl = (close_price - in_trade["entry"]) / in_trade["entry"] * 100
                trades.append({**in_trade, "exit": close_price, "exit_time": str(df.index[i]), "pnl_pct": round(pnl, 2)})
                in_trade = None
            elif in_trade["type"] == "SELL" and (rsi <= 30 or ema_cross_up):
                pnl = (in_trade["entry"] - close_price) / in_trade["entry"] * 100
                trades.append({**in_trade, "exit": close_price, "exit_time": str(df.index[i]), "pnl_pct": round(pnl, 2)})
                in_trade = None

    if not trades:
        return {"total_trades": 0, "win_rate": 0, "avg_pnl": 0, "total_pnl": 0, "trades": []}

    wins = [t for t in trades if t["pnl_pct"] > 0]
    total_pnl = sum(t["pnl_pct"] for t in trades)

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(trades) - len(wins),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "avg_pnl": round(total_pnl / len(trades), 2),
        "total_pnl": round(total_pnl, 2),
        "best_trade": round(max(t["pnl_pct"] for t in trades), 2),
        "worst_trade": round(min(t["pnl_pct"] for t in trades), 2),
        "trades": trades[-10:]  # last 10
    }

# ── Output formatting ───────────────────────────────────────────────────────
def print_signal(sig: dict, symbol: str, timeframe: str):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    signal_emoji = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "⚪"}
    trend_emoji = {"UPTREND": "📈", "DOWNTREND": "📉", "CONSOLIDATION": "➡️"}
    div_label = {"bullish": "✅ Bullish divergence", "bearish": "✅ Bearish divergence", "none": "❌ No divergence"}

    print(f"\n{'='*55}")
    print(f"Ξ {symbol} | {timeframe.upper()} | {now}")
    print(f"{'='*55}")
    print(f"Giá hiện tại:   ${sig['price']:,.2f}")
    print(f"RSI(14):        {sig['rsi']}")
    print(f"EMA(9) on RSI:  {sig['ema9_rsi']}")
    print(f"WMA(45) on RSI: {sig['wma45_rsi']}")
    print(f"Trend:          {trend_emoji[sig['trend']]} {sig['trend']}")
    print(f"Divergence:     {div_label[sig['divergence']]}")
    print(f"\n{signal_emoji[sig['signal']]} TÍN HIỆU ETH: {sig['signal']} ({sig['strength']})")

    print(f"\nĐiều kiện BUY:")
    c = sig["conditions"]["buy"]
    print(f"  {'✅' if c['rsi_zone'] else '❌'} RSI vùng oversold (RSI={sig['rsi']})")
    print(f"  {'✅' if c['ema_cross'] else '❌'} EMA(9) cắt lên WMA(45)")
    print(f"  {'✅' if c['divergence'] else '❌'} Bullish divergence")

    print(f"\nĐiều kiện SELL:")
    c = sig["conditions"]["sell"]
    print(f"  {'✅' if c['rsi_zone'] else '❌'} RSI vùng overbought (RSI={sig['rsi']})")
    print(f"  {'✅' if c['ema_cross'] else '❌'} EMA(9) cắt xuống WMA(45)")
    print(f"  {'✅' if c['divergence'] else '❌'} Bearish divergence")

    if sig["signal"] == "BUY":
        print(f"\n📌 Kế hoạch giao dịch ETH BUY:")
        print(f"  Entry:     ${sig['entry']:,.2f}")
        print(f"  Stop Loss: ${sig['stop_loss_buy']:,.2f} (-2.5%)")
        print(f"  TP1:       ${sig['tp1_buy']:,.2f} (+2.5%, 1:1 R:R)")
        print(f"  TP2:       ${sig['tp2_buy']:,.2f} (+5%, swing)")
    elif sig["signal"] == "SELL":
        print(f"\n📌 Kế hoạch giao dịch ETH SELL:")
        print(f"  Entry:     ${sig['entry']:,.2f}")
        print(f"  Stop Loss: ${sig['stop_loss_sell']:,.2f} (+2.5%)")
        print(f"  TP1:       ${sig['tp1_sell']:,.2f} (-2.5%, 1:1 R:R)")
        print(f"  TP2:       ${sig['tp2_sell']:,.2f} (-5%, swing)")

    print(f"{'='*55}\n")

def print_backtest(result: dict, symbol: str, timeframe: str):
    print(f"\n{'='*55}")
    print(f"Ξ BACKTEST ETH: {symbol} | {timeframe.upper()}")
    print(f"{'='*55}")
    print(f"Tổng giao dịch: {result['total_trades']}")
    print(f"Thắng: {result['wins']} | Thua: {result['losses']}")
    print(f"Win rate: {result['win_rate']}%")
    print(f"PnL trung bình: {result['avg_pnl']}%")
    print(f"Tổng PnL: {result['total_pnl']}%")
    if result['total_trades'] > 0:
        print(f"Trade tốt nhất: +{result['best_trade']}%")
        print(f"Trade tệ nhất: {result['worst_trade']}%")
        print(f"\n10 giao dịch gần nhất:")
        for t in result['trades']:
            emoji = "✅" if t['pnl_pct'] > 0 else "❌"
            print(f"  {emoji} {t['type']} @ ${t['entry']:,.0f} → ${t['exit']:,.0f} | {t['pnl_pct']:+.2f}%")
    print(f"{'='*55}\n")

# ── Main ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Ethereum Egan Trader - RSI EMA WMA Signal Analyzer")
    parser.add_argument("--symbol", default="ETHUSDT", help="Trading pair (default: ETHUSDT)")
    parser.add_argument("--timeframe", default="4h", choices=list(TIMEFRAME_MAP.keys()), help="Timeframe (default: 4h)")
    parser.add_argument("--mode", default="signal", choices=["signal", "backtest", "alert", "json"], help="Mode")
    parser.add_argument("--limit", default=500, type=int, help="Candles to fetch (default: 500)")
    args = parser.parse_args()

    print(f"Đang tải dữ liệu ETH {args.symbol} ({args.timeframe})...")
    df = fetch_ohlcv(args.symbol, TIMEFRAME_MAP[args.timeframe], limit=args.limit)
    df = add_indicators(df)
    print(f"Đã tải {len(df)} nến. Tính toán indicators...")

    if args.mode == "backtest":
        result = run_backtest(df)
        print_backtest(result, args.symbol, args.timeframe)
    elif args.mode == "json":
        import numpy as np
        sig = get_signal(df)
        sig["futures"] = get_futures_signal(df)

        def convert(obj):
            if isinstance(obj, (np.bool_,)):
                return bool(obj)
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            raise TypeError(f"Not serializable: {type(obj)}")

        print(json.dumps(sig, indent=2, default=convert))
    elif args.mode == "alert":
        sig = get_signal(df)
        if sig["signal"] != "NEUTRAL":
            print_signal(sig, args.symbol, args.timeframe)
        else:
            print(f"⚪ Không có tín hiệu ETH. RSI={sig['rsi']}, Trend={sig['trend']}")
    else:
        sig = get_signal(df)
        print_signal(sig, args.symbol, args.timeframe)

if __name__ == "__main__":
    main()
