"""
data_fetcher.py
===============
Fetches and calculates intraday market data for the dashboard.

For each screened ticker provides:
  - Live price, day change
  - VWAP (calculated from 1-min bars since open)
  - 9 EMA and 20 EMA (intraday, from 1-min bars)
  - PDH / PDL (from screener or re-fetched)
  - Gap % from prior close to today's open
  - Current RVOL (today's volume vs 20-day avg at this time of day)
  - Nearest high-OI options strikes (call support / put resistance)
"""

import logging
from datetime import datetime, time as dtime
from typing import Optional

import numpy as np
import pandas as pd
import pytz
import yfinance as yf

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")
MT = pytz.timezone("America/Denver")

MARKET_OPEN_ET  = dtime(9, 30)
MARKET_CLOSE_ET = dtime(16, 0)


# ── VWAP ──────────────────────────────────────────────────────────────────────

def calculate_vwap(df_1m: pd.DataFrame) -> Optional[float]:
    """
    VWAP = cumsum(typical_price * volume) / cumsum(volume)
    Only uses bars from market open onward.
    """
    try:
        df = df_1m.copy()
        df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert(ET)

        # Only bars from 9:30 AM ET today
        today = datetime.now(ET).date()
        mask = (
            (df.index.date == today) &
            (df.index.time >= MARKET_OPEN_ET)
        )
        df = df[mask]
        if df.empty:
            return None

        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        cum_vol = df["Volume"].cumsum()
        if cum_vol.iloc[-1] == 0:
            return None
        vwap = (typical * df["Volume"]).cumsum() / cum_vol
        return round(float(vwap.iloc[-1]), 2)
    except Exception as e:
        logger.debug(f"VWAP error: {e}")
        return None


# ── Intraday EMA ──────────────────────────────────────────────────────────────

def calculate_intraday_ema(df_1m: pd.DataFrame, period: int) -> Optional[float]:
    """EMA of intraday close prices over `period` bars."""
    try:
        close = df_1m["Close"].dropna()
        if len(close) < period:
            return None
        ema = close.ewm(span=period, adjust=False).mean()
        return round(float(ema.iloc[-1]), 2)
    except Exception as e:
        logger.debug(f"EMA error: {e}")
        return None


# ── Gap % ─────────────────────────────────────────────────────────────────────

def calculate_gap_pct(ticker_obj: yf.Ticker, prev_close: float) -> Optional[float]:
    """Gap = (today's open - prev close) / prev close * 100"""
    try:
        hist = ticker_obj.history(period="2d", interval="1d", prepost=False)
        if len(hist) < 1:
            return None
        today_open = float(hist["Open"].iloc[-1])
        if prev_close == 0:
            return None
        return round((today_open - prev_close) / prev_close * 100, 2)
    except Exception as e:
        logger.debug(f"Gap error: {e}")
        return None


# ── RVOL ─────────────────────────────────────────────────────────────────────

def calculate_rvol(df_1m: pd.DataFrame, avg_daily_volume: int) -> Optional[float]:
    """
    RVOL = today's volume so far / expected volume at this time of day.
    Expected = avg_daily_volume * (minutes_elapsed / 390)
    """
    try:
        df = df_1m.copy()
        df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert(ET)

        today = datetime.now(ET).date()
        mask = (df.index.date == today) & (df.index.time >= MARKET_OPEN_ET)
        todays = df[mask]
        if todays.empty or avg_daily_volume == 0:
            return None

        now_et = datetime.now(ET).time()
        open_minutes = max(
            (datetime.combine(today, now_et) - datetime.combine(today, MARKET_OPEN_ET)).seconds // 60,
            1
        )
        expected_vol = avg_daily_volume * (open_minutes / 390)
        todays_vol = float(todays["Volume"].sum())
        return round(todays_vol / expected_vol, 2) if expected_vol > 0 else None
    except Exception as e:
        logger.debug(f"RVOL error: {e}")
        return None


# ── Options OI ────────────────────────────────────────────────────────────────

def get_options_levels(ticker_obj: yf.Ticker, current_price: float) -> dict:
    """
    Returns the nearest high-OI call strike below price (support)
    and high-OI put strike above price (resistance), within 5% of price.
    """
    result = {"call_support": None, "put_resistance": None, "call_oi": 0, "put_oi": 0}
    try:
        exps = ticker_obj.options
        if not exps:
            return result

        # Use nearest expiry
        chain = ticker_obj.option_chain(exps[0])
        calls = chain.calls[["strike", "openInterest"]].dropna()
        puts  = chain.puts[["strike", "openInterest"]].dropna()

        price_low  = current_price * 0.95
        price_high = current_price * 1.05

        # Best call support: highest OI call strike BELOW current price (within 5%)
        call_candidates = calls[
            (calls["strike"] >= price_low) & (calls["strike"] <= current_price)
        ].sort_values("openInterest", ascending=False)
        if not call_candidates.empty:
            result["call_support"] = round(float(call_candidates.iloc[0]["strike"]), 2)
            result["call_oi"] = int(call_candidates.iloc[0]["openInterest"])

        # Best put resistance: highest OI put strike ABOVE current price (within 5%)
        put_candidates = puts[
            (puts["strike"] >= current_price) & (puts["strike"] <= price_high)
        ].sort_values("openInterest", ascending=False)
        if not put_candidates.empty:
            result["put_resistance"] = round(float(put_candidates.iloc[0]["strike"]), 2)
            result["put_oi"] = int(put_candidates.iloc[0]["openInterest"])

    except Exception as e:
        logger.debug(f"Options OI error: {e}")

    return result


# ── Master Fetch ──────────────────────────────────────────────────────────────

def fetch_ticker_data(screener_entry: dict) -> dict:
    """
    Fetches all intraday data for a single ticker.
    Returns a merged dict of screener data + live intraday data.
    """
    ticker = screener_entry["ticker"]
    data = dict(screener_entry)  # start with screener baseline

    try:
        t = yf.Ticker(ticker)

        # 1-min intraday data
        df_1m = t.history(period="1d", interval="1m", prepost=False)

        if df_1m.empty:
            data["live"] = False
            return data

        # Current price
        data["price"]      = round(float(df_1m["Close"].iloc[-1]), 2)
        data["day_volume"] = int(df_1m["Volume"].sum())

        # VWAP
        data["vwap"] = calculate_vwap(df_1m)

        # Intraday EMAs
        data["ema9_intraday"]  = calculate_intraday_ema(df_1m, 9)
        data["ema20_intraday"] = calculate_intraday_ema(df_1m, 20)

        # Gap %
        data["gap_pct_open"] = calculate_gap_pct(t, screener_entry.get("prev_close", 0))

        # RVOL (live)
        data["rvol_live"] = calculate_rvol(df_1m, screener_entry.get("avg_volume", 1))

        # Options levels
        opts = get_options_levels(t, data["price"])
        data.update(opts)

        # Day change %
        prev = screener_entry.get("prev_close", data["price"])
        data["day_change_pct"] = round((data["price"] - prev) / prev * 100, 2) if prev else 0

        data["live"] = True
        data["last_updated"] = datetime.now(MT).strftime("%I:%M:%S %p MT")

    except Exception as e:
        logger.warning(f"Failed to fetch live data for {ticker}: {e}")
        data["live"] = False

    return data
