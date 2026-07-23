from contextlib import asynccontextmanager
import logging
import os
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s - %(message)s")

from src.database import engine, Base
from src.api.admin import router as admin_router
from src.api.dashboard import router as dashboard_router
from src.services.scheduler import start_scheduler, stop_scheduler

TOPIC_ID_REGEX = re.compile(r"\.(\d+)(?:/)?$")


def _run_schema_upgrades(sync_conn):
    """Minimal schema upgrades without Alembic for local development."""
    from src.services.notifier import normalize_deal_url

    inspector = inspect(sync_conn)

    # --- target_sites upgrades ---
    if "target_sites" in inspector.get_table_names():
        ts_columns = {col["name"] for col in inspector.get_columns("target_sites")}
        if "source_type" not in ts_columns:
            sync_conn.execute(text("ALTER TABLE target_sites ADD COLUMN source_type VARCHAR(20) NOT NULL DEFAULT 'web'"))

    # --- scraped_topics upgrades ---
    if "scraped_topics" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("scraped_topics")}
    if "source_topic_id" not in columns:
        sync_conn.execute(text("ALTER TABLE scraped_topics ADD COLUMN source_topic_id VARCHAR(100)"))
        sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_scraped_topics_source_topic_id ON scraped_topics (source_topic_id)"))

    if "is_sticky" not in columns:
        sync_conn.execute(text("ALTER TABLE scraped_topics ADD COLUMN is_sticky BOOLEAN NOT NULL DEFAULT 0"))
        sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_scraped_topics_is_sticky ON scraped_topics (is_sticky)"))
    if "notification_sent" not in columns:
        sync_conn.execute(text("ALTER TABLE scraped_topics ADD COLUMN notification_sent BOOLEAN NOT NULL DEFAULT 0"))
        sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_scraped_topics_notification_sent ON scraped_topics (notification_sent)"))

    if "deal_url" not in columns:
        sync_conn.execute(text("ALTER TABLE scraped_topics ADD COLUMN deal_url VARCHAR(1000)"))

    if "clean_deal_url" not in columns:
        sync_conn.execute(text("ALTER TABLE scraped_topics ADD COLUMN clean_deal_url VARCHAR(1000)"))

    # Normalize stored clean URLs and strip tracking query params.
    columns = {col["name"] for col in inspector.get_columns("scraped_topics")}
    if "clean_deal_url" in columns:
        rows = sync_conn.execute(
            text("SELECT id, deal_url, clean_deal_url FROM scraped_topics")
        ).fetchall()
        for row_id, deal_url, clean_deal_url in rows:
            source_url = clean_deal_url or deal_url
            if not source_url:
                continue
            normalized = normalize_deal_url(source_url)
            if normalized != (clean_deal_url or ""):
                sync_conn.execute(
                    text("UPDATE scraped_topics SET clean_deal_url = :normalized WHERE id = :row_id"),
                    {"normalized": normalized, "row_id": row_id},
                )

    if "deal_title" not in columns:
        sync_conn.execute(text("ALTER TABLE scraped_topics ADD COLUMN deal_title VARCHAR(500)"))

    if "deal_price" not in columns:
        sync_conn.execute(text("ALTER TABLE scraped_topics ADD COLUMN deal_price VARCHAR(100)"))
    else:
        sync_conn.execute(
            text(
                "UPDATE scraped_topics "
                "SET deal_price = TRIM(" 
                "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(deal_price, '₺', ''), 'TL', ''), 'Tl', ''), 'tL', ''), 'tl', '')" 
                ") "
                "WHERE deal_price IS NOT NULL"
            )
        )

    if "domain_skipped" not in columns:
        sync_conn.execute(text("ALTER TABLE scraped_topics ADD COLUMN domain_skipped BOOLEAN NOT NULL DEFAULT 0"))
        sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_scraped_topics_domain_skipped ON scraped_topics (domain_skipped)"))
        # Fix records that were incorrectly marked as sent due to domain filtering.
        # Check allowed_domains and reset notification_sent for mismatched domains.
        if "allowed_domains" in inspector.get_table_names():
            allowed_rows = sync_conn.execute(
                text("SELECT domain FROM allowed_domains WHERE is_active = 1")
            ).fetchall()
            allowed_domains = [r[0].lower() for r in allowed_rows]
            if allowed_domains:
                sent_rows = sync_conn.execute(
                    text("SELECT id, url, deal_url FROM scraped_topics WHERE notification_sent = 1")
                ).fetchall()
                for row_id, url, deal_url in sent_rows:
                    link = deal_url or url or ""
                    try:
                        from urllib.parse import urlparse
                        hostname = (urlparse(link).hostname or "").lower().removeprefix("www.")
                        if not any(hostname == d or hostname.endswith("." + d) for d in allowed_domains):
                            sync_conn.execute(
                                text("UPDATE scraped_topics SET domain_skipped = 1, notification_sent = 0 WHERE id = :id"),
                                {"id": row_id},
                            )
                    except Exception:
                        pass

    columns = {col["name"] for col in inspector.get_columns("scraped_topics")}
    if "notification_block_reason" not in columns:
        sync_conn.execute(text("ALTER TABLE scraped_topics ADD COLUMN notification_block_reason VARCHAR(100)"))

    if "deleted_by_user" not in columns:
        sync_conn.execute(text("ALTER TABLE scraped_topics ADD COLUMN deleted_by_user BOOLEAN NOT NULL DEFAULT 0"))
        sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_scraped_topics_deleted_by_user ON scraped_topics (deleted_by_user)"))

    rows = sync_conn.execute(
        text("SELECT id, url FROM scraped_topics WHERE source_topic_id IS NULL")
    ).fetchall()
    for row_id, url in rows:
        match = TOPIC_ID_REGEX.search(url or "")
        if not match:
            continue
        sync_conn.execute(
            text("UPDATE scraped_topics SET source_topic_id = :topic_id WHERE id = :row_id"),
            {"topic_id": match.group(1), "row_id": row_id},
        )

    sync_conn.execute(
        text(
            "DELETE FROM scraped_topics "
            "WHERE site_id NOT IN (SELECT id FROM target_sites)"
        )
    )

    # --- allowed_domains table ---
    # Created automatically by Base.metadata.create_all via the AllowedDomain model.

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup Database tables (SQLite)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_run_schema_upgrades)
        
    # Start APScheduler Jobs
    await start_scheduler()
        
    yield
    
    # Cleanup logic
    await stop_scheduler()
    await engine.dispose()

app = FastAPI(
    title="Paygles API",
    description="Hot Deals Scraper API",
    version="1.0.0",
    lifespan=lifespan
)

_allowed_origins = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)
app.include_router(dashboard_router)

@app.get("/health")
async def health_check():
    return {"status": "ok"}
