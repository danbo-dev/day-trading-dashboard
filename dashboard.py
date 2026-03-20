"""
dashboard.py — Day Trading Confluence Dashboard
Run: streamlit run dashboard.py
Auto-refreshes every 3 min. Reads watchlist.json locally, fetches live
intraday data from yfinance, scores against Launchpad & Gap & Go setups,
and polls signals.json from GitHub for cloud-detected strong signals.
Includes a paper trade logger with P&L tracking.
"""
import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import streamlit as st
import pandas as pd
import requests
import pytz
from streamlit_autorefresh import st_autorefresh

from data_fetcher import get_ticker_snapshot, market_status, TickerSnapshot
from confluence_scorer import score_ticker, scores_to_dict, TickerScores, SIGNAL_STRONG, SIGNAL_MODERATE

# ── Config ────────────────────────────────────────────────────────────────────
WATCHLIST_PATH    = Path(__file__).parent / "watchlist.json"
PAPER_TRADES_PATH = Path(__file__).parent / "paper_trades.json"
SIGNALS_PATH      = Path(__file__).parent / "signals.json"
GITHUB_RAW_SIGNALS_URL = (
    "https://raw.githubusercontent.com/danbo-dev/"
    "day-trading-dashboard/main/signals.json"
)
GITHUB_RAW_WATCHLIST_URL = (
    "https://raw.githubusercontent.com/danbo-dev/"
    "day-trading-dashboard/main/watchlist.json"
)
REFRESH_MS = 3 * 60 * 1000
MT = pytz.timezone("America/Denver")

st.set_page_config(page_title="Day Trading Dashboard", page_icon="🎯", layout="wide")

st.markdown("""
<style>
.metric-card{background:#1a1a2e;border:1px solid #2a2a4e;border-radius:12px;padding:1rem 1.2rem;margin-bottom:.75rem}
.ticker-sym{font-size:1.4rem;font-weight:700}
.score-bar-bg{background:#2a2a3e;border-radius:6px;height:10px;width:100%;margin:4px 0}
.score-bar-fill{height:10px;border-radius:6px}
.signal-strong{color:#00e676;font-weight:700}
.signal-moderate{color:#ffd600;font-weight:600}
.signal-weak{color:#ef5350}
.banner{background:linear-gradient(90deg,#00e676,#1de9b6);color:#000;padding:.75rem 1.2rem;border-radius:10px;font-weight:700;margin-bottom:1rem}
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
for k, v in {"seen_signals": set()}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Helpers ───────────────────────────────────────────────────────────────────
@st.cache_data(ttl=180)
def load_watchlist():
    try:
        r = requests.get(GITHUB_RAW_WATCHLIST_URL, timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    if WATCHLIST_PATH.exists():
        return json.loads(WATCHLIST_PATH.read_text())
    return {"tickers": [], "generated_at_mt": "Not yet generated"}

def load_paper_trades():
    if not PAPER_TRADES_PATH.exists(): return []
    try: return json.loads(PAPER_TRADES_PATH.read_text())
    except: return []

def save_paper_trades(trades):
    PAPER_TRADES_PATH.write_text(json.dumps(trades, indent=2))

def fetch_cloud_signals():
    try:
        r = requests.get(GITHUB_RAW_SIGNALS_URL, timeout=5)
        if r.status_code == 200: return r.json()
    except: pass
    if SIGNALS_PATH.exists():
        try: return json.loads(SIGNALS_PATH.read_text())
        except: pass
    return None

def color(score):
    if score >= SIGNAL_STRONG: return "#00e676"
    if score >= SIGNAL_MODERATE: return "#ffd600"
    return "#ef5350"

def badge(label):
    cls = {"STRONG":"signal-strong","MODERATE":"signal-moderate","WEAK":"signal-weak"}[label]
    icon = {"STRONG":"🟢","MODERATE":"🟡","WEAK":"🔴"}[label]
    return f'<span class="{cls}">{icon} {label}</span>'

def bar(score):
    pct = score / 10 * 100
    return f'<div class="score-bar-bg"><div class="score-bar-fill" style="width:{pct:.0f}%;background:{color(score)}"></div></div>'

# ── Sidebar ───────────────────────────────────────────────────────────────────
def sidebar():
    st.sidebar.markdown("## ⚙️ Controls")
    status = market_status()
    icons = {"OPEN":"🟢","PRE-MARKET":"🟡","AFTER-HOURS":"🟠","CLOSED":"⚫"}
    st.sidebar.markdown(f"**Market:** {icons.get(status,'⚫')} {status}")
    st.sidebar.markdown(f"**Time:** {datetime.now(MT).strftime('%H:%M MT')}")
    wl = load_watchlist()
    st.sidebar.markdown(f"**Screener ran:** {wl.get('generated_at_mt','—')}")
    st.sidebar.markdown(f"**Tickers today:** {len(wl.get('tickers',[]))}")
    st.sidebar.divider()
    if st.sidebar.button("🔄 Refresh Now", use_container_width=True):
        st.cache_data.clear(); st.rerun()
    st.sidebar.divider()
    st.sidebar.markdown("**Score Guide**")
    st.sidebar.markdown("🟢 ≥ 7.5 Strong\n🟡 ≥ 5.0 Moderate\n🔴 < 5.0 Weak")

# ── Ticker card ───────────────────────────────────────────────────────────────
def render_card(sym, scores: Optional[TickerScores], snap: Optional[TickerSnapshot]):
    if not scores or not snap:
        st.markdown(f'<div class="metric-card"><span class="ticker-sym">{sym}</span> — Loading...</div>', unsafe_allow_html=True)
        return
    chg_color = "#00e676" if snap.day_change_pct >= 0 else "#ef5350"
    sign = "+" if snap.day_change_pct >= 0 else ""
    st.markdown(f"""
    <div class="metric-card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.5rem">
        <span class="ticker-sym">{sym}</span>
        <span style="font-size:1.2rem;font-weight:600">${snap.price:.2f}
          <span style="color:{chg_color};font-size:.9rem">{sign}{snap.day_change_pct:.1f}%</span>
        </span>
      </div>
      <div style="font-size:.82rem;color:#aaa;margin-bottom:.4rem">
        VWAP ${snap.vwap:.2f} &nbsp;|&nbsp; PDH ${snap.pdh:.2f} &nbsp;|&nbsp; RVOL {snap.rvol:.1f}x &nbsp;|&nbsp; Gap {'+' if snap.gap_pct>=0 else ''}{snap.gap_pct:.1f}%
      </div>
    </div>""", unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"""<div style="font-size:.8rem;color:#aaa">🚀 Launchpad &nbsp; {badge(scores.launchpad.signal_label)}</div>
        {bar(scores.launchpad.total)}
        <div style="font-size:1rem;font-weight:700;color:{color(scores.launchpad.total)}">{scores.launchpad.total:.1f}/10</div>""",
        unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div style="font-size:.8rem;color:#aaa">⚡ Gap & Go &nbsp; {badge(scores.gap_and_go.signal_label)}</div>
        {bar(scores.gap_and_go.total)}
        <div style="font-size:1rem;font-weight:700;color:{color(scores.gap_and_go.total)}">{scores.gap_and_go.total:.1f}/10</div>""",
        unsafe_allow_html=True)

    with st.expander(f"📋 {sym} breakdown"):
        t1, t2 = st.tabs(["🚀 Launchpad", "⚡ Gap & Go"])
        with t1:
            for r in scores.launchpad.rationale: st.markdown(f"- {r}")
            st.dataframe(pd.DataFrame([
                {"Component":"VWAP Position","Score":f"{scores.launchpad.vwap_points:.1f}/2.5"},
                {"Component":"PDH Reclaim",  "Score":f"{scores.launchpad.pdh_points:.1f}/2.5"},
                {"Component":"EMA Proximity","Score":f"{scores.launchpad.ema_points:.1f}/2.0"},
                {"Component":"Volume Dry-up","Score":f"{scores.launchpad.volume_points:.1f}/1.5"},
                {"Component":"EMA Stack",    "Score":f"{scores.launchpad.ema_stack_points:.1f}/1.5"},
            ]), hide_index=True, use_container_width=True)
        with t2:
            for r in scores.gap_and_go.rationale: st.markdown(f"- {r}")
            st.dataframe(pd.DataFrame([
                {"Component":"Gap Size",       "Score":f"{scores.gap_and_go.gap_size_points:.1f}/3.0"},
                {"Component":"Gap > PDH",      "Score":f"{scores.gap_and_go.gap_above_pdh_points:.1f}/2.0"},
                {"Component":"Pre-Mkt RVOL",   "Score":f"{scores.gap_and_go.pre_market_rvol_points:.1f}/2.0"},
                {"Component":"VWAP Hold",      "Score":f"{scores.gap_and_go.vwap_hold_points:.1f}/2.0"},
                {"Component":"Intraday RVOL",  "Score":f"{scores.gap_and_go.intraday_rvol_points:.1f}/1.0"},
            ]), hide_index=True, use_container_width=True)

# ── Paper trade logger ────────────────────────────────────────────────────────
def render_paper_trades():
    st.markdown("## 📝 Paper Trade Logger")
    trades = load_paper_trades()
    wl = load_watchlist()
    ticker_opts = [t["symbol"] for t in wl.get("tickers", [])]

    with st.expander("➕ Log New Trade", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            sym   = st.selectbox("Ticker", ticker_opts or ["—"])
            direc = st.selectbox("Direction", ["LONG","SHORT"])
        with c2:
            entry  = st.number_input("Entry $", min_value=0.0, step=0.01, format="%.2f")
            shares = st.number_input("Shares", min_value=1, step=1)
        with c3:
            setup = st.selectbox("Setup", ["Launchpad","Gap & Go","Other"])
            exit_ = st.number_input("Exit $ (0 = still open)", min_value=0.0, step=0.01, format="%.2f")
        notes = st.text_input("Notes (optional)")
        if st.button("✅ Log Trade", use_container_width=True):
            if sym and entry > 0 and shares > 0:
                pnl = None
                if exit_ > 0:
                    pnl = round((exit_ - entry) * shares * (1 if direc=="LONG" else -1), 2)
                trades.append({"id":len(trades)+1, "date":date.today().isoformat(),
                                "symbol":sym, "direction":direc, "setup":setup,
                                "entry":entry, "exit":exit_ or None, "shares":shares,
                                "pnl":pnl, "status":"CLOSED" if exit_ else "OPEN", "notes":notes})
                save_paper_trades(trades)
                st.success(f"Logged! {'P&L: $'+str(pnl) if pnl is not None else 'Still open.'}")
                st.rerun()

    open_trades = [t for t in trades if t["status"]=="OPEN"]
    if open_trades:
        with st.expander(f"🔒 Close Open Trade ({len(open_trades)} open)", expanded=False):
            labels = [f"#{t['id']} {t['symbol']} {t['direction']} @ ${t['entry']}" for t in open_trades]
            sel = st.selectbox("Select trade", labels)
            sel_id = int(sel.split("#")[1].split(" ")[0])
            close_px = st.number_input("Exit Price $", min_value=0.0, step=0.01, format="%.2f", key="cpx")
            if st.button("Close Trade"):
                for t in trades:
                    if t["id"] == sel_id:
                        t["exit"] = close_px
                        t["status"] = "CLOSED"
                        t["pnl"] = round((close_px - t["entry"]) * t["shares"] * (1 if t["direction"]=="LONG" else -1), 2)
                save_paper_trades(trades)
                st.rerun()

    if trades:
        df = pd.DataFrame(trades)
        cols = ["id","date","symbol","direction","setup","entry","exit","shares","pnl","status","notes"]
        df = df[[c for c in cols if c in df.columns]]
        df["pnl"] = df["pnl"].apply(lambda x: f"${x:+.2f}" if x is not None else "—")
        st.dataframe(df.sort_values("id", ascending=False), hide_index=True, use_container_width=True)

        closed = [t for t in trades if t["status"]=="CLOSED" and t["pnl"] is not None]
        if closed:
            st.markdown("### 📊 Performance")
            pnls = [t["pnl"] for t in closed]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            m1,m2,m3,m4,m5 = st.columns(5)
            m1.metric("Total P&L",  f"${sum(pnls):+.2f}")
            m2.metric("Win Rate",   f"{len(wins)/len(closed)*100:.0f}%")
            m3.metric("Avg Winner", f"${sum(wins)/len(wins):.2f}" if wins else "—")
            m4.metric("Avg Loser",  f"${sum(losses)/len(losses):.2f}" if losses else "—")
            m5.metric("Trades",     str(len(closed)))
            by_setup = {}
            for t in closed: by_setup.setdefault(t.get("setup","Other"),[]).append(t["pnl"])
            st.dataframe(pd.DataFrame([
                {"Setup":s,"Trades":len(v),"Total P&L":f"${sum(v):+.2f}",
                 "Win Rate":f"{sum(1 for x in v if x>0)/len(v)*100:.0f}%"}
                for s,v in by_setup.items()
            ]), hide_index=True, use_container_width=True)
    else:
        st.info("No trades logged yet.")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    st_autorefresh(interval=REFRESH_MS, limit=None, key="refresh")
    sidebar()

    st.markdown("# 🎯 Day Trading Confluence Dashboard")
    st.markdown("*Launchpad & Gap & Go signals — Paper Trading Mode*")

    # Cloud signal banners
    cloud = fetch_cloud_signals()
    if cloud:
        for sig in cloud.get("new_strong_signals", []):
            key = f"{sig['symbol']}_{sig.get('score',0):.1f}"
            if key not in st.session_state["seen_signals"]:
                st.session_state["seen_signals"].add(key)
                st.markdown(f"""<div class="banner">
                    🔔 NEW STRONG SIGNAL — {sig['symbol']} &nbsp;|&nbsp;
                    {sig['setup']} &nbsp;|&nbsp; {sig['score']:.1f}/10 &nbsp;|&nbsp; ${sig['price']:.2f}
                </div>""", unsafe_allow_html=True)

    wl = load_watchlist()
    symbols = [t["symbol"] for t in wl.get("tickers", [])]

    if not symbols:
        st.warning("⏳ No tickers yet — screener runs at 8:00 AM MT on weekdays. "
                   "You can also trigger it manually from GitHub Actions.")
        st.divider(); render_paper_trades(); return

    status = market_status()
    if status == "OPEN":
        st.success("🟢 Market OPEN — refreshing every 3 min")
    elif status == "PRE-MARKET":
        st.info("🟡 Pre-Market")
    else:
        st.warning(f"⚫ Market {status}")

    st.markdown(f"### Today's Watchlist ({len(symbols)} tickers)")

    snaps, scores_map = {}, {}
    pb = st.progress(0, text="Loading live data...")
    for i, sym in enumerate(symbols):
        snap = get_ticker_snapshot(sym)
        snaps[sym] = snap
        if not snap.error:
            scores_map[sym] = score_ticker(snap)
        pb.progress((i+1)/len(symbols), text=f"Loading {sym}...")
    pb.empty()

    sorted_syms = sorted(symbols, key=lambda s: scores_map[s].best_score if s in scores_map else 0, reverse=True)

    for i in range(0, len(sorted_syms), 2):
        cols = st.columns(2)
        for j, col in enumerate(cols):
            if i+j < len(sorted_syms):
                with col:
                    render_card(sorted_syms[i+j], scores_map.get(sorted_syms[i+j]), snaps.get(sorted_syms[i+j]))

    st.divider()
    render_paper_trades()
    now = datetime.now(MT).strftime("%H:%M:%S MT")
    st.markdown(f'<div style="color:#555;font-size:.75rem;text-align:center;margin-top:1rem">'
                f'Data via Yahoo Finance (15–20 min delayed) · Paper trading only · {now}</div>',
                unsafe_allow_html=True)

if __name__ == "__main__":
    main()
