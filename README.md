# Day Trading Confluence Dashboard

A systematic paper trading dashboard tracking two high-conviction confluence setups:

1. **The Launchpad** — Price above VWAP + above PDH + bullish EMA stack + call OI floor support
2. **The Gap & Go** — Notable gap from open + strong RVOL + holding VWAP + clear overhead runway

## Structure

```
day_trading_dashboard/
├── app.py                          # Streamlit dashboard (run locally)
├── screener.py                     # Pre-market screener (GitHub Actions)
├── data_fetcher.py                 # Live intraday data (VWAP, EMAs, options OI)
├── signal_engine.py                # Launchpad + Gap & Go scoring (0-100 each)
├── universe.py                     # S&P 500 + NASDAQ 100 ticker universe
├── requirements.txt
├── data/
│   └── screened_tickers.json       # Daily screener output (auto-updated)
├── trades/
│   └── paper_trades.csv            # Your paper trade log
└── .github/workflows/
    └── premarket_screener.yml      # Runs at 6 AM + 8 AM MT weekdays
```

## Signal Tiers

| Score | Tier | Meaning |
|-------|------|---------|
| 75–100 | 🟢 HIGH | High-conviction setup — monitor closely |
| 50–74  | 🟡 MEDIUM | Setup forming — not quite there yet |
| 0–49   | 🔴 LOW | Early/weak signal |

## Running the Dashboard

```bash
cd ~/Documents/day_trading_dashboard
streamlit run app.py
```

## Screener Schedule

- **6:00 AM MT** — Early pre-market scan (catches gap plays forming)
- **8:00 AM MT** — Final pre-market scan (your primary watchlist for the day)

Screened tickers are committed to `data/screened_tickers.json` automatically.
The dashboard reads this file and refreshes live data every 3 minutes.

## Screener Filters

| Filter | Threshold |
|--------|-----------|
| Price | $10 – $150 |
| Avg Daily Volume | > 1,000,000 shares |
| ATR | > 1.5% of price |
| Universe | S&P 500 + NASDAQ 100 |
