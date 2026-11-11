"""StockMetricsTool: real fundamentals and technical indicators from Yahoo Finance (via yfinance).

The LLM can't read numbers off finance.yahoo.com with a web-search tool, so it used to answer "N/A"
(or invent values). This tool fetches the data and computes the indicators in plain Python:
  fundamentals  EPS, revenue growth, gross margin, ROE, P/E   (Yahoo Finance company info)
  technicals    SMA 30/50/100/200, MACD (12, 26, 9), momentum (10 days)   (from daily closing prices)
It also confirms a company is publicly traded: an unknown ticker returns NOT_LISTED.
"""
import json
from typing import Type

import pandas as pd
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


def compute_indicators(close: pd.Series) -> dict:
    """Technical indicators from a series of daily closing prices (oldest first)."""
    close = close.dropna()
    result: dict = {"last_close": round(float(close.iloc[-1]), 2), "as_of": str(close.index[-1])[:10]}
    for window in (30, 50, 100, 200):
        result[f"SMA_{window}"] = round(float(close.rolling(window).mean().iloc[-1]), 2) if len(close) >= window else None
    if len(close) >= 35:  # 26 days for the slow EMA + 9 for the signal line
        macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        signal = macd.ewm(span=9, adjust=False).mean()
        result["MACD"] = round(float(macd.iloc[-1]), 3)
        result["MACD_signal"] = round(float(signal.iloc[-1]), 3)
        result["MACD_histogram"] = round(float(macd.iloc[-1] - signal.iloc[-1]), 3)
    else:
        result["MACD"] = result["MACD_signal"] = result["MACD_histogram"] = None
    if len(close) > 10:
        then = float(close.iloc[-11])
        result["momentum_10d"] = round(float(close.iloc[-1]) - then, 2)
        result["momentum_10d_pct"] = round((float(close.iloc[-1]) / then - 1) * 100, 2)
    else:
        result["momentum_10d"] = result["momentum_10d_pct"] = None
    return result


def _pct(value) -> str | None:
    return f"{value * 100:.1f}%" if isinstance(value, (int, float)) else None


MAX_TICKERS = 8


def fetch_metrics(ticker: str) -> dict:
    """Metrics for one ticker, or a NOT_LISTED / ERROR status the agent can act on."""
    import yfinance as yf

    try:
        stock = yf.Ticker(ticker)
        history = stock.history(period="1y", interval="1d", auto_adjust=True)
        if history.empty:
            return {"ticker": ticker, "status": "NOT_LISTED",
                    "message": "No price data: not a publicly traded ticker. Do not pick this company "
                               "and do not call this tool again for this ticker."}
        info = stock.info or {}
    except Exception as exc:  # noqa: BLE001 - tell the agent instead of crashing the crew
        return {"ticker": ticker, "status": "ERROR",
                "message": f"Could not fetch data: {exc}. Do not retry this ticker; report its metrics as unknown."}
    return {
        "ticker": ticker,
        "status": "OK",
        "source": f"Yahoo Finance via yfinance - https://finance.yahoo.com/quote/{ticker}",
        "name": info.get("longName") or info.get("shortName"),
        "currency": info.get("currency"),
        "EPS": info.get("trailingEps"),
        "revenue_growth": _pct(info.get("revenueGrowth")),
        "gross_profit_margin": _pct(info.get("grossMargins")),
        "return_on_equity": _pct(info.get("returnOnEquity")),
        "PE_ratio": info.get("trailingPE"),
        "forward_PE_ratio": info.get("forwardPE"),
        **compute_indicators(history["Close"]),
    }


class StockMetricsInput(BaseModel):
    """Input schema for StockMetricsTool."""
    tickers: str = Field(..., description=f"One or more stock ticker symbols separated by commas (max {MAX_TICKERS}), "
                                          "e.g. \"NVDA, MSFT, ASML.AS\"")


class StockMetricsTool(BaseTool):
    name: str = "Get stock metrics"
    description: str = (
        "Returns real financial metrics for publicly traded companies from Yahoo Finance: EPS, revenue growth, "
        "gross margin, return on equity, P/E ratio, SMA 30/50/100/200, MACD and 10-day momentum. "
        "Pass ALL the tickers you need in ONE call, separated by commas. "
        "Also use it to check that companies are publicly traded: unknown tickers return NOT_LISTED."
    )
    args_schema: Type[BaseModel] = StockMetricsInput

    def _run(self, tickers: str) -> str:
        symbols = list(dict.fromkeys(t.strip().upper() for t in tickers.replace(";", ",").split(",") if t.strip()))
        if not symbols:
            return json.dumps({"status": "ERROR", "message": "No ticker given."})
        results = [fetch_metrics(t) for t in symbols[:MAX_TICKERS]]
        if len(symbols) > MAX_TICKERS:
            results.append({"status": "ERROR", "message": f"Only the first {MAX_TICKERS} tickers were processed."})
        return json.dumps(results, default=str)
