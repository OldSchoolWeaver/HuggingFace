"""Reset the four traders: $10,000 each, no holdings, and their starting strategy.

    uv run -m backend.reset
"""

from prompts.strategies import cathie_strategy, george_strategy, ray_strategy, warren_strategy

from .accounts import Account


def reset_traders():
    Account.get("Warren").reset(warren_strategy)
    Account.get("George").reset(george_strategy)
    Account.get("Ray").reset(ray_strategy)
    Account.get("Cathie").reset(cathie_strategy)


if __name__ == "__main__":
    reset_traders()