"""
Exchange implementations.

This module contains implementations for various prediction market exchanges.
Each exchange is in its own subpackage.

Available exchanges:
- polymarket: Polymarket exchange

Example:
    ```python
    from prediction_markets.exchanges.polymarket import Polymarket

    exchange = Polymarket({"api_key": "..."})
    await exchange.init()
    ```
"""

# Exchange classes are imported lazily by the factory
# to avoid circular imports and allow optional dependencies

__all__: list[str] = []
