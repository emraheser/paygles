import logging
import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.future import select

from src.database import AsyncSessionLocal
from src.models.domain import AppSetting
from src.services.notifier import send_unsent_topic_notifications, fill_missing_deal_data
from src.services.scraper import ScraperService
from src.services.telegram_reader import TelegramReaderService

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
MAIN_JOB_ID = "main_scrape_job"
BACKFILL_JOB_ID = "backfill_job"
BACKFILL_INTERVAL_MINUTES = 15


async def _upsert_setting(
    session,
    key: str,
    value: str,
    description: str | None = None,
) -> None:
    result = await session.execute(select(AppSetting).where(AppSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting is None:
        setting = AppSetting(key=key, value=value, description=description)
        session.add(setting)
        return
    setting.value = value
    if description and not setting.description:
        setting.description = description

async def scheduled_scrape_task():
    """Timer task that initializes a DB session and runs the scraper"""
    logger.info("Executing periodic scrape job.")
    async with AsyncSessionLocal() as session:
        scraper = ScraperService(session)
        await scraper.run_all_sites()

        telegram_reader = TelegramReaderService(session)
        await telegram_reader.run_all_channels()

        sent_count = await send_unsent_topic_notifications(session)
        if sent_count:
            logger.info("Telegram notifications sent: %s", sent_count)

        await _upsert_setting(
            session,
            "last_scrape_completed_at",
            datetime.utcnow().isoformat(),
            "Last successful scrape completion time in UTC",
        )
        await session.commit()

async def get_scrape_interval_minutes(session) -> int:
    """Fetch interval from DB, default to 1 min if not set"""
    result = await session.execute(select(AppSetting).where(AppSetting.key == "scrape_interval_minutes"))
    setting = result.scalar_one_or_none()
    if setting and setting.value.isdigit():
        return max(1, int(setting.value))
    return 1  # Default 1 min


def _upsert_main_job(interval_minutes: int) -> None:
    scheduler.add_job(
        scheduled_scrape_task,
        "interval",
        minutes=interval_minutes,
        id=MAIN_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=30,
    )


def _upsert_backfill_job() -> None:
    scheduler.add_job(
        scheduled_backfill_task,
        "interval",
        minutes=BACKFILL_INTERVAL_MINUTES,
        id=BACKFILL_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=120,
    )


async def scheduled_backfill_task():
    """Lower-frequency task for expensive metadata backfills."""
    logger.info("Executing backfill job.")
    async with AsyncSessionLocal() as session:
        scraper = ScraperService(session)
        backfilled_links = await scraper.fill_missing_deal_links(batch_size=20)
        if backfilled_links:
            logger.info("Backfilled missing deal links: %s", backfilled_links)

        filled = await fill_missing_deal_data(session, batch_size=20)
        if filled:
            logger.info("Fixed %s topics with missing deal data", filled)

        await session.commit()

async def start_scheduler():
    """Called on app startup to attach jobs to APScheduler"""
    async with AsyncSessionLocal() as session:
        interval_minutes = await get_scrape_interval_minutes(session)

    _upsert_main_job(interval_minutes)
    _upsert_backfill_job()
    if not scheduler.running:
        scheduler.start()
    asyncio.create_task(scheduled_scrape_task())
    logger.info(f"Scheduler started with interval of {interval_minutes} minutes.")


async def refresh_scheduler_interval():
    """Re-read DB setting and apply updated interval without restart."""
    async with AsyncSessionLocal() as session:
        interval_minutes = await get_scrape_interval_minutes(session)

    _upsert_main_job(interval_minutes)
    logger.info("Scheduler interval refreshed to %s minutes.", interval_minutes)


async def stop_scheduler():
    """Called on app shutdown"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped.")
