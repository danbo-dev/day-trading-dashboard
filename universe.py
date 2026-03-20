"""
universe.py
===========
Fetches and returns the combined S&P 500 + NASDAQ 100 ticker universe.
Filters are applied downstream in the screener.
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)


def get_sp500_tickers() -> list[str]:
    """Fetch current S&P 500 tickers from Wikipedia."""
    try:
        table = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            attrs={"id": "constituents"},
        )[0]
        tickers = table["Symbol"].str.replace(".", "-", regex=False).tolist()
        logger.info(f"Fetched {len(tickers)} S&P 500 tickers")
        return tickers
    except Exception as e:
        logger.error(f"Failed to fetch S&P 500 tickers: {e}")
        return []


def get_nasdaq100_tickers() -> list[str]:
    """Fetch current NASDAQ 100 tickers from Wikipedia."""
    try:
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/Nasdaq-100"
        )
        # Find the table with 'Ticker' column
        for table in tables:
            cols = [c.lower() for c in table.columns]
            if "ticker" in cols:
                col = table.columns[[c.lower() == "ticker" for c in table.columns][0] if any(c.lower() == "ticker" for c in table.columns) else 0]
                tickers = table["Ticker"].str.replace(".", "-", regex=False).tolist()
                logger.info(f"Fetched {len(tickers)} NASDAQ 100 tickers")
                return tickers
        logger.warning("Could not find Ticker column in NASDAQ 100 tables")
        return []
    except Exception as e:
        logger.error(f"Failed to fetch NASDAQ 100 tickers: {e}")
        return []


def get_universe() -> list[str]:
    """
    Returns deduplicated, sorted list of S&P 500 + NASDAQ 100 tickers.
    Falls back to a hardcoded core list if Wikipedia is unavailable.
    """
    sp500 = get_sp500_tickers()
    ndx100 = get_nasdaq100_tickers()

    combined = list(set(sp500 + ndx100))
    combined.sort()

    if len(combined) < 100:
        logger.warning("Universe fetch returned too few tickers, using fallback list")
        return _fallback_universe()

    logger.info(f"Combined universe: {len(combined)} unique tickers")
    return combined


def _fallback_universe() -> list[str]:
    """Hardcoded fallback of high-liquidity names if Wikipedia is unavailable."""
    return [
        "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","JPM","LLY",
        "V","UNH","XOM","MA","JNJ","PG","HD","MRK","ABBV","CVX","KO","PEP",
        "COST","WMT","ADBE","AMD","NFLX","CRM","MCD","ABT","ACN","TMO","ORCL",
        "CSCO","BAC","NEE","DHR","GE","QCOM","TXN","INTC","WFC","MS","GS","C",
        "RTX","HON","SPGI","CAT","LOW","INTU","AXP","UPS","DE","ISRG","LMT",
        "BKNG","AMAT","REGN","MU","LRCX","ADI","KLAC","PANW","SNPS","CDNS",
        "MELI","ZM","DDOG","NET","CRWD","OKTA","SNOW","COIN","RBLX","U",
        "SOFI","HOOD","PLTR","AFRM","UPST","RIVN","LCID","F","GM","UBER",
        "LYFT","ABNB","DASH","PINS","SNAP","TWTR","PATH","AI","BBAI","SOUN",
    ]
