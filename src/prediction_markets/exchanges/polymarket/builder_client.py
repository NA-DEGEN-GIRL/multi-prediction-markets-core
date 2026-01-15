"""
Builder Relayer client for Polymarket gasless transactions.

Supports both Gnosis Safe wallets and Proxy wallets (Magic wallet).
Uses the official Polymarket Builder API for gasless split/merge operations.

Usage:
    from prediction_markets.exchanges.polymarket.builder_client import BuilderRelayerClient

    client = BuilderRelayerClient(
        private_key="0x...",
        chain_id=137,
        builder_api_key="...",
        builder_secret="...",
        builder_passphrase="...",
        wallet_type="proxy",  # or "safe"
    )

    # Split USDC into YES + NO tokens
    result = await client.split_position(condition_id, amount, neg_risk=True)
"""

import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import requests
from eth_abi import encode
from eth_account import Account
from eth_utils import keccak, to_checksum_address

# Import from official library
from py_builder_signing_sdk.config import BuilderConfig, BuilderApiKeyCreds
from py_builder_signing_sdk.signer import BuilderSigner


class WalletType(str, Enum):
    """Wallet type for relayer transactions."""
    SAFE = "SAFE"
    PROXY = "PROXY"


class CallType(int, Enum):
    """Call type for proxy transactions."""
    CALL = 0
    DELEGATECALL = 1


@dataclass
class Transaction:
    """Transaction for relayer execution."""
    to: str
    data: str
    value: str = "0"


class TransactionState:
    """Relayer transaction states."""
    NEW = "STATE_NEW"
    EXECUTED = "STATE_EXECUTED"
    MINED = "STATE_MINED"
    CONFIRMED = "STATE_CONFIRMED"
    FAILED = "STATE_FAILED"
    INVALID = "STATE_INVALID"

    PENDING_STATES = {NEW, EXECUTED}
    SUCCESS_STATES = {MINED, CONFIRMED}  # MINED is practically confirmed on Polygon
    FAILURE_STATES = {FAILED, INVALID}
    TERMINAL_STATES = SUCCESS_STATES | FAILURE_STATES


@dataclass
class RelayerResponse:
    """Response from relayer submission."""
    transaction_id: str
    status: str = "STATE_NEW"
    transaction_hash: str | None = None
    _client: Any = None  # Reference to BuilderRelayerClient for polling

    def is_pending(self) -> bool:
        """Check if transaction is still pending."""
        return self.status in TransactionState.PENDING_STATES

    def is_success(self) -> bool:
        """Check if transaction succeeded."""
        return self.status in TransactionState.SUCCESS_STATES

    def is_failed(self) -> bool:
        """Check if transaction failed."""
        return self.status in TransactionState.FAILURE_STATES

    def is_terminal(self) -> bool:
        """Check if transaction reached a terminal state."""
        return self.status in TransactionState.TERMINAL_STATES

    def wait(self, timeout: int = 120, poll_interval: float = 2.0) -> "RelayerResponse":
        """
        Wait for transaction to reach a terminal state.

        Args:
            timeout: Maximum time to wait in seconds
            poll_interval: Time between polls in seconds

        Returns:
            Updated RelayerResponse with final status
        """
        import time

        if self._client is None:
            print(f"[RelayerResponse] No client reference, cannot poll")
            return self

        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.is_terminal():
                return self

            # Poll for status
            try:
                tx_data = self._client.get_transaction(self.transaction_id)
                if tx_data:
                    self.status = tx_data.get("state", self.status)
                    self.transaction_hash = tx_data.get("transactionHash", self.transaction_hash)
                    print(f"[RelayerResponse] Status: {self.status}")

                    if self.is_terminal():
                        return self
            except Exception as e:
                print(f"[RelayerResponse] Poll error: {e}")

            time.sleep(poll_interval)

        print(f"[RelayerResponse] Timeout after {timeout}s, last status: {self.status}")
        return self


# Import contract addresses from constants module
from prediction_markets.exchanges.polymarket.constants import (
    MAINNET_CONTRACTS,
    TESTNET_CONTRACTS,
    POLYGON_MAINNET_CHAIN_ID,
    POLYGON_AMOY_CHAIN_ID,
    ZERO_ADDRESS,
)

# Contract addresses by chain ID (for backward compatibility)
CONTRACT_ADDRESSES = {
    POLYGON_MAINNET_CHAIN_ID: {
        "ctf": MAINNET_CONTRACTS.ctf,
        "usdc": MAINNET_CONTRACTS.usdc,
        "neg_risk_adapter": MAINNET_CONTRACTS.neg_risk_adapter,
        "proxy_factory": MAINNET_CONTRACTS.proxy_factory,
        "relay_hub": MAINNET_CONTRACTS.relay_hub,
    },
    POLYGON_AMOY_CHAIN_ID: {
        "ctf": TESTNET_CONTRACTS.ctf,
        "usdc": TESTNET_CONTRACTS.usdc,
        "neg_risk_adapter": TESTNET_CONTRACTS.neg_risk_adapter,
        "proxy_factory": TESTNET_CONTRACTS.proxy_factory,
        "relay_hub": TESTNET_CONTRACTS.relay_hub,
    },
}

# Binary partition for YES=1, NO=2
BINARY_PARTITION = [1, 2]
ZERO_BYTES32 = bytes(32)


def _function_selector(signature: str) -> bytes:
    """Get first 4 bytes of keccak256 hash of function signature."""
    return keccak(text=signature)[:4]


def encode_approve(spender: str, amount: int) -> str:
    """Encode ERC20 approve function call."""
    selector = _function_selector("approve(address,uint256)")
    encoded_args = encode(["address", "uint256"], [to_checksum_address(spender), amount])
    return "0x" + (selector + encoded_args).hex()


def encode_split_position(
    collateral_token: str,
    condition_id: bytes,
    amount: int,
    neg_risk: bool = False,
) -> tuple[str, str]:
    """
    Encode splitPosition function call.

    Returns:
        Tuple of (target_address, encoded_data)
    """
    if neg_risk:
        # NegRiskAdapter.splitPosition(bytes32 conditionId, uint256 amount)
        selector = _function_selector("splitPosition(bytes32,uint256)")
        encoded_args = encode(["bytes32", "uint256"], [condition_id, amount])
        target = CONTRACT_ADDRESSES[137]["neg_risk_adapter"]
    else:
        # CTF.splitPosition(address,bytes32,bytes32,uint256[],uint256)
        selector = _function_selector("splitPosition(address,bytes32,bytes32,uint256[],uint256)")
        encoded_args = encode(
            ["address", "bytes32", "bytes32", "uint256[]", "uint256"],
            [
                to_checksum_address(CONTRACT_ADDRESSES[137]["usdc"]),
                ZERO_BYTES32,
                condition_id,
                BINARY_PARTITION,
                amount,
            ],
        )
        target = CONTRACT_ADDRESSES[137]["ctf"]

    return target, "0x" + (selector + encoded_args).hex()


def encode_merge_positions(
    collateral_token: str,
    condition_id: bytes,
    amount: int,
    neg_risk: bool = False,
) -> tuple[str, str]:
    """
    Encode mergePositions function call.

    Returns:
        Tuple of (target_address, encoded_data)
    """
    if neg_risk:
        # NegRiskAdapter.mergePositions(bytes32 conditionId, uint256 amount)
        selector = _function_selector("mergePositions(bytes32,uint256)")
        encoded_args = encode(["bytes32", "uint256"], [condition_id, amount])
        target = CONTRACT_ADDRESSES[137]["neg_risk_adapter"]
    else:
        # CTF.mergePositions(address,bytes32,bytes32,uint256[],uint256)
        selector = _function_selector("mergePositions(address,bytes32,bytes32,uint256[],uint256)")
        encoded_args = encode(
            ["address", "bytes32", "bytes32", "uint256[]", "uint256"],
            [
                to_checksum_address(CONTRACT_ADDRESSES[137]["usdc"]),
                ZERO_BYTES32,
                condition_id,
                BINARY_PARTITION,
                amount,
            ],
        )
        target = CONTRACT_ADDRESSES[137]["ctf"]

    return target, "0x" + (selector + encoded_args).hex()


def encode_redeem_positions(
    collateral_token: str,
    condition_id: bytes,
) -> tuple[str, str]:
    """
    Encode redeemPositions function call.

    CTF.redeemPositions(address collateralToken, bytes32 parentCollectionId, bytes32 conditionId, uint256[] indexSets)

    Returns:
        Tuple of (target_address, encoded_data)
    """
    # CTF.redeemPositions(address,bytes32,bytes32,uint256[])
    selector = _function_selector("redeemPositions(address,bytes32,bytes32,uint256[])")
    encoded_args = encode(
        ["address", "bytes32", "bytes32", "uint256[]"],
        [
            to_checksum_address(collateral_token),
            ZERO_BYTES32,  # parentCollectionId = 0 for root conditions
            condition_id,
            BINARY_PARTITION,  # [1, 2] for YES/NO
        ],
    )
    target = CONTRACT_ADDRESSES[137]["ctf"]

    return target, "0x" + (selector + encoded_args).hex()


def encode_proxy_call(calls: list[tuple[int, str, int, str]]) -> str:
    """
    Encode proxy(ProxyCall[] calls) function call.

    Args:
        calls: List of (callType, to, value, data) tuples

    Returns:
        Encoded function call data
    """
    # proxy() selector: keccak256("proxy((uint8,address,uint256,bytes)[])")[:4]
    selector = bytes.fromhex("34ee9791")

    # Convert data strings to bytes
    calls_with_bytes = []
    for call_type, to_addr, value, data in calls:
        data_bytes = bytes.fromhex(data[2:]) if data.startswith("0x") else bytes.fromhex(data)
        calls_with_bytes.append((call_type, to_checksum_address(to_addr), value, data_bytes))

    encoded_args = encode(
        ["(uint8,address,uint256,bytes)[]"],
        [calls_with_bytes],
    )

    return "0x" + (selector + encoded_args).hex()


class BuilderRelayerClient:
    """
    Client for Polymarket Builder Relayer API.

    Supports gasless transactions for both Gnosis Safe and Proxy wallets.
    """

    RELAYER_URL = "https://relayer-v2.polymarket.com"

    def __init__(
        self,
        private_key: str,
        chain_id: int = 137,
        builder_api_key: str | None = None,
        builder_secret: str | None = None,
        builder_passphrase: str | None = None,
        wallet_type: str = "proxy",
        proxy_wallet: str | None = None,
    ):
        """
        Initialize Builder Relayer client.

        Args:
            private_key: Wallet private key
            chain_id: Chain ID (137 for mainnet)
            builder_api_key: Builder API key
            builder_secret: Builder API secret
            builder_passphrase: Builder API passphrase
            wallet_type: "proxy" for Magic wallet, "safe" for Gnosis Safe
            proxy_wallet: Proxy wallet address (optional, derived if not provided)
        """
        self._private_key = private_key
        self._chain_id = chain_id
        self._wallet_type = WalletType(wallet_type.upper())

        # Get addresses
        self._account = Account.from_key(private_key)
        self._address = self._account.address

        # Derive proxy wallet if not provided
        if proxy_wallet:
            self._proxy_wallet = to_checksum_address(proxy_wallet)
        else:
            self._proxy_wallet = self._derive_proxy_wallet()

        # Contract addresses
        self._contracts = CONTRACT_ADDRESSES.get(chain_id, CONTRACT_ADDRESSES[137])

        # Builder config and signer
        if builder_api_key and builder_secret and builder_passphrase:
            self._builder_creds = BuilderApiKeyCreds(
                key=builder_api_key,
                secret=builder_secret,
                passphrase=builder_passphrase,
            )
            self._builder_signer = BuilderSigner(self._builder_creds)
            self._builder_config = BuilderConfig(local_builder_creds=self._builder_creds)
        else:
            self._builder_creds = None
            self._builder_signer = None
            self._builder_config = None

        self._nonce: int | None = None

    def _derive_proxy_wallet(self) -> str:
        """
        Get proxy wallet address.

        NOTE: Proxy wallet derivation is not implemented because:
        - The proxy wallet is created by Polymarket's Proxy Factory contract
        - The derivation requires on-chain lookup or API call
        - Magic wallet users MUST provide POLYMARKET_PROXY_WALLET in .env

        For Magic/Proxy users (signature_type=1 or 2):
        - Go to https://polymarket.com/settings
        - Find "Deposit Address" or "Your wallet address"
        - Set POLYMARKET_PROXY_WALLET in your .env file

        Returns:
            Signing address as fallback (only correct for EOA users)
        """
        import warnings
        warnings.warn(
            "Proxy wallet not provided. For Magic wallet users (signature_type=1), "
            "you MUST set POLYMARKET_PROXY_WALLET in .env. "
            "Find it at https://polymarket.com/settings",
            UserWarning,
            stacklevel=2,
        )
        return self._address  # Fallback for EOA users only

    def _get_builder_headers(self, method: str, path: str, body: str = "") -> dict[str, str]:
        """Get builder authentication headers."""
        if not self._builder_signer:
            return {}

        # Use BuilderSigner to create properly formatted headers
        payload = self._builder_signer.create_builder_header_payload(method, path, body)

        return {
            "POLY_BUILDER_API_KEY": payload.POLY_BUILDER_API_KEY,
            "POLY_BUILDER_TIMESTAMP": payload.POLY_BUILDER_TIMESTAMP,
            "POLY_BUILDER_PASSPHRASE": payload.POLY_BUILDER_PASSPHRASE,
            "POLY_BUILDER_SIGNATURE": payload.POLY_BUILDER_SIGNATURE,
        }

    def _create_proxy_struct_hash(
        self,
        encoded_data: str,
        nonce: int,
        gas_limit: int = 500000,
        gas_price: int = 0,
        relayer_fee: int = 0,
        relay_address: str = "ZERO_ADDRESS",
    ) -> bytes:
        """
        Create struct hash for proxy transaction signing.

        Uses the "rlx:" prefix format from Polymarket's relayer.
        This is RAW CONCATENATION, not ABI encoding!
        """
        relay_hub = self._contracts["relay_hub"]

        # Data bytes
        data_bytes = bytes.fromhex(encoded_data[2:]) if encoded_data.startswith("0x") else bytes.fromhex(encoded_data)

        # Build the struct hash message via raw concatenation (NOT ABI encoding!)
        # Format: "rlx:" + from(20) + to(20) + data(var) + txFee(32) + gasPrice(32) + gasLimit(32) + nonce(32) + relayHub(20) + relay(20)
        # IMPORTANT: 'from' is the EOA signing address!
        message = b"rlx:"
        message += bytes.fromhex(self._address[2:])  # from = EOA address (20 bytes)
        message += bytes.fromhex(self._contracts["proxy_factory"][2:])  # to (20 bytes)
        message += data_bytes  # data (variable length)
        message += relayer_fee.to_bytes(32, "big")  # txFee (32 bytes)
        message += gas_price.to_bytes(32, "big")  # gasPrice (32 bytes)
        message += gas_limit.to_bytes(32, "big")  # gasLimit (32 bytes)
        message += nonce.to_bytes(32, "big")  # nonce (32 bytes)
        message += bytes.fromhex(relay_hub[2:])  # relayHub (20 bytes)
        message += bytes.fromhex(relay_address[2:] if relay_address.startswith("0x") else relay_address)  # relay (20 bytes)

        return keccak(message)

    def _sign_proxy_transaction(
        self,
        encoded_data: str,
        nonce: int,
        gas_limit: int = 500000,
        relay_address: str = "ZERO_ADDRESS",
    ) -> str:
        """Sign proxy transaction with struct hash using signMessage."""
        struct_hash = self._create_proxy_struct_hash(encoded_data, nonce, gas_limit, relay_address=relay_address)

        # Use sign_message which adds Ethereum signed message prefix
        # This matches TypeScript's signer.signMessage(structHash)
        from eth_account.messages import encode_defunct

        # struct_hash is bytes, convert to hex string for signing
        message = encode_defunct(struct_hash)
        signed = Account.sign_message(message, self._private_key)

        sig_hex = signed.signature.hex()
        if not sig_hex.startswith("0x"):
            sig_hex = "0x" + sig_hex
        return sig_hex

    def get_nonce(self) -> int:
        """Get current nonce from relayer."""
        url = f"{self.RELAYER_URL}/nonce"
        # Query with EOA address
        params = {"address": self._address, "type": self._wallet_type.value}

        headers = self._get_builder_headers("GET", f"/nonce?address={self._address}&type={self._wallet_type.value}")

        response = requests.get(url, params=params, headers=headers)
        if response.status_code == 200:
            data = response.json()
            nonce = int(data.get("nonce", 0))
            print(f"[BuilderClient] Nonce: {nonce}")
            return nonce
        else:
            print(f"[BuilderClient] Nonce error: {response.text}")
            return 0

    def get_relay_payload(self) -> dict[str, Any]:
        """Get relay payload including proxy wallet and nonce."""
        url = f"{self.RELAYER_URL}/relay-payload"
        # Query with EOA address - the relayer should return the proxy wallet info
        params = {"address": self._address, "type": self._wallet_type.value}

        headers = self._get_builder_headers("GET", f"/relay-payload?address={self._address}&type={self._wallet_type.value}")

        response = requests.get(url, params=params, headers=headers)
        print(f"[BuilderClient] Relay payload response ({response.status_code}): {response.text}")
        if response.status_code == 200:
            data = response.json()
            return data
        else:
            return {}

    def get_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        """Get transaction status by ID."""
        url = f"{self.RELAYER_URL}/transaction"
        params = {"id": transaction_id}

        headers = self._get_builder_headers("GET", f"/transaction?id={transaction_id}")

        response = requests.get(url, params=params, headers=headers)
        if response.status_code == 200:
            data = response.json()
            # Response is a list, return first item
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            return data
        else:
            return None

    def execute(
        self,
        transactions: list[Transaction],
        metadata: str = "",
    ) -> RelayerResponse:
        """
        Execute transactions via relayer.

        Args:
            transactions: List of Transaction objects
            metadata: Optional metadata string

        Returns:
            RelayerResponse with transaction ID
        """
        if self._wallet_type == WalletType.PROXY:
            return self._execute_proxy(transactions, metadata)
        else:
            return self._execute_safe(transactions, metadata)

    def _execute_proxy(
        self,
        transactions: list[Transaction],
        metadata: str = "",
    ) -> RelayerResponse:
        """Execute transactions for Proxy wallet."""
        # Get relay payload first (contains nonce and relay address)
        relay_payload = self.get_relay_payload()
        nonce = int(relay_payload.get("nonce", 0))
        relay_address = relay_payload.get("address", "ZERO_ADDRESS")

        print(f"[BuilderClient] Relay nonce: {nonce}, relay: {relay_address}")
        print(f"[BuilderClient] EOA address: {self._address}")
        print(f"[BuilderClient] Proxy wallet: {self._proxy_wallet}")

        # Encode proxy call with all transactions
        # typeCode: 1 = CALL in Polymarket's convention
        calls = []
        for tx in transactions:
            calls.append((
                1,  # typeCode = 1 (CALL in Polymarket)
                tx.to,
                int(tx.value),
                tx.data,
            ))

        encoded_data = encode_proxy_call(calls)

        # Sign the transaction with relay address
        # Use reasonable gas limit (10M was causing relay hub to reject)
        # Typical merge/split operations use ~150k-200k gas
        gas_limit = 500000
        signature = self._sign_proxy_transaction(encoded_data, nonce, gas_limit, relay_address)

        # Build payload
        # from = EOA address (the signer)
        # proxyWallet = derived proxy wallet address
        payload = {
            "from": self._address,
            "to": self._contracts["proxy_factory"],
            "proxyWallet": self._proxy_wallet,
            "data": encoded_data,
            "nonce": str(nonce),
            "signature": signature,
            "signatureParams": {
                "gasPrice": "0",
                "gasLimit": str(gas_limit),
                "relayerFee": "0",
                "relayHub": self._contracts["relay_hub"],
                "relay": relay_address,
            },
            "type": "PROXY",
            "metadata": metadata,
        }

        # Submit to relayer
        url = f"{self.RELAYER_URL}/submit"
        body_json = json.dumps(payload)
        headers = self._get_builder_headers("POST", "/submit", body_json)
        headers["Content-Type"] = "application/json"

        print(f"[BuilderClient] Submitting proxy transaction...")

        response = requests.post(url, json=payload, headers=headers)

        if response.status_code >= 400:
            raise Exception(f"Relayer error ({response.status_code}): {response.text}")

        data = response.json()
        print(f"[BuilderClient] Response: {data}")

        return RelayerResponse(
            transaction_id=data.get("transactionID", data.get("transactionId", data.get("id", ""))),
            status=data.get("state", TransactionState.NEW),
            transaction_hash=data.get("transactionHash"),
            _client=self,
        )

    def _execute_safe(
        self,
        transactions: list[Transaction],
        metadata: str = "",
    ) -> RelayerResponse:
        """Execute transactions for Gnosis Safe wallet."""
        # Use the official py-builder-relayer-client for Safe transactions
        from py_builder_relayer_client.client import RelayClient
        from py_builder_relayer_client.models import OperationType, SafeTransaction

        client = RelayClient(
            self.RELAYER_URL,
            self._chain_id,
            self._private_key,
            self._builder_config,
        )

        safe_txs = [
            SafeTransaction(
                to=tx.to,
                operation=OperationType.Call,
                data=tx.data,
                value=tx.value,
            )
            for tx in transactions
        ]

        resp = client.execute(safe_txs, metadata)
        return RelayerResponse(
            transaction_id=resp.id if hasattr(resp, 'id') else str(resp),
            status=TransactionState.NEW,
            _client=self,
        )

    # === High-level operations ===

    def split_position(
        self,
        condition_id: str,
        amount: int,
        neg_risk: bool = False,
    ) -> RelayerResponse:
        """
        Split USDC into YES + NO tokens.

        Args:
            condition_id: Market condition ID (hex string)
            amount: Amount in wei (USDC has 6 decimals)
            neg_risk: True for negative risk markets

        Returns:
            RelayerResponse with transaction details
        """
        # Convert condition_id to bytes
        if condition_id.startswith("0x"):
            condition_bytes = bytes.fromhex(condition_id[2:])
        else:
            condition_bytes = bytes.fromhex(condition_id)

        # Determine target and encode
        target, split_data = encode_split_position(
            self._contracts["usdc"],
            condition_bytes,
            amount,
            neg_risk,
        )

        # Create approve transaction (if needed)
        approve_data = encode_approve(target, 2**256 - 1)

        transactions = [
            Transaction(to=self._contracts["usdc"], data=approve_data),
            Transaction(to=target, data=split_data),
        ]

        return self.execute(transactions, "split")

    def merge_positions(
        self,
        condition_id: str,
        amount: int,
        neg_risk: bool = False,
    ) -> RelayerResponse:
        """
        Merge YES + NO tokens back into USDC.

        Args:
            condition_id: Market condition ID (hex string)
            amount: Amount in wei
            neg_risk: True for negative risk markets

        Returns:
            RelayerResponse with transaction details
        """
        # Convert condition_id to bytes
        if condition_id.startswith("0x"):
            condition_bytes = bytes.fromhex(condition_id[2:])
        else:
            condition_bytes = bytes.fromhex(condition_id)

        # Encode merge
        target, merge_data = encode_merge_positions(
            self._contracts["usdc"],
            condition_bytes,
            amount,
            neg_risk,
        )

        transactions = [
            Transaction(to=target, data=merge_data),
        ]

        return self.execute(transactions, "merge")

    def redeem_positions(
        self,
        condition_id: str,
    ) -> RelayerResponse:
        """
        Redeem winning positions after market resolution.

        Redeems both YES and NO tokens for a resolved market.
        Only winning tokens will return collateral (USDC).

        Args:
            condition_id: Market condition ID (hex string)

        Returns:
            RelayerResponse with transaction details
        """
        # Convert condition_id to bytes
        if condition_id.startswith("0x"):
            condition_bytes = bytes.fromhex(condition_id[2:])
        else:
            condition_bytes = bytes.fromhex(condition_id)

        # Encode redeem
        target, redeem_data = encode_redeem_positions(
            self._contracts["usdc"],
            condition_bytes,
        )

        transactions = [
            Transaction(to=target, data=redeem_data),
        ]

        return self.execute(transactions, "redeem")
