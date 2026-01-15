"""
Polymarket contract addresses and constants.

All contract addresses for Polygon mainnet and Amoy testnet.
These addresses should be the single source of truth across all modules.

Reference: https://docs.polymarket.com/#contract-addresses
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PolymarketContracts:
    """Contract addresses for a specific network."""
    ctf: str  # Conditional Token Framework
    usdc: str  # USDC collateral
    ctf_exchange: str  # CTF Exchange (order matching)
    neg_risk_adapter: str  # Neg Risk Adapter
    neg_risk_ctf_exchange: str  # Neg Risk CTF Exchange
    proxy_factory: str  # Proxy Wallet Factory
    relay_hub: str  # GSN Relay Hub


# Polygon Mainnet (chain_id: 137)
MAINNET_CONTRACTS = PolymarketContracts(
    ctf="0x4D97DCd97eC945f40cF65F87097ACe5EA0476045",
    usdc="0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    ctf_exchange="0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
    neg_risk_adapter="0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",
    neg_risk_ctf_exchange="0xC5d563A36AE78145C45a50134d48A1215220f80a",
    proxy_factory="0xaB45c5A4B0c941a2F231C04C3f49182e1A254052",
    relay_hub="0xD216153c06E857cD7f72665E0aF1d7D82172F494",
)

# Polygon Amoy Testnet (chain_id: 80002)
TESTNET_CONTRACTS = PolymarketContracts(
    ctf="0x69308FB512518e39F9b16112fA8d994F4e2Bf8bB",
    usdc="0x9c4e1703476e875070ee25b56a58b008cfb8fa78",
    ctf_exchange="0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",  # Same as mainnet
    neg_risk_adapter="0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",
    neg_risk_ctf_exchange="0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",
    proxy_factory="0xaB45c5A4B0c941a2F231C04C3f49182e1A254052",  # Same as mainnet
    relay_hub="0xD216153c06E857cD7f72665E0aF1d7D82172F494",  # Same as mainnet
)

# Chain IDs
POLYGON_MAINNET_CHAIN_ID = 137
POLYGON_AMOY_CHAIN_ID = 80002

# Zero address (for relay, taker defaults)
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# Relayer addresses (for GSN relay)
RELAY_ADDRESS = "0xa7be1729f709955d7e0081cf07806e9f806dae26"


def get_contracts(chain_id: int) -> PolymarketContracts:
    """
    Get contract addresses for a specific chain.

    Args:
        chain_id: Network chain ID (137 for mainnet, 80002 for testnet)

    Returns:
        PolymarketContracts with addresses for the chain

    Raises:
        ValueError: If chain_id is not supported
    """
    if chain_id == POLYGON_MAINNET_CHAIN_ID:
        return MAINNET_CONTRACTS
    elif chain_id == POLYGON_AMOY_CHAIN_ID:
        return TESTNET_CONTRACTS
    else:
        raise ValueError(f"Unsupported chain_id: {chain_id}. Use 137 (mainnet) or 80002 (testnet)")


# Legacy aliases for backward compatibility
# TODO: Remove these after updating all references
EXCHANGE_ADDRESS = MAINNET_CONTRACTS.ctf_exchange
NEG_RISK_EXCHANGE_ADDRESS = MAINNET_CONTRACTS.neg_risk_ctf_exchange
COLLATERAL_ADDRESS = MAINNET_CONTRACTS.usdc
NEG_RISK_ADAPTER_ADDRESS = MAINNET_CONTRACTS.neg_risk_adapter
