"""
screener.py — Pre-market screener. Runs at 8:00 AM MT via GitHub Actions.

Two-step process:
  Step 1: Fast daily-bar filter on full S&P500+NASDAQ100 universe → top 50 by ATR/volume
  Step 2: Pull real pre-market 1-min intraday data for those 50 → get actual gap % and pre-market RVOL
  Final:  Score and return top 15 by composite score

This ensures the gap % and RVOL figures reflect actual pre-market activity,
not incomplete daily bars, giving much more meaningful morning watchlists.
"""
import json, logging, sys, pytz
from datetime import datetime
from pathlib import Path
from data_fetcher import get_universe, batch_daily_filter, get_premarket_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
WATCHLIST_PATH = Path(__file__).parent / "watchlist.json"
MT = pytz.timezone("America/Denver")


def screener_score(row: dict) -> float:
    """
    Composite score for ranking. Weights:
      - Pre-market RVOL: 40% — most important, reflects real institutional activity
      - Gap %:           35% — overnight catalyst strength
      - ATR as % price:  25% — intraday range potential
    """
    pm_rvol = min(row.get("pre_market_rvol", row.get("rvol", 1.0)), 5.0) / 5.0
    gap     = min(abs(row["gap_pct"]), 10.0) / 10.0
    atr_n   = min(row["atr"] / row["price"], 0.05) / 0.05 if row["price"] > 0 else 0
    return (pm_rvol * 0.40) + (gap * 0.35) + (atr_n * 0.25)


def run_screener() -> list:
    logger.info("=" * 50)
    logger.info("PRE-MARKET SCREENER — Two-Step Process")
    logger.info("=" * 50)

    # Step 1: fetch universe and daily filter
    logger.info("Step 1: Fetching universe...")
    universe = get_universe()
    logger.info(f"Universe: {len(universe)} tickers")

    logger.info("Step 1: Daily-bar filter → selecting top 50 candidates...")
    candidates = batch_daily_filter(universe)
    logger.info(f"Step 1 complete: {len(candidates)} candidates selected")

    if not candidates:
        logger.warning("No candidates passed daily filter — returning empty watchlist")
        return []

    # Step 2: pull real pre-market intraday data
    logger.info("Step 2: Pulling pre-market intraday data...")
    enriched = get_premarket_data(candidates)
    logger.info(f"Step 2 complete: {len(enriched)} tickers enriched")

    # Score and rank
    scored = []
    for sym, d in enriched.items():
        score = screener_score(d)
        scored.append({
            "symbol": sym,
            "price": round(d["price"], 2),
            "gap_pct": round(d["gap_pct"], 2),
            "rvol": round(d.get("rvol", 1.0), 2),
            "pre_market_rvol": round(d.get("pre_market_rvol", 0.0), 2),
            "pre_market_volume": d.get("pre_market_volume", 0),
            "atr": round(d["atr"], 2),
            "avg_volume": d["avg_volume"],
            "screener_score": round(score, 4),
        })

    scored.sort(key=lambda x: x["screener_score"], reverse=True)
    top = scored[:15]

    logger.info(f"\nTop {len(top)} tickers for today:")
    logger.info(f"{'#':<3} {'Sym':<6} {'Price':>8} {'Gap':>8} {'PM RVOL':>8} {'ATR':>6} {'Score':>7}")
    logger.info("-" * 55)
    for i, t in enumerate(top, 1):
        logger.info(
            f"{i:<3} {t['symbol']:<6} ${t['price']:>7.2f} "
            f"{t['gap_pct']:>+7.1f}% {t['pre_market_rvol']:>7.1f}x "
            f"${t['atr']:>5.2f} {t['screener_score']:>7.3f}"
        )

    return top


def save_watchlist(tickers: list) -> None:
    now_mt = datetime.now(MT).strftime("%Y-%m-%d %H:%M MT")
    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "generated_at_mt": now_mt,
        "count": len(tickers),
        "tickers": tickers,
    }
    WATCHLIST_PATH.write_text(json.dumps(output, indent=2))
    logger.info(f"\nWatchlist saved → {WATCHLIST_PATH} at {now_mt}")


if __name__ == "__main__":
    try:
        results = run_screener()
        save_watchlist(results)
        logger.info("Screener complete.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Screener failed: {e}", exc_info=True)
        sys.exit(1)
