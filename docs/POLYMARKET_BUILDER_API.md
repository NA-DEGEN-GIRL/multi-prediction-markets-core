# Polymarket Builder API - PROXY Wallet 구현 가이드

## 개요

Polymarket의 Magic wallet 사용자는 개인키가 TEE(Trusted Execution Environment)에 저장되어 있어 로컬에서 서명할 수 없다. 이 문제를 해결하기 위해 Builder API를 사용하여 가스비 없이 split/merge 작업을 수행할 수 있다.

## 지갑 타입

| 타입 | 설명 | 사용자 |
|------|------|--------|
| **SAFE** | Gnosis Safe 지갑 | 일반 EOA 사용자 |
| **PROXY** | Polymarket 커스텀 프록시 지갑 | Magic Link 사용자 |

## 필수 자격증명

Builder 자격증명은 https://polymarket.com/settings?tab=builder 에서 생성 가능:

```bash
POLYMARKET_BUILDER_API_KEY=xxx
POLYMARKET_BUILDER_SECRET=xxx
POLYMARKET_BUILDER_PASSPHRASE=xxx
POLYMARKET_PROXY_WALLET=0x...  # Polymarket Settings에서 확인
```

## SDK 지원 현황

| SDK | SAFE | PROXY |
|-----|------|-------|
| TypeScript (`@polymarket/builder-relayer-client`) | ✅ | ✅ |
| Python (`py-builder-relayer-client`) | ✅ | ❌ |

**Python SDK는 PROXY를 지원하지 않으므로 직접 구현 필요!**

---

## PROXY 트랜잭션 구현

### 1. API 엔드포인트

```
Base URL: https://relayer-v2.polymarket.com

GET  /relay-payload?address={EOA}&type=PROXY  # nonce, relay 주소 조회
GET  /nonce?address={EOA}&type=PROXY          # nonce만 조회
POST /submit                                   # 트랜잭션 제출
```

### 2. 인증 헤더

Builder SDK를 사용하여 자동 생성:

```python
from py_builder_signing_sdk.config import BuilderConfig, BuilderApiKeyCreds
from py_builder_signing_sdk.signer import BuilderSigner

creds = BuilderApiKeyCreds(key=api_key, secret=secret, passphrase=passphrase)
signer = BuilderSigner(creds)
payload = signer.create_builder_header_payload(method, path, body)

headers = {
    "POLY_BUILDER_API_KEY": payload.POLY_BUILDER_API_KEY,
    "POLY_BUILDER_TIMESTAMP": payload.POLY_BUILDER_TIMESTAMP,
    "POLY_BUILDER_PASSPHRASE": payload.POLY_BUILDER_PASSPHRASE,
    "POLY_BUILDER_SIGNATURE": payload.POLY_BUILDER_SIGNATURE,
}
```

### 3. Struct Hash 생성

**순서가 매우 중요!**

```python
from eth_utils import keccak

def create_proxy_struct_hash(
    from_address: str,      # EOA 주소 (서명자)
    to_address: str,        # Proxy Factory 주소
    data: bytes,            # 인코딩된 트랜잭션 데이터
    tx_fee: int,            # 0
    gas_price: int,         # 0
    gas_limit: int,         # 500000 (10M은 relay hub에서 거부됨)
    nonce: int,             # relay-payload에서 받은 값
    relay_hub: str,         # RelayHub 컨트랙트 주소
    relay_address: str,     # relay-payload에서 받은 값
) -> bytes:
    # Raw concatenation (ABI encoding 아님!)
    message = b"rlx:"
    message += bytes.fromhex(from_address[2:])      # 20 bytes
    message += bytes.fromhex(to_address[2:])        # 20 bytes
    message += data                                  # variable
    message += tx_fee.to_bytes(32, "big")           # 32 bytes
    message += gas_price.to_bytes(32, "big")        # 32 bytes
    message += gas_limit.to_bytes(32, "big")        # 32 bytes
    message += nonce.to_bytes(32, "big")            # 32 bytes
    message += bytes.fromhex(relay_hub[2:])         # 20 bytes
    message += bytes.fromhex(relay_address[2:])     # 20 bytes

    return keccak(message)
```

### 4. 서명 생성 (핵심!)

**반드시 `sign_message` 사용! (Ethereum signed message prefix 추가)**

```python
from eth_account import Account
from eth_account.messages import encode_defunct

def sign_proxy_transaction(struct_hash: bytes, private_key: str) -> str:
    # encode_defunct adds: "\x19Ethereum Signed Message:\n" + len + message
    message = encode_defunct(struct_hash)
    signed = Account.sign_message(message, private_key)
    return "0x" + signed.signature.hex()
```

❌ **잘못된 방법:**
```python
# unsafe_sign_hash는 prefix를 추가하지 않음!
signed = Account.unsafe_sign_hash(struct_hash, private_key)
```

### 5. Payload 구조

```python
payload = {
    "from": eoa_address,           # EOA 주소 (서명자)
    "to": proxy_factory_address,   # Proxy Factory
    "proxyWallet": proxy_wallet,   # Proxy Wallet 주소
    "data": encoded_data,          # 인코딩된 proxy() 호출
    "nonce": str(nonce),
    "signature": signature,
    "signatureParams": {
        "gasPrice": "0",
        "gasLimit": "500000",
        "relayerFee": "0",
        "relayHub": relay_hub_address,
        "relay": relay_address,
    },
    "type": "PROXY",
    "metadata": "split",  # 또는 "merge"
}
```

### 6. 주소 필드 요약

| 필드 | 값 | 설명 |
|------|-----|------|
| `from` | EOA 주소 | 개인키로 서명하는 지갑 |
| `to` | Proxy Factory | `0xaB45c5A4B0c941a2F231C04C3f49182e1A254052` |
| `proxyWallet` | Proxy Wallet | Settings에서 확인한 주소 |
| `relay` | Relay 주소 | relay-payload 응답에서 받음 |
| `relayHub` | RelayHub | `0xD216153c06E857cD7f72665E0aF1d7D82172F494` |

---

## 컨트랙트 주소 (Polygon Mainnet)

```python
CONTRACTS = {
    "ctf": "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045",
    "usdc": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    "neg_risk_adapter": "0xC5d563A36AE78145C45a50134d48A1215220f80a",
    "proxy_factory": "0xaB45c5A4B0c941a2F231C04C3f49182e1A254052",
    "relay_hub": "0xD216153c06E857cD7f72665E0aF1d7D82172F494",
}
```

---

## Proxy Call 인코딩

여러 트랜잭션을 하나의 proxy() 호출로 묶기:

```python
from eth_abi import encode

def encode_proxy_call(calls: list[tuple[int, str, int, str]]) -> str:
    """
    Args:
        calls: List of (callType, to, value, data)
               callType: 1 = CALL
    """
    # proxy() selector: keccak256("proxy((uint8,address,uint256,bytes)[])")[:4]
    selector = bytes.fromhex("34ee9791")

    calls_with_bytes = []
    for call_type, to_addr, value, data in calls:
        data_bytes = bytes.fromhex(data[2:]) if data.startswith("0x") else bytes.fromhex(data)
        calls_with_bytes.append((call_type, to_addr, value, data_bytes))

    encoded_args = encode(
        ["(uint8,address,uint256,bytes)[]"],
        [calls_with_bytes],
    )

    return "0x" + (selector + encoded_args).hex()
```

---

## Split/Merge 인코딩

### Split Position

```python
def encode_split_position(condition_id: bytes, amount: int, neg_risk: bool):
    if neg_risk:
        # NegRiskAdapter.splitPosition(bytes32 conditionId, uint256 amount)
        selector = keccak(text="splitPosition(bytes32,uint256)")[:4]
        args = encode(["bytes32", "uint256"], [condition_id, amount])
        target = NEG_RISK_ADAPTER
    else:
        # CTF.splitPosition(address,bytes32,bytes32,uint256[],uint256)
        selector = keccak(text="splitPosition(address,bytes32,bytes32,uint256[],uint256)")[:4]
        args = encode(
            ["address", "bytes32", "bytes32", "uint256[]", "uint256"],
            [USDC, bytes(32), condition_id, [1, 2], amount]
        )
        target = CTF

    return target, "0x" + (selector + args).hex()
```

### Merge Positions

```python
def encode_merge_positions(condition_id: bytes, amount: int, neg_risk: bool):
    if neg_risk:
        selector = keccak(text="mergePositions(bytes32,uint256)")[:4]
        args = encode(["bytes32", "uint256"], [condition_id, amount])
        target = NEG_RISK_ADAPTER
    else:
        selector = keccak(text="mergePositions(address,bytes32,bytes32,uint256[],uint256)")[:4]
        args = encode(
            ["address", "bytes32", "bytes32", "uint256[]", "uint256"],
            [USDC, bytes(32), condition_id, [1, 2], amount]
        )
        target = CTF

    return target, "0x" + (selector + args).hex()
```

---

## 트러블슈팅

### 1. `invalid 'proxyWallet' field`

**원인:** payload에 `proxyWallet` 필드가 없거나, `from`이 잘못됨

**해결:**
- `from` = EOA 주소
- `proxyWallet` = Proxy Wallet 주소 (Settings에서 확인)

### 2. `invalid signature`

**원인 1:** `unsafe_sign_hash` 사용
- **해결:** `sign_message` + `encode_defunct` 사용

**원인 2:** struct hash 순서/인코딩 오류
- **해결:** 위의 정확한 순서와 바이트 크기 확인

**원인 3:** `from` 주소가 struct hash와 payload에서 다름
- **해결:** 둘 다 EOA 주소 사용

### 3. `401 invalid authorization`

**원인:** Builder 헤더 형식 오류

**해결:** 헤더 이름 확인
- ✅ `POLY_BUILDER_API_KEY`
- ❌ `POLY_API_KEY`

---

## 전체 플로우

```
1. relay-payload 조회 (EOA 주소로)
   └─> nonce, relay address 획득

2. 트랜잭션 인코딩
   └─> approve + split (또는 merge)
   └─> encode_proxy_call()로 묶기

3. Struct hash 생성
   └─> "rlx:" + from + to + data + fees + nonce + relay 정보
   └─> keccak256()

4. 서명 생성
   └─> encode_defunct(struct_hash)
   └─> Account.sign_message()

5. Relayer에 제출
   └─> POST /submit with Builder headers

6. 응답 확인
   └─> transactionID, state (STATE_NEW)

7. 상태 폴링 (선택사항)
   └─> GET /transaction?id={transactionID}
   └─> STATE_CONFIRMED or STATE_FAILED까지 대기
```

---

## 트랜잭션 상태

| 상태 | 설명 | 종류 |
|------|------|------|
| `STATE_NEW` | 접수됨 | Pending |
| `STATE_EXECUTED` | 실행됨 | Pending |
| `STATE_MINED` | 블록에 포함됨 | Pending |
| `STATE_CONFIRMED` | 확정됨 | Terminal ✅ |
| `STATE_FAILED` | 실패 | Terminal ❌ |
| `STATE_INVALID` | 유효하지 않음 | Terminal ❌ |

**주의:** `transactionID`만 받았다고 성공이 아님! 반드시 상태를 확인해야 함.

```python
response = client.split_position(condition_id, amount, neg_risk)

# 상태 폴링
response = response.wait(timeout=60, poll_interval=2.0)

if response.is_success():
    print("Success!")
elif response.is_failed():
    print(f"Failed: {response.status}")
else:
    print(f"Pending/Timeout: {response.status}")
```

---

## 참고 자료

- [Polymarket Builder Docs](https://docs.polymarket.com/developers/builders/builder-intro)
- [magic-proxy-builder-example](https://github.com/Polymarket/magic-proxy-builder-example)
- [builder-relayer-client (TypeScript)](https://github.com/Polymarket/builder-relayer-client)
- [py-builder-relayer-client (Python, SAFE only)](https://pypi.org/project/py-builder-relayer-client/)
