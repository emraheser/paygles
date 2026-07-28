import asyncio
import ipaddress
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlencode, urlparse

from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.domain import TrackedProduct
from src.services.notifier import _fetch_page_metadata, telegram_notifier

logger = logging.getLogger(__name__)

PRODUCT_CHECK_INTERVAL_SETTING_KEY = "product_check_interval_minutes"
DEFAULT_PRODUCT_CHECK_INTERVAL_MINUTES = 10

STORE_NAMES = {
    "amazon.com.tr": "Amazon",
    "hepsiburada.com": "Hepsiburada",
    "trendyol.com": "Trendyol",
    "n11.com": "N11",
    "teknosa.com": "Teknosa",
    "mediamarkt.com.tr": "MediaMarkt",
    "vatanbilgisayar.com": "Vatan Bilgisayar",
    "idefix.com": "İdefix",
    "pttavm.com": "PttAVM",
    "ciceksepeti.com": "Çiçeksepeti",
}


class ProductMetadataError(ValueError):
    pass


@dataclass(frozen=True)
class ProductSnapshot:
    title: str
    url: str
    store_name: str
    price_cents: int


def validate_product_url(value: str) -> str:
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProductMetadataError("Geçerli bir ürün bağlantısı girin.")
    if parsed.hostname.lower() == "localhost":
        raise ProductMetadataError("Yerel ağ bağlantıları takip edilemez.")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return url
    if not address.is_global:
        raise ProductMetadataError("Yerel ağ bağlantıları takip edilemez.")
    return url


def price_text_to_cents(value: str | None) -> int | None:
    if not value:
        return None
    cleaned = re.sub(r"[^0-9,.-]", "", value).strip()
    if not cleaned:
        return None
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif cleaned.count(".") > 1 or (
        cleaned.count(".") == 1 and len(cleaned.rsplit(".", 1)[1]) == 3
    ):
        cleaned = cleaned.replace(".", "")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    if amount <= 0:
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_price_cents(value: int) -> str:
    whole, decimal = divmod(value, 100)
    whole_text = f"{whole:,}".replace(",", ".")
    if decimal:
        return f"{whole_text},{decimal:02d} TL"
    return f"{whole_text} TL"


def build_akakce_url(title: str) -> str:
    return f"https://www.akakce.com/arama/?{urlencode({'q': title.strip()})}"


def get_store_name(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower().removeprefix("www.")
    for domain, name in STORE_NAMES.items():
        if hostname == domain or hostname.endswith(f".{domain}"):
            return name
    parts = hostname.split(".")
    return (parts[-2] if len(parts) > 1 else hostname).replace("-", " ").title()


def should_send_price_drop(
    initial_price_cents: int,
    current_price_cents: int,
    last_notified_price_cents: int | None,
    previous_price_cents: int | None,
) -> bool:
    if current_price_cents >= initial_price_cents:
        return False

    # If price was at/above the baseline and dropped below it again, notify.
    if previous_price_cents is not None and previous_price_cents >= initial_price_cents:
        return True

    # Under baseline, notify whenever price changed from last notified value.
    # This keeps the baseline anchored to initial_price_cents as requested.
    return (
        last_notified_price_cents is None
        or current_price_cents != last_notified_price_cents
    )


async def fetch_product_snapshot(
    url: str,
    source_title: str | None = None,
) -> ProductSnapshot:
    valid_url = validate_product_url(url)
    title, price, resolved_url = await asyncio.to_thread(
        _fetch_page_metadata,
        valid_url,
        source_title,
    )
    price_cents = price_text_to_cents(price)
    if price_cents is None:
        raise ProductMetadataError(
            "Bu bağlantıda ürün fiyatı bulunamadı. Doğrudan ürün sayfası bağlantısını deneyin."
        )
    final_url = validate_product_url(resolved_url or valid_url)
    fallback_title = source_title or get_store_name(final_url)
    return ProductSnapshot(
        title=(title or fallback_title).strip()[:500],
        url=final_url,
        store_name=get_store_name(final_url),
        price_cents=price_cents,
    )


async def check_tracked_product(
    db: AsyncSession,
    product: TrackedProduct,
) -> bool:
    checked_at = datetime.utcnow()
    try:
        snapshot = await fetch_product_snapshot(product.url, product.title)
    except ProductMetadataError as exc:
        product.last_checked_at = checked_at
        product.last_error = str(exc)
        await db.flush()
        return False

    previous_price_cents = product.current_price_cents

    product.title = snapshot.title
    product.store_name = snapshot.store_name
    product.current_price_cents = snapshot.price_cents
    product.lowest_price_cents = min(
        product.lowest_price_cents,
        snapshot.price_cents,
    )
    product.last_checked_at = checked_at
    product.last_error = None

    notify = should_send_price_drop(
        product.initial_price_cents,
        snapshot.price_cents,
        product.last_notified_price_cents,
        previous_price_cents,
    )
    if notify:
        sent = await telegram_notifier.send_price_drop(
            title=product.title,
            link_url=product.url,
            store_name=product.store_name,
            initial_price=format_price_cents(product.initial_price_cents),
            current_price=format_price_cents(snapshot.price_cents),
        )
        if sent:
            product.last_notified_price_cents = snapshot.price_cents

    await db.flush()
    return notify


async def check_all_tracked_products(db: AsyncSession) -> int:
    products = (
        await db.execute(
            select(TrackedProduct)
            .where(TrackedProduct.is_active == True)
            .order_by(TrackedProduct.id.asc())
        )
    ).scalars().all()
    detected_drops = 0
    for product in products:
        try:
            if await check_tracked_product(db, product):
                detected_drops += 1
        except Exception:
            logger.exception("Tracked product check failed for id=%s", product.id)
    return detected_drops
