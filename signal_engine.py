"""
signal_engine.py
================
Scores each ticker against the two primary confluence setups:

  SETUP 1 — "Launchpad" (Bullish):
    Price above VWAP             → 25 pts
    Price above PDH              → 25 pts
    Price above 9 EMA > 20 EMA  → 25 pts
    High-OI call strike nearby   → 25 pts

  SETUP 2 — "Gap & Go" (Bullish):
    Gap up >= 1.5% from open     → 25 pts
    Live RVOL >= 1.5x            → 25 pts
    Price holding above VWAP     → 25 pts
    Low overhead resistance      → 25 pts

Score range: 0–100 each.
Signal tier:
  >= 75  →  🟢 HIGH
  50–74  →  🟡 MEDIUM
  < 50   →  🔴 LOW
"""

from typing import Optional


SIGNAL_HIGH   = "🟢 HIGH"
SIGNAL_MEDIUM = "🟡 MEDIUM"
SIGNAL_LOW    = "🔴 LOW"


def _tier(score: float) -> str:
    if score >= 75:
        return SIGNAL_HIGH
    elif score >= 50:
        return SIGNAL_MEDIUM
    return SIGNAL_LOW


# ── Launchpad Score ───────────────────────────────────────────────────────────

def launchpad_score(data: dict) -> dict:
    """
    Scores the Launchpad confluence setup.
    Returns score (0-100), tier, and component breakdown.
    """
    price        = data.get("price") or 0
    vwap         = data.get("vwap")
    pdh          = data.get("pdh") or 0
    ema9         = data.get("ema9_intraday") or data.get("ema9") or 0
    ema20        = data.get("ema20_intraday") or data.get("ema20") or 0
    call_support = data.get("call_support")
    call_oi      = data.get("call_oi") or 0

    components = {}

    # ── Component 1: Price vs VWAP (25 pts) ──────────────────────────────────
    if vwap and price:
        dist_pct = (price - vwap) / vwap * 100
        if dist_pct >= 0:
            pts = 25                           # above VWAP
        elif dist_pct >= -0.5:
            pts = 12                           # within 0.5% below
        else:
            pts = 0
    else:
        pts = 0
    components["above_vwap"] = {"pts": pts, "max": 25, "detail": f"${vwap:.2f}" if vwap else "N/A"}

    # ── Component 2: Price vs PDH (25 pts) ───────────────────────────────────
    if pdh and price:
        dist_pct = (price - pdh) / pdh * 100
        if dist_pct >= 0:
            pts = 25                           # above PDH
        elif dist_pct >= -0.5:
            pts = 15                           # within 0.5% below
        elif dist_pct >= -1.5:
            pts = 5                            # approaching PDH
        else:
            pts = 0
    else:
        pts = 0
    components["above_pdh"] = {"pts": pts, "max": 25, "detail": f"${pdh:.2f}" if pdh else "N/A"}

    # ── Component 3: EMA stack (25 pts) ──────────────────────────────────────
    if price and ema9 and ema20:
        if price > ema9 > ema20:
            pts = 25                           # full bullish stack
        elif price > ema9:
            pts = 15                           # above 9 only
        elif price > ema20:
            pts = 8                            # above 20 only
        else:
            pts = 0
    else:
        pts = 0
    components["ema_stack"] = {"pts": pts, "max": 25, "detail": f"9EMA ${ema9:.2f} / 20EMA ${ema20:.2f}" if ema9 and ema20 else "N/A"}

    # ── Component 4: Call OI floor support (25 pts) ───────────────────────────
    if call_support and price:
        dist_pct = (price - call_support) / price * 100   # % below price
        if dist_pct <= 1.0 and call_oi >= 500:
            pts = 25                           # strong floor nearby
        elif dist_pct <= 2.0 and call_oi >= 200:
            pts = 15
        elif dist_pct <= 3.0:
            pts = 8
        else:
            pts = 0
    else:
        pts = 0
    components["call_support"] = {"pts": pts, "max": 25, "detail": f"${call_support} OI:{call_oi:,}" if call_support else "N/A"}

    total = sum(c["pts"] for c in components.values())
    return {
        "score":      total,
        "tier":       _tier(total),
        "components": components,
    }


# ── Gap & Go Score ────────────────────────────────────────────────────────────

def gap_and_go_score(data: dict) -> dict:
    """
    Scores the Gap & Go confluence setup.
    Returns score (0-100), tier, and component breakdown.
    """
    price        = data.get("price") or 0
    vwap         = data.get("vwap")
    gap_pct      = data.get("gap_pct_open") or data.get("gap_pct") or 0
    rvol         = data.get("rvol_live") or data.get("rvol") or 1.0
    w52_high     = data.get("w52_high") or 0
    put_resist   = data.get("put_resistance")
    put_oi       = data.get("put_oi") or 0

    components = {}

    # ── Component 1: Gap size (25 pts) ────────────────────────────────────────
    # Only bullish gaps score fully; bearish gaps score partial (can still Gap & Go short)
    gap_abs = abs(gap_pct)
    if gap_abs >= 4.0:
        pts = 25
    elif gap_abs >= 3.0:
        pts = 20
    elif gap_abs >= 2.0:
        pts = 15
    elif gap_abs >= 1.5:
        pts = 10
    else:
        pts = 0
    components["gap_size"] = {"pts": pts, "max": 25, "detail": f"{gap_pct:+.1f}%"}

    # ── Component 2: Relative Volume (25 pts) ─────────────────────────────────
    if rvol >= 3.0:
        pts = 25
    elif rvol >= 2.0:
        pts = 20
    elif rvol >= 1.5:
        pts = 15
    elif rvol >= 1.2:
        pts = 8
    else:
        pts = 0
    components["rvol"] = {"pts": pts, "max": 25, "detail": f"{rvol:.1f}x"}

    # ── Component 3: Holding above VWAP (25 pts) ──────────────────────────────
    if vwap and price:
        dist_pct = (price - vwap) / vwap * 100
        if dist_pct >= 0.5:
            pts = 25                           # comfortably above VWAP
        elif dist_pct >= 0:
            pts = 18                           # at/just above VWAP
        elif dist_pct >= -0.3:
            pts = 8                            # barely below — watch for reclaim
        else:
            pts = 0
    else:
        pts = 0
    components["vwap_hold"] = {"pts": pts, "max": 25, "detail": f"${vwap:.2f}" if vwap else "N/A"}

    # ── Component 4: Overhead resistance clearance (25 pts) ───────────────────
    # Use nearest of: put_resistance, 52-week high
    overhead_levels = []
    if put_resist and put_resist > price:
        overhead_levels.append(("Put wall", put_resist))
    if w52_high and w52_high > price:
        overhead_levels.append(("52w High", w52_high))

    if overhead_levels:
        nearest_level, nearest_price = min(overhead_levels, key=lambda x: x[1])
        dist_pct = (nearest_price - price) / price * 100
        if dist_pct >= 4.0:
            pts = 25                           # clear runway
        elif dist_pct >= 2.5:
            pts = 18
        elif dist_pct >= 1.5:
            pts = 10
        else:
            pts = 3                            # wall very close
        detail = f"{nearest_level} ${nearest_price:.2f} ({dist_pct:.1f}% away)"
    else:
        pts = 20                               # no obvious overhead = bullish
        detail = "No wall detected"
    components["overhead_clear"] = {"pts": pts, "max": 25, "detail": detail}

    total = sum(c["pts"] for c in components.values())
    return {
        "score":      total,
        "tier":       _tier(total),
        "components": components,
    }


# ── Combined Signal ───────────────────────────────────────────────────────────

def score_ticker(data: dict) -> dict:
    """
    Runs both setups and returns combined scoring.
    best_setup = whichever scores higher.
    """
    lp = launchpad_score(data)
    gg = gap_and_go_score(data)

    if lp["score"] >= gg["score"]:
        best_setup = "Launchpad"
        best_tier  = lp["tier"]
        best_score = lp["score"]
    else:
        best_setup = "Gap & Go"
        best_tier  = gg["tier"]
        best_score = gg["score"]

    return {
        "launchpad":        lp,
        "gap_and_go":       gg,
        "best_setup":       best_setup,
        "best_score":       best_score,
        "best_tier":        best_tier,
        "alert_worthy":     best_score >= 75,
    }
