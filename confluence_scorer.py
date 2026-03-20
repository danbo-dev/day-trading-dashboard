"""
confluence_scorer.py
====================
Scores each ticker against the two primary confluence setups:

  1. LAUNCHPAD  — Consolidation above key levels, coiling for a breakout
  2. GAP & GO   — Gap up above prior resistance with volume confirmation

Each score is 0–10. The raw component breakdown is also returned
so the dashboard can explain exactly why a score is what it is.
"""

from dataclasses import dataclass, field
from typing import Optional
from data_fetcher import TickerSnapshot


# ─── Score thresholds ────────────────────────────────────────────────────────

SIGNAL_STRONG   = 7.5   # 🟢 Strong — highest conviction
SIGNAL_MODERATE = 5.0   # 🟡 Moderate — worth watching
SIGNAL_WEAK     = 0.0   # 🔴 Weak — no clear setup


@dataclass
class LaunchpadScore:
    """Breakdown of the Launchpad confluence score."""
    total: float                    # 0 – 10
    vwap_points: float              # 0 – 2.5
    pdh_points: float               # 0 – 2.5
    ema_points: float               # 0 – 2.0
    volume_points: float            # 0 – 1.5
    ema_stack_points: float         # 0 – 1.5
    signal_label: str               # STRONG / MODERATE / WEAK
    rationale: list[str] = field(default_factory=list)


@dataclass
class GapAndGoScore:
    """Breakdown of the Gap & Go confluence score."""
    total: float                    # 0 – 10
    gap_size_points: float          # 0 – 3.0
    gap_above_pdh_points: float     # 0 – 2.0
    pre_market_rvol_points: float   # 0 – 2.0
    vwap_hold_points: float         # 0 – 2.0
    intraday_rvol_points: float     # 0 – 1.0
    signal_label: str
    rationale: list[str] = field(default_factory=list)


@dataclass
class TickerScores:
    """Combined scores for a ticker."""
    symbol: str
    price: float
    launchpad: LaunchpadScore
    gap_and_go: GapAndGoScore
    best_score: float               # max of the two
    best_setup: str                 # "Launchpad" | "Gap & Go" | "None"
    snapshot_timestamp: str


def score_ticker(snap: TickerSnapshot) -> TickerScores:
    """Compute both confluence scores for a given TickerSnapshot."""
    lp = _score_launchpad(snap)
    gg = _score_gap_and_go(snap)

    best_score = max(lp.total, gg.total)
    if lp.total >= gg.total and lp.total >= SIGNAL_MODERATE:
        best_setup = "Launchpad"
    elif gg.total >= lp.total and gg.total >= SIGNAL_MODERATE:
        best_setup = "Gap & Go"
    else:
        best_setup = "None"

    return TickerScores(
        symbol=snap.symbol,
        price=snap.price,
        launchpad=lp,
        gap_and_go=gg,
        best_score=best_score,
        best_setup=best_setup,
        snapshot_timestamp=snap.timestamp.strftime("%H:%M:%S UTC"),
    )


# ─── Launchpad scoring ────────────────────────────────────────────────────────

def _score_launchpad(snap: TickerSnapshot) -> LaunchpadScore:
    """
    Launchpad: consolidation above key levels, coiling for a breakout.

    Components:
        1. VWAP position       (0 – 2.5 pts)
        2. PDH reclaim         (0 – 2.5 pts)
        3. EMA proximity       (0 – 2.0 pts)
        4. Volume dry-up       (0 – 1.5 pts)
        5. Bullish EMA stack   (0 – 1.5 pts)
    Max = 10.0
    """
    rationale = []

    # 1. VWAP — price above is bullish bias; sitting just above is ideal
    vwap_pct = _pct_diff(snap.price, snap.vwap)
    if snap.above_vwap:
        if vwap_pct <= 1.5:
            vwap_pts = 2.5  # Tight to VWAP above — ideal coil zone
            rationale.append(f"✅ Price is {vwap_pct:.1f}% above VWAP (tight coil zone)")
        elif vwap_pct <= 3.0:
            vwap_pts = 1.5
            rationale.append(f"✅ Price is {vwap_pct:.1f}% above VWAP")
        else:
            vwap_pts = 0.75
            rationale.append(f"⚠️ Price is extended {vwap_pct:.1f}% above VWAP")
    else:
        vwap_pts = 0.0
        rationale.append(f"❌ Price is below VWAP ({vwap_pct:.1f}%)")

    # 2. PDH reclaim — prior resistance now acting as support
    pdh_pct = _pct_diff(snap.price, snap.pdh)
    if snap.above_pdh:
        if pdh_pct <= 1.0:
            pdh_pts = 2.5  # Sitting right on top of PDH — best case
            rationale.append(f"✅ Price is {pdh_pct:.1f}% above PDH (holding support)")
        elif pdh_pct <= 2.5:
            pdh_pts = 1.5
            rationale.append(f"✅ Price is {pdh_pct:.1f}% above PDH")
        else:
            pdh_pts = 0.5
            rationale.append(f"⚠️ Price is {pdh_pct:.1f}% above PDH (extended)")
    else:
        pdh_pts = 0.0
        below_pct = _pct_diff(snap.pdh, snap.price)
        rationale.append(f"❌ Price is {below_pct:.1f}% below PDH")

    # 3. EMA proximity — riding the 9 or 20 EMA is the coil sweet spot
    ema_pts = 0.0
    near9 = snap.above_ema9 and _pct_diff(snap.price, snap.ema9) <= 1.5
    near20 = snap.above_ema20 and _pct_diff(snap.price, snap.ema20) <= 2.5
    if near9:
        ema_pts += 1.0
        rationale.append(f"✅ Riding 9 EMA (${snap.ema9:.2f})")
    elif snap.above_ema9:
        ema_pts += 0.5
        rationale.append(f"✅ Above 9 EMA (${snap.ema9:.2f})")
    else:
        rationale.append(f"❌ Below 9 EMA (${snap.ema9:.2f})")
    if near20:
        ema_pts += 1.0
        rationale.append(f"✅ Riding 20 EMA (${snap.ema20:.2f})")
    elif snap.above_ema20:
        ema_pts += 0.5
        rationale.append(f"✅ Above 20 EMA (${snap.ema20:.2f})")
    else:
        rationale.append(f"❌ Below 20 EMA (${snap.ema20:.2f})")
    ema_pts = min(ema_pts, 2.0)

    # 4. Volume dry-up — low RVOL during consolidation = energy building
    if snap.rvol < 0.7:
        vol_pts = 1.5
        rationale.append(f"✅ Volume drying up (RVOL {snap.rvol:.2f}x) — coiling signal")
    elif snap.rvol < 1.0:
        vol_pts = 1.0
        rationale.append(f"✅ Volume below average (RVOL {snap.rvol:.2f}x)")
    elif snap.rvol < 1.5:
        vol_pts = 0.5
        rationale.append(f"➖ Normal volume (RVOL {snap.rvol:.2f}x)")
    else:
        vol_pts = 0.0
        rationale.append(f"⚠️ Volume elevated (RVOL {snap.rvol:.2f}x) — may be moving already")

    # 5. Bullish EMA stack
    if snap.ema_stack_bullish:
        stack_pts = 1.5
        rationale.append(f"✅ Bullish EMA stack (9 > 20 > 50)")
    elif snap.above_ema9 and snap.above_ema20:
        stack_pts = 0.75
        rationale.append(f"➖ Above 9 & 20 EMA but 50 EMA stack not confirmed")
    else:
        stack_pts = 0.0
        rationale.append(f"❌ EMAs not in bullish alignment")

    total = round(vwap_pts + pdh_pts + ema_pts + vol_pts + stack_pts, 2)
    return LaunchpadScore(
        total=total,
        vwap_points=vwap_pts,
        pdh_points=pdh_pts,
        ema_points=ema_pts,
        volume_points=vol_pts,
        ema_stack_points=stack_pts,
        signal_label=_label(total),
        rationale=rationale,
    )


# ─── Gap & Go scoring ─────────────────────────────────────────────────────────

def _score_gap_and_go(snap: TickerSnapshot) -> GapAndGoScore:
    """
    Gap & Go: gap up above prior resistance with volume confirmation.

    Components:
        1. Gap size            (0 – 3.0 pts)
        2. Gap above PDH       (0 – 2.0 pts)
        3. Pre-market RVOL     (0 – 2.0 pts)
        4. VWAP hold           (0 – 2.0 pts)
        5. Intraday RVOL       (0 – 1.0 pts)
    Max = 10.0
    """
    rationale = []

    # 1. Gap size — bigger gap = stronger catalyst signal
    gap = abs(snap.gap_pct)
    gap_dir = "up" if snap.gap_pct >= 0 else "down"
    if gap >= 4.0:
        gap_pts = 3.0
        rationale.append(f"✅ Gap {gap_dir} {gap:.1f}% — strong catalyst")
    elif gap >= 2.5:
        gap_pts = 2.0
        rationale.append(f"✅ Gap {gap_dir} {gap:.1f}%")
    elif gap >= 1.5:
        gap_pts = 1.0
        rationale.append(f"➖ Gap {gap_dir} {gap:.1f}% — modest")
    else:
        gap_pts = 0.0
        rationale.append(f"❌ Gap {gap:.1f}% — too small for setup")

    # 2. Gap above PDH — opened above prior resistance
    if snap.gap_above_pdh:
        gap_pdh_pts = 2.0
        rationale.append(f"✅ Opened above PDH (${snap.pdh:.2f}) — resistance cleared")
    else:
        gap_pdh_pts = 0.0
        rationale.append(f"❌ Did not open above PDH (${snap.pdh:.2f})")

    # 3. Pre-market RVOL — institutional footprint before open
    pmrvol = snap.pre_market_rvol
    if pmrvol >= 3.0:
        pm_pts = 2.0
        rationale.append(f"✅ Pre-market RVOL {pmrvol:.1f}x — heavy interest")
    elif pmrvol >= 2.0:
        pm_pts = 1.5
        rationale.append(f"✅ Pre-market RVOL {pmrvol:.1f}x — good interest")
    elif pmrvol >= 1.5:
        pm_pts = 0.75
        rationale.append(f"➖ Pre-market RVOL {pmrvol:.1f}x — moderate")
    else:
        pm_pts = 0.0
        rationale.append(f"❌ Pre-market RVOL {pmrvol:.1f}x — weak")

    # 4. VWAP hold — gap is holding, not fading back
    vwap_pct = _pct_diff(snap.price, snap.vwap)
    if snap.above_vwap:
        if vwap_pct <= 2.0:
            vwap_pts = 2.0
            rationale.append(f"✅ Holding above VWAP (${snap.vwap:.2f}) — gap defending")
        else:
            vwap_pts = 1.0
            rationale.append(f"✅ Above VWAP but extended ({vwap_pct:.1f}%)")
    else:
        vwap_pts = 0.0
        rationale.append(f"❌ Below VWAP — gap may be fading")

    # 5. Intraday RVOL — confirms follow-through buying
    if snap.rvol >= 2.5:
        rvol_pts = 1.0
        rationale.append(f"✅ Intraday RVOL {snap.rvol:.1f}x — strong follow-through")
    elif snap.rvol >= 1.5:
        rvol_pts = 0.5
        rationale.append(f"➖ Intraday RVOL {snap.rvol:.1f}x")
    else:
        rvol_pts = 0.0
        rationale.append(f"❌ Intraday RVOL {snap.rvol:.1f}x — weak follow-through")

    total = round(gap_pts + gap_pdh_pts + pm_pts + vwap_pts + rvol_pts, 2)
    return GapAndGoScore(
        total=total,
        gap_size_points=gap_pts,
        gap_above_pdh_points=gap_pdh_pts,
        pre_market_rvol_points=pm_pts,
        vwap_hold_points=vwap_pts,
        intraday_rvol_points=rvol_pts,
        signal_label=_label(total),
        rationale=rationale,
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _pct_diff(price: float, reference: float) -> float:
    """Percentage difference of price from reference (positive = above)."""
    if reference == 0:
        return 0.0
    return abs((price - reference) / reference * 100)


def _label(score: float) -> str:
    if score >= SIGNAL_STRONG:
        return "STRONG"
    if score >= SIGNAL_MODERATE:
        return "MODERATE"
    return "WEAK"


def scores_to_dict(ts: TickerScores) -> dict:
    """Serialize TickerScores to a JSON-safe dict (for signals.json)."""
    return {
        "symbol": ts.symbol,
        "price": ts.price,
        "best_score": ts.best_score,
        "best_setup": ts.best_setup,
        "launchpad": {
            "total": ts.launchpad.total,
            "signal_label": ts.launchpad.signal_label,
            "vwap_points": ts.launchpad.vwap_points,
            "pdh_points": ts.launchpad.pdh_points,
            "ema_points": ts.launchpad.ema_points,
            "volume_points": ts.launchpad.volume_points,
            "ema_stack_points": ts.launchpad.ema_stack_points,
            "rationale": ts.launchpad.rationale,
        },
        "gap_and_go": {
            "total": ts.gap_and_go.total,
            "signal_label": ts.gap_and_go.signal_label,
            "gap_size_points": ts.gap_and_go.gap_size_points,
            "gap_above_pdh_points": ts.gap_and_go.gap_above_pdh_points,
            "pre_market_rvol_points": ts.gap_and_go.pre_market_rvol_points,
            "vwap_hold_points": ts.gap_and_go.vwap_hold_points,
            "intraday_rvol_points": ts.gap_and_go.intraday_rvol_points,
            "rationale": ts.gap_and_go.rationale,
        },
        "snapshot_timestamp": ts.snapshot_timestamp,
    }
