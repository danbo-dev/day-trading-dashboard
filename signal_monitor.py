"""
signal_monitor.py — Intraday signal monitor. Runs every 5 min via GitHub Actions.
Reads watchlist.json, scores each ticker, writes signals.json.
"""
import json, logging, sys
from datetime import datetime, timezone
from pathlib import Path
import pytz
from data_fetcher import get_ticker_snapshot, market_status
from confluence_scorer import score_ticker, scores_to_dict, SIGNAL_STRONG

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
WATCHLIST_PATH = Path(__file__).parent / "watchlist.json"
SIGNALS_PATH   = Path(__file__).parent / "signals.json"
MT = pytz.timezone("America/Denver")


def load_watchlist() -> list:
    if not WATCHLIST_PATH.exists():
        return []
    return [t["symbol"] for t in json.loads(WATCHLIST_PATH.read_text()).get("tickers", [])]


def load_existing_signals() -> dict:
    if not SIGNALS_PATH.exists():
        return {}
    try:
        data = json.loads(SIGNALS_PATH.read_text())
        # Handle case where file contains a list instead of dict
        if isinstance(data, list):
            return {}
        return data
    except Exception:
        return {}

def run_monitor():
    status = market_status()
    now_mt = datetime.now(MT).strftime("%Y-%m-%d %H:%M MT")
    logger.info(f"Market: {status} | {now_mt}")

    if status not in ("OPEN", "PRE-MARKET"):
        _write([], status, now_mt)
        return

    symbols = load_watchlist()
    if not symbols:
        _write([], status, now_mt)
        return

    existing = load_existing_signals()
    prev_strong = {s for s, d in existing.get("signals", {}).items() if d.get("best_score", 0) >= SIGNAL_STRONG}

    signals, new_strong = {}, []
    for sym in symbols:
        snap = get_ticker_snapshot(sym)
        if snap.error:
            logger.warning(f"{sym}: {snap.error}")
            continue
        scored = score_ticker(snap)
        signals[sym] = scores_to_dict(scored)
        if scored.best_score >= SIGNAL_STRONG and sym not in prev_strong:
            new_strong.append({"symbol": sym, "score": scored.best_score,
                               "setup": scored.best_setup, "price": snap.price})
            logger.info(f"🔔 NEW STRONG SIGNAL: {sym} — {scored.best_setup} {scored.best_score:.1f}/10")
        else:
            logger.info(f"{sym}: LP={scored.launchpad.total:.1f} GG={scored.gap_and_go.total:.1f}")

    _write(signals, status, now_mt, new_strong)
    logger.info(f"signals.json updated — {len(signals)} tickers")


def _write(signals, status, ts, new_strong=None):
    SIGNALS_PATH.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_at_mt": ts,
        "market_status": status,
        "new_strong_signals": new_strong or [],
        "signal_count": len(signals),
        "signals": signals,
    }, indent=2))


if __name__ == "__main__":
    try:
        run_monitor()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Monitor failed: {e}", exc_info=True)
        sys.exit(1)
