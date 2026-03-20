"""
dashboard.py
============
Day Trading Confluence Dashboard — Streamlit local app.

Run with:
    streamlit run dashboard.py

Auto-refreshes every 3 minutes during market hours.
Reads watchlist.json locally (updated each morning by the GitHub Actions screener).
Fetches live intraday data directly from yfinance for scoring.
Polls signals.json from GitHub to catch cloud-detected signals.
Includes a paper trade logger with P&L tracking.
"""

import json
import time
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import pytz
from streamlit_autorefresh import st_autorefresh

from data_fetcher import get_ticker_snapshot, market_status, TickerSnapshot
from confluence_scorer import (
    score_ticker, scores_to_dict, TickerScores,
    SIGNAL_STRONG, SIGNAL_MODERATE,
)

# ─── Config ───────────────────────────────────────────────────────────────────

WATCHLIST_PATH    = Path(__file__).parent / "watchlist.json"
PAPER_TRADES_PATH = Path(__file__).parent / "paper_trades.json"
SIGNALS_PATH      = Path(__file__).parent / "signals.json"

# Replace with your GitHub username/repo after setup
GITHUB_RAW_SIGNALS_URL = (
    "https://raw.githubusercontent.com/YOUR_GITHUB_USERNAME/"
    "day-trading-dashboard/main/signals.json"
)

REFRESH_INTERVAL_MS = 3 * 60 * 1000   # 3 minutes
MT = pytz.timezone("America/Denver")
ET = pytz.timezone("America/New_York")

logging.basicConfig(level=logging.WARNING)

# ─── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Day Trading Dashboard",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ───────────────────────────────────────────────────────────────

st.markdown("""
<style>
    .main-title { font-size: 2rem; font-weight: 700; margin-bottom: 0; }
    .subtitle   { color: #888; font-size: 0.9rem; margin-bottom: 1.5rem; }
    .metric-card {
        background: #1a1a2e;
        border: 1px solid #333;
        border-radius: 12px;
        padding: 1rem 1.2rem;
        margin-bottom: 0.75rem;
    }
    .ticker-name { font-size: 1.4rem; font-weight: 700; }
    .price-tag   { font-size: 1.1rem; color: #aaa; }
    .score-bar-bg {
        background: #2a2a3e;
        border-radius: 6px;
        height: 10px;
        width: 100%;
        margin: 4px 0;
    }
    .score-bar-fill {
        height: 10px;
        border-radius: 6px;
    }
    .signal-strong   { color: #00e676; font-weight: 700; }
    .signal-moderate { color: #ffd600; font-weight: 600; }
    .signal-weak     { color: #ef5350; }
    .new-signal-banner {
        background: linear-gradient(90deg, #00e676 0%, #1de9b6 100%);
        color: #000;
        padding: 0.75rem 1.2rem;
        border-radius: 10px;
        font-weight: 700;
        font-size: 1rem;
        margin-bottom: 1rem;
    }
    .stButton button {
        border-radius: 8px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)


# ─── Session state init ───────────────────────────────────────────────────────

def _init_state():
    defaults = {
        "scores_cache": {},         # symbol -> TickerScores
        "last_fetch_time": None,
        "seen_strong_signals": set(),
        "new_signal_banner": None,
        "loading": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ─── Data helpers ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_watchlist() -> dict:
    if not WATCHLIST_PATH.exists():
        return {"tickers": [], "generated_at_mt": "Not yet generated"}
    return json.loads(WATCHLIST_PATH.read_text())


def load_paper_trades() -> list[dict]:
    if not PAPER_TRADES_PATH.exists():
        return []
    try:
        return json.loads(PAPER_TRADES_PATH.read_text())
    except Exception:
        return []


def save_paper_trades(trades: list[dict]) -> None:
    PAPER_TRADES_PATH.write_text(json.dumps(trades, indent=2))


def fetch_cloud_signals() -> Optional[dict]:
    """Fetch the latest signals.json from GitHub (fallback to local)."""
    try:
        r = requests.get(GITHUB_RAW_SIGNALS_URL, timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    # Fallback to local file
    if SIGNALS_PATH.exists():
        try:
            return json.loads(SIGNALS_PATH.read_text())
        except Exception:
            pass
    return None


def _color_for_score(score: float) -> str:
    if score >= SIGNAL_STRONG:
        return "#00e676"
    if score >= SIGNAL_MODERATE:
        return "#ffd600"
    return "#ef5350"


def _badge(label: str) -> str:
    if label == "STRONG":
        return '<span class="signal-strong">🟢 STRONG</span>'
    if label == "MODERATE":
        return '<span class="signal-moderate">🟡 MODERATE</span>'
    return '<span class="signal-weak">🔴 WEAK</span>'


def _score_bar_html(score: float) -> str:
    pct = score / 10.0 * 100
    color = _color_for_score(score)
    return (
        f'<div class="score-bar-bg">'
        f'<div class="score-bar-fill" style="width:{pct:.0f}%;background:{color};"></div>'
        f'</div>'
    )


# ─── Sidebar ──────────────────────────────────────────────────────────────────

def render_sidebar():
    st.sidebar.markdown("## ⚙️ Controls")

    status = market_status()
    status_emoji = {"OPEN": "🟢", "PRE-MARKET": "🟡", "AFTER-HOURS": "🟠", "CLOSED": "⚫"}
    st.sidebar.markdown(
        f"**Market:** {status_emoji.get(status, '⚫')} {status}"
    )

    now_mt = datetime.now(MT).strftime("%H:%M MT")
    st.sidebar.markdown(f"**Time:** {now_mt}")

    wl = load_watchlist()
    st.sidebar.markdown(
        f"**Screener ran:** {wl.get('generated_at_mt', 'Not yet run')}"
    )
    st.sidebar.markdown(f"**Tickers tracked:** {len(wl.get('tickers', []))}")

    st.sidebar.divider()
    st.sidebar.markdown("**Auto-refresh every 3 min**")
    if st.sidebar.button("🔄 Refresh Now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.divider()
    st.sidebar.markdown("## 📘 Score Guide")
    st.sidebar.markdown("""
| Score | Signal |
|-------|--------|
| ≥ 7.5 | 🟢 Strong |
| ≥ 5.0 | 🟡 Moderate |
| < 5.0 | 🔴 Weak |
""")
    st.sidebar.markdown("""
**Launchpad:**
Price above VWAP + PDH + riding EMA with volume drying up

**Gap & Go:**
Gap > 2% above PDH, pre-market volume surge, holding VWAP
""")


# ─── Ticker card ──────────────────────────────────────────────────────────────

def render_ticker_card(sym: str, scores: Optional[TickerScores], snap: Optional[TickerSnapshot]):
    if scores is None or snap is None:
        st.markdown(f"""
        <div class="metric-card">
            <span class="ticker-name">{sym}</span>
            <span class="price-tag"> — Loading...</span>
        </div>""", unsafe_allow_html=True)
        return

    change_color = "#00e676" if snap.day_change_pct >= 0 else "#ef5350"
    change_sign = "+" if snap.day_change_pct >= 0 else ""

    with st.container():
        st.markdown(f"""
        <div class="metric-card">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem;">
                <span class="ticker-name">{sym}</span>
                <span style="font-size:1.2rem; font-weight:600;">${snap.price:.2f}
                    <span style="color:{change_color}; font-size:0.9rem;">
                        {change_sign}{snap.day_change_pct:.1f}%
                    </span>
                </span>
            </div>
            <div style="margin-bottom:0.4rem; font-size:0.85rem; color:#aaa;">
                VWAP ${snap.vwap:.2f} &nbsp;|&nbsp;
                PDH ${snap.pdh:.2f} &nbsp;|&nbsp;
                RVOL {snap.rvol:.1f}x &nbsp;|&nbsp;
                Gap {'+' if snap.gap_pct >= 0 else ''}{snap.gap_pct:.1f}%
            </div>
        """, unsafe_allow_html=True)

        col1, col2 = st.columns(2)

        with col1:
            st.markdown(f"""
            <div style="font-size:0.8rem; color:#aaa; margin-bottom:2px;">
                🚀 Launchpad &nbsp; {_badge(scores.launchpad.signal_label)}
            </div>
            {_score_bar_html(scores.launchpad.total)}
            <div style="font-size:1rem; font-weight:700; color:{_color_for_score(scores.launchpad.total)};">
                {scores.launchpad.total:.1f} / 10
            </div>
            """, unsafe_allow_html=True)

        with col2:
            st.markdown(f"""
            <div style="font-size:0.8rem; color:#aaa; margin-bottom:2px;">
                ⚡ Gap & Go &nbsp; {_badge(scores.gap_and_go.signal_label)}
            </div>
            {_score_bar_html(scores.gap_and_go.total)}
            <div style="font-size:1rem; font-weight:700; color:{_color_for_score(scores.gap_and_go.total)};">
                {scores.gap_and_go.total:.1f} / 10
            </div>
            """, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

        # Expandable rationale
        with st.expander(f"📋 {sym} Score Breakdown"):
            tab1, tab2 = st.tabs(["🚀 Launchpad", "⚡ Gap & Go"])
            with tab1:
                for r in scores.launchpad.rationale:
                    st.markdown(f"- {r}")
                _mini_score_table({
                    "VWAP Position": scores.launchpad.vwap_points,
                    "PDH Reclaim": scores.launchpad.pdh_points,
                    "EMA Proximity": scores.launchpad.ema_points,
                    "Volume Dry-up": scores.launchpad.volume_points,
                    "EMA Stack": scores.launchpad.ema_stack_points,
                }, max_pts=[2.5, 2.5, 2.0, 1.5, 1.5])
            with tab2:
                for r in scores.gap_and_go.rationale:
                    st.markdown(f"- {r}")
                _mini_score_table({
                    "Gap Size": scores.gap_and_go.gap_size_points,
                    "Gap > PDH": scores.gap_and_go.gap_above_pdh_points,
                    "Pre-Mkt RVOL": scores.gap_and_go.pre_market_rvol_points,
                    "VWAP Hold": scores.gap_and_go.vwap_hold_points,
                    "Intraday RVOL": scores.gap_and_go.intraday_rvol_points,
                }, max_pts=[3.0, 2.0, 2.0, 2.0, 1.0])


def _mini_score_table(components: dict, max_pts: list):
    rows = []
    for (name, pts), mx in zip(components.items(), max_pts):
        pct = pts / mx * 100 if mx > 0 else 0
        bar = f"{'█' * int(pct / 10)}{'░' * (10 - int(pct / 10))}"
        rows.append({"Component": name, "Score": f"{pts:.2f}/{mx:.1f}", "Bar": bar})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


# ─── Paper Trade Logger ───────────────────────────────────────────────────────

def render_paper_trades():
    st.markdown("## 📝 Paper Trade Logger")

    trades = load_paper_trades()

    # New trade form
    with st.expander("➕ Log New Trade", expanded=False):
        wl = load_watchlist()
        ticker_options = [t["symbol"] for t in wl.get("tickers", [])]

        c1, c2, c3 = st.columns(3)
        with c1:
            sym = st.selectbox("Ticker", ticker_options or ["—"])
            direction = st.selectbox("Direction", ["LONG", "SHORT"])
        with c2:
            entry_price = st.number_input("Entry Price ($)", min_value=0.0, step=0.01, format="%.2f")
            shares = st.number_input("Shares", min_value=1, step=1)
        with c3:
            setup = st.selectbox("Setup", ["Launchpad", "Gap & Go", "Other"])
            exit_price = st.number_input("Exit Price ($) — 0 if still open", min_value=0.0, step=0.01, format="%.2f")

        notes = st.text_input("Notes (optional)")

        if st.button("✅ Log Trade", use_container_width=True):
            if sym and entry_price > 0 and shares > 0:
                pnl = None
                if exit_price > 0:
                    if direction == "LONG":
                        pnl = round((exit_price - entry_price) * shares, 2)
                    else:
                        pnl = round((entry_price - exit_price) * shares, 2)

                trade = {
                    "id": len(trades) + 1,
                    "date": date.today().isoformat(),
                    "symbol": sym,
                    "direction": direction,
                    "setup": setup,
                    "entry": entry_price,
                    "exit": exit_price if exit_price > 0 else None,
                    "shares": shares,
                    "pnl": pnl,
                    "status": "CLOSED" if exit_price > 0 else "OPEN",
                    "notes": notes,
                    "logged_at": datetime.utcnow().isoformat(),
                }
                trades.append(trade)
                save_paper_trades(trades)
                st.success(f"Trade logged! {'P&L: $' + str(pnl) if pnl is not None else 'Still open.'}")
                st.rerun()

    # Close open trade
    open_trades = [t for t in trades if t["status"] == "OPEN"]
    if open_trades:
        with st.expander(f"🔒 Close Open Trade ({len(open_trades)} open)", expanded=False):
            trade_labels = [f"#{t['id']} {t['symbol']} {t['direction']} @ ${t['entry']}" for t in open_trades]
            selected_label = st.selectbox("Select trade to close", trade_labels)
            selected_id = int(selected_label.split("#")[1].split(" ")[0])
            close_price = st.number_input("Exit Price ($)", min_value=0.0, step=0.01, format="%.2f", key="close_price")
            if st.button("Close Trade"):
                for t in trades:
                    if t["id"] == selected_id:
                        t["exit"] = close_price
                        t["status"] = "CLOSED"
                        if t["direction"] == "LONG":
                            t["pnl"] = round((close_price - t["entry"]) * t["shares"], 2)
                        else:
                            t["pnl"] = round((t["entry"] - close_price) * t["shares"], 2)
                save_paper_trades(trades)
                st.rerun()

    # Trade table
    if trades:
        df = pd.DataFrame(trades)
        display_cols = ["id", "date", "symbol", "direction", "setup",
                        "entry", "exit", "shares", "pnl", "status", "notes"]
        df = df[[c for c in display_cols if c in df.columns]]
        df["pnl"] = df["pnl"].apply(lambda x: f"${x:+.2f}" if x is not None else "—")

        st.dataframe(
            df.sort_values("id", ascending=False),
            hide_index=True,
            use_container_width=True,
        )

        # P&L summary
        closed = [t for t in trades if t["status"] == "CLOSED" and t["pnl"] is not None]
        if closed:
            st.markdown("### 📊 Performance Summary")
            pnls = [t["pnl"] for t in closed]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Total P&L", f"${sum(pnls):+.2f}")
            m2.metric("Win Rate", f"{len(wins)/len(closed)*100:.0f}%")
            m3.metric("Avg Winner", f"${sum(wins)/len(wins):.2f}" if wins else "—")
            m4.metric("Avg Loser",  f"${sum(losses)/len(losses):.2f}" if losses else "—")
            m5.metric("Trades", str(len(closed)))

            # P&L by setup
            st.markdown("**By Setup:**")
            setup_pnl: dict[str, list] = {}
            for t in closed:
                setup_pnl.setdefault(t.get("setup", "Other"), []).append(t["pnl"])
            setup_rows = [
                {
                    "Setup": s,
                    "Trades": len(v),
                    "Total P&L": f"${sum(v):+.2f}",
                    "Win Rate": f"{sum(1 for x in v if x > 0)/len(v)*100:.0f}%",
                }
                for s, v in setup_pnl.items()
            ]
            st.dataframe(pd.DataFrame(setup_rows), hide_index=True, use_container_width=True)
    else:
        st.info("No trades logged yet. Use the form above to log your first paper trade.")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    # Auto-refresh
    st_autorefresh(interval=REFRESH_INTERVAL_MS, limit=None, key="main_refresh")

    render_sidebar()

    st.markdown('<div class="main-title">🎯 Day Trading Confluence Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Launchpad & Gap & Go signals — Paper Trading Mode</div>', unsafe_allow_html=True)

    # Check cloud signals for new strong signal banners
    cloud = fetch_cloud_signals()
    if cloud:
        new_signals = cloud.get("new_strong_signals", [])
        for sig in new_signals:
            key = f"{sig['symbol']}_{sig.get('score', 0):.1f}"
            if key not in st.session_state["seen_strong_signals"]:
                st.session_state["seen_strong_signals"].add(key)
                st.markdown(f"""
                <div class="new-signal-banner">
                    🔔 NEW STRONG SIGNAL — {sig['symbol']}
                    &nbsp;|&nbsp; {sig['setup']} &nbsp;|&nbsp;
                    Score: {sig['score']:.1f}/10 &nbsp;|&nbsp;
                    Price: ${sig['price']:.2f}
                </div>""", unsafe_allow_html=True)

    # Load watchlist
    wl = load_watchlist()
    symbols = [t["symbol"] for t in wl.get("tickers", [])]

    if not symbols:
        st.warning(
            "⏳ No tickers in today's watchlist yet. "
            "The pre-market screener runs at 8:00 AM MT on weekdays. "
            "Check back after that, or manually trigger the screener from GitHub Actions."
        )
        render_paper_trades()
        return

    # Market status header
    status = market_status()
    now_mt = datetime.now(MT).strftime("%H:%M:%S MT")
    col_status, col_time = st.columns([1, 1])
    with col_status:
        if status == "OPEN":
            st.success(f"🟢 Market OPEN — refreshing every 3 min")
        elif status == "PRE-MARKET":
            st.info(f"🟡 Pre-Market — data may be limited")
        else:
            st.warning(f"⚫ Market {status}")
    with col_time:
        st.markdown(f"**Last update:** {now_mt}")

    st.divider()

    # Fetch and score each ticker
    st.markdown(f"### Today's Watchlist ({len(symbols)} tickers)")

    # Progress bar during initial load
    if not st.session_state["scores_cache"]:
        progress_text = "Loading live data..."
        pb = st.progress(0, text=progress_text)

    snaps: dict[str, TickerSnapshot] = {}
    scores_map: dict[str, TickerScores] = {}

    for i, sym in enumerate(symbols):
        snap = get_ticker_snapshot(sym)
        snaps[sym] = snap
        if not snap.error:
            scores_map[sym] = score_ticker(snap)
        if not st.session_state["scores_cache"]:
            pb.progress((i + 1) / len(symbols), text=f"Loading {sym}...")

    if not st.session_state["scores_cache"]:
        pb.empty()

    st.session_state["scores_cache"] = scores_map
    st.session_state["last_fetch_time"] = now_mt

    # Sort by best score descending
    sorted_syms = sorted(
        symbols,
        key=lambda s: scores_map[s].best_score if s in scores_map else 0,
        reverse=True,
    )

    # Render cards in 2-column grid
    for i in range(0, len(sorted_syms), 2):
        cols = st.columns(2)
        for j, col in enumerate(cols):
            if i + j < len(sorted_syms):
                sym = sorted_syms[i + j]
                with col:
                    render_ticker_card(
                        sym,
                        scores_map.get(sym),
                        snaps.get(sym),
                    )

    st.divider()
    render_paper_trades()

    # Footer
    st.markdown(
        f'<div style="color:#555; font-size:0.75rem; text-align:center; margin-top:1rem;">'
        f'Data via Yahoo Finance (15–20 min delayed) · '
        f'For paper trading only · Last update {now_mt}'
        f'</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
