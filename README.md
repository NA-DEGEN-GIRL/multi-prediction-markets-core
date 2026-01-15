# Multi-Prediction-Markets

> **Language / 언어 선택**
> - [한국어](#한국어-korean) | [English](#english)

---

## 면책조항 (Disclaimer)

> **경고**: 이 소프트웨어는 교육 및 연구 목적으로만 제공됩니다. 예측 시장 거래는 상당한 재정적 위험을 수반하며, 투자한 원금의 전부 또는 일부를 잃을 수 있습니다. 이 라이브러리를 사용하여 발생하는 모든 거래 손실, 기술적 오류, 또는 기타 손해에 대해 개발자는 어떠한 책임도 지지 않습니다. 실제 자금으로 거래하기 전에 반드시 해당 거래소의 이용약관을 확인하고, 관할 지역의 법률을 준수하시기 바랍니다. 본인의 판단과 책임 하에 사용하시기 바랍니다.

> **Warning**: This software is provided for educational and research purposes only. Trading on prediction markets involves significant financial risk, and you may lose all or part of your invested capital. The developers assume no responsibility for any trading losses, technical errors, or other damages arising from the use of this library. Before trading with real funds, please review the terms of service of the relevant exchanges and comply with the laws of your jurisdiction. Use at your own discretion and risk.

---

# 한국어 (Korean)

## 소개

다양한 예측 시장 거래소를 통합하는 Python 라이브러리입니다. [ccxt](https://github.com/ccxt/ccxt)에서 영감을 받아 설계되었습니다.

## 주요 기능

- **통합 인터페이스**: 여러 예측 시장 거래소를 단일 API로 접근
- **WebSocket 우선**: 실시간 데이터 스트리밍, REST 자동 폴백
- **비동기 네이티브**: asyncio 기반 고성능 설계
- **타입 안전**: 완전한 타입 힌트 및 dataclass 지원

## 지원 거래소

| 거래소 | REST | WebSocket | Trading | Split/Merge | 상태 |
|--------|------|-----------|---------|-------------|------|
| Polymarket | ✅ | ✅ | ✅ | ✅ | **구현 완료** |

> 추후 다른 예측 시장 거래소들이 추가될 예정입니다.

---

## Polymarket 설정 가이드

### 1. 계정 생성 (이메일 가입)

**Polymarket은 이메일 가입을 사용합니다.**

이메일로 가입하면 "Magic Wallet"이 자동 생성되어 가스비 걱정 없이 거래할 수 있습니다.

### 2. 개인키 내보내기

이메일로 가입했다면 개인키를 내보내야 API를 사용할 수 있습니다.

1. [Polymarket](https://polymarket.com) 로그인
2. 우측 상단 프로필 → **Settings** 클릭
3. **Export Private Key** 버튼 클릭
4. 이메일 인증 후 개인키 복사

> ⚠️ **주의**: 개인키는 절대 타인과 공유하지 마세요!

### 3. Proxy Wallet 주소 확인

이메일 사용자는 "Proxy Wallet" 주소를 찾아야 합니다.

1. [Polymarket Settings](https://polymarket.com/settings) 접속
2. **Deposit Address** 또는 **Your wallet address** 확인
3. `0x`로 시작하는 42자리 주소가 Proxy Wallet 주소입니다

> **Proxy Wallet이란?**
> - Polymarket이 사용자 대신 관리하는 스마트 컨트랙트 지갑
> - 실제 토큰과 포지션이 저장되는 곳
> - API로 포지션 조회, 주문 시 이 주소가 필요합니다

### 4. Builder API 발급 (Split/Merge용)

가스비 없이 Split/Merge를 하려면 Builder API가 필요합니다.

1. [Builder Settings](https://polymarket.com/settings?tab=builder) 접속
2. **Create API Key** 클릭
3. 다음 3가지를 모두 저장:
   - **API Key**: `POLYMARKET_BUILDER_API_KEY`
   - **Secret**: `POLYMARKET_BUILDER_SECRET`
   - **Passphrase**: `POLYMARKET_BUILDER_PASSPHRASE`

> **Builder API가 필요한 이유:**
> - 이메일 사용자의 개인키는 TEE(Trusted Execution Environment)에 저장됨
> - 로컬에서 직접 서명이 불가능하여 Split/Merge 시 Builder API 필요
> - Builder API를 사용하면 가스비 무료!

---

## 환경 설정

### 파일 구조

```
프로젝트/
├── .env              # 민감한 정보 (절대 공유 금지!)
├── .env.config       # 일반 설정 (공유 가능)
├── .env.example      # .env 템플릿
└── .env.config.example  # .env.config 템플릿 (없으면 .env.config 참조)
```

### .env 설정 (민감한 정보)

`.env.example`을 `.env`로 복사한 후 수정하세요.

```bash
cp .env.example .env
```

#### 필수 변수

| 변수명 | 설명 | 예시 |
|--------|------|------|
| `POLYMARKET_PRIVATE_KEY` | 개인키 (Settings에서 내보내기) | `0x1234...abcd` |
| `POLYMARKET_PROXY_WALLET` | Proxy Wallet 주소 | `0xabcd...1234` |

#### Builder API 변수 (Split/Merge용)

| 변수명 | 설명 | 필수 여부 |
|--------|------|----------|
| `POLYMARKET_BUILDER_API_KEY` | Builder API 키 | Split/Merge 필수 |
| `POLYMARKET_BUILDER_SECRET` | Builder API 시크릿 | Split/Merge 필수 |
| `POLYMARKET_BUILDER_PASSPHRASE` | Builder API 패스프레이즈 | Split/Merge 필수 |

> **Builder API 없으면?**
> - Split/Merge 기능 사용 불가
> - 일반 주문/취소는 Builder 없이도 가능

#### RPC 설정 (선택사항)

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `MATIC_RPC` | Polygon RPC URL | `https://polygon-rpc.com` |

> 안정적인 서비스를 위해 [Alchemy](https://alchemy.com), [Infura](https://infura.io), [QuickNode](https://quicknode.com) 등의 유료 RPC 사용을 권장합니다.

### .env 예시

```bash
# 개인키 (Settings → Export Private Key)
POLYMARKET_PRIVATE_KEY=0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef

# Proxy Wallet 주소 (Settings에서 확인)
POLYMARKET_PROXY_WALLET=0xYourProxyWalletAddress

# Builder API (Settings → Builder 탭) - Split/Merge 사용 시 필수
POLYMARKET_BUILDER_API_KEY=your-api-key
POLYMARKET_BUILDER_SECRET=your-secret
POLYMARKET_BUILDER_PASSPHRASE=your-passphrase

# (선택) 프라이빗 RPC
MATIC_RPC=https://polygon-mainnet.g.alchemy.com/v2/YOUR_API_KEY
```

### .env.config 설정 (일반 설정)

민감하지 않은 설정값들입니다. 공유해도 됩니다.

| 변수명 | 설명 | 기본값 | 예시 |
|--------|------|--------|------|
| `POLYMARKET_CHAIN_ID` | 네트워크 ID | `137` | Polygon Mainnet |
| `POLYMARKET_MAX_MARKETS` | 로드할 최대 마켓 수 | `100` | |
| `POLYMARKET_WS_ENABLED` | WebSocket 사용 여부 | `true` | |

#### 테스트 설정 (낮은 중요도)

> **참고**: 아래 `TEST_*` 변수들은 `tests/test_polymarket.py` 실행 시에만 사용됩니다.
> 라이브러리를 직접 코드에서 사용할 때는 이 변수들이 **필요하지 않습니다**.
> 테스트를 실행하지 않을 계획이라면 이 섹션은 건너뛰셔도 됩니다.

| 변수명 | 설명 | 예시 |
|--------|------|------|
| `TEST_SEARCH_QUERY` | 마켓 검색 키워드 | `bitcoin` |
| `TEST_SEARCH_TAG` | 카테고리 필터 | `crypto`, `sports`, `politics` |
| `TEST_MIN_VOLUME` | 최소 24시간 거래량 ($) | `100000` |
| `TEST_MARKET_ID` | 고정 마켓 ID (아래 참조) | |
| `TEST_ORDER_SIZE` | 테스트 주문 크기 | `10` |
| `TEST_ORDER_SIZE_TYPE` | 주문 단위 | `usd` 또는 `shares` |
| `TEST_SPLIT_AMOUNT` | Split/Merge 테스트 금액 (USDC) | `1` |

#### TEST_MARKET_ID 지원 형식

```bash
# 1. Condition ID (0x로 시작하는 66자리)
TEST_MARKET_ID=0xe79197c217363dcab8f0deec6f3ea146e434e0071918fb3a544732c57e08c0e1

# 2. 마켓 URL (특정 마켓)
TEST_MARKET_ID=https://polymarket.com/event/bitcoin-above-on-january-12/bitcoin-above-92k-on-january-12

# 3. 이벤트 URL (마켓 선택 프롬프트 표시)
TEST_MARKET_ID=https://polymarket.com/event/portugal-presidential-election

# 4. Database ID
TEST_MARKET_ID=1122819
```

---

## 설치

```bash
# uv 사용 (권장)
git clone https://github.com/your-repo/multi-prediction-markets.git
cd multi-prediction-markets
uv sync --all-packages

# pip 사용
pip install -e core
```

---

## 사용 예시

### 기본 사용법

```python
import asyncio
from prediction_markets import create_exchange, get_polymarket_config

async def main():
    # .env에서 자동으로 설정 로드
    config = get_polymarket_config()
    exchange = create_exchange("polymarket", config)

    try:
        await exchange.init()
        print(f"연결 완료! 지갑: {exchange.address}")

        # 마켓 로드
        markets = await exchange.load_markets()
        print(f"{len(markets)}개 마켓 로드됨")

    finally:
        await exchange.close()

asyncio.run(main())
```

### 마켓 검색

```python
async def search_example():
    config = get_polymarket_config()
    exchange = create_exchange("polymarket", config)

    try:
        await exchange.init()

        # 키워드로 검색
        markets = await exchange.search_markets(keyword="bitcoin", limit=10)
        for m in markets:
            print(f"- {m.title}")
            print(f"  ID: {m.id}")
            print(f"  Volume: ${m.volume_24h}")

    finally:
        await exchange.close()
```

### 오더북 조회

```python
async def orderbook_example():
    config = get_polymarket_config()
    exchange = create_exchange("polymarket", config)

    try:
        await exchange.init()

        # URL로 마켓 지정 가능
        market_url = "https://polymarket.com/event/bitcoin-above-on-january-12/bitcoin-above-92k-on-january-12"

        ob = await exchange.fetch_orderbook(market_url)
        print(f"Best Bid: {ob.best_bid}")
        print(f"Best Ask: {ob.best_ask}")
        print(f"Spread: {ob.spread}")

    finally:
        await exchange.close()
```

### 주문 생성

```python
from decimal import Decimal
from prediction_markets.base.types import OrderSide, OutcomeSide, SizeType

async def order_example():
    config = get_polymarket_config()
    exchange = create_exchange("polymarket", config)

    try:
        await exchange.init()

        # 지정가 주문 (체결 안 되는 가격으로)
        order = await exchange.create_order(
            market_id="0x...",  # condition ID
            side=OrderSide.BUY,
            outcome=OutcomeSide.YES,
            size=Decimal("10"),      # 10 shares
            price=Decimal("0.30"),   # $0.30
            size_type=SizeType.SHARES,
        )
        print(f"주문 생성됨: {order.id}")

        # 주문 취소
        await exchange.cancel_orders([order.id])
        print("주문 취소됨")

    finally:
        await exchange.close()
```

### 포지션 조회

```python
async def position_example():
    config = get_polymarket_config()
    exchange = create_exchange("polymarket", config)

    try:
        await exchange.init()

        # 모든 포지션 조회
        positions = await exchange.get_all_positions()
        for pos in positions:
            print(f"Market: {pos.market_id[:20]}...")
            print(f"  Outcome: {pos.outcome.value}")
            print(f"  Size: {pos.size}")
            print(f"  Avg Price: {pos.avg_price}")
            print(f"  PnL: {pos.unrealized_pnl}")

        # 포트폴리오 요약
        summary = await exchange.fetch_portfolio_summary()
        print(f"\nTotal Value: ${summary.total_value}")
        print(f"Cash: ${summary.cash_balance}")
        print(f"Positions: ${summary.positions_value}")

    finally:
        await exchange.close()
```

### Split/Merge (USDC ↔ YES+NO 토큰)

```python
async def split_merge_example():
    config = get_polymarket_config()
    exchange = create_exchange("polymarket", config)

    try:
        await exchange.init()

        market_id = "0x..."  # condition ID

        # Split: 1 USDC → 1 YES + 1 NO
        result = await exchange.split_position(
            condition_id=market_id,
            amount=Decimal("1"),  # 1 USDC
        )
        print(f"Split 결과: {result['status']}")

        # Merge: 1 YES + 1 NO → 1 USDC
        result = await exchange.merge_positions(
            condition_id=market_id,
            amount=Decimal("1"),  # 1 set
        )
        print(f"Merge 결과: {result['status']}")

    finally:
        await exchange.close()
```

### 이벤트의 마켓 목록 조회

```python
async def event_markets_example():
    config = get_polymarket_config()
    exchange = create_exchange("polymarket", config)

    try:
        await exchange.init()

        # 이벤트 slug로 조회
        event = await exchange.fetch_event("portugal-presidential-election")

        print(f"Event: {event.title}")
        print(f"Markets: {len(event.markets)}")

        for market in event.markets:
            print(f"- {market.title}")
            print(f"  ID: {market.id}")

    finally:
        await exchange.close()
```

---

## 테스트 실행

```bash
# 환경 설정 후
python tests/test_polymarket.py
```

테스트는 대화형으로 진행되며, 실제 주문 전 확인을 요청합니다.

---

## API 레퍼런스

### Exchange 메서드

#### 라이프사이클
- `init()` - 거래소 연결 초기화
- `close()` - 모든 연결 종료

#### 마켓 데이터
- `load_markets()` - 최근 마켓 정보 로드
- `search_markets(keyword, tag, limit)` - 마켓 검색
- `fetch_market(market_id)` - URL/ID로 마켓 조회
- `fetch_market_resolution(market_id)` - 해결 상태 조회
- `fetch_orderbook(market_id, outcome)` - 오더북 조회
- `fetch_market_price(market_id, outcome)` - 현재가 조회
- `fetch_event(slug)` - 이벤트 조회 (마켓 포함)

#### 트레이딩
- `create_order(...)` - 주문 생성
- `cancel_orders(order_ids)` - 주문 취소
- `fetch_open_orders()` - 미체결 주문 조회

#### 포지션/계정
- `get_all_positions()` - 모든 포지션 조회
- `fetch_position(market_id)` - 특정 마켓 포지션 조회
- `fetch_portfolio_summary()` - 포트폴리오 요약

#### Split/Merge (CTF)
- `split_position(condition_id, amount)` - USDC를 YES+NO로 분할
- `merge_positions(condition_id, amount)` - YES+NO를 USDC로 병합

### 타입

```python
from prediction_markets import (
    Market,           # 마켓 정보
    Order,            # 주문 정보
    OrderBook,        # 오더북 (매수/매도 호가)
    Position,         # 포지션 정보
    PortfolioSummary, # 포트폴리오 요약
    Resolution,       # 해결 상태 (YES/NO/INVALID)
    OrderSide,        # BUY, SELL
    OutcomeSide,      # YES, NO
    OrderType,        # MARKET, LIMIT 등
    SizeType,         # SHARES, USD
)
```

---

## 프로젝트 구조

```
multi-prediction-markets/       # 워크스페이스 (메인 레포)
├── core/                       # 코어 래퍼 라이브러리 (서브모듈)
│   ├── src/prediction_markets/
│   │   ├── base/               # 베이스 클래스 및 타입
│   │   ├── common/             # 공통 유틸리티, 예외
│   │   └── exchanges/          # 거래소별 구현
│   │       └── polymarket/
│   ├── tests/                  # core 테스트
│   └── examples/               # 사용 예제
├── ui/                         # 트레이딩 UI (서브모듈, 예정)
├── bots/                       # 트레이딩 봇 (서브모듈, 예정)
├── .env.example                # 환경변수 템플릿
└── .env.config                 # 일반 설정
```

---

## 문제 해결

### "Invalid signature" 에러
- `POLYMARKET_PROXY_WALLET`이 올바르게 설정되어 있는지 확인

### "Unauthorized" 에러
- 개인키가 올바른지 확인
- Builder API 자격증명이 올바른지 확인 (Split/Merge 사용 시)

### Split/Merge 실패
- Builder API가 설정되어 있는지 확인 (필수)
- USDC 잔액이 충분한지 확인

### 포지션이 조회되지 않음
- `POLYMARKET_PROXY_WALLET`이 올바른지 확인
- 실제로 포지션이 있는지 웹에서 확인

---

## 개발

```bash
# 저장소 클론
git clone https://github.com/your-repo/multi-prediction-markets.git
cd multi-prediction-markets

# 의존성 설치
uv sync --all-packages

# 테스트 실행
pytest

# 타입 체크
mypy core/src

# 린팅
ruff check .
```

---

# English

## Introduction

A unified Python library for interacting with multiple prediction market exchanges, inspired by [ccxt](https://github.com/ccxt/ccxt).

## Features

- **Unified Interface**: Single API to interact with multiple prediction market exchanges
- **WebSocket First**: Real-time data with automatic REST fallback
- **Async Native**: Built on asyncio for high-performance applications
- **Type Safe**: Full type hints and dataclasses for IDE support

## Supported Exchanges

| Exchange | REST | WebSocket | Trading | Split/Merge | Status |
|----------|------|-----------|---------|-------------|--------|
| Polymarket | ✅ | ✅ | ✅ | ✅ | **Implemented** |

> More prediction market exchanges will be added in the future.

---

## Polymarket Setup Guide

### 1. Create Account (Email Signup)

**Polymarket uses email signup.**

Email signup creates a "Magic Wallet" for gasless trading.

### 2. Export Private Key

If you signed up with email, you need to export your private key:

1. Log in to [Polymarket](https://polymarket.com)
2. Click profile → **Settings**
3. Click **Export Private Key**
4. Complete email verification and copy the key

> ⚠️ **Warning**: Never share your private key!

### 3. Find Your Proxy Wallet Address

Email users need to find their "Proxy Wallet" address:

1. Go to [Polymarket Settings](https://polymarket.com/settings)
2. Find **Deposit Address** or **Your wallet address**
3. The 42-character address starting with `0x` is your Proxy Wallet

### 4. Get Builder API Credentials (For Split/Merge)

For gasless Split/Merge operations:

1. Go to [Builder Settings](https://polymarket.com/settings?tab=builder)
2. Click **Create API Key**
3. Save all three:
   - **API Key**: `POLYMARKET_BUILDER_API_KEY`
   - **Secret**: `POLYMARKET_BUILDER_SECRET`
   - **Passphrase**: `POLYMARKET_BUILDER_PASSPHRASE`

---

## Environment Setup

### .env Configuration (Sensitive)

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

#### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `POLYMARKET_PRIVATE_KEY` | Your private key | `0x1234...abcd` |
| `POLYMARKET_PROXY_WALLET` | Proxy Wallet address | `0xabcd...1234` |

#### Builder API Variables (Required for Split/Merge)

| Variable | Description |
|----------|-------------|
| `POLYMARKET_BUILDER_API_KEY` | Builder API key |
| `POLYMARKET_BUILDER_SECRET` | Builder API secret |
| `POLYMARKET_BUILDER_PASSPHRASE` | Builder API passphrase |

### .env Example

```bash
POLYMARKET_PRIVATE_KEY=0x1234567890abcdef...
POLYMARKET_PROXY_WALLET=0xYourProxyWalletAddress

# Required for Split/Merge
POLYMARKET_BUILDER_API_KEY=your-api-key
POLYMARKET_BUILDER_SECRET=your-secret
POLYMARKET_BUILDER_PASSPHRASE=your-passphrase
```

### Test Settings (Low Priority)

> **Note**: The `TEST_*` variables in `.env.example` and `.env.config.example` are **only used** when running `tests/test_polymarket.py`.
> You do **not** need these variables when using the library in your own code.
> If you don't plan to run the test script, you can skip these settings.

---

## Installation

```bash
# Using uv (recommended)
git clone https://github.com/your-repo/multi-prediction-markets.git
cd multi-prediction-markets
uv sync --all-packages

# Using pip
pip install -e core
```

---

## Quick Start

```python
import asyncio
from prediction_markets import create_exchange, get_polymarket_config

async def main():
    config = get_polymarket_config()
    exchange = create_exchange("polymarket", config)

    try:
        await exchange.init()

        # Load markets
        markets = await exchange.load_markets()
        print(f"Found {len(markets)} markets")

        # Search markets
        results = await exchange.search_markets(keyword="bitcoin", limit=5)
        for m in results:
            print(f"- {m.title}")

    finally:
        await exchange.close()

asyncio.run(main())
```

---

## API Reference

### Exchange Methods

#### Lifecycle
- `init()` - Initialize exchange connections
- `close()` - Close all connections

#### Market Data
- `load_markets()` - Load recent markets
- `search_markets(keyword, tag, limit)` - Search markets
- `fetch_market(market_id)` - Get market by URL/ID
- `fetch_market_resolution(market_id)` - Get resolution status
- `fetch_orderbook(market_id, outcome)` - Get orderbook
- `fetch_market_price(market_id, outcome)` - Get current price
- `fetch_event(slug)` - Get event with its markets

#### Trading
- `create_order(...)` - Create a new order
- `cancel_orders(order_ids)` - Cancel orders
- `fetch_open_orders()` - Get open orders

#### Positions/Account
- `get_all_positions()` - Get all positions
- `fetch_position(market_id)` - Get position for a market
- `fetch_portfolio_summary()` - Get portfolio summary

#### Split/Merge (CTF)
- `split_position(condition_id, amount)` - Split USDC into YES+NO
- `merge_positions(condition_id, amount)` - Merge YES+NO into USDC

---

## Development

```bash
# Clone repository
git clone https://github.com/your-repo/multi-prediction-markets.git
cd multi-prediction-markets

# Install dependencies
uv sync --all-packages

# Run tests
pytest

# Type checking
mypy core/src

# Linting
ruff check .
```

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Implement your changes
4. Add tests
5. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) for details.
