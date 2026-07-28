from typing import Annotated
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc, func, or_
from sqlalchemy.exc import IntegrityError

from src.database import get_db
from src.models.domain import AppSetting, ScrapedTopic, TargetSite, TrackedProduct
from src.schemas.dashboard import (
    DashboardSyncStatusResponse,
    DashboardTopicResponse,
    DashboardForceSendRequest,
    TrackedProductCreate,
    TrackedProductResponse,
    TrackedProductSettingsResponse,
    TrackedProductSettingsUpdate,
)
from src.services.notifier import (
    telegram_notifier,
    normalize_deal_title,
    normalize_deal_url,
    normalize_deal_price,
)
from src.services.product_tracker import (
    DEFAULT_PRODUCT_CHECK_INTERVAL_MINUTES,
    PRODUCT_CHECK_INTERVAL_SETTING_KEY,
    ProductMetadataError,
    build_akakce_url,
    check_tracked_product,
    fetch_product_snapshot,
    format_price_cents,
)
from src.services.scheduler import refresh_product_tracking_interval

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
DbDep = Annotated[AsyncSession, Depends(get_db)]


def _tracked_product_response(product: TrackedProduct) -> TrackedProductResponse:
    display_title = normalize_deal_title(product.title)
    discount_percent = 0.0
    if product.current_price_cents < product.initial_price_cents:
        discount_percent = round(
            (product.initial_price_cents - product.current_price_cents)
            / product.initial_price_cents
            * 100,
            1,
        )
    return TrackedProductResponse(
        id=product.id,
        title=display_title,
        url=product.url,
        store_name=product.store_name,
        initial_price_cents=product.initial_price_cents,
        current_price_cents=product.current_price_cents,
        lowest_price_cents=product.lowest_price_cents,
        initial_price=format_price_cents(product.initial_price_cents),
        current_price=format_price_cents(product.current_price_cents),
        lowest_price=format_price_cents(product.lowest_price_cents),
        discount_percent=discount_percent,
        akakce_url=build_akakce_url(display_title),
        is_active=product.is_active,
        last_checked_at=product.last_checked_at,
        last_error=product.last_error,
        created_at=product.created_at,
    )


@router.get("/sync-status", response_model=DashboardSyncStatusResponse)
async def get_sync_status(db: DbDep):
    result = await db.execute(
        select(AppSetting).where(
            AppSetting.key.in_(["last_scrape_completed_at", "scrape_interval_minutes"])
        )
    )
    settings = {row.key: row.value for row in result.scalars().all()}

    last_scrape_value = settings.get("last_scrape_completed_at")
    last_scrape_completed_at = None
    if last_scrape_value:
        try:
            normalized_last_scrape = last_scrape_value.replace("Z", "+00:00")
            last_scrape_completed_at = datetime.fromisoformat(normalized_last_scrape)
        except Exception:
            last_scrape_completed_at = None

    interval_value = settings.get("scrape_interval_minutes", "1")
    scrape_interval_minutes = 1
    if interval_value.isdigit():
        scrape_interval_minutes = max(1, int(interval_value))

    return DashboardSyncStatusResponse(
        last_scrape_completed_at=last_scrape_completed_at,
        scrape_interval_minutes=scrape_interval_minutes,
    )

@router.get("/topics", response_model=list[DashboardTopicResponse])
async def list_recent_topics(db: DbDep, limit: int = 50):
    """Fetch topics ordered by time label (source_date fallback scraped_at)."""
    topic_time = func.coalesce(ScrapedTopic.source_date, ScrapedTopic.scraped_at)
    stmt = (
        select(ScrapedTopic, TargetSite.name.label("site_name"))
        .join(TargetSite, TargetSite.id == ScrapedTopic.site_id)
        .where(ScrapedTopic.is_sticky == False)
        .where(ScrapedTopic.deleted_by_user == False)
        .where(
            or_(
                TargetSite.source_type != "donanimhaber_thread",
                (ScrapedTopic.clean_deal_url.isnot(None)) & (ScrapedTopic.clean_deal_url != ""),
                (ScrapedTopic.deal_url.isnot(None)) & (ScrapedTopic.deal_url != ""),
            )
        )
        .order_by(desc(topic_time), desc(ScrapedTopic.scraped_at), desc(ScrapedTopic.id))
        .limit(limit)
    )
    
    result = await db.execute(stmt)
    rows = result.all()
    
    # Map the join result to the Pydantic response manually
    response = []
    for topic, site_name in rows:
        # Never expose Telegram channel links to the frontend.
        # If deal_url exists use it as primary; for telegram-sourced topics
        # without deal_url the url field stays but this should be rare
        # since the reader already skips those.
        display_url = normalize_deal_url(topic.clean_deal_url or topic.deal_url or topic.url)
        display_title = normalize_deal_title(topic.title)
        display_deal_title = normalize_deal_title(topic.deal_title) or None
        response.append(
            DashboardTopicResponse(
                id=topic.id,
                site_name=site_name,
            title=display_title,
                url=display_url,
                deal_url=topic.deal_url,
                clean_deal_url=topic.clean_deal_url,
                deal_title=display_deal_title,
                deal_price=normalize_deal_price(topic.deal_price),
                akakce_url=build_akakce_url(display_deal_title or display_title),
                notification_sent=topic.notification_sent,
                domain_skipped=topic.domain_skipped,
                notification_block_reason=topic.notification_block_reason,
                source_date=topic.source_date,
                scraped_at=topic.scraped_at
            )
        )
        
    return response


@router.get("/tracked-products", response_model=list[TrackedProductResponse])
async def list_tracked_products(db: DbDep):
    products = (
        await db.execute(
            select(TrackedProduct).order_by(
                desc(TrackedProduct.is_active),
                desc(TrackedProduct.created_at),
            )
        )
    ).scalars().all()
    return [_tracked_product_response(product) for product in products]


@router.post(
    "/tracked-products",
    response_model=TrackedProductResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tracked_product(payload: TrackedProductCreate, db: DbDep):
    try:
        snapshot = await fetch_product_snapshot(payload.url)
    except ProductMetadataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    existing = await db.execute(
        select(TrackedProduct).where(TrackedProduct.url == snapshot.url)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Bu ürün zaten takip ediliyor.")

    product = TrackedProduct(
        title=snapshot.title,
        url=snapshot.url,
        store_name=snapshot.store_name,
        initial_price_cents=snapshot.price_cents,
        current_price_cents=snapshot.price_cents,
        lowest_price_cents=snapshot.price_cents,
        last_checked_at=datetime.utcnow(),
    )
    db.add(product)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Bu ürün zaten takip ediliyor.") from exc
    await db.refresh(product)
    return _tracked_product_response(product)


@router.post(
    "/tracked-products/{product_id}/check",
    response_model=TrackedProductResponse,
)
async def check_product_now(product_id: int, db: DbDep):
    product = await db.get(TrackedProduct, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Takip edilen ürün bulunamadı.")
    await check_tracked_product(db, product)
    await db.commit()
    await db.refresh(product)
    return _tracked_product_response(product)


@router.patch(
    "/tracked-products/{product_id}/toggle",
    response_model=TrackedProductResponse,
)
async def toggle_tracked_product(product_id: int, db: DbDep):
    product = await db.get(TrackedProduct, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Takip edilen ürün bulunamadı.")
    product.is_active = not product.is_active
    await db.commit()
    await db.refresh(product)
    return _tracked_product_response(product)


@router.delete(
    "/tracked-products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_tracked_product(product_id: int, db: DbDep):
    product = await db.get(TrackedProduct, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Takip edilen ürün bulunamadı.")
    await db.delete(product)
    await db.commit()


@router.get(
    "/tracked-products-settings",
    response_model=TrackedProductSettingsResponse,
)
async def get_tracked_product_settings(db: DbDep):
    result = await db.execute(
        select(AppSetting).where(
            AppSetting.key.in_(
                [PRODUCT_CHECK_INTERVAL_SETTING_KEY, "last_product_check_completed_at"]
            )
        )
    )
    settings = {setting.key: setting.value for setting in result.scalars().all()}
    interval_value = settings.get(
        PRODUCT_CHECK_INTERVAL_SETTING_KEY,
        str(DEFAULT_PRODUCT_CHECK_INTERVAL_MINUTES),
    )
    interval = DEFAULT_PRODUCT_CHECK_INTERVAL_MINUTES
    if interval_value.isdigit():
        interval = max(1, min(1440, int(interval_value)))

    last_check_completed_at = None
    last_check_value = settings.get("last_product_check_completed_at")
    if last_check_value:
        try:
            last_check_completed_at = datetime.fromisoformat(
                last_check_value.replace("Z", "+00:00")
            )
        except ValueError:
            last_check_completed_at = None
    return TrackedProductSettingsResponse(
        check_interval_minutes=interval,
        last_check_completed_at=last_check_completed_at,
    )


@router.put(
    "/tracked-products-settings",
    response_model=TrackedProductSettingsResponse,
)
async def update_tracked_product_settings(
    payload: TrackedProductSettingsUpdate,
    db: DbDep,
):
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == PRODUCT_CHECK_INTERVAL_SETTING_KEY)
    )
    setting = result.scalar_one_or_none()
    if setting is None:
        setting = AppSetting(
            key=PRODUCT_CHECK_INTERVAL_SETTING_KEY,
            value=str(payload.check_interval_minutes),
            description="Özel ürün fiyat kontrol aralığı (dakika)",
        )
        db.add(setting)
    else:
        setting.value = str(payload.check_interval_minutes)
    await db.commit()
    await refresh_product_tracking_interval()
    return TrackedProductSettingsResponse(
        check_interval_minutes=payload.check_interval_minutes,
    )


@router.post("/topics/{topic_id}/send")
async def force_send_topic(topic_id: int, db: DbDep, payload: DashboardForceSendRequest | None = None):
    """Force-send a topic notification, bypassing domain filter."""
    result = await db.execute(
        select(ScrapedTopic, TargetSite.name.label("site_name"))
        .join(TargetSite, TargetSite.id == ScrapedTopic.site_id)
        .where(ScrapedTopic.id == topic_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Topic not found")
    topic, site_name = row
    override_title = ((payload.title if payload else "") or "").strip() or None
    override_link = ((payload.link if payload else "") or "").strip() or None
    sent = await telegram_notifier.send_topic(topic, site_name, override_title=override_title, override_link=override_link)
    if sent:
        topic.notification_sent = True
        topic.domain_skipped = False
        topic.notification_block_reason = None
        await db.commit()
        return {"message": "Bildirim gönderildi."}
    raise HTTPException(status_code=500, detail="Bildirim gönderilemedi.")


@router.delete("/topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_topic(topic_id: int, db: DbDep):
    result = await db.execute(select(ScrapedTopic).where(ScrapedTopic.id == topic_id))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    topic.deleted_by_user = True
    topic.notification_sent = True
    await db.commit()


@router.post("/demo-topic", response_model=DashboardTopicResponse)
async def create_demo_topic(db: DbDep):
    """Insert a temporary demo topic to test dashboard notifications."""
    # Pick the first active site
    site_result = await db.execute(
        select(TargetSite).where(TargetSite.is_active == True).limit(1)
    )
    site = site_result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=400, detail="No active site to attach demo topic to")

    demo = ScrapedTopic(
        site_id=site.id,
        title="[DEMO] Bildirim Testi — Bu kayıt silinebilir",
        url=f"https://example.com/demo-{int(datetime.utcnow().timestamp())}",
        notification_sent=False,
        domain_skipped=False,
        is_sticky=False,
        deleted_by_user=False,
        deal_title="Demo Ürün — Bildirim Testi",
        deal_price="99,99",
        deal_url="https://example.com/demo-product",
        clean_deal_url="https://example.com/demo-product",
        source_date=datetime.utcnow(),
        scraped_at=datetime.utcnow(),
    )
    db.add(demo)
    await db.commit()
    await db.refresh(demo)

    return DashboardTopicResponse(
        id=demo.id,
        site_name=site.name,
        title=normalize_deal_title(demo.title),
        url=demo.url,
        deal_url=demo.deal_url,
        clean_deal_url=demo.clean_deal_url,
        deal_title=normalize_deal_title(demo.deal_title) or None,
        deal_price=demo.deal_price,
        akakce_url=build_akakce_url(normalize_deal_title(demo.deal_title or demo.title)),
        notification_sent=demo.notification_sent,
        domain_skipped=demo.domain_skipped,
        notification_block_reason=demo.notification_block_reason,
        source_date=demo.source_date,
        scraped_at=demo.scraped_at,
    )
