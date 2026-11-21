"""MCP server for share prices, used when there's no MASSIVE_API_KEY.

With a key, traders get Massive's own MCP server instead (see backend/mcp_config.py). This one serves the prices
from backend.market, which falls back to simulated prices, so the trading floor runs without any market data key.

    uv run -m mcp_servers.market_server
"""

from mcp.server.fastmcp import FastMCP

from backend.market import get_share_price

mcp = FastMCP("market_server")


@mcp.tool()
async def lookup_share_price(symbol: str) -> float:
    """Get the current share price of a stock.

    Args:
        symbol: The ticker symbol of the stock, e.g. AAPL
    """
    return get_share_price(symbol)


if __name__ == "__main__":
    mcp.run(transport="stdio")
