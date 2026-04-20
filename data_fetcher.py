"""
data_fetcher.py — All yfinance interactions for the day trading dashboard.
Handles intraday data, pre-market data, daily OHLCV, EMAs, VWAP, ATR, PDH/PDL.
"""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
import logging, pytz, time

logger = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")
MT = pytz.timezone("America/Denver")


@dataclass
class TickerSnapshot:
    symbol: str
    price: float
    prev_close: float
    day_change_pct: float
    gap_pct: float
    volume_today: int
    avg_volume_20d: int
    rvol: float
    pre_market_volume: int
    avg_pre_market_volume: int
    pre_market_rvol: float
    vwap: float
    pdh: float
    pdl: float
    prev_close_val: float
    ema9: float
    ema20: float
    ema50: float
    atr: float
    high_today: float
    low_today: float
    open_today: float
    week_52_high: float
    week_52_low: float
    above_vwap: bool
    above_pdh: bool
    above_ema9: bool
    above_ema20: bool
    ema_stack_bullish: bool
    gap_above_pdh: bool
    timestamp: datetime = field(default_factory=datetime.utcnow)
    error: Optional[str] = None


def get_universe() -> list:
    try:
        sp500 = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            flavor="lxml"
        )[0]["Symbol"].tolist()
        sp500 = [s.replace(".", "-") for s in sp500]
        try:
            ndx_tables = pd.read_html(
                "https://en.wikipedia.org/wiki/Nasdaq-100",
                flavor="lxml"
            )
            ndx = []
            for t in ndx_tables:
                if "Ticker" in t.columns:
                    ndx = t["Ticker"].tolist()
                    break
        except Exception:
            ndx = []
        combined = list(set(sp500 + ndx))
        logger.info(f"Universe: {len(combined)} tickers")
        return combined
    except Exception as e:
        logger.warning(f"Universe fetch failed ({e}), using fallback")
        return [
            "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","AMD","ORCL",
            "NFLX","ADBE","QCOM","TXN","CRM","NOW","PLTR","PANW","CRWD","ZS",
            "JPM","GS","MS","BAC","V","MA","UNH","LLY","ABBV","AMGN",
            "XOM","CVX","COP","HD","COST","WMT","NKE","SBUX","MCD","CMG",
            "BA","CAT","HON","LMT","RTX","GE","UPS","FDX","UBER","ABNB",
            "SHOP","SNOW","DDOG","NET","COIN","MSTR","ARM","SMCI","MU","AMAT",
            "LRCX","KLAC","MRVL","DELL","HPQ","IBM","CSCO","INTC","F","GM",
            "PFE","MRK","JNJ","BMY","GILD","REGN","MRNA","ABBV","TMO","WFC",
            "C","AXP","PYPL","BKNG","ABNB","UBER","LYFT","DASH","SNAP","PINS",
        ]


def calculate_vwap(intraday: pd.DataFrame) -> float:
    try:
        df = intraday.copy()
        if df.index.tzinfo is None:
            df.index = df.index.tz_localize("UTC")
        df = df.tz_convert(ET)
        df = df[df.index.time >= pd.Timestamp("09:30").time()]
        if df.empty:
            return float("nan")
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        return float((typical * df["Volume"]).cumsum().iloc[-1] / df["Volume"].cumsum().iloc[-1])
    except Exception:
        return float("nan")


def calculate_atr(daily: pd.DataFrame, period: int = 14) -> float:
    try:
        h, l, c = daily["High"], daily["Low"], daily["Close"].shift(1)
        tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
        return float(tr.rolling(period).mean().iloc[-1])
    except Exception:
        return float("nan")


def batch_daily_filter(symbols: list) -> list:
    """
    Step 1 of two-step screener: fast daily-bar filter.
    Downloads 30d daily bars for all symbols in batches.
    Returns top 50 candidates ranked by ATR and avg volume.
    These are candidates for the slower pre-market intraday pull.
    """
    candidates = []
    batch_size = 50

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        try:
            raw = yf.download(
                batch, period="30d", interval="1d",
                group_by="ticker", auto_adjust=True,
                progress=False, threads=True
            )
            for sym in batch:
                try:
                    df = raw[sym] if len(batch) > 1 and sym in raw.columns.get_level_values(0) \
                        else (raw if len(batch) == 1 else pd.DataFrame())
                    if df.empty or len(df) < 5:
                        continue

                    price = float(df["Close"].iloc[-1])
                    if price < 10 or price > 75:
                        continue
                    # ATR must be at least 1.5% of price (replaces flat $0.75 ATR floor)
                    atr_pct_check = atr / price if price > 0 else 0
                    if atr_pct_check < 0.015:
                        continue

                    avg_vol = int(df["Volume"].iloc[-21:-1].mean())
                    if avg_vol < 1_000_000:
                        continue

                    h, l, c = df["High"], df["Low"], df["Close"].shift(1)
                    tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
                    atr = float(tr.rolling(14).mean().iloc[-1])
                    if atr < 0.75:
                        continue

                    # Rank by ATR as % of price (volatility) + avg volume
                    atr_pct = atr / price
                    vol_score = min(avg_vol / 5_000_000, 1.0)
                    rank_score = (atr_pct * 0.6) + (vol_score * 0.4)

                    candidates.append({
                        "symbol": sym,
                        "price": round(price, 2),
                        "avg_volume": avg_vol,
                        "atr": round(atr, 2),
                        "atr_pct": round(atr_pct, 4),
                        "rank_score": round(rank_score, 4),
                        "prev_close": float(df["Close"].iloc[-2]),
                    })
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Batch {i // batch_size + 1} failed: {e}")

        if i + batch_size < len(symbols):
            time.sleep(0.3)

    # Sort by rank score and return top 50
    candidates.sort(key=lambda x: x["rank_score"], reverse=True)
    top50 = candidates[:50]
    logger.info(f"Daily filter: {len(candidates)} passed → top {len(top50)} selected for pre-market pull")
    return top50


def get_premarket_data(candidates: list) -> dict:
    """
    Step 2 of two-step screener: pull real pre-market intraday data.
    For each candidate, fetches 1-min bars with prepost=True to get
    actual pre-market price and volume for today.
    Returns dict of symbol -> enriched data.
    """
    results = {}
    symbols = [c["symbol"] for c in candidates]
    candidate_map = {c["symbol"]: c for c in candidates}

    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            intraday = ticker.history(
                period="1d", interval="1m",
                prepost=True, auto_adjust=True
            )

            if intraday.empty:
                # Fall back to daily data gap estimate
                c = candidate_map[sym]
                results[sym] = {**c, "gap_pct": 0.0, "rvol": 1.0,
                                 "pre_market_rvol": 0.0, "pre_market_volume": 0}
                continue

            if intraday.index.tzinfo is None:
                intraday.index = intraday.index.tz_localize("UTC")
            intraday_et = intraday.tz_convert(ET)

            # Split pre-market vs regular hours
            pre_mask = intraday_et.index.time < pd.Timestamp("09:30").time()
            reg_mask = intraday_et.index.time >= pd.Timestamp("09:30").time()

            pre_bars = intraday_et[pre_mask]
            reg_bars = intraday_et[reg_mask]

            prev_close = candidate_map[sym]["prev_close"]
            avg_vol = candidate_map[sym]["avg_volume"]

            # Pre-market price is the last pre-market bar close
            if not pre_bars.empty:
                pre_price = float(pre_bars["Close"].iloc[-1])
                pre_vol = int(pre_bars["Volume"].sum())
            else:
                pre_price = prev_close
                pre_vol = 0

            # Gap % = pre-market price vs prior close
            gap_pct = ((pre_price - prev_close) / prev_close * 100) if prev_close else 0

            # Pre-market RVOL = pre vol vs avg pre-market vol (est. 15% of daily)
            avg_pre_vol = int(avg_vol * 0.15)
            pre_rvol = pre_vol / avg_pre_vol if avg_pre_vol > 0 else 0.0

            # Intraday RVOL if market is open
            if not reg_bars.empty:
                now_et = datetime.now(ET)
                mins_open = max(1, (now_et.hour * 60 + now_et.minute) - 570)
                reg_vol = int(reg_bars["Volume"].sum())
                prorated_avg = avg_vol * (mins_open / 390)
                rvol = reg_vol / prorated_avg if prorated_avg > 0 else 1.0
                current_price = float(reg_bars["Close"].iloc[-1])
            else:
                rvol = pre_rvol
                current_price = pre_price
                reg_vol = 0

            results[sym] = {
                **candidate_map[sym],
                "price": round(current_price, 2),
                "gap_pct": round(gap_pct, 2),
                "rvol": round(rvol, 2),
                "pre_market_rvol": round(pre_rvol, 2),
                "pre_market_volume": pre_vol,
                "volume_today": reg_vol,
            }

        except Exception as e:
            logger.debug(f"Pre-market pull failed for {sym}: {e}")
            # Include with defaults so it's not lost entirely
            c = candidate_map[sym]
            results[sym] = {**c, "gap_pct": 0.0, "rvol": 1.0,
                             "pre_market_rvol": 0.0, "pre_market_volume": 0}

        time.sleep(0.1)  # Light rate limiting

    logger.info(f"Pre-market data fetched for {len(results)} tickers")
    return results


def batch_screener_data(symbols: list) -> dict:
    """
    Legacy single-step screener — kept for compatibility.
    Now calls the two-step process internally.
    """
    candidates = batch_daily_filter(symbols)
    return get_premarket_data(candidates)


def get_ticker_snapshot(symbol: str) -> TickerSnapshot:
    try:
        ticker = yf.Ticker(symbol)
        daily = ticker.history(period="60d", interval="1d", auto_adjust=True)
        if len(daily) < 3:
            raise ValueError("Insufficient history")
        yearly = ticker.history(period="1y", interval="1d", auto_adjust=True)
        week_52_high = float(yearly["High"].max())
        week_52_low = float(yearly["Low"].min())

        pdh = float(daily["High"].iloc[-2])
        pdl = float(daily["Low"].iloc[-2])
        prev_close_val = float(daily["Close"].iloc[-2])

        closes = daily["Close"]
        ema9  = float(closes.ewm(span=9,  adjust=False).mean().iloc[-1])
        ema20 = float(closes.ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(closes.ewm(span=50, adjust=False).mean().iloc[-1])
        atr   = calculate_atr(daily)
        avg_vol = int(daily["Volume"].iloc[-21:-1].mean())

        intraday = ticker.history(period="1d", interval="1m", prepost=True, auto_adjust=True)
        if intraday.empty:
            price = float(daily["Close"].iloc[-1])
            open_today = high_today = low_today = price
            volume_today = int(daily["Volume"].iloc[-1])
            vwap = price
            pre_market_vol = 0
        else:
            if intraday.index.tzinfo is None:
                intraday.index = intraday.index.tz_localize("UTC")
            intraday_et = intraday.tz_convert(ET)
            pre_mask = intraday_et.index.time < pd.Timestamp("09:30").time()
            reg_mask = intraday_et.index.time >= pd.Timestamp("09:30").time()
            pre_market_vol = int(intraday_et[pre_mask]["Volume"].sum())
            reg = intraday_et[reg_mask]
            if not reg.empty:
                price = float(reg["Close"].iloc[-1])
                open_today = float(reg["Open"].iloc[0])
                high_today = float(reg["High"].max())
                low_today  = float(reg["Low"].min())
                volume_today = int(reg["Volume"].sum())
            else:
                pm = intraday_et[pre_mask]
                price = float(pm["Close"].iloc[-1]) if not pm.empty else prev_close_val
                open_today = high_today = low_today = price
                volume_today = 0
            vwap = calculate_vwap(intraday_et)
            if np.isnan(vwap):
                vwap = price

        gap_pct = (open_today - prev_close_val) / prev_close_val * 100 if prev_close_val else 0
        day_change_pct = (price - prev_close_val) / prev_close_val * 100 if prev_close_val else 0
        now_et = datetime.now(ET)
        mins = max(1, (now_et.hour * 60 + now_et.minute) - 570)
        rvol = (volume_today / (avg_vol * mins / 390)) if avg_vol > 0 else 1.0
        avg_pre = int(avg_vol * 0.15)
        pre_rvol = pre_market_vol / avg_pre if avg_pre > 0 else 1.0

        return TickerSnapshot(
            symbol=symbol, price=price, prev_close=prev_close_val,
            day_change_pct=day_change_pct, gap_pct=gap_pct,
            volume_today=volume_today, avg_volume_20d=avg_vol, rvol=rvol,
            pre_market_volume=pre_market_vol, avg_pre_market_volume=avg_pre,
            pre_market_rvol=pre_rvol, vwap=vwap, pdh=pdh, pdl=pdl,
            prev_close_val=prev_close_val, ema9=ema9, ema20=ema20, ema50=ema50,
            atr=atr, high_today=high_today, low_today=low_today, open_today=open_today,
            week_52_high=week_52_high, week_52_low=week_52_low,
            above_vwap=price > vwap, above_pdh=price > pdh,
            above_ema9=price > ema9, above_ema20=price > ema20,
            ema_stack_bullish=ema9 > ema20 > ema50, gap_above_pdh=open_today > pdh,
        )
    except Exception as e:
        logger.warning(f"Snapshot failed for {symbol}: {e}")
        return TickerSnapshot(
            symbol=symbol, price=0, prev_close=0, day_change_pct=0, gap_pct=0,
            volume_today=0, avg_volume_20d=0, rvol=0, pre_market_volume=0,
            avg_pre_market_volume=0, pre_market_rvol=0, vwap=0, pdh=0, pdl=0,
            prev_close_val=0, ema9=0, ema20=0, ema50=0, atr=0,
            high_today=0, low_today=0, open_today=0, week_52_high=0, week_52_low=0,
            above_vwap=False, above_pdh=False, above_ema9=False, above_ema20=False,
            ema_stack_bullish=False, gap_above_pdh=False, error=str(e)
        )


def market_status() -> str:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return "CLOSED"
    t = now.time()
    if pd.Timestamp("04:00").time() <= t < pd.Timestamp("09:30").time():
        return "PRE-MARKET"
    if pd.Timestamp("09:30").time() <= t <= pd.Timestamp("16:00").time():
        return "OPEN"
    if pd.Timestamp("16:00").time() < t <= pd.Timestamp("20:00").time():
        return "AFTER-HOURS"
    return "CLOSED"
