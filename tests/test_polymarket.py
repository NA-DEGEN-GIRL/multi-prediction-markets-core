"""
Polymarket 통합 테스트.

사용법:
    # 공개 API 테스트 (인증 불필요)
    python tests/test_polymarket.py

    # .env 파일에 POLYMARKET_PRIVATE_KEY 설정 후 실행
    python tests/test_polymarket.py

설정:
    SKIP 딕셔너리에서 테스트 on/off 가능
    TEST_MARKET_ID: 고정 마켓 ID (주문 테스트용)
    TEST_ORDER_SIZE: 주문 크기
    TEST_ORDER_SIZE_TYPE: "shares" 또는 "usd"
"""

import asyncio
import json
import random
import sys
from decimal import Decimal
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import re

from prediction_markets import create_exchange, get_polymarket_config, get_test_config, Event, EventStatus
from prediction_markets.base.types import MarketStatus, OrderSide, OutcomeSide, SizeType

# === 설정 (from .env and .env.config) ===
EXCHANGE = "polymarket"
CONFIG = get_polymarket_config()
TEST_CONFIG = get_test_config()
PRIVATE_KEY = CONFIG.get("private_key")

# 검색 설정 (from .env.config)
SEARCH_QUERY = TEST_CONFIG.search_query
SEARCH_TAG = TEST_CONFIG.search_tag  # 카테고리 필터 (crypto, sports, politics 등)
SEARCH_LIMIT = 10
MIN_VOLUME = Decimal(TEST_CONFIG.min_volume)

# 고정 마켓 ID (설정시 검색 대신 직접 사용)
FIXED_MARKET_ID = TEST_CONFIG.market_id

# 주문 설정 (from .env.config)
ORDER_SIZE = Decimal(str(TEST_CONFIG.order_size))
ORDER_SIZE_TYPE = SizeType(TEST_CONFIG.order_size_type)  # shares or usd
ORDER_PRICE_OFFSET = Decimal("0.05")

# Split/Merge 설정 (on-chain CTF 작업)
SPLIT_AMOUNT = Decimal(str(TEST_CONFIG.split_amount))

# 테스트 스킵 설정
SKIP = {
    "get_categories": False,  # 카테고리 목록 (Crypto, Sports, Politics 등)
    "load_events": True,  # 검색만 사용할거면 True
    "search_events": False,  # 이벤트 검색 (이벤트 → 마켓 선택)
    "market_details": False,  # 상세 마켓 정보
    "orderbook": False,
    "market_price": False,
    "fee_structure": False,
    "positions": False,
    "open_orders": False,
    "portfolio": False,
    "split_merge": False,  # Split/Merge 테스트 (on-chain, 가스비 발생!)
    "place_order": False,  # Limit 주문 테스트 (주의: 실제 주문!)
    "market_order": False,  # Market 주문 테스트 (주의: 실제 주문!)
    "close_position": False,  # 포지션 청산 테스트 (주의: 실제 주문!)
    "get_position": False,  # 단일 포지션 조회 (market_order 후 테스트)
}


def format_decimal(value: Decimal | None, decimals: int = 2) -> str:
    """Format decimal for display."""
    if value is None:
        return "N/A"
    return f"{value:,.{decimals}f}"


def print_raw(raw: dict, prefix: str = "", title: str = "RAW DATA"):
    """Print raw data in a clean, readable format."""
    if not raw:
        return
    print(f"{prefix}[{title}]")
    # Pretty print with indentation
    formatted = json.dumps(raw, indent=2, default=str, ensure_ascii=False)
    for line in formatted.split('\n'):
        print(f"{prefix}  {line}")


def print_market_details(m, prefix="", show_raw: bool = True):
    """Print detailed market information."""
    print(f"{prefix}Title: {m.title}")
    print(f"{prefix}ID: {m.id}")
    print(f"{prefix}Status: {m.status.value}")
    print(f"{prefix}Outcomes: {m.outcomes}")
    print(f"{prefix}Category: {m.category}")
    print(f"{prefix}Volume 24h: ${format_decimal(m.volume_24h)}")
    print(f"{prefix}Liquidity: ${format_decimal(m.liquidity)}")
    print(f"{prefix}End Date: {m.end_date}")
    if m.description:
        print(f"{prefix}Description: {m.description}")
    if show_raw and m.raw:
        print_raw(m.raw, prefix=prefix)


def print_order_details(o, prefix="", show_raw: bool = True):
    """Print order details."""
    print(f"{prefix}Order ID: {o.id}")
    print(f"{prefix}Market: {o.market_id}")
    print(f"{prefix}Side: {o.side.value}")
    print(f"{prefix}Outcome: {o.outcome.value}")
    print(f"{prefix}Type: {o.order_type.value}")
    print(f"{prefix}Price: {o.price}")
    print(f"{prefix}Size: {o.size}")
    print(f"{prefix}Filled: {o.filled_size}")
    print(f"{prefix}Remaining: {o.remaining_size}")
    print(f"{prefix}Status: {o.status.value}")
    print(f"{prefix}Created: {o.created_at}")
    if show_raw and o.raw:
        print_raw(o.raw, prefix=prefix)


def print_position_details(p, prefix="", show_raw: bool = True):
    """Print position details."""
    print(f"{prefix}Market: {p.market_id}")
    print(f"{prefix}Outcome: {p.outcome.value}")
    print(f"{prefix}Size: {p.size}")
    print(f"{prefix}Avg Price: {p.avg_price}")
    print(f"{prefix}Current Price: {p.current_price}")
    print(f"{prefix}Unrealized PnL: {p.unrealized_pnl}")
    print(f"{prefix}Realized PnL: {p.realized_pnl}")
    if show_raw and p.raw:
        print_raw(p.raw, prefix=prefix)


def print_event_summary(event: Event, index: int, prefix: str = ""):
    """Print event summary for selection."""
    status_icon = "🟢" if event.status == EventStatus.ACTIVE else "🔴"
    vol = format_decimal(event.volume_24h) if event.volume_24h else "N/A"
    print(f"{prefix}{index}. {status_icon} {event.title}")
    print(f"{prefix}   Markets: {len(event.markets)}개 | Volume: ${vol}")
    print(f"{prefix}   Slug: {event.slug}")


async def usd_to_shares(exchange, market_id: str, usd_amount: Decimal, outcome: OutcomeSide) -> Decimal:
    """Convert USD amount to shares based on current market price."""
    try:
        price = await exchange.get_market_price(market_id, outcome)
        token_price = price.best_ask or price.mid_price or Decimal("0.5")

        if token_price <= 0:
            token_price = Decimal("0.5")

        # shares = usd / price
        shares = usd_amount / token_price
        return shares.quantize(Decimal("0.01"))  # Round to 2 decimals
    except Exception:
        # Fallback: assume 50 cent price
        return (usd_amount / Decimal("0.5")).quantize(Decimal("0.01"))


async def get_order_size(exchange, market_id: str, outcome: OutcomeSide) -> Decimal:
    """Get order size in shares, converting from USD if needed."""
    if ORDER_SIZE_TYPE == SizeType.USD:
        return await usd_to_shares(exchange, market_id, ORDER_SIZE, outcome)
    return ORDER_SIZE


async def main():
    print(f"\n{'='*60}")
    print(f"  Polymarket 통합 테스트")
    print(f"{'='*60}")
    print(f"Chain ID: {CONFIG.get('chain_id', 137)}")
    print(f"Private Key: {'설정됨' if PRIVATE_KEY and PRIVATE_KEY != '0x...' else '미설정'}")
    print(f"Search Query: '{SEARCH_QUERY}'" + (f" (tag: {SEARCH_TAG})" if SEARCH_TAG else ""))
    print(f"Min Volume: ${MIN_VOLUME}")
    print(f"Order Size: {ORDER_SIZE} ({ORDER_SIZE_TYPE.value})")
    if FIXED_MARKET_ID:
        print(f"Fixed Market ID: {FIXED_MARKET_ID}")
    print()

    has_auth = PRIVATE_KEY and PRIVATE_KEY != "0x..."
    if has_auth:
        SKIP["positions"] = False
        SKIP["open_orders"] = False
        SKIP["portfolio"] = False
    else:
        SKIP["place_order"] = True  # 인증 없으면 주문 비활성화

    exchange = create_exchange(EXCHANGE, CONFIG)
    selected_market = None
    selected_market_id = FIXED_MARKET_ID  # 고정 마켓 ID 우선 사용

    try:
        await exchange.init()
        print(f"[OK] Exchange 초기화 완료")
        if exchange.address:
            print(f"     Signing Wallet: {exchange.address}")
            print(f"     (Split/Merge용 MATIC 필요: https://polygonscan.com/address/{exchange.address})")

        # === 고정 마켓/이벤트 ID 사용시 로드 ===
        if FIXED_MARKET_ID:
            print(f"\n--- 고정 마켓/이벤트 로드 ---")
            try:
                # 이벤트 URL/slug인지 확인
                is_event_url = bool(re.search(r"polymarket\.com/event/[^/]+/?$", FIXED_MARKET_ID))
                # 이벤트 slug 추출 (URL이면 slug만)
                event_slug = None
                if is_event_url:
                    match = re.search(r"/event/([^/]+)/?", FIXED_MARKET_ID)
                    event_slug = match.group(1) if match else FIXED_MARKET_ID
                elif "/" not in FIXED_MARKET_ID and not FIXED_MARKET_ID.startswith("0x"):
                    # 0x로 시작하지 않는 짧은 문자열 = event slug로 간주
                    event_slug = FIXED_MARKET_ID

                if event_slug:
                    # fetch_event로 이벤트 조회
                    event = await exchange.fetch_event(event_slug)

                    print(f"\n[EVENT] {event.title}")
                    print(f"        {len(event.markets)}개의 마켓이 있습니다. 선택하세요:\n")

                    for i, m in enumerate(event.markets, 1):
                        status_icon = "🟢" if m.status == MarketStatus.ACTIVE else "🔴"
                        vol = format_decimal(m.volume_24h) if m.volume_24h else "N/A"
                        print(f"     {i}. {status_icon} {m.title}")
                        print(f"        Volume: ${vol}")
                        print()

                    # 사용자 입력 받기
                    while True:
                        try:
                            choice = input(f"     마켓 번호 선택 (1-{len(event.markets)}): ").strip()
                            idx = int(choice) - 1
                            if 0 <= idx < len(event.markets):
                                selected_market = event.markets[idx]
                                selected_market_id = selected_market.id
                                print(f"\n[OK] 선택됨: {selected_market.title}")
                                break
                            else:
                                print(f"     [ERROR] 1-{len(event.markets)} 사이의 번호를 입력하세요.")
                        except ValueError:
                            print(f"     [ERROR] 숫자를 입력하세요.")
                else:
                    # 마켓 ID로 직접 로드
                    selected_market = await exchange.fetch_market(FIXED_MARKET_ID)
                    selected_market_id = selected_market.id

                print(f"[OK] 마켓 로드 완료")
                print(f"     Condition ID: {selected_market_id}")
                print_market_details(selected_market, prefix="     ", show_raw=False)

                # 토큰 ID 캐싱
                from prediction_markets.exchanges.polymarket.parser import parse_market_tokens
                tokens = parse_market_tokens(selected_market.raw)
                if tokens:
                    exchange._market_tokens[selected_market_id] = tokens
                    print(f"     Tokens: {tokens}")

            except Exception as e:
                print(f"[FAIL] 고정 마켓/이벤트 로드 실패: {e}")
                import traceback
                traceback.print_exc()
                selected_market_id = None  # 실패시 검색으로 폴백

        # === get_categories ===
        if not SKIP["get_categories"]:
            print(f"\n--- get_categories ---")
            try:
                categories = await exchange.get_categories()
                print(f"[OK] {len(categories)}개 카테고리")
                cnt = 0
                for c in categories:
                    print(f"     - {c.get('label', '?')}: {c.get('slug', '')}")
                    cnt += 1
                    if cnt == 5:
                        break
                print("...")
            except Exception as e:
                print(f"[FAIL] get_categories: {e}")

        # === load_events (선택적) ===
        if not SKIP["load_events"]:
            print(f"\n--- load_events ---")
            try:
                events = await exchange.load_events()
                total_markets = sum(len(e.markets) for e in events.values())
                print(f"[OK] {len(events)}개 이벤트 로드 (총 {total_markets}개 마켓)")
                for i, (eid, e) in enumerate(list(events.items())[:3]):
                    print(f"     {i+1}. {e.title} ({len(e.markets)}개 마켓)")
            except Exception as e:
                print(f"[FAIL] load_events: {e}")

        # === search_events (이벤트 → 마켓 선택) ===
        if not SKIP["search_events"] and not FIXED_MARKET_ID:
            tag_info = f", tag='{SEARCH_TAG}'" if SEARCH_TAG else ""
            print(f"\n--- search_events (keyword='{SEARCH_QUERY}'{tag_info}) ---")
            try:
                # 이벤트 검색
                events = await exchange.search_events(keyword=SEARCH_QUERY, tag=SEARCH_TAG, limit=SEARCH_LIMIT)
                print(f"[OK] {len(events)}개 이벤트 검색됨\n")

                if not events:
                    print(f"     [WARN] 검색 결과 없음")
                else:
                    # 이벤트 목록 표시
                    print(f"     [이벤트 목록]")
                    for i, event in enumerate(events, 1):
                        print_event_summary(event, i, prefix="     ")
                        print()

                    # 이벤트 선택
                    selected_event = None
                    while True:
                        try:
                            choice = input(f"     이벤트 번호 선택 (1-{len(events)}, 0=건너뛰기): ").strip()
                            if choice == "0":
                                print(f"     이벤트 선택 건너뜀")
                                break
                            idx = int(choice) - 1
                            if 0 <= idx < len(events):
                                selected_event = events[idx]
                                print(f"\n     [선택됨] {selected_event.title}")
                                break
                            else:
                                print(f"     [ERROR] 1-{len(events)} 사이의 번호를 입력하세요.")
                        except ValueError:
                            print(f"     [ERROR] 숫자를 입력하세요.")

                    # 마켓 선택
                    if selected_event and selected_event.markets:
                        print(f"\n     [마켓 목록] ({len(selected_event.markets)}개)")
                        for i, m in enumerate(selected_event.markets, 1):
                            status_icon = "🟢" if m.status == MarketStatus.ACTIVE else "🔴"
                            vol = format_decimal(m.volume_24h) if m.volume_24h else "N/A"
                            print(f"     {i}. {status_icon} {m.title}")
                            print(f"        Volume: ${vol} | ID: {m.id[:20]}...")
                            print()

                        while True:
                            try:
                                choice = input(f"     마켓 번호 선택 (1-{len(selected_event.markets)}): ").strip()
                                idx = int(choice) - 1
                                if 0 <= idx < len(selected_event.markets):
                                    selected_market = selected_event.markets[idx]
                                    selected_market_id = selected_market.id
                                    print(f"\n     [선택됨] {selected_market.title}")

                                    # 토큰 ID 캐싱
                                    from prediction_markets.exchanges.polymarket.parser import parse_market_tokens
                                    tokens = parse_market_tokens(selected_market.raw)
                                    if tokens:
                                        exchange._market_tokens[selected_market_id] = tokens
                                        print(f"     Tokens: {tokens}")

                                    print()
                                    print_market_details(selected_market, prefix="     ", show_raw=False)
                                    break
                                else:
                                    print(f"     [ERROR] 1-{len(selected_event.markets)} 사이의 번호를 입력하세요.")
                            except ValueError:
                                print(f"     [ERROR] 숫자를 입력하세요.")
                    elif selected_event:
                        print(f"     [WARN] 선택된 이벤트에 마켓이 없습니다.")

            except Exception as e:
                print(f"[FAIL] search_events: {e}")
                import traceback
                traceback.print_exc()

        # === market_details ===
        if not SKIP["market_details"] and selected_market_id:
            print(f"\n--- market / resolution ---")
            try:
                market = await exchange.fetch_market(selected_market_id)
                resolution = await exchange.get_market_resolution(selected_market_id)
                print(f"[OK] Market")
                print(f"     Title: {market.title}")
                print(f"     Status: {market.status.value}")
                print(f"     Outcomes: {market.outcomes}")
                print(f"     End Date: {market.end_date}")
                print(f"     Resolution: {resolution}")
                if market.raw:
                    print_raw(market.raw, prefix="     ")
            except Exception as e:
                print(f"[FAIL] fetch_market: {e}")

        # === orderbook ===
        if not SKIP["orderbook"] and selected_market_id:
            print(f"\n--- orderbook (YES) ---")
            try:
                ob = await exchange.get_orderbook(selected_market_id, OutcomeSide.YES)
                print(f"[OK] Orderbook (YES)")
                print(f"     Best Bid: {ob.best_bid}")
                print(f"     Best Ask: {ob.best_ask}")
                print(f"     Mid Price: {ob.mid_price}")
                print(f"     Spread: {ob.spread}")
                print(f"     Depth: {len(ob.bids)} bids, {len(ob.asks)} asks")

                # Top 3 levels
                if ob.bids:
                    print(f"     Top Bids: {[(str(b.price), str(b.size)) for b in ob.bids[:3]]}")
                if ob.asks:
                    print(f"     Top Asks: {[(str(a.price), str(a.size)) for a in ob.asks[:3]]}")
            except Exception as e:
                print(f"[FAIL] orderbook: {e}")

        # === market_price ===
        if not SKIP["market_price"] and selected_market_id:
            print(f"\n--- market_price (YES) ---")
            try:
                price = await exchange.get_market_price(selected_market_id, OutcomeSide.YES)
                print(f"[OK] Price (YES)")
                print(f"     Mid: {price.mid_price}")
                print(f"     Bid: {price.best_bid}, Ask: {price.best_ask}")
                print(f"     Last: {price.last_price}")
            except Exception as e:
                print(f"[FAIL] market_price: {e}")

        # === fee_structure ===
        if not SKIP["fee_structure"]:
            print(f"\n--- fee_structure ---")
            try:
                fees = exchange.get_fee_structure()
                print(f"[OK] Fees")
                print(f"     Maker: {fees.maker_fee * 100}%")
                print(f"     Taker: {fees.taker_fee * 100}%")
                print(f"     Settlement: {fees.settlement_fee * 100}%")
            except Exception as e:
                print(f"[FAIL] fee_structure: {e}")

        # === positions ===
        if not SKIP["positions"] and has_auth:
            print(f"\n--- positions ---")
            try:
                positions = await exchange.get_all_positions()
                print(f"[OK] {len(positions)}개 포지션")
                for i, p in enumerate(positions[:5]):
                    print(f"\n     [{i+1}] {p.outcome.value} Position")
                    print_position_details(p, prefix="     ")
                if len(positions) > 5:
                    print(f"\n     ... 외 {len(positions) - 5}개 포지션")
            except Exception as e:
                print(f"[FAIL] positions: {e}")

        # === open_orders ===
        if not SKIP["open_orders"] and has_auth:
            print(f"\n--- open_orders ---")
            try:
                orders = await exchange.get_open_orders()
                print(f"[OK] {len(orders)}개 미체결 주문")
                for i, o in enumerate(orders[:5]):
                    print(f"\n     [{i+1}] {o.side.value} {o.outcome.value} Order")
                    print_order_details(o, prefix="     ")
                if len(orders) > 5:
                    print(f"\n     ... 외 {len(orders) - 5}개 주문")
            except Exception as e:
                print(f"[FAIL] open_orders: {e}")

        # === portfolio ===
        if not SKIP["portfolio"] and has_auth:
            print(f"\n--- portfolio ---")
            try:
                summary = await exchange.get_portfolio_summary()
                print(f"[OK] Portfolio")
                print(f"     Total Value: ${format_decimal(summary.total_value)}")
                print(f"     Cash: ${format_decimal(summary.cash_balance)}")
                print(f"     Positions: ${format_decimal(summary.positions_value)}")
                print(f"     Count: {summary.positions_count}")
            except Exception as e:
                print(f"[FAIL] portfolio: {e}")

        # === split (on-chain CTF) ===
        if not SKIP["split_merge"] and has_auth and selected_market_id:
            print(f"\n--- split 테스트 (on-chain, 가스비 발생!) ---")
            try:
                # Show market info including neg_risk
                neg_risk = False
                if selected_market and selected_market.raw:
                    neg_risk = selected_market.raw.get("neg_risk", False)
                print(f"     Split: {SPLIT_AMOUNT} USDC -> YES + NO tokens")
                print(f"     Market: {selected_market_id}")
                print(f"     neg_risk: {neg_risk}")

                confirm = input("     Split을 실행하시겠습니까? (yes/no): ")
                if confirm.lower() == "yes":
                    result = await exchange.split_position(
                        condition_id=selected_market_id,
                        amount=SPLIT_AMOUNT,
                    )
                    status = result.get('status', 'unknown')
                    if status == "success":
                        print(f"[OK] Split 완료!")
                    else:
                        print(f"[FAIL] Split 실패! (status: {status})")
                    print(f"     TX Hash: {result.get('tx_hash', 'N/A')}")
                    print(f"     Status: {status}")
                    print(f"     State: {result.get('state', 'N/A')}")
                else:
                    print(f"     Split 취소됨")

            except Exception as e:
                print(f"[FAIL] split: {e}")
                import traceback
                traceback.print_exc()

        # === merge (on-chain CTF) ===
        if not SKIP["split_merge"] and has_auth and selected_market_id:
            print(f"\n--- merge 테스트 (on-chain, 가스비 발생!) ---")
            try:
                print(f"     Merge: {SPLIT_AMOUNT} YES + NO -> USDC")
                print(f"     Market: {selected_market_id}")

                merge_confirm = input("     Merge를 실행하시겠습니까? (yes/no): ")
                if merge_confirm.lower() == "yes":
                    merge_result = await exchange.merge_positions(
                        condition_id=selected_market_id,
                        amount=SPLIT_AMOUNT,
                    )
                    merge_status = merge_result.get('status', 'unknown')
                    if merge_status == "success":
                        print(f"[OK] Merge 완료!")
                    else:
                        print(f"[FAIL] Merge 실패! (status: {merge_status})")
                    print(f"     TX Hash: {merge_result.get('tx_hash', 'N/A')}")
                    print(f"     Status: {merge_status}")
                    print(f"     State: {merge_result.get('state', 'N/A')}")
                else:
                    print(f"     Merge 취소됨")

            except Exception as e:
                print(f"[FAIL] merge: {e}")
                import traceback
                traceback.print_exc()

        # === place_order ===
        if not SKIP["place_order"] and has_auth and selected_market_id:
            print(f"\n--- place_order (실제 주문!) ---")
            try:
                # 현재 가격 조회
                price = await exchange.get_market_price(selected_market_id, OutcomeSide.YES)
                if price.best_bid is None:
                    print(f"[SKIP] 가격 정보 없음")
                else:
                    # 주문 수량 계산 (USD면 shares로 변환)
                    order_shares = await get_order_size(exchange, selected_market_id, OutcomeSide.YES)

                    # 매수 주문: best_bid보다 낮은 가격으로 (체결 안되게)
                    order_price = price.best_bid - ORDER_PRICE_OFFSET
                    order_price = max(Decimal("0.01"), min(Decimal("0.99"), order_price))

                    market_title = selected_market.title if selected_market else selected_market_id
                    print(f"     Market: {market_title}")
                    print(f"     Side: BUY")
                    print(f"     Outcome: YES")
                    if ORDER_SIZE_TYPE == SizeType.USD:
                        print(f"     Size: ${ORDER_SIZE} -> {order_shares} shares")
                    else:
                        print(f"     Size: {order_shares} shares")
                    print(f"     Price: {order_price} (best_bid: {price.best_bid})")
                    print()

                    # 확인 (실제 실행시)
                    confirm = input("     주문을 실행하시겠습니까? (yes/no): ")
                    if confirm.lower() == "yes":
                        order = await exchange.create_order(
                            market_id=selected_market_id,
                            side=OrderSide.BUY,
                            outcome=OutcomeSide.YES,
                            size=order_shares,
                            price=order_price,
                            size_type=SizeType.SHARES,  # 이미 변환됨
                        )
                        print(f"[OK] 주문 생성됨!")
                        print_order_details(order, prefix="     ")

                        # 주문 취소
                        cancel_confirm = input("\n     주문을 취소하시겠습니까? (yes/no): ")
                        if cancel_confirm.lower() == "yes":
                            success = await exchange.cancel_orders([order.id])
                            print(f"     취소 결과: {'성공' if success else '실패'}")
                    else:
                        print(f"     주문 취소됨")

            except Exception as e:
                print(f"[FAIL] place_order: {e}")
                import traceback
                traceback.print_exc()

        # === market_order ===
        if not SKIP["market_order"] and has_auth and selected_market_id:
            print(f"\n--- market_order (시장가 주문!) ---")
            try:
                # 주문 수량 계산 (USD면 shares로 변환)
                order_shares = await get_order_size(exchange, selected_market_id, OutcomeSide.YES)

                market_title = selected_market.title if selected_market else selected_market_id
                print(f"     Market: {market_title}")
                print(f"     Side: BUY")
                print(f"     Outcome: YES")
                if ORDER_SIZE_TYPE == SizeType.USD:
                    print(f"     Size: ${ORDER_SIZE} -> {order_shares} shares")
                else:
                    print(f"     Size: {order_shares} shares")
                print(f"     Type: MARKET (price=None, 자동으로 orderbook sweep)")
                print()

                # 확인 (실제 실행시)
                confirm = input("     시장가 주문을 실행하시겠습니까? (yes/no): ")
                if confirm.lower() == "yes":
                    # Market order: price 생략하면 자동으로 시장가 주문
                    order = await exchange.create_order(
                        market_id=selected_market_id,
                        side=OrderSide.BUY,
                        outcome=OutcomeSide.YES,
                        size=order_shares,
                        # price 생략 = 시장가 주문 (orderbook sweep)
                    )
                    print(f"[OK] 시장가 주문 완료!")
                    print_order_details(order, prefix="     ")
                else:
                    print(f"     주문 취소됨")

            except Exception as e:
                print(f"[FAIL] market_order: {e}")
                import traceback
                traceback.print_exc()

        # === close_position ===
        if not SKIP["close_position"] and has_auth and selected_market_id:
            print(f"\n--- close_position (포지션 청산!) ---")
            try:
                # 현재 포지션 확인
                position = await exchange.get_position(selected_market_id)
                if position is None or position.size <= 0:
                    print(f"[SKIP] 해당 마켓에 포지션 없음")
                else:
                    print(f"     현재 포지션:")
                    print_position_details(position, prefix="     ")
                    print()

                    market_title = selected_market.title if selected_market else selected_market_id
                    print(f"     Market: {market_title}")
                    print(f"     청산할 포지션: {position.outcome.value} {position.size} shares")
                    print(f"     현재가: {position.current_price}")
                    print(f"     주문 타입: 시장가 (orderbook sweep)")
                    print()

                    # 확인 (실제 실행시)
                    confirm = input("     포지션을 청산하시겠습니까? (yes/no): ")
                    if confirm.lower() == "yes":
                        order = await exchange.close_position(
                            market_id=selected_market_id,
                            outcome=position.outcome,
                            size=None,  # 전체 청산
                        )
                        if order:
                            print(f"[OK] 포지션 청산 주문 생성!")
                            print_order_details(order, prefix="     ")
                        else:
                            print(f"[OK] 청산할 포지션이 없거나 이미 청산됨")
                    else:
                        print(f"     청산 취소됨")

            except Exception as e:
                print(f"[FAIL] close_position: {e}")
                import traceback
                traceback.print_exc()

        # === get_position ===
        if not SKIP["get_position"] and has_auth and selected_market_id:
            print(f"\n--- get_position (단일 포지션) ---")
            try:
                position = await exchange.get_position(selected_market_id)
                if position:
                    print(f"[OK] 포지션 있음")
                    print_position_details(position, prefix="     ")
                else:
                    print(f"[OK] 해당 마켓에 포지션 없음")
            except Exception as e:
                print(f"[FAIL] get_position: {e}")
                import traceback
                traceback.print_exc()

        print(f"\n{'='*60}")
        print(f"  테스트 완료")
        print(f"{'='*60}\n")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()

    finally:
        await exchange.close()


if __name__ == "__main__":
    asyncio.run(main())
