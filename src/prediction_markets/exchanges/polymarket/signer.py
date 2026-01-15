"""
Polymarket order signing module.

Handles EIP-712 order signing using py_order_utils library.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum
from typing import Any

from eth_account import Account

# py_order_utils imports
try:
    from py_order_utils.builders import OrderBuilder as UtilsOrderBuilder
    from py_order_utils.model import OrderData
    from py_order_utils.signer import Signer

    HAS_ORDER_UTILS = True
except ImportError:
    HAS_ORDER_UTILS = False


class Side(IntEnum):
    """Order side."""

    BUY = 0
    SELL = 1


class SignatureType(IntEnum):
    """
    Signature type for different wallet types.

    POLY_PROXY (1) is the default and recommended type for Polymarket.
    """

    EOA = 0  # Legacy: Standard EOA (not used by Polymarket)
    POLY_PROXY = 1  # Polymarket Magic wallet (default, recommended)
    POLY_GNOSIS_SAFE = 2  # Gnosis Safe proxy


@dataclass
class OrderArgs:
    """Arguments for creating an order."""

    token_id: str
    side: Side
    size: Decimal  # Number of shares
    price: Decimal  # Price per share (0 to 1)
    fee_rate_bps: int = 0  # Fee rate in basis points
    nonce: int = 0
    expiration: int = 0  # Unix timestamp, 0 = no expiration
    taker: str = "0x0000000000000000000000000000000000000000"


@dataclass
class CreateOrderOptions:
    """Options for order creation."""

    tick_size: Decimal = Decimal("0.01")  # Price tick size (0.01 or 0.001)
    neg_risk: bool = False  # Negative risk market


@dataclass
class SignedOrder:
    """Signed order ready for submission."""

    order: dict[str, Any]
    signature: str
    owner: str
    order_type: str = "GTC"  # Good Till Cancelled


# Rounding configuration based on tick size
ROUNDING_CONFIG = {
    "0.1": {"price": 1, "size": 2, "amount": 3},
    "0.01": {"price": 2, "size": 2, "amount": 4},
    "0.001": {"price": 3, "size": 2, "amount": 5},
    "0.0001": {"price": 4, "size": 2, "amount": 6},
}

# Import contract addresses from constants module
from prediction_markets.exchanges.polymarket.constants import (
    COLLATERAL_ADDRESS,
    EXCHANGE_ADDRESS,
    NEG_RISK_ADAPTER_ADDRESS,
    NEG_RISK_EXCHANGE_ADDRESS,
)


class OrderSigner:
    """
    Signs orders for Polymarket using EIP-712.

    Example:
        ```python
        signer = OrderSigner(
            private_key="0x...",
            chain_id=137,
        )

        signed = signer.create_and_sign_order(
            OrderArgs(
                token_id="...",
                side=Side.BUY,
                size=Decimal("10"),
                price=Decimal("0.65"),
            )
        )

        # Submit to API
        await client.post_order(signed.to_dict())
        ```
    """

    def __init__(
        self,
        private_key: str,
        chain_id: int = 137,
        signature_type: SignatureType = SignatureType.POLY_PROXY,
        funder: str | None = None,
    ) -> None:
        """
        Initialize order signer.

        Args:
            private_key: Wallet private key (hex string)
            chain_id: Chain ID (137 for Polygon mainnet)
            signature_type: Type of signature to use (default: POLY_PROXY)
            funder: Funder address (proxy wallet address from Polymarket settings)
        """
        if not HAS_ORDER_UTILS:
            raise ImportError(
                "py_order_utils is required for order signing. "
                "Install with: pip install py-order-utils"
            )

        self._private_key = private_key
        self._chain_id = chain_id
        self._signature_type = signature_type
        self._funder = funder

        # Get address from private key
        account = Account.from_key(private_key)
        self._address = account.address

        # Initialize py_order_utils signer
        self._signer = Signer(private_key)

        # Create builders for regular and neg_risk exchanges
        self._builder = UtilsOrderBuilder(
            EXCHANGE_ADDRESS, chain_id, self._signer
        )
        self._builder_neg_risk = UtilsOrderBuilder(
            NEG_RISK_EXCHANGE_ADDRESS, chain_id, self._signer
        )

    @property
    def address(self) -> str:
        """Get wallet address."""
        return self._address

    def create_and_sign_order(
        self,
        args: OrderArgs,
        options: CreateOrderOptions | None = None,
    ) -> SignedOrder:
        """
        Create and sign an order.

        Args:
            args: Order arguments
            options: Order creation options

        Returns:
            Signed order ready for submission
        """
        options = options or CreateOrderOptions()

        # Get rounding config
        tick_str = str(options.tick_size)
        round_config = ROUNDING_CONFIG.get(tick_str, ROUNDING_CONFIG["0.01"])

        # Round price and size
        price = self._round_decimal(args.price, round_config["price"])
        size = self._round_decimal(args.size, round_config["size"])

        # Calculate amounts (matches py-clob-client logic)
        # BUY: maker spends USDC, taker receives shares
        # SELL: maker spends shares, taker receives USDC
        if args.side == Side.BUY:
            maker_amount = self._to_wei(size * price)  # USDC to spend
            taker_amount = self._to_wei(size)          # shares to receive
        else:  # SELL
            maker_amount = self._to_wei(size)          # shares to sell
            taker_amount = self._to_wei(size * price)  # USDC to receive

        # Build order data (all numeric fields must be strings)
        order_data = OrderData(
            maker=self._funder or self._address,
            signer=self._address,
            taker=args.taker,
            tokenId=args.token_id,
            makerAmount=str(maker_amount),
            takerAmount=str(taker_amount),
            side=int(args.side),
            feeRateBps=str(args.fee_rate_bps),
            nonce=str(args.nonce),
            expiration=str(args.expiration),
            signatureType=int(self._signature_type),
        )

        # Select builder based on neg_risk
        builder = self._builder_neg_risk if options.neg_risk else self._builder

        # Sign order
        signed_order = builder.build_signed_order(order_data)

        return SignedOrder(
            order=signed_order.order.dict(),
            signature=signed_order.signature,
            owner=self._address,
        )

    def create_market_order(
        self,
        token_id: str,
        side: Side,
        amount: Decimal,  # USD amount
        price: Decimal,  # Expected price
        options: CreateOrderOptions | None = None,
    ) -> SignedOrder:
        """
        Create a market order (FOK - Fill or Kill).

        Args:
            token_id: Token ID to trade
            side: BUY or SELL
            amount: Amount in USD
            price: Expected execution price
            options: Order creation options

        Returns:
            Signed market order
        """
        options = options or CreateOrderOptions()

        # Calculate size from amount
        size = amount / price

        args = OrderArgs(
            token_id=token_id,
            side=side,
            size=size,
            price=price,
        )

        signed = self.create_and_sign_order(args, options)
        signed.order_type = "FOK"  # Fill or Kill for market orders
        return signed

    def _round_decimal(self, value: Decimal, decimals: int) -> Decimal:
        """Round decimal to specified number of decimal places."""
        quantize_str = "0." + "0" * decimals
        return value.quantize(Decimal(quantize_str))

    def _to_wei(self, value: Decimal) -> int:
        """Convert decimal to wei (6 decimals for USDC)."""
        return int(value * Decimal("1000000"))


class OrderSignerManual:
    """
    Manual order signer without py_order_utils dependency.

    Use this if py_order_utils is not available.
    Implements basic EIP-712 signing for Polymarket orders.
    """

    # EIP-712 domain
    DOMAIN_NAME = "Polymarket CTF Exchange"
    DOMAIN_VERSION = "1"

    # Order type hash
    ORDER_TYPEHASH = "Order(uint256 salt,address maker,address signer,address taker,uint256 tokenId,uint256 makerAmount,uint256 takerAmount,uint256 expiration,uint256 nonce,uint256 feeRateBps,uint8 side,uint8 signatureType)"

    def __init__(
        self,
        private_key: str,
        chain_id: int = 137,
        signature_type: SignatureType = SignatureType.POLY_PROXY,
        funder: str | None = None,
    ) -> None:
        """Initialize manual signer."""
        self._private_key = private_key
        self._chain_id = chain_id
        self._signature_type = signature_type
        self._funder = funder

        account = Account.from_key(private_key)
        self._address = account.address

    @property
    def address(self) -> str:
        """Get wallet address."""
        return self._address

    def create_and_sign_order(
        self,
        args: OrderArgs,
        options: CreateOrderOptions | None = None,
    ) -> SignedOrder:
        """
        Create and sign order manually.

        This is a fallback implementation.
        Prefer using OrderSigner with py_order_utils.
        """
        import secrets
        from eth_account.messages import encode_structured_data

        options = options or CreateOrderOptions()

        # Get rounding config
        tick_str = str(options.tick_size)
        round_config = ROUNDING_CONFIG.get(tick_str, ROUNDING_CONFIG["0.01"])

        price = self._round_decimal(args.price, round_config["price"])
        size = self._round_decimal(args.size, round_config["size"])

        # Select exchange address
        exchange = NEG_RISK_EXCHANGE_ADDRESS if options.neg_risk else EXCHANGE_ADDRESS

        # Generate random salt
        salt = secrets.randbits(256)

        # Calculate amounts (matches py-clob-client logic)
        # BUY: maker spends USDC, taker receives shares
        # SELL: maker spends shares, taker receives USDC
        if args.side == Side.BUY:
            maker_amount = self._to_wei(size * price)  # USDC to spend
            taker_amount = self._to_wei(size)          # shares to receive
        else:  # SELL
            maker_amount = self._to_wei(size)          # shares to sell
            taker_amount = self._to_wei(size * price)  # USDC to receive

        # Build order
        order = {
            "salt": salt,
            "maker": self._funder or self._address,
            "signer": self._address,
            "taker": args.taker,
            "tokenId": int(args.token_id),
            "makerAmount": maker_amount,
            "takerAmount": taker_amount,
            "expiration": args.expiration,
            "nonce": args.nonce,
            "feeRateBps": args.fee_rate_bps,
            "side": int(args.side),
            "signatureType": int(self._signature_type),
        }

        # EIP-712 structured data
        structured_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "Order": [
                    {"name": "salt", "type": "uint256"},
                    {"name": "maker", "type": "address"},
                    {"name": "signer", "type": "address"},
                    {"name": "taker", "type": "address"},
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "makerAmount", "type": "uint256"},
                    {"name": "takerAmount", "type": "uint256"},
                    {"name": "expiration", "type": "uint256"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "feeRateBps", "type": "uint256"},
                    {"name": "side", "type": "uint8"},
                    {"name": "signatureType", "type": "uint8"},
                ],
            },
            "primaryType": "Order",
            "domain": {
                "name": self.DOMAIN_NAME,
                "version": self.DOMAIN_VERSION,
                "chainId": self._chain_id,
                "verifyingContract": exchange,
            },
            "message": order,
        }

        # Sign
        encoded = encode_structured_data(primitive=structured_data)
        account = Account.from_key(self._private_key)
        signed = account.sign_message(encoded)

        return SignedOrder(
            order=order,
            signature=signed.signature.hex(),
            owner=self._address,
        )

    def _round_decimal(self, value: Decimal, decimals: int) -> Decimal:
        """Round decimal."""
        quantize_str = "0." + "0" * decimals
        return value.quantize(Decimal(quantize_str))

    def _to_wei(self, value: Decimal) -> int:
        """Convert to wei."""
        return int(value * Decimal("1000000"))


def get_order_signer(
    private_key: str,
    chain_id: int = 137,
    signature_type: SignatureType = SignatureType.POLY_PROXY,
    funder: str | None = None,
) -> OrderSigner | OrderSignerManual:
    """
    Get appropriate order signer.

    Uses OrderSigner if py_order_utils is available,
    falls back to OrderSignerManual otherwise.

    Args:
        private_key: Wallet private key (hex string)
        chain_id: Chain ID (137 for Polygon mainnet)
        signature_type: Type of signature (default: POLY_PROXY)
        funder: Proxy wallet address from Polymarket settings
    """
    if HAS_ORDER_UTILS:
        return OrderSigner(private_key, chain_id, signature_type, funder)
    else:
        return OrderSignerManual(private_key, chain_id, signature_type, funder)
