# 🎯 Day Trading Confluence Dashboard

Systematic, formula-driven day trading signals built around two setups:

| Setup | What it detects |
|---|---|
| 🚀 **Launchpad** | Consolidation above VWAP + PDH + EMA with volume drying up |
| ⚡ **Gap & Go** | Gap >2% above prior resistance with pre-market volume surge |

## Quick Start (Local)

```bash
git clone https://github.com/danbo-dev/day-trading-dashboard.git
cd day-trading-dashboard
pip3 install -r requirements.txt
streamlit run dashboard.py
```

## GitHub Actions (Cloud — runs automatically)

- **Pre-Market Screener**: 8:00 AM MT weekdays → writes `watchlist.json`
- **Intraday Monitor**: Every 5 min 9:30 AM–4 PM ET → writes `signals.json`

Enable write permissions: **Settings → Actions → General → Read and write permissions**

## Score Guide

| Score | Signal |
|---|---|
| ≥ 7.5 | 🟢 Strong |
| ≥ 5.0 | 🟡 Moderate |
| < 5.0 | 🔴 Weak |

**Paper trading only. Data via Yahoo Finance (15–20 min delayed).**
