import json
import logging
import os

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from src.models.domain import TargetSite

logger = logging.getLogger(__name__)

SUPPORTED_SOURCE_TYPES = {"web", "telegram", "donanimhaber_thread"}


def _as_bool(value, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def parse_target_sites_from_env() -> list[dict]:
    raw = (os.getenv("TARGET_SITES_JSON", "") or "").strip()
    if not raw:
        return []

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.exception("Invalid TARGET_SITES_JSON value. Must be a valid JSON array.")
        return []

    if not isinstance(payload, list):
        logger.warning("TARGET_SITES_JSON must be a JSON array.")
        return []

    normalized: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        source_type = str(item.get("source_type", "web")).strip().lower()

        if not name or not url:
            continue
        if source_type not in SUPPORTED_SOURCE_TYPES:
            logger.warning("Unsupported source_type in TARGET_SITES_JSON: %s", source_type)
            continue

        topic_list_selector = str(item.get("topic_list_selector", "") or "").strip()
        title_selector = str(item.get("title_selector", "") or "").strip()
        link_selector = str(item.get("link_selector", "") or "").strip()
        date_selector_raw = item.get("date_selector")
        date_selector = str(date_selector_raw).strip() if date_selector_raw else None

        if source_type == "web" and (
            not topic_list_selector or not title_selector or not link_selector
        ):
            logger.warning(
                "Skipping web source without selectors in TARGET_SITES_JSON: %s",
                name,
            )
            continue

        normalized.append(
            {
                "name": name,
                "url": url,
                "source_type": source_type,
                "topic_list_selector": topic_list_selector,
                "title_selector": title_selector,
                "link_selector": link_selector,
                "date_selector": date_selector,
                "is_active": _as_bool(item.get("is_active"), True),
            }
        )

    return normalized


async def sync_target_sites_from_env(db: AsyncSession) -> int:
    """Sync non-manual target sites from TARGET_SITES_JSON.

    If TARGET_SITES_JSON is empty, leaves DB rows unchanged.
    """
    sources = parse_target_sites_from_env()
    if not sources:
        logger.info("TARGET_SITES_JSON is empty or invalid. Skipping source sync.")
        return 0

    touched = 0

    await db.execute(
        update(TargetSite)
        .where(TargetSite.source_type != "manual")
        .values(is_active=False)
    )
    touched += 1

    for source in sources:
        existing = (
            await db.execute(
                select(TargetSite).where(
                    TargetSite.url == source["url"],
                    TargetSite.source_type == source["source_type"],
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            db.add(TargetSite(**source))
            touched += 1
            continue

        for key, value in source.items():
            setattr(existing, key, value)
        touched += 1

    logger.info("Synced %s sources from TARGET_SITES_JSON.", len(sources))
    return touched
