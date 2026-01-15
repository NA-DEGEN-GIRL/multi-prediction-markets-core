"""
Configuration management for prediction markets.

Loads configuration from environment variables with sensible defaults.
Supports both global config and exchange-specific configs.

Usage:
    ```python
    from prediction_markets.config import get_polymarket_config, load_env

    # Load .env file (optional, done automatically in most cases)
    load_env()

    # Get Polymarket config dict
    config = get_polymarket_config()

    # Create exchange with config
    from prediction_markets import create_exchange
    exchange = create_exchange("polymarket", config)
    ```
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def load_env(env_path: str | Path | None = None) -> bool:
    """
    Load environment variables from .env and .env.config files.

    Files loaded (in order):
    1. .env.config - General configuration (can be shared)
    2. .env - Secrets (private keys, etc.) - overrides .env.config

    Args:
        env_path: Path to .env file. If None, searches in current dir and parent dirs.

    Returns:
        True if any .env file was found and loaded, False otherwise.
    """
    try:
        from dotenv import load_dotenv

        if env_path:
            return load_dotenv(env_path)

        # Search for .env files in current and parent directories
        current = Path.cwd()
        loaded = False

        for _ in range(5):  # Max 5 levels up
            # Load .env.config first (general settings)
            config_file = current / ".env.config"
            if config_file.exists():
                load_dotenv(config_file)
                loaded = True

            # Load .env second (secrets, overrides .env.config)
            env_file = current / ".env"
            if env_file.exists():
                load_dotenv(env_file, override=True)
                loaded = True

            if loaded:
                return True

            current = current.parent

        return False
    except ImportError:
        return False


def _get_bool(key: str, default: bool = False) -> bool:
    """Get boolean from environment variable."""
    value = os.environ.get(key, "").lower()
    if value in ("true", "1", "yes", "on"):
        return True
    if value in ("false", "0", "no", "off"):
        return False
    return default


def _get_int(key: str, default: int) -> int:
    """Get integer from environment variable."""
    value = os.environ.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_float(key: str, default: float) -> float:
    """Get float from environment variable."""
    value = os.environ.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass
class PolymarketConfig:
    """Polymarket exchange configuration."""

    # Authentication
    private_key: str | None = None
    chain_id: int = 137  # Polygon mainnet
    funder: str | None = None
    proxy_wallet: str | None = None  # Proxy wallet address for positions

    # Builder credentials (for gasless split/merge via Relayer)
    builder_api_key: str | None = None
    builder_secret: str | None = None
    builder_passphrase: str | None = None

    # RPC
    rpc_url: str | None = None  # Custom RPC URL (uses public RPC if not set)

    # Market loading
    max_markets: int = 500
    use_events: bool = True  # Use Events endpoint (more efficient)

    # WebSocket
    ws_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for exchange initialization."""
        config: dict[str, Any] = {
            "chain_id": self.chain_id,
            "max_markets": self.max_markets,
            "use_events": self.use_events,
            "ws_enabled": self.ws_enabled,
        }

        if self.private_key and self.private_key != "0x...":
            config["private_key"] = self.private_key

        # funder is used for order signing (maker address)
        # proxy_wallet is used for position queries
        # For Magic/Proxy wallets, they're the same address
        if self.funder:
            config["funder"] = self.funder
        elif self.proxy_wallet and self.proxy_wallet != "0x...":
            # Use proxy_wallet as funder if not explicitly set
            config["funder"] = self.proxy_wallet

        if self.proxy_wallet and self.proxy_wallet != "0x...":
            config["proxy_wallet"] = self.proxy_wallet

        # Builder credentials for gasless split/merge
        if self.builder_api_key:
            config["builder_api_key"] = self.builder_api_key
        if self.builder_secret:
            config["builder_secret"] = self.builder_secret
        if self.builder_passphrase:
            config["builder_passphrase"] = self.builder_passphrase

        # RPC URL
        if self.rpc_url:
            config["rpc_url"] = self.rpc_url

        return config

    @classmethod
    def from_env(cls) -> "PolymarketConfig":
        """Load config from environment variables."""
        proxy_wallet = os.environ.get("POLYMARKET_PROXY_WALLET", "").strip() or None
        if proxy_wallet == "0x...":
            proxy_wallet = None

        # RPC URL: MATIC_RPC or POLYMARKET_RPC_URL
        rpc_url = os.environ.get("MATIC_RPC") or os.environ.get("POLYMARKET_RPC_URL")

        return cls(
            private_key=os.environ.get("POLYMARKET_PRIVATE_KEY"),
            chain_id=_get_int("POLYMARKET_CHAIN_ID", 137),
            funder=os.environ.get("POLYMARKET_FUNDER"),
            proxy_wallet=proxy_wallet,
            builder_api_key=os.environ.get("POLYMARKET_BUILDER_API_KEY"),
            builder_secret=os.environ.get("POLYMARKET_BUILDER_SECRET"),
            builder_passphrase=os.environ.get("POLYMARKET_BUILDER_PASSPHRASE"),
            rpc_url=rpc_url,
            max_markets=_get_int("POLYMARKET_MAX_MARKETS", 500),
            use_events=_get_bool("POLYMARKET_USE_EVENTS", True),
            ws_enabled=_get_bool("POLYMARKET_WS_ENABLED", True),
        )


def get_polymarket_config(
    *,
    private_key: str | None = None,
    chain_id: int | None = None,
    rpc_url: str | None = None,
    max_markets: int | None = None,
    use_events: bool | None = None,
    ws_enabled: bool | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Get Polymarket configuration dict.

    Loads from environment variables, with optional overrides.

    Args:
        private_key: Override private key
        chain_id: Override chain ID
        rpc_url: Override RPC URL (default: MATIC_RPC env var or public RPC)
        max_markets: Override max markets
        use_events: Override use_events
        ws_enabled: Override WebSocket setting
        **kwargs: Additional config options

    Returns:
        Config dict ready for create_exchange()

    Example:
        ```python
        # Use environment variables
        config = get_polymarket_config()

        # Override specific values
        config = get_polymarket_config(max_markets=100, ws_enabled=False)

        # Use custom RPC
        config = get_polymarket_config(rpc_url="https://polygon-mainnet.g.alchemy.com/v2/xxx")

        # Use with exchange
        exchange = create_exchange("polymarket", config)
        ```
    """
    # Load from environment
    env_config = PolymarketConfig.from_env()

    # Apply overrides
    if private_key is not None:
        env_config.private_key = private_key
    if chain_id is not None:
        env_config.chain_id = chain_id
    if rpc_url is not None:
        env_config.rpc_url = rpc_url
    if max_markets is not None:
        env_config.max_markets = max_markets
    if use_events is not None:
        env_config.use_events = use_events
    if ws_enabled is not None:
        env_config.ws_enabled = ws_enabled

    # Convert to dict and merge with kwargs
    config = env_config.to_dict()
    config.update(kwargs)

    return config


@dataclass
class TestConfig:
    """Test configuration."""

    # Search settings
    search_query: str = "btc"
    search_tag: str | None = None  # Category filter (e.g., "crypto", "sports")
    min_volume: int = 1000  # Minimum 24h volume ($)

    # Market ID (optional - for direct testing without search)
    market_id: str | None = None  # Condition ID for order tests

    # Order settings
    order_enabled: bool = False  # WARNING: True = real orders!
    order_size: float = 1.0  # Size in shares or USD
    order_size_type: str = "shares"  # "shares" or "usd"

    # Split/Merge settings (on-chain CTF operations)
    split_amount: float = 1.0  # Amount in USDC for split/merge test

    @classmethod
    def from_env(cls) -> "TestConfig":
        """Load test config from environment variables."""
        search_tag = os.environ.get("TEST_SEARCH_TAG", "").strip() or None
        market_id = os.environ.get("TEST_MARKET_ID", "").strip() or None
        return cls(
            search_query=os.environ.get("TEST_SEARCH_QUERY", "btc"),
            search_tag=search_tag,
            min_volume=_get_int("TEST_MIN_VOLUME", 1000),
            market_id=market_id,
            order_enabled=_get_bool("TEST_ORDER_ENABLED", False),
            order_size=_get_float("TEST_ORDER_SIZE", 1.0),
            order_size_type=os.environ.get("TEST_ORDER_SIZE_TYPE", "shares").lower(),
            split_amount=_get_float("TEST_SPLIT_AMOUNT", 1.0),
        )


def get_test_config() -> TestConfig:
    """Get test configuration from environment."""
    return TestConfig.from_env()


# Auto-load .env on import
load_env()
