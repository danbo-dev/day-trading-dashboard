"""
screener.py — Pre-market screener. Runs at 8:00 AM MT via GitHub Actions.
Filters S&P500 + NASDAQ100 universe to top 15 day-trade candidates.
Writes watchlist.json for the dashboard to consume.
"""
import json, logging, sys
from datetime import datetime
from pathlib import Path
from data_fetcher import get_universe, batch_screener_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
WATCHLIST_PATH = Path(__file__).parent / "watchlist.json"


def screener_score(row: dict) -> float:
    gap   = min(abs(row["gap_pct"]), 10.0) / 10.0
    rvol  = min(row["rvol"], 5.0) / 5.0
    atr_n = min(row["atr"] / row["price"], 0.05) / 0.05
    return (gap * 0.45) + (rvol * 0.35) + (atr_n * 0.20)


def run_screener() -> list:
    logger.info("Fetching universe...")
    universe = get_universe()
    logger.info(f"Universe: {len(universe)} tickers")

    logger.info("Downloading batch data...")
    raw = batch_screener_data(universe)
    logger.info(f"Raw data: {len(raw)} tickers passed basic filters")

    filtered = []
    for sym, d in raw.items():
        if abs(d["gap_pct"]) < 0.5: continue   # loosened for mid-day
        if d["rvol"] < 0.8: continue            # loosened for mid-day
        score = screener_score(d)
        filtered.append({
            "symbol": sym,
            "price": round(d["price"], 2),
            "gap_pct": round(d["gap_pct"], 2),
            "rvol": round(d["rvol"], 2),
            "atr": round(d["atr"], 2),
            "avg_volume": d["avg_volume"],
            "screener_score": round(score, 4),
        })

    filtered.sort(key=lambda x: x["screener_score"], reverse=True)
    top = filtered[:15]

    logger.info(f"Top {len(top)} tickers:")
    for i, t in enumerate(top, 1):
        logger.info(f"  {i:2d}. {t['symbol']:<6} ${t['price']:>7.2f}  Gap:{t['gap_pct']:+.1f}%  RVOL:{t['rvol']:.1f}x  Score:{t['screener_score']:.3f}")
    return top


def save_watchlist(tickers: list) -> None:
    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "generated_at_mt": datetime.now().strftime("%Y-%m-%d %H:%M MT"),
        "count": len(tickers),
        "tickers": tickers,
    }
    WATCHLIST_PATH.write_text(json.dumps(output, indent=2))
    logger.info(f"Watchlist saved → {WATCHLIST_PATH}")


if __name__ == "__main__":
    try:
        results = run_screener()
        save_watchlist(results)
        sys.exit(0)
    except Exception as e:
        logger.error(f"Screener failed: {e}", exc_info=True)
        sys.exit(1)
