"""
╔══════════════════════════════════════════════════════════════╗
║     MARKET REGIME INDICATOR — Discord Bot (v3 FIXED)         ║
║     Fixes: Supertrend array error, VIX 6w period, imports    ║
╚══════════════════════════════════════════════════════════════╝

ONE-TIME SETUP — run this first in Command Prompt:
  pip install yfinance requests beautifulsoup4 apscheduler pytz numpy

USAGE:
  python market_regime_bot.py            <- run once now
  python market_regime_bot.py schedule   <- auto every Saturday 4:30 PM IST
"""

import sys
import json
import re
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# ── Safe imports with helpful error messages ──────────────────
try:
    import requests
except ImportError:
    print("ERROR: 'requests' not installed.")
    print("Fix : pip install requests")
    sys.exit(1)

try:
    import yfinance as yf
except ImportError:
    print("ERROR: 'yfinance' not installed.")
    print("Fix : pip install yfinance")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: 'beautifulsoup4' not installed.")
    print("Fix : pip install beautifulsoup4")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════
# 🔧  PASTE YOUR DISCORD WEBHOOK URL HERE  (only change needed)
# ══════════════════════════════════════════════════════════════
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1495700462270287954/qLTVZtLYOrsrAZKZbJ5WfzuYpbcmTk0Os3E1O3iUqqQbSYz4xiuGfcKEwStAKoxNxQ2V"
# ══════════════════════════════════════════════════════════════

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ──────────────────────────────────────────────────────────────
# HELPER: guarantee 1-D numpy float array
# Fixes: "setting an array element with a sequence"
# Cause: newer yfinance returns 2-D arrays from MultiIndex cols
# ──────────────────────────────────────────────────────────────
def _to_1d(x):
    arr = np.array(x, dtype=float)
    return arr.flatten()


# ──────────────────────────────────────────────────────────────
# 1.  NIFTY 50 PRICE
# ──────────────────────────────────────────────────────────────
def fetch_nifty_price():
    try:
        t    = yf.Ticker("^NSEI")
        hist = t.history(period="5d", interval="1d")
        if not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 2), \
                   hist.index[-1].strftime("%d-%m-%Y")
    except Exception as e:
        print(f"  [NIFTY Price] Error: {e}")
    return None, None


# ──────────────────────────────────────────────────────────────
# 2.  SUPERTREND (10, 3) WEEKLY  — FIXED
#
#  FIX A: Use yf.Ticker().history() not yf.download()
#         → avoids MultiIndex columns entirely
#  FIX B: _to_1d() on every price array
#         → guarantees 1-D float, eliminates "array with sequence"
# ──────────────────────────────────────────────────────────────
def compute_supertrend_weekly(period=10, multiplier=3.0):
    try:
        # Ticker.history always returns simple (non-Multi) columns
        t  = yf.Ticker("^NSEI")
        df = t.history(period="2y", interval="1wk")
        df = df[["High", "Low", "Close"]].dropna().copy()
        n  = len(df)

        # Force 1-D float arrays — THE key fix
        highs  = _to_1d(df["High"])
        lows   = _to_1d(df["Low"])
        closes = _to_1d(df["Close"])

        # True Range
        tr = np.zeros(n, dtype=float)
        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            tr[i] = max(
                highs[i] - lows[i],
                abs(highs[i]  - closes[i-1]),
                abs(lows[i]   - closes[i-1])
            )

        # ATR — Wilder (seed then EWM)
        atr = np.zeros(n, dtype=float)
        atr[period-1] = np.mean(tr[:period])
        alpha = 1.0 / period
        for i in range(period, n):
            atr[i] = alpha * tr[i] + (1.0 - alpha) * atr[i-1]

        # Basic bands
        hl2 = (highs + lows) / 2.0
        bub = hl2 + multiplier * atr
        blb = hl2 - multiplier * atr

        # Final bands + direction
        ub        = bub.copy()
        lb        = blb.copy()
        st        = np.full(n, np.nan, dtype=float)
        direction = np.zeros(n, dtype=int)

        for i in range(period, n):
            ub[i] = bub[i] if (bub[i] < ub[i-1] or closes[i-1] > ub[i-1]) else ub[i-1]
            lb[i] = blb[i] if (blb[i] > lb[i-1] or closes[i-1] < lb[i-1]) else lb[i-1]

            if i == period:
                direction[i] = 1 if closes[i] > ub[i] else -1
            elif direction[i-1] == -1 and closes[i] > ub[i]:
                direction[i] = 1
            elif direction[i-1] ==  1 and closes[i] < lb[i]:
                direction[i] = -1
            else:
                direction[i] = direction[i-1]

            st[i] = lb[i] if direction[i] == 1 else ub[i]

        last_dir = int(direction[-1])
        last_st  = round(float(st[-1]), 2)
        status   = "ABOVE" if last_dir == 1 else "BELOW"
        score    = 1 if last_dir == 1 else 0

        # Verification table — last 6 weeks
        print(f"\n  {'WEEK':<12} {'CLOSE':>10} {'ST(10,3)':>10}  DIR      STATUS")
        print(f"  {'-'*56}")
        for i in range(-6, 0):
            wk  = df.index[i].strftime("%d-%b-%y")
            cl  = round(float(closes[i]), 2)
            sv  = round(float(st[i]),     2) if not np.isnan(st[i]) else 0.0
            d   = int(direction[i])
            tag = "ABOVE ✅" if d == 1 else "BELOW ❌"
            print(f"  {wk:<12} {cl:>10,.2f} {sv:>10,.2f}  {'BULL' if d==1 else 'BEAR':>6}   {tag}")
        print()

        return status, last_st, score

    except Exception as e:
        print(f"  [Supertrend] Error: {e}")
        import traceback; traceback.print_exc()
        return None, None, None


# ──────────────────────────────────────────────────────────────
# 3.  NIFTY PE (Trailing TTM)
# ──────────────────────────────────────────────────────────────
def fetch_nifty_pe():
    try:
        r    = requests.get("https://nifty-pe-ratio.com/", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text()
        m    = re.search(r'PE ratio is\s+([\d.]+)', text)
        if m:  return float(m.group(1))
        m2   = re.search(r'(\d{2}\.\d{2})\s+on a consolidated', text)
        if m2: return float(m2.group(1))
    except Exception as e:
        print(f"  [PE Ratio] Error: {e}")
    return None


# ──────────────────────────────────────────────────────────────
# 4.  INDIA VIX — CURRENT
# ──────────────────────────────────────────────────────────────
def fetch_india_vix():
    try:
        t    = yf.Ticker("^INDIAVIX")
        hist = t.history(period="5d", interval="1d")
        if not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 2)
    except Exception as e:
        print(f"  [India VIX] Error: {e}")
    return None


# ──────────────────────────────────────────────────────────────
# 5.  INDIA VIX — 1 MONTH AGO  — FIXED
#
#  FIX: period="6w" is INVALID in yfinance → replaced with "3mo"
#       then we pick the close ~21 trading days back from today
# ──────────────────────────────────────────────────────────────
def fetch_india_vix_1m_ago():
    try:
        t    = yf.Ticker("^INDIAVIX")
        hist = t.history(period="3mo", interval="1d")   # was "6w" — invalid
        hist = hist.dropna()
        if hist.empty:
            raise ValueError("No VIX data returned")

        # ~21 trading days = ~1 calendar month
        idx      = -22 if len(hist) >= 22 else 0
        val      = round(float(hist["Close"].iloc[idx]), 2)
        ago_date = hist.index[idx].strftime("%d-%m-%Y")
        print(f"        → {val}  (from {ago_date}, ~1 month ago)")
        return val

    except Exception as e:
        print(f"  [VIX 1M Ago] Error: {e}")
    return None


# ──────────────────────────────────────────────────────────────
# SCORING ENGINE
# ──────────────────────────────────────────────────────────────
def compute_scores(st_status, pe, vix_now, vix_1m_ago):
    scores  = {}
    details = {}

    scores["supertrend"] = (1 if st_status=="ABOVE" else 0) if st_status else None
    scores["pe"]         = (1 if pe < 25 else 0) if pe is not None else None
    scores["vix_level"]  = (1 if vix_now < 25 else 0) if vix_now is not None else None

    if vix_now is not None and vix_1m_ago is not None and vix_1m_ago != 0:
        chg = ((vix_now - vix_1m_ago) / vix_1m_ago) * 100
        details["vix_change_pct"] = round(chg, 2)
        scores["vix_spike"] = 1 if (vix_now < 18 and chg < 40) else 0
    else:
        details["vix_change_pct"] = None
        scores["vix_spike"]       = None

    valid  = [v for v in scores.values() if v is not None]
    total  = sum(valid)
    max_sc = len(valid)
    mode   = "AGGRESSIVE" if total >= 3 else "DEFENSIVE"
    color  = 0x00C851 if total >= 3 else 0xFF4444

    return scores, details, total, max_sc, mode, color


# ──────────────────────────────────────────────────────────────
# DISCORD EMBED
# ──────────────────────────────────────────────────────────────
def _f(v, s=""): return f"{v:,.2f}{s}" if v is not None else "N/A"
def _s(v):
    if v is None: return "⚠️ N/A"
    return "✅  1" if v == 1 else "❌  0"

def build_embed(nifty_price, price_date, st_status, st_value, pe,
                vix_now, vix_1m_ago, scores, details, total, max_sc,
                market_mode, color):

    today   = datetime.now().strftime("%d-%m-%Y")
    vix_chg = details.get("vix_change_pct")
    chg_s   = f"{vix_chg:+.2f}%" if vix_chg is not None else "N/A"
    bar     = "█"*total + "░"*(max_sc-total)
    emoji   = "🟢" if market_mode == "AGGRESSIVE" else "🔴"
    pe_tag  = "fair value" if pe and pe < 22 else "elevated" if pe and pe >= 25 else "moderate"
    vix_tag = "fear subsiding ↓" if vix_chg and vix_chg < 0 else "volatility rising ↑"

    return {"embeds": [{"title": f"📊  Market Regime Indicator — {today}",
        "description": f"**Last Close:** {price_date or today}   |   **NIFTY 50:** `₹{_f(nifty_price)}`\n\u200b",
        "color": color,
        "fields": [
            {"name":"📈  Supertrend (Weekly 10,3)",
             "value":f"Status : **{st_status or 'N/A'}**\nLine   : `{_f(st_value)}`\nScore  : {_s(scores['supertrend'])}",
             "inline":True},
            {"name":"💹  NIFTY PE (Trailing TTM)",
             "value":f"Value  : **{_f(pe)}**\nRule   : PE < 25\nScore  : {_s(scores['pe'])}",
             "inline":True},
            {"name":"\u200b","value":"\u200b","inline":True},
            {"name":"😨  India VIX (Current)",
             "value":f"Value  : **{_f(vix_now)}**\nRule   : VIX < 25\nScore  : {_s(scores['vix_level'])}",
             "inline":True},
            {"name":"📅  VIX 1-Month Change",
             "value":(f"Now    : **{_f(vix_now)}**\n1M ago : **{_f(vix_1m_ago)}**\n"
                      f"Change : **{chg_s}**\nRule   : VIX<18 & Δ<40%\nScore  : {_s(scores['vix_spike'])}"),
             "inline":True},
            {"name":"\u200b","value":"\u200b","inline":True},
            {"name":"─────────────────────────────────────",
             "value":f"**Score  →  {total} / {max_sc}  [ {bar} ]**\n**Mode   →  {emoji}  {market_mode}**",
             "inline":False},
            {"name":"📝  Summary",
             "value":(f"• Trend **{'BULLISH' if st_status=='ABOVE' else 'BEARISH'}** — "
                      f"price {'above' if st_status=='ABOVE' else 'below'} weekly ST({_f(st_value)}); PE {pe} → {pe_tag}.\n"
                      f"• VIX {vix_now} ({chg_s} vs 1M ago) — {vix_tag}."),
             "inline":False}
        ],
        "footer":{"text":"ST: Yahoo Finance (computed 10,3 weekly) · PE: nifty-pe-ratio.com · VIX: Yahoo Finance | Saturdays 4:30 PM IST"},
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    }]}


# ──────────────────────────────────────────────────────────────
# DISCORD POSTER
# ──────────────────────────────────────────────────────────────
def post_to_discord(payload):
    if DISCORD_WEBHOOK_URL == "YOUR_DISCORD_WEBHOOK_URL_HERE":
        print("\n" + "═"*60)
        print("  ⚠️  WEBHOOK NOT SET")
        print("  Edit line 44:  DISCORD_WEBHOOK_URL = 'https://discord.com/api/webhooks/...'")
        print("═"*60)
        return False
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload,
                          headers={"Content-Type":"application/json"}, timeout=15)
        if r.status_code in (200, 204):
            print("\n  ✅  Successfully posted to Discord!")
            return True
        print(f"\n  ❌  Discord error {r.status_code}: {r.text}")
        return False
    except Exception as e:
        print(f"\n  ❌  {e}")
        return False


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────
def run():
    print("\n" + "═"*60)
    print("  Market Regime Indicator — Fetching data...")
    print("═"*60)

    print("\n  [1/5] Fetching NIFTY 50 price...")
    nifty_price, price_date = fetch_nifty_price()
    print(f"        → Rs.{nifty_price} ({price_date})")

    print("  [2/5] Computing Supertrend (10,3) weekly...")
    st_status, st_value, _ = compute_supertrend_weekly()
    print(f"        → {st_status}  |  Line: {st_value}")

    print("  [3/5] Fetching NIFTY PE (Trailing TTM)...")
    pe = fetch_nifty_pe()
    print(f"        → {pe}")

    print("  [4/5] Fetching India VIX (current)...")
    vix_now = fetch_india_vix()
    print(f"        → {vix_now}")

    print("  [5/5] Fetching India VIX (1 month ago)...")
    vix_1m_ago = fetch_india_vix_1m_ago()

    scores, details, total, max_sc, mode, color = compute_scores(
        st_status, pe, vix_now, vix_1m_ago)
    chg = details.get("vix_change_pct")

    print("\n" + "═"*60)
    print(f"  Supertrend (10,3)  : {st_status}        Score {scores['supertrend']}")
    print(f"  NIFTY PE (TTM)     : {pe}              Score {scores['pe']}")
    print(f"  India VIX Level    : {vix_now}          Score {scores['vix_level']}")
    print(f"  VIX 1M Change      : {chg}%        Score {scores['vix_spike']}")
    print(f"  {'-'*38}")
    print(f"  TOTAL SCORE        : {total} / {max_sc}")
    print(f"  MARKET MODE        : {'[AGGRESSIVE]' if mode=='AGGRESSIVE' else '[DEFENSIVE]'}")
    print("═"*60)

    embed = build_embed(nifty_price, price_date, st_status, st_value, pe,
                        vix_now, vix_1m_ago, scores, details, total, max_sc, mode, color)
    post_to_discord(embed)


# ──────────────────────────────────────────────────────────────
# SCHEDULER — every Saturday 4:30 PM IST
# ──────────────────────────────────────────────────────────────
def start_scheduler():
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
        import pytz
    except ImportError:
        print("Run: pip install apscheduler pytz")
        sys.exit(1)

    IST = pytz.timezone("Asia/Kolkata")
    sched = BlockingScheduler(timezone=IST)
    sched.add_job(run, CronTrigger(day_of_week="sat", hour=16, minute=30, timezone=IST))
    print("\n  Scheduler active — posts every Saturday 4:30 PM IST")
    print("  Press Ctrl+C to stop\n")
    run()   # run once on startup
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n  Stopped.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "schedule":
        start_scheduler()
    else:
        run()