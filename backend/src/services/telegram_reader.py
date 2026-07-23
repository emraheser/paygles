import logging
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError

from src.models.domain import TargetSite, ScrapedTopic, KeywordFilter
from src.services.notifier import (
    normalize_deal_url,
    build_deal_metadata_for_new_record,
    _can_use_title_price_fallback,
    _extract_price_from_text,
    _is_coupon_or_campaign_title,
    _is_discussion_title,
    _is_homepage_or_junk_url,
    _is_non_product_title,
)

logger = logging.getLogger(__name__)

# URL pattern to extract links from message text
URL_REGEX = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)

# Domains to skip (Telegram internal links, not useful as deal links)
SKIP_DOMAINS = {"t.me", "telegram.me", "telegram.org"}


def _get_telethon_client():
    """Lazy-create a Telethon client using env vars. Returns None if not configured."""
    api_id = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()

    if not api_id or not api_hash:
        return None

    from telethon import TelegramClient
    from telethon.sessions import StringSession

    string_session = os.getenv("TELETHON_STRING_SESSION", "").strip()
    if string_session:
        session = StringSession(string_session)
    else:
        session = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "paygles_telethon",
        )

    client = TelegramClient(session, int(api_id), api_hash)
    return client


def _extract_first_external_url(text: str) -> str | None:
    """Extract the first non-Telegram URL from message text."""
    if not text:
        return None
    for match in URL_REGEX.finditer(text):
        url = match.group(0).rstrip("*.,;:!?)")
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if any(domain == skip or domain.endswith("." + skip) for skip in SKIP_DOMAINS):
            continue
        return url
    return None


def _extract_button_url(message) -> str | None:
    """Extract the first external URL from inline keyboard buttons."""
    markup = message.reply_markup
    if markup is None:
        return None
    rows = getattr(markup, "rows", None)
    if not rows:
        return None
    for row in rows:
        for button in row.buttons:
            url = getattr(button, "url", None)
            if not url:
                continue
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if any(domain == skip or domain.endswith("." + skip) for skip in SKIP_DOMAINS):
                continue
            return url
    return None


class TelegramReaderService:
    """Reads messages from Telegram channels the user is subscribed to."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _load_active_keywords(self) -> list[str]:
        """Load all active keyword filters from DB."""
        result = await self.db.execute(
            select(KeywordFilter.keyword).where(KeywordFilter.is_active == True)
        )
        return [row[0] for row in result.all()]

    async def run_all_channels(self):
        """Read all active telegram-type sources."""
        result = await self.db.execute(
            select(TargetSite).where(
                TargetSite.is_active == True,
                TargetSite.source_type == "telegram",
            )
        )
        channels = result.scalars().all()
        if not channels:
            return

        # Load keyword filters once for the entire run
        self._keywords = await self._load_active_keywords()

        client = _get_telethon_client()
        if client is None:
            logger.warning(
                "Telegram reader disabled: TELEGRAM_API_ID / TELEGRAM_API_HASH not set."
            )
            return

        try:
            ss_val = os.getenv("TELETHON_STRING_SESSION", "").strip()
            logger.warning("Telegram connect: StringSession=%s chars, API_ID=%s",
                        len(ss_val) if ss_val else 0,
                        os.getenv("TELEGRAM_API_ID", "")[:4] + "...")
            await client.connect()
            authorized = await client.is_user_authorized()
            logger.warning("Telegram connected, authorized=%s, session_dc=%s",
                        authorized, client.session.dc_id if hasattr(client.session, 'dc_id') else '?')
            if not authorized:
                logger.warning(
                    "Telegram client not authorized. Run the auth flow once manually."
                )
                return

            for channel in channels:
                channel_name = channel.name  # cache before session may expire
                try:
                    await self._read_channel(client, channel)
                except Exception:
                    logger.exception("Error reading Telegram channel %s", channel_name)
        finally:
            await client.disconnect()

    async def _read_channel(self, client, site: TargetSite):
        """Fetch recent messages from a single Telegram channel and upsert topics."""
        channel_identifier = site.url.strip()
        site_name = site.name  # cache for logging after potential session expire
        site_id = site.id
        logger.info("Reading Telegram channel: %s (%s)", site_name, channel_identifier)

        # Load existing URLs to avoid duplicates
        existing_urls = {
            row[0]
            for row in (
                await self.db.execute(
                    select(ScrapedTopic.url).where(ScrapedTopic.site_id == site_id)
                )
            ).all()
        }

        # Check if this is the first read for this channel.
        # If no topics exist yet, this is a seed run — mark all as already notified
        # so the bot doesn't spam old messages.
        site_topic_count = (
            await self.db.execute(
                select(ScrapedTopic.id).where(ScrapedTopic.site_id == site_id).limit(1)
            )
        ).first()
        is_first_run = site_topic_count is None

        entity = await client.get_entity(channel_identifier)

        inserted_count = 0
        run_started_at = datetime.utcnow()
        consecutive_seen = 0

        async for message in client.iter_messages(entity, limit=30):
            if not message.text:
                continue

            text = message.text.strip()
            if not text:
                continue

            # Use first line as the title / headline of the message
            first_line = text.split("\n")[0].strip()

            # Keyword filtering: if keywords are defined, only check the first
            # line (headline) of the message — e.g. "🔥Schafer 7 Parça Tencere Seti"
            if self._keywords:
                headline_lower = first_line.lower()
                if not any(kw in headline_lower for kw in self._keywords):
                    continue

            title = first_line[:200] if first_line else text[:200]

            # Build a unique URL for this message
            channel_username = getattr(entity, "username", None)
            if channel_username:
                message_url = f"https://t.me/{channel_username}/{message.id}"
            else:
                message_url = f"https://t.me/c/{entity.id}/{message.id}"

            if message_url in existing_urls:
                consecutive_seen += 1
                if consecutive_seen >= 5:
                    break
                continue
            consecutive_seen = 0

            # Extract deal link: prefer inline button URL, fallback to text
            deal_url = _extract_button_url(message) or _extract_first_external_url(text)
            cleaned_deal_url = normalize_deal_url(deal_url) if deal_url else None


            # Message date → UTC naive
            source_date = None
            if message.date:
                source_date = message.date.astimezone(timezone.utc).replace(tzinfo=None)

            if source_date and source_date > datetime.utcnow() + timedelta(days=1):
                continue

            observed_at = run_started_at - timedelta(microseconds=inserted_count)

            topic = ScrapedTopic(
                site_id=site_id,
                title=title,
                url=message_url,
                source_topic_id=str(message.id),
                is_sticky=False,
                notification_sent=True if is_first_run else False,
                source_date=source_date or datetime.utcnow(),
                scraped_at=observed_at,
                deal_url=deal_url,
                clean_deal_url=cleaned_deal_url,
            )
            if deal_url:
                deal_title, deal_price, resolved_url = await build_deal_metadata_for_new_record(
                    cleaned_deal_url or deal_url,
                    title,
                )
                topic.clean_deal_url = normalize_deal_url(resolved_url or cleaned_deal_url or deal_url)
                topic.deal_title = deal_title
                topic.deal_price = deal_price
                # Fallback: extract price from forum title if page didn't have one
                if not deal_price and _can_use_title_price_fallback(title):
                    topic.deal_price = _extract_price_from_text(title)
            elif _is_discussion_title(title):
                continue

            if (
                _is_coupon_or_campaign_title(title)
                and (
                    not topic.clean_deal_url
                )
                and not topic.deal_title
                and not topic.deal_price
            ):
                continue
            if _is_discussion_title(title) and not topic.deal_title and not topic.deal_price:
                continue
            self.db.add(topic)
            existing_urls.add(message_url)
            inserted_count += 1

        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            logger.warning(
                "Commit conflict while saving Telegram topics for %s", site_name
            )
        else:
            if inserted_count:
                logger.info(
                    "Saved %s new topics from Telegram channel %s",
                    inserted_count,
                    site_name,
                )
