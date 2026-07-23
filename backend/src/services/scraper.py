import logging
import re
from datetime import datetime
from datetime import timedelta, timezone
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse, unquote
from zoneinfo import ZoneInfo

from scrapling import Fetcher
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError

from src.models.domain import TargetSite, ScrapedTopic
from src.services.notifier import (
    normalize_deal_url,
    build_deal_metadata_for_new_record,
    _can_use_title_price_fallback,
    _extract_price_from_text,
    _is_coupon_or_campaign_title,
    _is_discussion_title,
    _is_non_product_title,
)

logger = logging.getLogger(__name__)
TOPIC_ID_REGEX = re.compile(r"\.(\d+)(?:/)?$")
ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")
TR_MONTHS = {
    "ocak": 1,
    "subat": 2,
    "mart": 3,
    "nisan": 4,
    "mayis": 5,
    "haziran": 6,
    "temmuz": 7,
    "agustos": 8,
    "eylul": 9,
    "ekim": 10,
    "kasim": 11,
    "aralik": 12,
}
TR_CHAR_MAP = str.maketrans("cCcgGiIoOsSuU", "cCcgGiIoOsSuU")
TR_CHAR_MAP.update(str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU"))


class ScraperService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def run_all_sites(self):
        """Scrape all active web sites"""
        result = await self.db.execute(
            select(TargetSite).where(
                TargetSite.is_active == True,
                TargetSite.source_type == "web",
            )
        )
        active_sites = result.scalars().all()
        logger.info(f"Starting scrape for {len(active_sites)} active sites.")

        for site in active_sites:
            try:
                await self.scrape_site(site)
            except Exception:
                logger.exception("Error scraping %s", site.name)

    async def scrape_site(self, site: TargetSite):
        """Fetch page and extract topics using configured CSS selectors"""
        site_name = site.name
        site_url = site.url
        fetch_url = self._normalized_listing_url(site_url)
        logger.info("Scraping %s at %s", site_name, fetch_url)
        site_topics = (
            await self.db.execute(
                select(ScrapedTopic).where(ScrapedTopic.site_id == site.id)
            )
        ).scalars().all()
        site_topic_by_url = {topic.url: topic for topic in site_topics}

        page = Fetcher.get(fetch_url, timeout=20)
        topic_nodes = page.css(site.topic_list_selector)
        logger.info("Found %s nodes on %s", len(topic_nodes), site_name)
        inserted_count = 0
        updated_count = 0
        run_started_at = datetime.utcnow()

        for idx, node in enumerate(topic_nodes):
            try:
                link_nodes = node.css(site.link_selector)
                link_node = self._pick_topic_link_node(link_nodes)
                title_nodes = node.css(site.title_selector)
                title_node = self._pick_title_node(title_nodes, link_node)

                if not title_node or not link_node:
                    continue

                title = title_node.text.strip()
                url = link_node.attrib.get("href", "")

                if not title or not url:
                    continue

                if url.startswith("#") or url.startswith("javascript:"):
                    continue

                url = urljoin(site_url, url)
                is_sticky = self._is_sticky_topic(node)
                observed_at = run_started_at - timedelta(microseconds=idx)

                source_date = self._extract_source_date(node, site.date_selector)
                if not source_date:
                    source_date = datetime.utcnow()
                is_future_date = source_date > datetime.utcnow() + timedelta(days=1)

                source_topic_id = None
                match = TOPIC_ID_REGEX.search(url)
                if match:
                    source_topic_id = match.group(1)

                existing_topic = site_topic_by_url.get(url)
                if existing_topic:
                    if existing_topic.deleted_by_user:
                        continue
                    changed = False
                    if not is_future_date and existing_topic.source_date != source_date:
                        existing_topic.source_date = source_date
                        changed = True
                    if source_topic_id and existing_topic.source_topic_id != source_topic_id:
                        existing_topic.source_topic_id = source_topic_id
                        changed = True
                    if existing_topic.is_sticky != is_sticky:
                        existing_topic.is_sticky = is_sticky
                        changed = True
                    if existing_topic.scraped_at != observed_at:
                        existing_topic.scraped_at = observed_at
                        changed = True
                    if changed:
                        updated_count += 1
                    continue

                if is_future_date:
                    continue

                topic = ScrapedTopic(
                    site_id=site.id,
                    title=title,
                    url=url,
                    source_topic_id=source_topic_id,
                    is_sticky=is_sticky,
                    notification_sent=False,
                    source_date=source_date,
                    scraped_at=observed_at,
                )
                deal_url = self._extract_deal_url(url, site_url)
                if deal_url:
                    cleaned_deal_url = normalize_deal_url(deal_url)
                    deal_title, deal_price, resolved_url = await build_deal_metadata_for_new_record(
                        cleaned_deal_url,
                        title,
                    )
                    topic.deal_url = deal_url
                    topic.clean_deal_url = normalize_deal_url(resolved_url or cleaned_deal_url)
                    topic.deal_title = deal_title
                    topic.deal_price = deal_price
                    # Fallback: extract price from forum title if page didn't have one
                    if not deal_price and _can_use_title_price_fallback(title):
                        topic.deal_price = _extract_price_from_text(title)
                elif _is_discussion_title(title):
                    continue

                if (
                    (_is_coupon_or_campaign_title(title) or _is_discussion_title(title))
                    and not (topic.deal_url or topic.clean_deal_url)
                    and not topic.deal_title
                    and not topic.deal_price
                ):
                    continue
                self.db.add(topic)
                site_topic_by_url[url] = topic
                inserted_count += 1
            except Exception as e:
                logger.debug("Failed node on %s: %s", site_name, e)

        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            logger.warning("Commit conflict while saving topics for %s", site_name)
        else:
            logger.info(
                "Saved %s new topics and updated %s topics for %s",
                inserted_count,
                updated_count,
                site_name,
            )

    async def fill_missing_deal_links(self, batch_size: int = 20) -> int:
        """Backfill missing deal links for existing web topics."""
        stmt = (
            select(ScrapedTopic, TargetSite)
            .join(TargetSite, TargetSite.id == ScrapedTopic.site_id)
            .where(TargetSite.source_type == "web")
            .where(TargetSite.is_active == True)
            .where(ScrapedTopic.deleted_by_user == False)
            .where(ScrapedTopic.is_sticky == False)
            .where(
                or_(
                    ScrapedTopic.deal_url.is_(None),
                    ScrapedTopic.deal_url == "",
                )
            )
            .order_by(ScrapedTopic.id.desc())
            .limit(batch_size)
        )
        rows = (await self.db.execute(stmt)).all()
        if not rows:
            return 0

        fixed = 0
        for topic, site in rows:
            deal_url = self._extract_deal_url(topic.url, site.url)
            if not deal_url:
                continue
            cleaned_deal_url = normalize_deal_url(deal_url)
            deal_title, deal_price, resolved_url = await build_deal_metadata_for_new_record(
                cleaned_deal_url,
                topic.title,
            )
            topic.deal_url = deal_url
            topic.clean_deal_url = normalize_deal_url(resolved_url or cleaned_deal_url)
            if deal_title:
                topic.deal_title = deal_title
            if deal_price:
                topic.deal_price = deal_price
            elif not (topic.deal_price or "").strip() and _can_use_title_price_fallback(topic.title):
                topic.deal_price = _extract_price_from_text(topic.title)
            fixed += 1

        if fixed:
            try:
                await self.db.commit()
            except IntegrityError:
                await self.db.rollback()
                logger.warning("Commit conflict while backfilling missing deal links")
                return 0
        return fixed

    @staticmethod
    def _normalize_text(value: str) -> str:
        cleaned = value.strip().translate(TR_CHAR_MAP).lower().replace(",", " ")
        return " ".join(cleaned.split())

    @staticmethod
    def _to_utc_naive(value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=ISTANBUL_TZ)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def _parse_source_text(self, value: str) -> datetime | None:
        normalized = self._normalize_text(value)
        if not normalized:
            return None

        now_tr = datetime.now(ISTANBUL_TZ)

        if normalized == "az once":
            return self._to_utc_naive(now_tr)

        minute_match = re.search(r"(\d+)\s+dakika\s+once", normalized)
        if minute_match:
            dt = now_tr - timedelta(minutes=int(minute_match.group(1)))
            return self._to_utc_naive(dt)

        hour_match = re.search(r"(\d+)\s+saat\s+once", normalized)
        if hour_match:
            dt = now_tr - timedelta(hours=int(hour_match.group(1)))
            return self._to_utc_naive(dt)

        day_match = re.search(r"(\d+)\s+gun\s+once", normalized)
        if day_match:
            dt = now_tr - timedelta(days=int(day_match.group(1)))
            return self._to_utc_naive(dt)

        today_match = re.search(r"bugun(?:\s+(\d{1,2}):(\d{2}))?", normalized)
        if today_match:
            hour = int(today_match.group(1) or now_tr.hour)
            minute = int(today_match.group(2) or now_tr.minute)
            dt = now_tr.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return self._to_utc_naive(dt)

        yesterday_match = re.search(r"dun(?:\s+(\d{1,2}):(\d{2}))?", normalized)
        if yesterday_match:
            hour = int(yesterday_match.group(1) or now_tr.hour)
            minute = int(yesterday_match.group(2) or now_tr.minute)
            dt = (now_tr - timedelta(days=1)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            return self._to_utc_naive(dt)

        abs_match = re.search(
            r"(\d{1,2})\s+([a-z]+)(?:\s+(\d{4}))?(?:\s+(\d{1,2}):(\d{2}))?",
            normalized,
        )
        if abs_match:
            day = int(abs_match.group(1))
            month_name = abs_match.group(2)
            month = TR_MONTHS.get(month_name)
            if month:
                raw_year = abs_match.group(3)
                year = int(raw_year or now_tr.year)
                hour = int(abs_match.group(4) or 0)
                minute = int(abs_match.group(5) or 0)
                dt = datetime(year, month, day, hour, minute, tzinfo=ISTANBUL_TZ)
                if not raw_year and dt > now_tr + timedelta(days=1):
                    dt = dt.replace(year=dt.year - 1)
                return self._to_utc_naive(dt)

        return None

    def _parse_source_node(self, node) -> datetime | None:
        data_time = node.attrib.get("data-time")
        if data_time and data_time.isdigit():
            return datetime.fromtimestamp(int(data_time), tz=timezone.utc).replace(
                tzinfo=None
            )

        datetime_attr = node.attrib.get("datetime")
        if datetime_attr:
            try:
                return self._to_utc_naive(
                    datetime.fromisoformat(datetime_attr.replace("Z", "+00:00"))
                )
            except ValueError:
                pass

        title_attr = node.attrib.get("title")
        if title_attr:
            parsed_title = self._parse_source_text(title_attr)
            if parsed_title:
                return parsed_title

        return self._parse_source_text(node.text)

    def _extract_source_date(self, node, date_selector: str | None) -> datetime | None:
        selectors = [
            ".structItem-cell--latest time",
            ".structItem-latestDate time",
            ".structItem-cell--latest .u-dt",
            ".structItem-cell--latest time[datetime]",
        ]
        if date_selector:
            selectors.append(date_selector)
        selectors.extend(
            [
                ".structItem-cell--main .structItem-startDate time",
                ".structItem-cell--main .structItem-minor .structItem-startDate time",
                ".structItem-cell--main .structItem-minor time.u-dt",
                ".structItem-cell--main .structItem-minor time[datetime]",
            ]
        )

        candidates: list[datetime] = []
        for selector in selectors:
            nodes = node.css(selector)
            if not nodes:
                continue

            for candidate in nodes:
                parsed = self._parse_source_node(candidate)
                if parsed:
                    candidates.append(parsed)
                    continue
                if selector == date_selector:
                    parsed_from_text = self._parse_source_text(candidate.text)
                    if parsed_from_text:
                        candidates.append(parsed_from_text)

        return max(candidates) if candidates else None

    @staticmethod
    def _is_sticky_topic(node) -> bool:
        css_class = (node.attrib.get("class") or "").lower()
        if "sticky" in css_class or "pinned" in css_class or "locked" in css_class:
            return True
        sticky_badges = node.css(".label--sticky, .label--pinned, .structItem-status--locked")
        if sticky_badges:
            return True
        status_nodes = node.css(".structItem-status")
        for status in status_nodes:
            status_class = (status.attrib.get("class") or "").lower()
            if "locked" in status_class:
                return True
        return False

    @staticmethod
    def _normalized_listing_url(url: str) -> str:
        """
        Enforce topic-creation ordering on XenForo-like forum listing URLs.
        This keeps behavior stable even if site-side default filters change.
        """
        parsed = urlparse(url)
        path = parsed.path.lower()
        if "/konu/" in path:
            return url
        if "/forumlar/" not in path and "/forums/" not in path:
            return url

        query = parse_qs(parsed.query, keep_blank_values=True)
        query["order"] = ["post_date"]
        query["direction"] = ["desc"]
        normalized_query = urlencode(query, doseq=True)
        return urlunparse(parsed._replace(query=normalized_query))

    @staticmethod
    def _pick_topic_link_node(link_nodes):
        if not link_nodes:
            return None
        for candidate in link_nodes:
            href = candidate.attrib.get("href", "")
            if "/konu/" in href:
                return candidate
        for candidate in link_nodes:
            href = candidate.attrib.get("href", "")
            if "prefix_id=" not in href and href:
                return candidate
        return link_nodes[0]

    @staticmethod
    def _pick_title_node(title_nodes, link_node):
        if not title_nodes:
            return link_node
        if link_node:
            link_href = link_node.attrib.get("href", "")
            for candidate in title_nodes:
                if candidate.attrib.get("href", "") == link_href and candidate.text.strip():
                    return candidate
        for candidate in title_nodes:
            if candidate.text.strip():
                return candidate
        return link_node

    @staticmethod
    def _extract_deal_url(topic_url: str, site_url: str) -> str | None:
        """Visit a topic page and extract the first external link from the first post."""
        site_domain = urlparse(site_url).netloc.lower()
        try:
            page = Fetcher.get(topic_url, timeout=20)
        except Exception as exc:
            logger.debug("Failed to fetch topic page %s: %s", topic_url, exc)
            return None

        # XenForo first post content selectors (try in order)
        content_selectors = [
            ".message-body .bbWrapper",
            ".message-content .bbWrapper",
            ".messageText",
            "article .bbWrapper",
        ]
        content_node = None
        for sel in content_selectors:
            nodes = page.css(sel)
            if nodes:
                content_node = nodes[0]
                break

        if content_node is None:
            return None

        def _normalize_extracted_href(raw_href: str) -> str | None:
            href = (raw_href or "").strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                return None
            parsed_href = urlparse(href)
            if parsed_href.scheme and parsed_href.netloc:
                return href
            if href.startswith("/") and site_url:
                return urljoin(site_url, href)
            return None

        def _decode_possible_redirect(href: str) -> str | None:
            parsed = urlparse(href)
            host = (parsed.hostname or "").lower()
            if not host.endswith(site_domain):
                return None
            qs = parse_qs(parsed.query, keep_blank_values=True)
            for key in ("url", "u", "to", "target", "redirect", "r"):
                values = qs.get(key) or []
                for value in values:
                    candidate = unquote((value or "").strip())
                    parsed_candidate = urlparse(candidate)
                    if parsed_candidate.scheme and parsed_candidate.netloc:
                        if parsed_candidate.netloc.lower().endswith(site_domain):
                            continue
                        return candidate
            return None

        links = content_node.css("a[href]")
        for link in links:
            href = _normalize_extracted_href(link.attrib.get("href", ""))
            if not href:
                continue
            parsed = urlparse(href)
            # Skip links pointing back to the same forum
            if parsed.netloc.lower().endswith(site_domain):
                redirected = _decode_possible_redirect(href)
                if redirected:
                    return redirected
                continue
            return href

        # Fallback: some posts include plain-text URLs instead of <a href>.
        raw_html = getattr(content_node, "html_content", "") or getattr(content_node, "body", "") or ""
        if isinstance(raw_html, bytes):
            raw_html = raw_html.decode("utf-8", errors="replace")
        text_blob = (raw_html or "") + " " + (content_node.text or "")
        for match in re.finditer(r"https?://[^\s<>'\"\\)\\]]+", text_blob, flags=re.IGNORECASE):
            candidate = match.group(0).rstrip("*.,;:!?)]")
            parsed = urlparse(candidate)
            if not parsed.scheme or not parsed.netloc:
                continue
            if parsed.netloc.lower().endswith(site_domain):
                redirected = _decode_possible_redirect(candidate)
                if redirected:
                    return redirected
                continue
            return candidate

        return None
