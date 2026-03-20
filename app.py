"""
app.py
======
Day Trading Confluence Dashboard — Streamlit app.

Features:
  - Loads today's screened tickers from data/screened_tickers.json
  - Fetches live intraday data every 3 minutes
  - Scores each ticker on Launchpad + Gap & Go setups
  - Shows signal strength with color coding
  - In-dashboard toast notifications when a ticker hits HIGH signal
  - Paper trade logger with running P&L scorecard
"""

import json
import time
import logging
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pytz
import streamlit as st

from data_fetcher import fetch_ticker_data
from signal_engine import score_ticker, SIGNAL_HIGH, SIGNAL_MEDIUM, SIGNAL_LOW

# ── Config ────────────────────────────────────────────────────────────────────
MT = pytz.timezone("America/Denver")
DATA_FILE   = Path(__file__).parent / "data" / "screened_tickers.json"
TRADES_FILE = Path(__file__).parent / "trades" / "paper_trades.csv"
REFRESH_SEC = 180   # 3 minutes

TIER_COLOR = {
    SIGNAL_HIGH:   "#00c853",
    SIGNAL_MEDIUM: "#ffab00",
    SIGNAL_LOW:    "#ff3d00",
}

logger = logging.getLogger(__name__)

# ── Page Setup ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Day Trading Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {font-size: 1.8rem; font-weight: 700; margin-bottom: 0;}
    .sub-header  {color: #888; font-size: 0.9rem; margin-top: 0;}
    .metric-box  {background: #1a1a2e; border-radius: 8px; padding: 12px 16px; margin: 4px 0;}
    .HIGH        {color: #00c853; font-weight: 700;}
    .MEDIUM      {color: #ffab00; font-weight: 700;}
    .LOW         {color: #ff3d00; font-weight: 600;}
    .score-bar   {height: 8px; border-radius: 4px; background: #333; margin-top: 4px;}
    .ticker-row  {border-bottom: 1px solid #2a2a3e; padding: 8px 0;}
    .stExpander  {border: 1px solid #2a2a3e !important;}
    div[data-testid="stMetricValue"] {font-size: 1.4rem !important;}
</style>
""", unsafe_allow_html=True)


# ── Session State ─────────────────────────────────────────────────────────────
if "live_data"        not in st.session_state: st.session_state.live_data        = {}
if "prev_tiers"       not in st.session_state: st.session_state.prev_tiers       = {}
if "last_refresh"     not in st.session_state: st.session_state.last_refresh     = 0
if "alert_queue"      not in st.session_state: st.session_state.alert_queue      = []
if "trades"           not in st.session_state: st.session_state.trades           = []
if "open_trade"       not in st.session_state: st.session_state.open_trade       = None
if "refreshing"       not in st.session_state: st.session_state.refreshing       = False


# ── Data Loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_screened_tickers() -> dict:
    if not DATA_FILE.exists():
        return {"tickers": [], "screened_at": "No screen run yet", "screen_date": ""}
    with open(DATA_FILE) as f:
        return json.load(f)


def load_trades() -> list[dict]:
    if not TRADES_FILE.exists():
        return []
    try:
        df = pd.read_csv(TRADES_FILE)
        return df.to_dict("records")
    except Exception:
        return []


def save_trade(trade: dict) -> None:
    TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
    trades = load_trades()
    trades.append(trade)
    pd.DataFrame(trades).to_csv(TRADES_FILE, index=False)


def refresh_live_data(screened: list[dict]) -> None:
    """Fetch live data for all tickers and detect new HIGH signals."""
    new_data = {}
    new_alerts = []

    for entry in screened:
        ticker = entry["ticker"]
        with st.spinner(f"Fetching {ticker}…"):
            live = fetch_ticker_data(entry)
            scored = score_ticker(live)
            live["signals"] = scored
            new_data[ticker] = live

            # Detect tier upgrades → notification
            prev_tier = st.session_state.prev_tiers.get(ticker)
            new_tier  = scored["best_tier"]
            if new_tier == SIGNAL_HIGH and prev_tier != SIGNAL_HIGH:
                new_alerts.append({
                    "ticker": ticker,
                    "setup":  scored["best_setup"],
                    "score":  scored["best_score"],
                    "price":  live.get("price"),
                })

    st.session_state.live_data    = new_data
    st.session_state.prev_tiers   = {t: d["signals"]["best_tier"] for t, d in new_data.items()}
    st.session_state.last_refresh = time.time()
    st.session_state.alert_queue  = new_alerts


# ── Helpers ───────────────────────────────────────────────────────────────────

def score_bar_html(score: float, color: str) -> str:
    width = max(int(score), 0)
    return f"""<div class="score-bar">
        <div style="width:{width}%; height:100%; border-radius:4px; background:{color};"></div>
    </div>"""


def tier_badge(tier: str) -> str:
    css = tier.split()[-1]  # HIGH / MEDIUM / LOW
    return f'<span class="{css}">{tier}</span>'


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚙️ Controls")

    auto_refresh = st.toggle("Auto-refresh (3 min)", value=True)
    if st.button("🔄 Refresh Now", use_container_width=True):
        screened_raw = load_screened_tickers()
        refresh_live_data(screened_raw.get("tickers", []))
        st.rerun()

    last = st.session_state.last_refresh
    if last:
        elapsed = int(time.time() - last)
        st.caption(f"Last refresh: {elapsed}s ago")

    st.divider()
    st.markdown("**Filter signals**")
    show_high   = st.checkbox("🟢 HIGH",   value=True)
    show_medium = st.checkbox("🟡 MEDIUM", value=True)
    show_low    = st.checkbox("🔴 LOW",    value=True)
    tier_filter = []
    if show_high:   tier_filter.append(SIGNAL_HIGH)
    if show_medium: tier_filter.append(SIGNAL_MEDIUM)
    if show_low:    tier_filter.append(SIGNAL_LOW)

    st.divider()
    screened_meta = load_screened_tickers()
    st.caption(f"**Screen date:** {screened_meta.get('screen_date','—')}")
    st.caption(f"**Tickers:** {screened_meta.get('count', 0)}")
    st.caption(f"**Screened at:** {screened_meta.get('screened_at','—')[:16]}")


# ── Auto-refresh Logic ────────────────────────────────────────────────────────

screened_raw = load_screened_tickers()
screened_tickers = screened_raw.get("tickers", [])

# Initial load
if not st.session_state.live_data and screened_tickers:
    refresh_live_data(screened_tickers)

# Auto-refresh check
if auto_refresh and (time.time() - st.session_state.last_refresh > REFRESH_SEC):
    refresh_live_data(screened_tickers)

# Show notifications for new HIGH signals
for alert in st.session_state.alert_queue:
    st.toast(
        f"🚨 {alert['ticker']} just hit {alert['setup']} HIGH signal @ ${alert['price']}",
        icon="🟢",
    )
st.session_state.alert_queue = []


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown('<p class="main-header">📈 Day Trading Confluence Dashboard</p>', unsafe_allow_html=True)
st.markdown(f'<p class="sub-header">{datetime.now(MT).strftime("%A, %B %d, %Y — %I:%M %p MT")} · Paper Trading Mode</p>', unsafe_allow_html=True)

# ── Main Signal Table ─────────────────────────────────────────────────────────

st.markdown("### 🎯 Today's Screened Tickers")

if not st.session_state.live_data:
    st.info("No live data yet. Click **Refresh Now** in the sidebar, or wait for auto-refresh.")
else:
    live = st.session_state.live_data

    # Build summary rows
    rows = []
    for ticker, data in live.items():
        sig = data.get("signals", {})
        tier = sig.get("best_tier", SIGNAL_LOW)
        if tier not in tier_filter:
            continue
        rows.append({
            "ticker":      ticker,
            "price":       data.get("price"),
            "day_chg":     data.get("day_change_pct"),
            "vwap":        data.get("vwap"),
            "pdh":         data.get("pdh"),
            "rvol":        data.get("rvol_live") or data.get("rvol"),
            "gap_pct":     data.get("gap_pct_open") or data.get("gap_pct"),
            "launchpad":   sig.get("launchpad", {}).get("score", 0),
            "gap_and_go":  sig.get("gap_and_go", {}).get("score", 0),
            "best_setup":  sig.get("best_setup"),
            "best_score":  sig.get("best_score", 0),
            "best_tier":   tier,
            "live":        data.get("live", False),
            "_data":       data,
        })

    rows.sort(key=lambda x: x["best_score"], reverse=True)

    if not rows:
        st.warning("No tickers match the current filter.")
    else:
        # Header row
        hc = st.columns([1, 1, 1, 1, 1, 1.2, 1.2, 1.5, 1])
        for col, label in zip(hc, ["Ticker", "Price", "Day%", "RVOL", "Gap%", "Launchpad", "Gap & Go", "Best Signal", "Action"]):
            col.markdown(f"**{label}**")
        st.divider()

        for row in rows:
            lp_color = TIER_COLOR[SIGNAL_HIGH if row["launchpad"] >= 75 else SIGNAL_MEDIUM if row["launchpad"] >= 50 else SIGNAL_LOW]
            gg_color = TIER_COLOR[SIGNAL_HIGH if row["gap_and_go"] >= 75 else SIGNAL_MEDIUM if row["gap_and_go"] >= 50 else SIGNAL_LOW]

            cols = st.columns([1, 1, 1, 1, 1, 1.2, 1.2, 1.5, 1])
            cols[0].markdown(f"**{row['ticker']}**" + (" 🔴" if not row["live"] else ""))
            cols[1].markdown(f"${row['price']:.2f}" if row["price"] else "—")

            chg = row["day_chg"]
            if chg is not None:
                color = "#00c853" if chg >= 0 else "#ff3d00"
                cols[2].markdown(f'<span style="color:{color}">{chg:+.1f}%</span>', unsafe_allow_html=True)
            else:
                cols[2].markdown("—")

            cols[3].markdown(f"{row['rvol']:.1f}x" if row["rvol"] else "—")
            
            gap = row["gap_pct"]
            if gap is not None:
                gcolor = "#00c853" if gap >= 0 else "#ff3d00"
                cols[4].markdown(f'<span style="color:{gcolor}">{gap:+.1f}%</span>', unsafe_allow_html=True)
            else:
                cols[4].markdown("—")

            # Score bars
            with cols[5]:
                st.markdown(f"**{row['launchpad']:.0f}**/100", unsafe_allow_html=True)
                st.markdown(score_bar_html(row["launchpad"], lp_color), unsafe_allow_html=True)

            with cols[6]:
                st.markdown(f"**{row['gap_and_go']:.0f}**/100", unsafe_allow_html=True)
                st.markdown(score_bar_html(row["gap_and_go"], gg_color), unsafe_allow_html=True)

            with cols[7]:
                tier_color = TIER_COLOR[row["best_tier"]]
                st.markdown(
                    f'<span style="color:{tier_color}; font-weight:700;">{row["best_tier"]}</span> '
                    f'<span style="color:#aaa; font-size:0.8rem;">({row["best_setup"]})</span>',
                    unsafe_allow_html=True,
                )

            with cols[8]:
                if st.button("Trade", key=f"trade_{row['ticker']}"):
                    st.session_state.open_trade = {
                        "ticker":    row["ticker"],
                        "price":     row["price"],
                        "setup":     row["best_setup"],
                        "timestamp": datetime.now(MT).isoformat(),
                    }

            # Expandable detail
            with st.expander(f"  Detail — {row['ticker']}", expanded=False):
                d = row["_data"]
                sig = d.get("signals", {})

                dcol1, dcol2 = st.columns(2)

                with dcol1:
                    st.markdown("**Launchpad Components**")
                    lp_comps = sig.get("launchpad", {}).get("components", {})
                    for k, v in lp_comps.items():
                        label = k.replace("_", " ").title()
                        pts = v.get("pts", 0)
                        detail = v.get("detail", "")
                        bar_color = "#00c853" if pts >= 20 else "#ffab00" if pts >= 10 else "#555"
                        st.markdown(f"**{label}**: {pts}/25 — {detail}")
                        st.markdown(score_bar_html(pts / 25 * 100, bar_color), unsafe_allow_html=True)

                with dcol2:
                    st.markdown("**Gap & Go Components**")
                    gg_comps = sig.get("gap_and_go", {}).get("components", {})
                    for k, v in gg_comps.items():
                        label = k.replace("_", " ").title()
                        pts = v.get("pts", 0)
                        detail = v.get("detail", "")
                        bar_color = "#00c853" if pts >= 20 else "#ffab00" if pts >= 10 else "#555"
                        st.markdown(f"**{label}**: {pts}/25 — {detail}")
                        st.markdown(score_bar_html(pts / 25 * 100, bar_color), unsafe_allow_html=True)

                st.markdown("---")
                kc = st.columns(4)
                kc[0].metric("VWAP",       f"${d.get('vwap', 0):.2f}"  if d.get("vwap") else "N/A")
                kc[1].metric("PDH",        f"${d.get('pdh', 0):.2f}"   if d.get("pdh") else "N/A")
                kc[2].metric("PDL",        f"${d.get('pdl', 0):.2f}"   if d.get("pdl") else "N/A")
                kc[3].metric("Call Floor", f"${d.get('call_support',0):.2f}" if d.get("call_support") else "N/A")

        st.caption(f"Auto-refreshes every {REFRESH_SEC//60} minutes · Last: {datetime.fromtimestamp(st.session_state.last_refresh, MT).strftime('%I:%M:%S %p MT') if st.session_state.last_refresh else '—'}")


# ── Paper Trade Entry Modal ───────────────────────────────────────────────────

if st.session_state.open_trade:
    ot = st.session_state.open_trade
    st.divider()
    st.markdown(f"### 📝 Log Paper Trade — {ot['ticker']}")

    with st.form("trade_entry_form"):
        fc1, fc2, fc3, fc4 = st.columns(4)
        direction   = fc1.selectbox("Direction", ["Long", "Short"])
        entry_price = fc2.number_input("Entry Price", value=float(ot["price"] or 0), step=0.01)
        shares      = fc3.number_input("Shares", min_value=1, value=100, step=10)
        setup       = fc4.selectbox("Setup", ["Launchpad", "Gap & Go"], index=0 if ot["setup"] == "Launchpad" else 1)

        fc5, fc6 = st.columns(2)
        exit_price = fc5.number_input("Exit Price (0 = still open)", min_value=0.0, value=0.0, step=0.01)
        notes      = fc6.text_input("Notes", placeholder="e.g. broke above PDH on volume")

        sc1, sc2 = st.columns(2)
        submitted  = sc1.form_submit_button("✅ Log Trade", use_container_width=True)
        cancelled  = sc2.form_submit_button("✖ Cancel",   use_container_width=True)

    if submitted:
        pnl = 0.0
        status = "Open"
        if exit_price > 0:
            if direction == "Long":
                pnl = (exit_price - entry_price) * shares
            else:
                pnl = (entry_price - exit_price) * shares
            status = "Win" if pnl > 0 else "Loss"

        trade = {
            "date":        date.today().isoformat(),
            "time":        datetime.now(MT).strftime("%H:%M"),
            "ticker":      ot["ticker"],
            "direction":   direction,
            "setup":       setup,
            "entry_price": entry_price,
            "exit_price":  exit_price if exit_price > 0 else "",
            "shares":      shares,
            "pnl":         round(pnl, 2),
            "status":      status,
            "notes":       notes,
        }
        save_trade(trade)
        st.session_state.trades = load_trades()
        st.session_state.open_trade = None
        st.success(f"Trade logged! P&L: ${pnl:+.2f}")
        st.rerun()

    if cancelled:
        st.session_state.open_trade = None
        st.rerun()


# ── Paper Trade Scorecard ─────────────────────────────────────────────────────

st.divider()
st.markdown("### 🏆 Paper Trade Scorecard")

trades = load_trades()
if not trades:
    st.info("No paper trades logged yet. Use the **Trade** button on any ticker to log your first trade.")
else:
    df = pd.DataFrame(trades)

    # Summary metrics
    closed = df[df["status"].isin(["Win", "Loss"])]
    total_pnl   = df["pnl"].sum()
    win_rate    = len(closed[closed["status"] == "Win"]) / len(closed) * 100 if len(closed) > 0 else 0
    avg_winner  = closed[closed["pnl"] > 0]["pnl"].mean() if len(closed[closed["pnl"] > 0]) > 0 else 0
    avg_loser   = closed[closed["pnl"] < 0]["pnl"].mean() if len(closed[closed["pnl"] < 0]) > 0 else 0
    rr_ratio    = abs(avg_winner / avg_loser) if avg_loser != 0 else 0

    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
    pnl_color = "#00c853" if total_pnl >= 0 else "#ff3d00"
    mc1.metric("Total P&L",   f"${total_pnl:+.2f}")
    mc2.metric("Win Rate",    f"{win_rate:.0f}%")
    mc3.metric("Avg Winner",  f"${avg_winner:+.2f}")
    mc4.metric("Avg Loser",   f"${avg_loser:+.2f}")
    mc5.metric("Reward/Risk", f"{rr_ratio:.2f}x")

    # Setup breakdown
    if "setup" in df.columns and len(closed) > 0:
        st.markdown("**Performance by Setup**")
        setup_stats = closed.groupby("setup").agg(
            Trades=("pnl", "count"),
            Total_PnL=("pnl", "sum"),
            Win_Rate=("status", lambda x: (x == "Win").mean() * 100),
        ).reset_index()
        st.dataframe(setup_stats.style.format({"Total_PnL": "${:.2f}", "Win_Rate": "{:.0f}%"}), use_container_width=True)

    # Trade log
    with st.expander("📋 Full Trade Log", expanded=False):
        display_df = df[["date", "time", "ticker", "direction", "setup", "entry_price", "exit_price", "shares", "pnl", "status", "notes"]].copy()
        st.dataframe(display_df, use_container_width=True)

    # Cumulative P&L chart
    if len(closed) > 1:
        closed_sorted = closed.copy()
        closed_sorted["cumulative_pnl"] = closed_sorted["pnl"].cumsum()
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=list(range(len(closed_sorted))),
            y=closed_sorted["cumulative_pnl"],
            mode="lines+markers",
            line=dict(color="#4fc3f7", width=2),
            marker=dict(
                color=["#00c853" if p > 0 else "#ff3d00" for p in closed_sorted["pnl"]],
                size=8,
            ),
            name="Cumulative P&L",
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="#555")
        fig.update_layout(
            title="Cumulative Paper P&L",
            paper_bgcolor="#0e1117",
            plot_bgcolor="#0e1117",
            font_color="#ccc",
            height=300,
            margin=dict(l=40, r=20, t=40, b=30),
        )
        st.plotly_chart(fig, use_container_width=True)

# ── Auto-refresh countdown ────────────────────────────────────────────────────
if auto_refresh:
    elapsed = time.time() - (st.session_state.last_refresh or time.time())
    remaining = max(REFRESH_SEC - int(elapsed), 0)
    st.caption(f"⏱ Next auto-refresh in {remaining}s")
    time.sleep(1)
    st.rerun()
