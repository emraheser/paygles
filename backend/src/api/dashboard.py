from typing import Annotated
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc, func

from src.database import get_db
from src.models.domain import AppSetting, ScrapedTopic, TargetSite
from src.schemas.dashboard import DashboardSyncStatusResponse, DashboardTopicResponse, DashboardForceSendRequest
from src.services.notifier import telegram_notifier, normalize_deal_url, normalize_deal_price

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
DbDep = Annotated[AsyncSession, Depends(get_db)]


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
        response.append(
            DashboardTopicResponse(
                id=topic.id,
                site_name=site_name,
                title=topic.title,
                url=display_url,
                deal_url=topic.deal_url,
                clean_deal_url=topic.clean_deal_url,
                deal_title=topic.deal_title,
                deal_price=normalize_deal_price(topic.deal_price),
                notification_sent=topic.notification_sent,
                domain_skipped=topic.domain_skipped,
                notification_block_reason=topic.notification_block_reason,
                source_date=topic.source_date,
                scraped_at=topic.scraped_at
            )
        )
        
    return response


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
        title=demo.title,
        url=demo.url,
        deal_url=demo.deal_url,
        clean_deal_url=demo.clean_deal_url,
        deal_title=demo.deal_title,
        deal_price=demo.deal_price,
        notification_sent=demo.notification_sent,
        domain_skipped=demo.domain_skipped,
        notification_block_reason=demo.notification_block_reason,
        source_date=demo.source_date,
        scraped_at=demo.scraped_at,
    )
