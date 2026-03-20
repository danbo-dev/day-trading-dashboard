"""
screener.py
===========
Pre-market screener — runs via GitHub Actions at 8:00 AM MT (14:00 UTC) weekdays.

Filters S&P 500 + NASDAQ 100 down to the day's top 10-15 candidates using:
  - Price: $10-$150
  - Avg daily volume > 1,000,000
  - Gap >= 1.5% (up or down) from prior close
  - Relative Volume >= 1.3x 20-day avg
  - ATR >= 1.5% of price (sufficient range for intraday moves)
  - EMA stack alignment

Output: data/screened_tickers.json (committed by GitHub Actions)
"""

import json, logging, time
from datetime import datetime, date
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import pytz

from universe import get_universe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

MIN_PRICE       = 10.0
MAX_PRICE       = 150.0
MIN_AVG_VOLUME  = 1_000_000
MIN_ATR_PCT     = 1.5
MAX_CANDIDATES  = 15
DATA_FILE       = Path(__file__).parent / "data" / "screened_tickers.json"


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def atr(high, low, close, period=14):
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]

def ema_stack(close):
    if len(close) < 55:
        return 0.5
    e9, e20, e50 = ema(close,9).iloc[-1], ema(close,20).iloc[-1], ema(close,50).iloc[-1]
    p = close.iloc[-1]
    return sum([p > e9, e9 > e20, e20 > e50]) / 3.0


def screen_universe():
    tickers = get_universe()
    logger.info(f"Screening {len(tickers)} tickers ...")

    BATCH = 100
    all_data = {}
    for i in range(0, len(tickers), BATCH):
        batch = tickers[i:i+BATCH]
        logger.info(f"  Batch {i//BATCH+1}/{-(-len(tickers)//BATCH)} ...")
        try:
            raw = yf.download(
                " ".join(batch), period="65d", interval="1d",
                group_by="ticker", auto_adjust=True,
                prepost=False, threads=True, progress=False
            )
            if len(batch) == 1:
                if not raw.empty:
                    all_data[batch[0]] = raw
            else:
                for t in batch:
                    try:
                        df = raw[t].dropna(how="all")
                        if not df.empty:
                            all_data[t] = df
                    except (KeyError, TypeError):
                        pass
        except Exception as e:
            logger.error(f"Batch error: {e}")
        time.sleep(0.5)

    logger.info(f"Downloaded {len(all_data)} tickers")
    candidates = []

    for ticker, df in all_data.items():
        try:
            if len(df) < 21:
                continue
            close  = df["Close"]
            high   = df["High"]
            low    = df["Low"]
            volume = df["Volume"]

            last_close = float(close.iloc[-1])
            prev_close = float(close.iloc[-2])

            if not (MIN_PRICE <= last_close <= MAX_PRICE):
                continue

            avg_vol = float(volume.iloc[-21:-1].mean())
            if avg_vol < MIN_AVG_VOLUME:
                continue

            atr_val = float(atr(high, low, close))
            atr_pct = (atr_val / last_close) * 100
            if atr_pct < MIN_ATR_PCT:
                continue

            gap_pct  = ((last_close - prev_close) / prev_close) * 100
            last_vol = float(volume.iloc[-1])
            rvol     = last_vol / avg_vol if avg_vol > 0 else 1.0
            es       = ema_stack(close)

            e9   = float(ema(close, 9).iloc[-1])
            e20  = float(ema(close, 20).iloc[-1])
            e50  = float(ema(close, 50).iloc[-1])
            pdh  = float(high.iloc[-2])
            pdl  = float(low.iloc[-2])
            w52h = float(high.rolling(252).max().iloc[-1])
            w52l = float(low.rolling(252).min().iloc[-1])

            gap_s  = min(abs(gap_pct) / 5.0, 1.0) * 30
            rvol_s = min((rvol - 1.0) / 2.0, 1.0) * 30
            ema_s  = es * 20
            atr_s  = min((atr_pct - MIN_ATR_PCT) / 3.0, 1.0) * 20
            score  = gap_s + rvol_s + ema_s + atr_s

            candidates.append({
                "ticker": ticker, "price": round(last_close, 2),
                "prev_close": round(prev_close, 2), "gap_pct": round(gap_pct, 2),
                "rvol": round(rvol, 2), "avg_volume": int(avg_vol),
                "atr": round(atr_val, 2), "atr_pct": round(atr_pct, 2),
                "ema9": round(e9, 2), "ema20": round(e20, 2), "ema50": round(e50, 2),
                "ema_stack": round(es, 2), "pdh": round(pdh, 2), "pdl": round(pdl, 2),
                "w52_high": round(w52h, 2), "w52_low": round(w52l, 2),
                "composite_score": round(score, 1),
            })
        except Exception as e:
            logger.debug(f"Skip {ticker}: {e}")

    candidates.sort(key=lambda x: x["composite_score"], reverse=True)
    top = candidates[:MAX_CANDIDATES]
    logger.info(f"Selected {len(top)} candidates")
    for c in top:
        logger.info(f"  {c['ticker']:6s}  ${c['price']:6.2f}  gap={c['gap_pct']:+.1f}%  rvol={c['rvol']:.1f}x  score={c['composite_score']:.0f}")
    return top


def save_results(candidates):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "screened_at": datetime.now(pytz.timezone("America/Denver")).isoformat(),
        "screen_date": date.today().isoformat(),
        "count": len(candidates),
        "tickers": candidates,
    }
    with open(DATA_FILE, "w") as f:
        json.dump(output, f, indent=2)
    logger.info(f"Saved -> {DATA_FILE}")


if __name__ == "__main__":
    candidates = screen_universe()
    save_results(candidates)
    print(f"\n✅ Done — {len(candidates)} tickers saved")
