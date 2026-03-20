"""
signal_monitor.py
=================
Intraday signal monitor. Runs every 5 minutes during market hours via
GitHub Actions. Reads today's watchlist.json, fetches live snapshots,
scores each ticker, and writes results to signals.json.

The local Streamlit dashboard reads signals.json from the GitHub raw URL
every refresh cycle and shows a notification banner when a new strong
signal appears.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytz

from data_fetcher import get_ticker_snapshot, market_status
from confluence_scorer import score_ticker, scores_to_dict, SIGNAL_STRONG, SIGNAL_MODERATE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

WATCHLIST_PATH = Path(__file__).parent / "watchlist.json"
SIGNALS_PATH   = Path(__file__).parent / "signals.json"
MT = pytz.timezone("America/Denver")


def load_watchlist() -> list[str]:
    """Load today's screened tickers from watchlist.json."""
    if not WATCHLIST_PATH.exists():
        logger.warning("watchlist.json not found — using empty list")
        return []
    data = json.loads(WATCHLIST_PATH.read_text())
    return [t["symbol"] for t in data.get("tickers", [])]


def load_existing_signals() -> dict:
    """Load the current signals.json to detect new signals."""
    if not SIGNALS_PATH.exists():
        return {}
    try:
        return json.loads(SIGNALS_PATH.read_text())
    except Exception:
        return {}


def run_monitor() -> None:
    status = market_status()
    now_mt = datetime.now(MT).strftime("%Y-%m-%d %H:%M MT")

    logger.info(f"Market status: {status} | {now_mt}")

    if status not in ("OPEN", "PRE-MARKET"):
        logger.info("Market not active — writing status-only output")
        _write_signals([], status, now_mt)
        return

    symbols = load_watchlist()
    if not symbols:
        logger.warning("No tickers in watchlist")
        _write_signals([], status, now_mt)
        return

    logger.info(f"Scoring {len(symbols)} tickers: {symbols}")
    existing = load_existing_signals()
    prev_strong = set(
        s for s, d in existing.get("signals", {}).items()
        if d.get("best_score", 0) >= SIGNAL_STRONG
    )

    signals = {}
    new_strong = []

    for sym in symbols:
        logger.info(f"  Fetching {sym}...")
        snap = get_ticker_snapshot(sym)

        if snap.error:
            logger.warning(f"  {sym}: error — {snap.error}")
            continue

        scored = score_ticker(snap)
        d = scores_to_dict(scored)
        signals[sym] = d

        # Detect newly strong signals (crossed threshold since last run)
        if scored.best_score >= SIGNAL_STRONG and sym not in prev_strong:
            new_strong.append({
                "symbol": sym,
                "score": scored.best_score,
                "setup": scored.best_setup,
                "price": snap.price,
            })
            logger.info(f"  🔔 NEW STRONG SIGNAL: {sym} — {scored.best_setup} {scored.best_score:.1f}/10")
        else:
            logger.info(
                f"  {sym}: LP={scored.launchpad.total:.1f} "
                f"GG={scored.gap_and_go.total:.1f} "
                f"[{scored.best_setup}]"
            )

    _write_signals(signals, status, now_mt, new_strong)
    logger.info(f"✅ signals.json updated — {len(signals)} tickers scored")


def _write_signals(
    signals: dict | list,
    market_status_str: str,
    timestamp: str,
    new_strong: list | None = None,
) -> None:
    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_at_mt": timestamp,
        "market_status": market_status_str,
        "new_strong_signals": new_strong or [],
        "signal_count": len(signals) if isinstance(signals, dict) else 0,
        "signals": signals if isinstance(signals, dict) else {},
    }
    SIGNALS_PATH.write_text(json.dumps(output, indent=2))


if __name__ == "__main__":
    try:
        run_monitor()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Monitor failed: {e}", exc_info=True)
        sys.exit(1)
