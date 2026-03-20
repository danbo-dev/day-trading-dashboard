"""
confluence_scorer.py — Scores tickers against Launchpad and Gap & Go setups.
Each setup scores 0–10. Full rationale breakdown is included per component.
"""
from dataclasses import dataclass, field
from typing import Optional
from data_fetcher import TickerSnapshot

SIGNAL_STRONG   = 7.5
SIGNAL_MODERATE = 5.0


@dataclass
class LaunchpadScore:
    total: float
    vwap_points: float
    pdh_points: float
    ema_points: float
    volume_points: float
    ema_stack_points: float
    signal_label: str
    rationale: list = field(default_factory=list)


@dataclass
class GapAndGoScore:
    total: float
    gap_size_points: float
    gap_above_pdh_points: float
    pre_market_rvol_points: float
    vwap_hold_points: float
    intraday_rvol_points: float
    signal_label: str
    rationale: list = field(default_factory=list)


@dataclass
class TickerScores:
    symbol: str
    price: float
    launchpad: LaunchpadScore
    gap_and_go: GapAndGoScore
    best_score: float
    best_setup: str
    snapshot_timestamp: str


def score_ticker(snap: TickerSnapshot) -> TickerScores:
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
        symbol=snap.symbol, price=snap.price,
        launchpad=lp, gap_and_go=gg,
        best_score=best_score, best_setup=best_setup,
        snapshot_timestamp=snap.timestamp.strftime("%H:%M:%S UTC"),
    )


def _pct_diff(price, ref):
    return abs((price - ref) / ref * 100) if ref else 0


def _label(score):
    if score >= SIGNAL_STRONG:   return "STRONG"
    if score >= SIGNAL_MODERATE: return "MODERATE"
    return "WEAK"


def _score_launchpad(snap: TickerSnapshot) -> LaunchpadScore:
    rationale = []
    # 1. VWAP (0–2.5)
    vwap_pct = _pct_diff(snap.price, snap.vwap)
    if snap.above_vwap:
        if vwap_pct <= 1.5:
            vwap_pts = 2.5; rationale.append(f"✅ Tight to VWAP ({vwap_pct:.1f}% above) — ideal coil zone")
        elif vwap_pct <= 3.0:
            vwap_pts = 1.5; rationale.append(f"✅ Above VWAP ({vwap_pct:.1f}%)")
        else:
            vwap_pts = 0.75; rationale.append(f"⚠️ Extended above VWAP ({vwap_pct:.1f}%)")
    else:
        vwap_pts = 0.0; rationale.append(f"❌ Below VWAP")

    # 2. PDH (0–2.5)
    pdh_pct = _pct_diff(snap.price, snap.pdh)
    if snap.above_pdh:
        if pdh_pct <= 1.0:
            pdh_pts = 2.5; rationale.append(f"✅ Sitting on PDH (${snap.pdh:.2f}) — resistance turned support")
        elif pdh_pct <= 2.5:
            pdh_pts = 1.5; rationale.append(f"✅ Above PDH by {pdh_pct:.1f}%")
        else:
            pdh_pts = 0.5; rationale.append(f"⚠️ Extended {pdh_pct:.1f}% above PDH")
    else:
        pdh_pts = 0.0; rationale.append(f"❌ Below PDH (${snap.pdh:.2f})")

    # 3. EMA proximity (0–2.0)
    ema_pts = 0.0
    if snap.above_ema9 and _pct_diff(snap.price, snap.ema9) <= 1.5:
        ema_pts += 1.0; rationale.append(f"✅ Riding 9 EMA (${snap.ema9:.2f})")
    elif snap.above_ema9:
        ema_pts += 0.5; rationale.append(f"✅ Above 9 EMA (${snap.ema9:.2f})")
    else:
        rationale.append(f"❌ Below 9 EMA (${snap.ema9:.2f})")
    if snap.above_ema20 and _pct_diff(snap.price, snap.ema20) <= 2.5:
        ema_pts += 1.0; rationale.append(f"✅ Riding 20 EMA (${snap.ema20:.2f})")
    elif snap.above_ema20:
        ema_pts += 0.5; rationale.append(f"✅ Above 20 EMA (${snap.ema20:.2f})")
    else:
        rationale.append(f"❌ Below 20 EMA (${snap.ema20:.2f})")
    ema_pts = min(ema_pts, 2.0)

    # 4. Volume dry-up (0–1.5)
    if snap.rvol < 0.7:
        vol_pts = 1.5; rationale.append(f"✅ Volume drying up (RVOL {snap.rvol:.2f}x) — coiling signal")
    elif snap.rvol < 1.0:
        vol_pts = 1.0; rationale.append(f"✅ Below-avg volume (RVOL {snap.rvol:.2f}x)")
    elif snap.rvol < 1.5:
        vol_pts = 0.5; rationale.append(f"➖ Normal volume (RVOL {snap.rvol:.2f}x)")
    else:
        vol_pts = 0.0; rationale.append(f"⚠️ Elevated volume (RVOL {snap.rvol:.2f}x) — may be moving already")

    # 5. EMA stack (0–1.5)
    if snap.ema_stack_bullish:
        stack_pts = 1.5; rationale.append("✅ Bullish EMA stack (9 > 20 > 50)")
    elif snap.above_ema9 and snap.above_ema20:
        stack_pts = 0.75; rationale.append("➖ Above 9 & 20 EMA, stack not fully confirmed")
    else:
        stack_pts = 0.0; rationale.append("❌ EMAs not in bullish alignment")

    total = round(vwap_pts + pdh_pts + ema_pts + vol_pts + stack_pts, 2)
    return LaunchpadScore(total=total, vwap_points=vwap_pts, pdh_points=pdh_pts,
                          ema_points=ema_pts, volume_points=vol_pts,
                          ema_stack_points=stack_pts, signal_label=_label(total),
                          rationale=rationale)


def _score_gap_and_go(snap: TickerSnapshot) -> GapAndGoScore:
    rationale = []
    # 1. Gap size (0–3.0)
    gap = abs(snap.gap_pct)
    direction = "up" if snap.gap_pct >= 0 else "down"
    if gap >= 4.0:
        gap_pts = 3.0; rationale.append(f"✅ Gap {direction} {gap:.1f}% — strong catalyst signal")
    elif gap >= 2.5:
        gap_pts = 2.0; rationale.append(f"✅ Gap {direction} {gap:.1f}%")
    elif gap >= 1.5:
        gap_pts = 1.0; rationale.append(f"➖ Gap {direction} {gap:.1f}% — modest")
    else:
        gap_pts = 0.0; rationale.append(f"❌ Gap too small ({gap:.1f}%)")

    # 2. Gap above PDH (0–2.0)
    if snap.gap_above_pdh:
        gap_pdh_pts = 2.0; rationale.append(f"✅ Opened above PDH (${snap.pdh:.2f}) — prior resistance cleared")
    else:
        gap_pdh_pts = 0.0; rationale.append(f"❌ Did not open above PDH (${snap.pdh:.2f})")

    # 3. Pre-market RVOL (0–2.0)
    pm = snap.pre_market_rvol
    if pm >= 3.0:
        pm_pts = 2.0; rationale.append(f"✅ Pre-market RVOL {pm:.1f}x — heavy institutional interest")
    elif pm >= 2.0:
        pm_pts = 1.5; rationale.append(f"✅ Pre-market RVOL {pm:.1f}x")
    elif pm >= 1.5:
        pm_pts = 0.75; rationale.append(f"➖ Pre-market RVOL {pm:.1f}x — moderate")
    else:
        pm_pts = 0.0; rationale.append(f"❌ Pre-market RVOL {pm:.1f}x — weak")

    # 4. VWAP hold (0–2.0)
    vwap_pct = _pct_diff(snap.price, snap.vwap)
    if snap.above_vwap:
        if vwap_pct <= 2.0:
            vwap_pts = 2.0; rationale.append(f"✅ Holding above VWAP (${snap.vwap:.2f}) — gap defending")
        else:
            vwap_pts = 1.0; rationale.append(f"✅ Above VWAP but extended ({vwap_pct:.1f}%)")
    else:
        vwap_pts = 0.0; rationale.append(f"❌ Below VWAP — gap may be fading")

    # 5. Intraday RVOL (0–1.0)
    if snap.rvol >= 2.5:
        rvol_pts = 1.0; rationale.append(f"✅ Intraday RVOL {snap.rvol:.1f}x — strong follow-through")
    elif snap.rvol >= 1.5:
        rvol_pts = 0.5; rationale.append(f"➖ Intraday RVOL {snap.rvol:.1f}x")
    else:
        rvol_pts = 0.0; rationale.append(f"❌ Intraday RVOL {snap.rvol:.1f}x — weak follow-through")

    total = round(gap_pts + gap_pdh_pts + pm_pts + vwap_pts + rvol_pts, 2)
    return GapAndGoScore(total=total, gap_size_points=gap_pts,
                         gap_above_pdh_points=gap_pdh_pts, pre_market_rvol_points=pm_pts,
                         vwap_hold_points=vwap_pts, intraday_rvol_points=rvol_pts,
                         signal_label=_label(total), rationale=rationale)


def scores_to_dict(ts: TickerScores) -> dict:
    return {
        "symbol": ts.symbol, "price": ts.price,
        "best_score": ts.best_score, "best_setup": ts.best_setup,
        "launchpad": {
            "total": ts.launchpad.total, "signal_label": ts.launchpad.signal_label,
            "vwap_points": ts.launchpad.vwap_points, "pdh_points": ts.launchpad.pdh_points,
            "ema_points": ts.launchpad.ema_points, "volume_points": ts.launchpad.volume_points,
            "ema_stack_points": ts.launchpad.ema_stack_points, "rationale": ts.launchpad.rationale,
        },
        "gap_and_go": {
            "total": ts.gap_and_go.total, "signal_label": ts.gap_and_go.signal_label,
            "gap_size_points": ts.gap_and_go.gap_size_points,
            "gap_above_pdh_points": ts.gap_and_go.gap_above_pdh_points,
            "pre_market_rvol_points": ts.gap_and_go.pre_market_rvol_points,
            "vwap_hold_points": ts.gap_and_go.vwap_hold_points,
            "intraday_rvol_points": ts.gap_and_go.intraday_rvol_points,
            "rationale": ts.gap_and_go.rationale,
        },
        "snapshot_timestamp": ts.snapshot_timestamp,
    }
